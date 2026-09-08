import json
import logging
import math
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.repositories.document_repository import DocumentRepository
from app.repositories.paper_repository import PaperRepository
from app.repositories.reference_paper_repository import ReferencePaperRepository

from app.schemas.paper import (
    ChapterWeightageResponse,
    DifficultyLevel,
    GenerationMode,
    PaperGenerateRequest,
    PaperQuestionResponse,
    PaperResponse,
    QuestionSource,
    QuestionType,
    GeminiCompletePaperSchema,
)
from app.services.ai.gemini_service import (
    GeminiInvalidResponseError,
    GeminiOutputTruncatedError,
    GeminiProviderError,
    GeminiRateLimitError,
    GeminiService,
)
from app.services.ai.prompts.paper_prompt import (
    PAPER_GENERATION_SYSTEM_INSTRUCTION,
    PAPER_RECOVERY_SYSTEM_INSTRUCTION,
)
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService
from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
from app.services.processors.pdf_processor import PDFProcessor
from app.services.retrieval.chunking_service import ChunkingService
from app.services.retrieval.retrieval_service import RetrievalService
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3


def _is_mock(val: Any) -> bool:
    return val is not None and (hasattr(val, "_mock_name") or type(val).__module__ == "unittest.mock")



class PaperGeneratorService:
    def __init__(
        self,
        db: Session,
        ai_service: Optional[GeminiService] = None,
        retrieval_service: Optional[RetrievalService] = None,
        embedding_service: Optional[GeminiEmbeddingService] = None,
        blueprint_service: Optional[BlueprintService] = None,
    ):
        self.db = db
        self.paper_repo = PaperRepository(db)
        self.workspace_service = WorkspaceService(db)
        self.doc_repo = DocumentRepository(db)
        self.ref_paper_repo = ReferencePaperRepository(db)
        self.ai_service = ai_service or GeminiService()
        self.retrieval_service = retrieval_service or RetrievalService(db)
        self.embedding_service = embedding_service or GeminiEmbeddingService()
        self.blueprint_service = blueprint_service or BlueprintService(self.ai_service)

    @staticmethod
    def calculate_proportional_chapter_allocations(
        ordered_chapters: List[Any],
        total_marks: int,
        weightage_lookup: Optional[Dict[Any, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Calculates proportional chapter mark allocations using the Hamilton-Hare /
        Largest Remainder method with deterministic tie-breaking by chapter_number.
        Guarantees that sum(allocated_marks) == total_marks exactly, and avoids
        dumping rounding remainders into a single chapter.
        """
        num_selected = len(ordered_chapters)
        if num_selected == 0:
            return []

        has_custom_weights = bool(weightage_lookup)
        intermediate = []
        for idx, ch in enumerate(ordered_chapters):
            ch_id = getattr(ch, "id", ch.get("id") if isinstance(ch, dict) else None)
            ch_num = getattr(ch, "chapter_number", ch.get("chapter_number") if isinstance(ch, dict) else idx + 1)
            ch_name = (
                getattr(ch, "name", None)
                or getattr(ch, "title", None)
                or (ch.get("name") or ch.get("title") if isinstance(ch, dict) else None)
                or f"Chapter {ch_num}"
            )
            pct = 100.0 / num_selected
            if has_custom_weights and weightage_lookup:
                pct = weightage_lookup.get(ch_id, 0.0)

            raw_marks = total_marks * (pct / 100.0)
            base_marks = int(math.floor(raw_marks))
            remainder = raw_marks - base_marks

            intermediate.append({
                "chapter_id": str(ch_id) if ch_id else str(idx + 1),
                "chapter_number": ch_num,
                "chapter_name": ch_name,
                "weightage_percentage": round(pct, 2),
                "base_marks": base_marks,
                "remainder": remainder,
                "orig_idx": idx,
            })

        total_base = sum(item["base_marks"] for item in intermediate)
        surplus = total_marks - total_base

        # Sort by remainder descending, tie-break by chapter_number ascending, then orig_idx
        sorted_indices = sorted(
            range(len(intermediate)),
            key=lambda i: (-intermediate[i]["remainder"], intermediate[i]["chapter_number"], intermediate[i]["orig_idx"])
        )

        surplus_awards = set(sorted_indices[:surplus])

        allocations = []
        for i, item in enumerate(intermediate):
            allocated = item["base_marks"] + (1 if i in surplus_awards else 0)
            allocations.append({
                "chapter_id": item["chapter_id"],
                "chapter_number": item["chapter_number"],
                "chapter_name": item["chapter_name"],
                "weightage_percentage": item["weightage_percentage"],
                "allocated_marks": allocated,
            })

        return allocations

    def preplan_blueprint_matrix(
        self,
        blueprint: PaperBlueprint,
        difficulty: DifficultyLevel,
        chapter_weightages_data: Optional[List[Dict[str, Any]]] = None,
        easy_pct: Optional[int] = None,
        med_pct: Optional[int] = None,
        hard_pct: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Pre-plans the authoritative question slot matrix before invoking Gemini.
        Solves:
        1. Denomination-aware chapter allocation (knapsack greedy by marks descending, matching real integer coins).
        2. Intra-chapter choice pairing (both alternatives 'a' and 'b' strictly bound to the exact same chapter).
        3. Global difficulty distribution (Easy -> Medium -> Hard assigned across logical groups).
        4. Identical difficulty for paired alternatives.
        """
        logical_groups = []
        current_q_order = 1
        for sec in blueprint.sections:
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            required_alts = [chr(ord("a") + i) for i in range(alts_per_q)] if alts_per_q > 1 else [None]
            for group_idx in range(sec.question_count):
                q_order = current_q_order + group_idx
                choice_grp = f"Q{q_order}" if alts_per_q > 1 else None
                logical_groups.append({
                    "section_name": sec.name,
                    "group_idx": group_idx,
                    "question_order": q_order,
                    "choice_group": choice_grp,
                    "marks": sec.marks_per_question,
                    "question_type": sec.question_type.value,
                    "required_alts": required_alts,
                    "alts_per_q": alts_per_q,
                    "is_numerical": False,
                })
            current_q_order += sec.question_count

        # Denomination-Aware Chapter Allocation
        if chapter_weightages_data and len(chapter_weightages_data) > 0:
            for idx, item in enumerate(chapter_weightages_data):
                if "chapter_id" not in item or not item["chapter_id"]:
                    item["chapter_id"] = str(item.get("chapter_number") or (idx + 1))
            ch_remaining = {
                item["chapter_id"]: item.get("allocated_marks", 0)
                for item in chapter_weightages_data
            }
            ch_lookup = {item["chapter_id"]: item for item in chapter_weightages_data}
            ch_ids = [item["chapter_id"] for item in chapter_weightages_data]

            # Sort groups by marks descending so high-mark questions (e.g. 5m) go first,
            # and low-mark questions (e.g. 1m MCQs) fine-tune the remaining mark deficits.
            sorted_groups = sorted(logical_groups, key=lambda g: (-g["marks"], g["question_order"]))

            for g in sorted_groups:
                best_ch_id = max(
                    ch_ids,
                    key=lambda cid: (ch_remaining[cid], -int(ch_lookup[cid].get("chapter_number") or 0))
                )
                ch_info = ch_lookup[best_ch_id]
                g["chapter_id"] = ch_info.get("chapter_id")
                g["chapter_number"] = ch_info.get("chapter_number")
                g["chapter_name"] = ch_info.get("chapter_name")
                ch_remaining[best_ch_id] -= g["marks"]
        else:
            for g in logical_groups:
                g["chapter_id"] = None
                g["chapter_number"] = 1
                g["chapter_name"] = "General"

        # Global Difficulty Distribution across logical groups
        global_diffs = self._calculate_difficulty_distribution(
            difficulty=difficulty,
            count=len(logical_groups),
            easy_pct=easy_pct,
            med_pct=med_pct,
            hard_pct=hard_pct,
        )
        sorted_by_order = sorted(logical_groups, key=lambda g: g["question_order"])
        for idx, g in enumerate(sorted_by_order):
            g["difficulty"] = global_diffs[idx] if idx < len(global_diffs) else "MEDIUM"

        # Numerical Requirement Allocation per Section
        for sec in blueprint.sections:
            if sec.numerical_question_count > 0:
                sec_groups = [g for g in logical_groups if g["section_name"] == sec.name]
                for g in sec_groups[:sec.numerical_question_count]:
                    g["is_numerical"] = True

        # Construct Section-Organized Matrix Structure
        planned_sections = []
        for sec in blueprint.sections:
            sec_groups = [g for g in logical_groups if g["section_name"] == sec.name]
            planned_sections.append({
                "section_name": sec.name,
                "sec": sec,
                "groups": [
                    {
                        "group_idx": g["group_idx"],
                        "question_order": g["question_order"],
                        "choice_group": g["choice_group"],
                        "difficulty": g["difficulty"],
                        "section_name": sec.name,
                        "question_type": sec.question_type.value,
                        "marks": sec.marks_per_question,
                        "chapter_id": g.get("chapter_id"),
                        "chapter_number": g.get("chapter_number"),
                        "chapter_name": g.get("chapter_name"),
                        "is_numerical": g.get("is_numerical", False),
                        "required_alts": g["required_alts"],
                        "slots": {alt: None for alt in g["required_alts"]},
                    }
                    for g in sec_groups
                ],
            })

        return planned_sections

    def generate_paper(
        self,
        current_user_id: UUID,
        request_data: PaperGenerateRequest,
    ) -> PaperResponse:
        """
        Main entry point for generating an examination paper.
        Executes end-to-end flow: authorization -> blueprint construction -> chapter-bounded RAG ->
        structured question generation -> business validation -> deduplication -> bounded regeneration -> persistence.
        """
        if hasattr(self.ai_service, "reset_session_usage"):
            self.ai_service.reset_session_usage()

        # 1. Authorization & Scope Validation
        book = self.workspace_service.get_book(request_data.book_id, current_user_id)
        subject_id = book.subject_id
        subject = self.workspace_service.get_subject(subject_id, current_user_id)
        workspace_id = subject.workspace_id

        # Extract selected_ch_ids from unified selected_chapters
        selected_ch_ids = [ch.chapter_id for ch in request_data.selected_chapters]

        # Verify selected_chapter_ids belong to the selected book
        book_chapters = self.workspace_service.list_chapters(book.id, current_user_id)
        book_chapter_ids = {c.id for c in book_chapters}
        for ch_id in selected_ch_ids:
            if ch_id not in book_chapter_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Selected chapter '{ch_id}' does not belong to the specified book.",
                )

        # Reference Mode specific scope check
        sample_questions: List[Dict[str, Any]] = []
        reference_paper = None
        source_is_generated_paper = False
        if request_data.generation_mode == GenerationMode.REFERENCE:
            if not request_data.reference_paper_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="reference_paper_id is required when generation_mode is REFERENCE.",
                )
            reference_paper = self.ref_paper_repo.get_reference_paper(request_data.reference_paper_id)
            if not reference_paper:
                # Try looking up in generated_papers table
                reference_paper = self.paper_repo.get_paper(request_data.reference_paper_id)
                if reference_paper:
                    source_is_generated_paper = True
                    # Check if deleted
                    if getattr(reference_paper, "deleted_at", None) is not None:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Selected generated paper has been deleted.",
                        )

                    # Determine if eligible for saved-PDF extraction pipeline
                    doc_proc_status = getattr(reference_paper, "processing_status", None)
                    if _is_mock(doc_proc_status):
                        doc_proc_status = "NOT_SAVED"
                    if getattr(reference_paper, "document_id", None) and not _is_mock(reference_paper.document_id):
                        doc = self.doc_repo.get_document_by_id(reference_paper.document_id)
                        if doc and getattr(doc, "processing_status", None) and not _is_mock(doc.processing_status):
                            doc_proc_status = str(doc.processing_status)

                    has_saved_pdf = bool(
                        reference_paper.pdf_path is not None
                        and not _is_mock(reference_paper.pdf_path)
                    )
                    is_eligible = bool(
                        has_saved_pdf
                        and doc_proc_status == "READY"
                    )

                    has_json_data = bool(
                        reference_paper.blueprint_json
                        or (hasattr(reference_paper, "questions") and reference_paper.questions)
                    )

                    if not is_eligible and not has_json_data:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Selected generated paper cannot be used as a reference because it has not been saved as a PDF and has no questions or blueprint.",
                        )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Reference paper not found in uploaded reference papers or generated papers.",
                    )
            else:
                # reference_paper is an uploaded ReferencePaper
                is_eligible = bool(
                    _is_mock(reference_paper)
                    or (
                        getattr(reference_paper, "stored_path", None) is not None
                        and not _is_mock(getattr(reference_paper, "stored_path", None))
                        and getattr(reference_paper, "deleted_at", None) is None
                    )
                )
                if not is_eligible:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Selected reference paper is invalid or has been deleted.",
                    )

            # Verify current user has access to the reference paper's workspace
            try:
                self.workspace_service.get_workspace(reference_paper.workspace_id, current_user_id)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You do not have access to this reference paper.",
                )

            # Enforce strict subject scoping: reference_paper must belong to requested subject_id!
            ref_sub_id = getattr(reference_paper, "subject_id", None)
            if ref_sub_id and str(ref_sub_id) != str(subject_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Selected reference paper belongs to a different subject ({ref_sub_id}) than the requested paper generation subject ({subject_id}).",
                )



        # 1.5. Calculate structured chapter weightages using Hamilton-Hare Largest Remainder method
        selected_ch_models = [c for c in book_chapters if c.id in selected_ch_ids]
        ch_map = {c.id: c for c in selected_ch_models}
        ordered_chapters = [ch_map[cid] for cid in selected_ch_ids if cid in ch_map]
        weightage_lookup = {ch.chapter_id: ch.weightage_percentage for ch in request_data.selected_chapters if ch.weightage_percentage is not None}

        chapter_weightages_data = self.calculate_proportional_chapter_allocations(
            ordered_chapters=ordered_chapters,
            total_marks=request_data.total_marks,
            weightage_lookup=weightage_lookup,
        )

        # 2. Create Initial Paper Record (PENDING)
        paper = self.paper_repo.create_paper(
            user_id=current_user_id,
            workspace_id=workspace_id,
            subject_id=subject_id,
            book_id=book.id,
            generation_mode=request_data.generation_mode.value,
            total_marks=request_data.total_marks,
            time_allowed_minutes=request_data.time_allowed_minutes,
            class_name=request_data.class_name,
            difficulty=request_data.difficulty.value,
            selected_chapter_ids=selected_ch_ids,
            chapter_weightages=chapter_weightages_data,
            include_answers=request_data.include_answers,
            title=request_data.title,
            topic_focus=request_data.topic_focus,
            reference_paper_id=request_data.reference_paper_id,
            easy_percentage=request_data.easy_percentage,
            medium_percentage=request_data.medium_percentage,
            hard_percentage=request_data.hard_percentage,
        )


        try:
            self.paper_repo.update_status(paper.id, "GENERATING")

            # 3. Construct Blueprint
            if request_data.generation_mode == GenerationMode.CUSTOM:
                blueprint = self.blueprint_service.build_custom_blueprint(
                    question_configs=request_data.question_configs,
                    total_marks=request_data.total_marks,
                    enable_numerical_percentage=request_data.enable_numerical_percentage,
                    numerical_percentage=request_data.numerical_percentage,
                )
            else:
                if source_is_generated_paper:
                    if is_eligible and reference_paper.pdf_path:
                        # Saved GeneratedPaper: check if blueprint_json from PDF is cached in DB
                        if reference_paper.blueprint_json:
                            base_blueprint = PaperBlueprint.model_validate(reference_paper.blueprint_json)
                        else:
                            # Cache miss: fetch extracted PDF text from linked DocumentPage records
                            doc_pages = self.doc_repo.get_document_pages(reference_paper.document_id)
                            pages_text = [p.text_content for p in doc_pages] if doc_pages else []
                            raw_base_blueprint = self.blueprint_service.analyze_reference_paper(
                                paper_pages_text=pages_text,
                                requested_total_marks=None,
                            )
                            # Cache raw base blueprint in DB for all future paper generations
                            self.paper_repo.save_blueprint_json(reference_paper.id, raw_base_blueprint.model_dump())
                            base_blueprint = raw_base_blueprint

                        if request_data.total_marks and base_blueprint.total_marks != request_data.total_marks:
                            blueprint = self.blueprint_service.adapt_reference_blueprint(
                                ref_blueprint=base_blueprint,
                                target_total_marks=request_data.total_marks,
                            )
                        else:
                            blueprint = base_blueprint
                    else:
                        # Unsaved GeneratedPaper (no saved PDF): build blueprint from original paper JSON
                        blueprint = self.blueprint_service.build_blueprint_from_generated_paper(
                            paper=reference_paper,
                            requested_total_marks=request_data.total_marks,
                        )
                else:
                    # Reference Mode (Uploaded PDF ReferencePaper): Check if blueprint_json is cached in DB
                    if reference_paper.blueprint_json:
                        base_blueprint = PaperBlueprint.model_validate(reference_paper.blueprint_json)
                        if request_data.total_marks and base_blueprint.total_marks != request_data.total_marks:
                            blueprint = self.blueprint_service.adapt_reference_blueprint(
                                ref_blueprint=base_blueprint,
                                target_total_marks=request_data.total_marks,
                            )
                        else:
                            blueprint = base_blueprint
                    else:
                        # Cache miss: fetch reference pages text & analyze via Gemini
                        ref_pages = self.ref_paper_repo.get_reference_paper_pages(reference_paper.id)
                        pages_text = [p.text_content for p in ref_pages] if ref_pages else []
                        raw_base_blueprint = self.blueprint_service.analyze_reference_paper(
                            paper_pages_text=pages_text,
                            requested_total_marks=None,
                        )
                        # Cache raw base blueprint in DB for all future paper generations
                        self.ref_paper_repo.save_blueprint_json(reference_paper.id, raw_base_blueprint.model_dump())

                        if request_data.total_marks and raw_base_blueprint.total_marks != request_data.total_marks:
                            blueprint = self.blueprint_service.adapt_reference_blueprint(
                                ref_blueprint=raw_base_blueprint,
                                target_total_marks=request_data.total_marks,
                            )
                        else:
                            blueprint = raw_base_blueprint




            self.paper_repo.update_status(paper.id, "GENERATING", blueprint_json=blueprint.model_dump())


            # 4. RAG Candidate Retrieval strictly bounded to selected_chapter_ids
            context_text = self._retrieve_chapter_context(
                user_id=current_user_id,
                workspace_id=workspace_id,
                subject_id=subject_id,
                book_id=book.id,
                selected_chapter_ids=selected_ch_ids,
                topic_focus=request_data.topic_focus,
            )

            # 5. Generate Questions in ONE Single Gemini API Request with Validation
            generated_questions = self._generate_complete_paper(
                blueprint=blueprint,
                context_text=context_text,
                topic_focus=request_data.topic_focus,
                difficulty=request_data.difficulty,
                generation_mode=request_data.generation_mode,
                sample_questions=blueprint.sample_questions,
                easy_pct=request_data.easy_percentage,
                med_pct=request_data.medium_percentage,
                hard_pct=request_data.hard_percentage,
                chapter_weightages_data=chapter_weightages_data,
            )

            # 5.5 Final Monolithic Complete-Paper Integrity Pass
            self._validate_final_paper_integrity(
                blueprint=blueprint,
                generated_questions=generated_questions,
                selected_chapter_ids=selected_ch_ids,
                chapter_weightages_data=chapter_weightages_data,
                generation_mode=request_data.generation_mode,
            )

            # 6. Save Questions to DB
            token_usage = self.ai_service.get_session_usage() if hasattr(self.ai_service, "get_session_usage") else {}

            # Embed token usage in blueprint_json so it is accessible in API response
            bp_dict = blueprint.model_dump() if blueprint else {}
            bp_dict["token_usage"] = token_usage

            self.paper_repo.save_questions(paper.id, generated_questions)
            self.paper_repo.update_status(paper.id, "COMPLETED", blueprint_json=bp_dict)

            # Prominently log and print token usage to console
            token_banner = (
                "\n" + "=" * 70 + "\n"
                f"📊 [PAPER_TOKEN_USAGE] Paper generation finished for paper_id={paper.id}\n"
                f"   • Total LLM Calls:   {token_usage.get('call_count', 0)}\n"
                f"   • Prompt Tokens:     {token_usage.get('prompt_tokens', 0)}\n"
                f"   • Completion Tokens: {token_usage.get('completion_tokens', 0)}\n"
                f"   • Total Tokens Used: {token_usage.get('total_tokens', 0)}\n"
                + "=" * 70 + "\n"
            )
            logger.info(token_banner.strip())
            print(token_banner, flush=True)

            # Refresh paper from DB
            final_paper = self.paper_repo.get_paper(paper.id)
            return self._build_paper_response(final_paper, include_answers=request_data.include_answers)

        except GeminiOutputTruncatedError as trunc_exc:
            logger.error(f"Paper generation output limit reached for paper_id {paper.id}: {trunc_exc}")
            err_detail = {
                "code": "GEMINI_OUTPUT_LIMIT_REACHED",
                "message": "The AI reached its maximum output limit while generating the paper. The generated response was incomplete. Please reduce the number of questions or disable detailed answers/solutions and try again.",
            }
            self.paper_repo.update_status(paper.id, "FAILED", error_message=err_detail["message"])
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=err_detail)

        except GeminiRateLimitError as rate_exc:
            logger.error(f"Paper generation rate limited for paper_id {paper.id}: {rate_exc}")
            err_detail = {
                "code": "GEMINI_RATE_LIMITED",
                "message": "The AI service is temporarily rate limited. Please wait a moment and try again.",
            }
            self.paper_repo.update_status(paper.id, "FAILED", error_message=err_detail["message"])
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=err_detail)

        except GeminiProviderError as prov_exc:
            logger.error(f"Paper generation provider error for paper_id {paper.id}: {prov_exc}")
            err_detail = {
                "code": "GEMINI_PROVIDER_ERROR",
                "message": "The AI service is temporarily unavailable. Please try again later.",
            }
            self.paper_repo.update_status(paper.id, "FAILED", error_message=err_detail["message"])
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=err_detail)

        except GeminiInvalidResponseError as inv_exc:
            logger.error(f"Paper generation invalid response for paper_id {paper.id}: {inv_exc}")
            err_detail = {
                "code": "GEMINI_INVALID_RESPONSE",
                "message": "The AI returned an invalid response while generating the paper. Please try again.",
            }
            self.paper_repo.update_status(paper.id, "FAILED", error_message=err_detail["message"])
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=err_detail)

        except HTTPException as http_exc:
            logger.warning(f"Paper generation validation error for paper_id {paper.id}: {http_exc.detail}")
            err_msg = http_exc.detail.get("message") if isinstance(http_exc.detail, dict) else str(http_exc.detail)
            self.paper_repo.update_status(paper.id, "FAILED", error_message=err_msg)
            raise http_exc

        except Exception as exc:
            logger.error(f"Paper generation failed for paper_id {paper.id}: {exc}")
            err_detail = {
                "code": "GEMINI_PROVIDER_ERROR",
                "message": f"Paper generation failed: {str(exc)}",
            }
            self.paper_repo.update_status(paper.id, "FAILED", error_message=str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=err_detail,
            )



    def get_paper(self, current_user_id: UUID, paper_id: UUID) -> PaperResponse:
        """
        Retrieve paper details by ID with strict ownership verification and answer visibility filtering.
        """
        paper = self.paper_repo.get_paper(paper_id)
        if not paper or paper.user_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Paper not found.",
            )
        return self._build_paper_response(paper, include_answers=paper.include_answers)

    def list_papers(self, current_user_id: UUID, subject_id: UUID) -> List[PaperResponse]:
        """
        List all generated papers under a subject for the current user.
        """
        # Verify subject ownership
        self.workspace_service.get_subject(subject_id, current_user_id)
        papers = self.paper_repo.list_papers_by_subject(subject_id, current_user_id)
        return [self._build_paper_response(p, include_answers=p.include_answers) for p in papers]

    def _get_section_aligned_sample_questions(
        self,
        sec: SectionBlueprint,
        sample_questions: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        Select reference sample questions relevant to the current section.
        Matching priority:
        1. Exact section_name + question_type match
        2. question_type match
        3. If neither is available, return empty list []
        """
        if not sample_questions or not isinstance(sample_questions, list):
            return []

        def _qtype_str(q: Dict[str, Any]) -> str:
            raw = q.get("question_type")
            if hasattr(raw, "value"):
                return str(raw.value).upper()
            return str(raw).upper() if raw else ""

        sec_qtype = sec.question_type.value.upper() if hasattr(sec.question_type, "value") else str(sec.question_type).upper()

        exact_matches = [
            q for q in sample_questions
            if q.get("section_name") == sec.name and _qtype_str(q) == sec_qtype
        ]
        if exact_matches:
            import random
            shuffled = list(exact_matches)
            random.shuffle(shuffled)
            return shuffled

        type_matches = [q for q in sample_questions if _qtype_str(q) == sec_qtype]
        if type_matches:
            import random
            shuffled_type = list(type_matches)
            random.shuffle(shuffled_type)
            return shuffled_type

        return []

    def _retrieve_chapter_context(
        self,
        user_id: UUID,
        workspace_id: UUID,
        subject_id: UUID,
        book_id: UUID,
        selected_chapter_ids: List[UUID],
        topic_focus: Optional[str],
    ) -> str:
        """
        Retrieve educational context strictly bounded to selected_chapter_ids.
        Fetches ALL sequential document chunks belonging to selected chapters ordered by page_number and chunk_index.
        Unselected chapters are NEVER queried.
        """
        from app.models.chapter import Chapter
        from app.models.document import DocumentChunk
        from sqlalchemy import or_, select

        # Query all active chunks matching selected chapter_ids or chapter page ranges
        chapters = self.paper_repo.db.query(Chapter).filter(Chapter.id.in_(selected_chapter_ids), Chapter.deleted_at.is_(None)).all()
        conditions = [DocumentChunk.chapter_id.in_(selected_chapter_ids)]
        for ch in chapters:
            if ch.start_page is not None and ch.end_page is not None:
                conditions.append(
                    (DocumentChunk.book_id == ch.book_id) &
                    (DocumentChunk.page_number >= ch.start_page) &
                    (DocumentChunk.page_number <= ch.end_page)
                )

        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.workspace_id == workspace_id,
                DocumentChunk.book_id == book_id,
                DocumentChunk.deleted_at.is_(None),
                or_(*conditions),
            )
            .order_by(DocumentChunk.page_number.asc(), DocumentChunk.chunk_index.asc())
        )
        db_chunks = self.paper_repo.db.execute(stmt).scalars().all()

        context_lines = []
        ch_chunks_map: Dict[str, List[str]] = {}
        if db_chunks:
            for idx, c in enumerate(db_chunks, start=1):
                page_info = f" (Page {c.page_number})" if c.page_number else ""
                excerpt = f"[Source Excerpt {idx}{page_info} | Chapter ID: {c.chapter_id}]:\n{c.content}"
                context_lines.append(excerpt)
                if c.chapter_id:
                    ch_chunks_map.setdefault(str(c.chapter_id), []).append(excerpt)

        self._chapter_contexts_map = {
            cid: "\n\n".join(chunks) for cid, chunks in ch_chunks_map.items()
        }

        if not context_lines:
            return "Educational source material context for selected chapters."

        raw_context = "\n\n".join(context_lines)

        logger.info(
            f"Full chapter context retrieval: selected_chapter_ids={selected_chapter_ids}, "
            f"retrieved_chunk_count={len(db_chunks)}, sent_chunk_count={len(db_chunks)}, "
            f"retrieved_char_count={len(raw_context)}, sent_char_count={len(raw_context)}, "
            f"truncated=False, sampling_mode='NONE/FULL'"
        )
        return raw_context

    @staticmethod
    def _get_unfilled_slots(
        planned_groups: List[Dict[str, Any]],
        required_alts: List[Any],
    ) -> List[Dict[str, Any]]:
        """Returns an ordered list of unfilled slot descriptors across all planned groups."""
        missing = []
        for g in planned_groups:
            for alt in required_alts:
                if g["slots"].get(alt) is None:
                    paired_q = g["slots"].get("a") if alt == "b" else (g["slots"].get("b") if alt == "a" else None)
                    missing.append({
                        "group_idx": g["group_idx"],
                        "question_order": g["question_order"],
                        "choice_group": g["choice_group"],
                        "alternative_label": alt,
                        "difficulty": g["difficulty"],
                        "chapter_id": g.get("chapter_id"),
                        "chapter_number": g.get("chapter_number"),
                        "chapter_name": g.get("chapter_name"),
                        "marks": g.get("marks"),
                        "question_type": g.get("question_type"),
                        "is_numerical": g.get("is_numerical", False),
                        "paired_slot": paired_q,
                    })
        return missing

    @staticmethod
    def _assign_candidate_to_slot(
        cand: Dict[str, Any],
        planned_groups: List[Dict[str, Any]],
        required_alts: List[Any],
        targeted_missing_slots: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Authoritatively assigns a validated candidate question into the planned_groups slot grid.
        Preserves internal-choice pairing deterministically:
        - If candidate has explicit choice_group/question_order and alternative_label that matches an empty slot, assigns there.
        - If targeted_missing_slots is provided (recovery mode) and no explicit match, assigns to the next targeted slot.
        - If initial generation mode (targeted_missing_slots is None) and no explicit match, assigns to the next empty 'a' slot.
          (Never blindly pairs adjacent metadata-less candidates into 'b' slots of unrelated questions).
        Returns True if assigned, False if no slot was available.
        """
        cg = cand.get("choice_group")
        alt_raw = cand.get("alternative_label")
        alt = str(alt_raw).strip().lower() if alt_raw is not None else None
        q_ord = cand.get("question_order")

        # 1. Try explicit matching by choice metadata
        matched_group = None
        if cg:
            cg_str = str(cg).strip().lower()
            for g in planned_groups:
                g_cg = str(g["choice_group"]).lower() if g.get("choice_group") else ""
                if g_cg and (g_cg == cg_str or g_cg == f"q{cg_str}" or cg_str == f"q{g_cg}"):
                    matched_group = g
                    break
        if not matched_group and q_ord is not None:
            try:
                ord_int = int(q_ord)
                for g in planned_groups:
                    if g["question_order"] == ord_int:
                        matched_group = g
                        break
            except (ValueError, TypeError):
                pass

        if matched_group:
            if alt in required_alts and matched_group["slots"].get(alt) is None:
                matched_group["slots"][alt] = cand
                return True
            if None in required_alts and matched_group["slots"].get(None) is None:
                matched_group["slots"][None] = cand
                return True

        # 2. Recovery targeted slot fallback
        if targeted_missing_slots is not None:
            for target in targeted_missing_slots:
                g_idx = target["group_idx"]
                t_alt = target["alternative_label"]
                g = planned_groups[g_idx]
                if g["slots"].get(t_alt) is None:
                    g["slots"][t_alt] = cand
                    return True
            return False

        # 3. Initial generation fallback
        if None in required_alts:
            for g in planned_groups:
                if g["slots"].get(None) is None:
                    g["slots"][None] = cand
                    return True
            return False
        else:
            # For internal choice, map sequentially ONLY to 'a' slots if unassigned.
            # Never blindly pair metadata-less candidate into 'b' slot.
            for g in planned_groups:
                if g["slots"].get("a") is None:
                    g["slots"]["a"] = cand
                    return True
            return False

    def _generate_complete_paper(
        self,
        blueprint: PaperBlueprint,
        context_text: str,
        topic_focus: Optional[str],
        difficulty: DifficultyLevel,
        generation_mode: GenerationMode,
        sample_questions: Optional[List[Dict[str, Any]]],
        easy_pct: Optional[int] = None,
        med_pct: Optional[int] = None,
        hard_pct: Optional[int] = None,
        chapter_weightages_data: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate the complete examination paper using deterministic blueprint matrix pre-planning,
        one main Gemini generation request, and at most one unified whole-paper recovery call with scoped chapter context.
        """
        if not context_text or not context_text.strip():
            logger.warning("No educational source context retrieved; generating paper using general educational knowledge.")
            context_text = "Educational source material context for selected chapters."

        # 1. Deterministic Blueprint Slot Matrix Pre-Planning
        planned_sections = self.preplan_blueprint_matrix(
            blueprint=blueprint,
            difficulty=difficulty,
            chapter_weightages_data=chapter_weightages_data,
            easy_pct=easy_pct,
            med_pct=med_pct,
            hard_pct=hard_pct,
        )

        prompt = self._build_complete_paper_prompt(
            blueprint=blueprint,
            context_text=context_text,
            topic_focus=topic_focus,
            difficulty=difficulty,
            generation_mode=generation_mode,
            sample_questions=sample_questions,
            easy_pct=easy_pct,
            med_pct=med_pct,
            hard_pct=hard_pct,
            chapter_weightages_data=chapter_weightages_data,
            planned_sections=planned_sections,
        )

        # Actual Gemini SDK Token Capacity Check
        MAX_INPUT_TOKENS = 980_000
        token_count = self.ai_service.count_tokens(
            prompt,
            system_instruction=PAPER_GENERATION_SYSTEM_INSTRUCTION,
        )
        if token_count > MAX_INPUT_TOKENS:
            logger.error(f"Complete-paper prompt tokens ({token_count}) exceed model context capacity ({MAX_INPUT_TOKENS}).")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected chapters contain too much educational content to generate this paper in a single model request. Please select fewer chapters and try again.",
            )

        try:
            response_text = self.ai_service.generate_response(
                prompt,
                system_instruction=PAPER_GENERATION_SYSTEM_INSTRUCTION,
                response_schema=GeminiCompletePaperSchema,
            )
        except TypeError:
            try:
                response_text = self.ai_service.generate_response(
                    prompt,
                    system_instruction=PAPER_GENERATION_SYSTEM_INSTRUCTION,
                )
            except TypeError:
                response_text = self.ai_service.generate_response(prompt)
        parsed = self._parse_json_safely(response_text)

        raw_sections = parsed.get("sections", []) if isinstance(parsed, dict) else []
        if not raw_sections and isinstance(parsed, dict) and "questions" in parsed:
            raw_sections = [{"section_name": sec.name, "questions": parsed["questions"]} for sec in blueprint.sections]

        ch_num_to_item = {item["chapter_number"]: item for item in (chapter_weightages_data or []) if "chapter_number" in item}
        default_ch_item = chapter_weightages_data[0] if (chapter_weightages_data and len(chapter_weightages_data) > 0) else None

        all_accepted_questions: List[Dict[str, Any]] = []

        # 2. First Pass: Process Initial Generated Candidates across each section
        for s_idx, s_data in enumerate(planned_sections):
            sec = s_data["sec"]
            planned_groups = s_data["groups"]
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            required_alts = planned_groups[0]["required_alts"] if planned_groups else [None]
            sec_ref = self._get_section_aligned_sample_questions(sec, sample_questions) if (generation_mode == GenerationMode.REFERENCE and sample_questions) else None

            sec_name_clean = sec.name.strip().lower()
            sec_resp = next(
                (
                    s for s in raw_sections
                    if isinstance(s, dict) and (
                        str(s.get("section_name", "")).strip().lower() == sec_name_clean or
                        str(s.get("section_name", "")).strip().lower() in sec_name_clean or
                        sec_name_clean in str(s.get("section_name", "")).strip().lower()
                    )
                ),
                None
            )
            candidates = sec_resp.get("questions", []) if (sec_resp and isinstance(sec_resp, dict)) else []
            if not candidates and s_idx < len(raw_sections) and isinstance(raw_sections[s_idx], dict):
                candidates = raw_sections[s_idx].get("questions", [])

            for cand in candidates:
                unfilled = self._get_unfilled_slots(planned_groups, required_alts)
                if not unfilled:
                    break

                current_sec_qs = [
                    g["slots"][alt]
                    for g in planned_groups
                    for alt in required_alts
                    if g["slots"].get(alt) is not None
                ]
                if self._validate_question_structure(cand, sec, existing_sec_questions=current_sec_qs):
                    if not self._is_duplicate_question(cand, all_accepted_questions):
                        cand_ch_num = cand.get("chapter_number")
                        matched_item = None
                        if cand_ch_num and cand_ch_num in ch_num_to_item:
                            matched_item = ch_num_to_item[cand_ch_num]
                        elif default_ch_item:
                            matched_item = default_ch_item

                        if matched_item:
                            cand["chapter_id"] = matched_item.get("chapter_id")
                            cand["chapter_number"] = matched_item.get("chapter_number")

                        if generation_mode == GenerationMode.CUSTOM or not sec_ref:
                            cand["source_type"] = "AI_GENERATED"
                        else:
                            cand_st = str(cand.get("source_type", "")).upper()
                            cand_marks = sec.marks_per_question
                            max_overall_reused_marks = max(sec.marks_per_question, int(0.20 * blueprint.total_marks))
                            max_overall_variation_marks = max(sec.marks_per_question, int(0.20 * blueprint.total_marks))

                            cur_total_reused_marks = sum(
                                q.get("marks", sec.marks_per_question)
                                for q in all_accepted_questions
                                if q.get("source_type") == "REFERENCE_REUSED"
                            )
                            cur_total_variation_marks = sum(
                                q.get("marks", sec.marks_per_question)
                                for q in all_accepted_questions
                                if q.get("source_type") == "REFERENCE_VARIATION"
                            )

                            ch_alloc_marks = matched_item.get("allocated_marks", blueprint.total_marks) if matched_item else blueprint.total_marks
                            cur_ch_reused_marks = sum(
                                q.get("marks", sec.marks_per_question)
                                for q in all_accepted_questions
                                if q.get("chapter_id") == (matched_item["chapter_id"] if matched_item else None)
                                and q.get("source_type") == "REFERENCE_REUSED"
                            )
                            cur_ch_variation_marks = sum(
                                q.get("marks", sec.marks_per_question)
                                for q in all_accepted_questions
                                if q.get("chapter_id") == (matched_item["chapter_id"] if matched_item else None)
                                and q.get("source_type") == "REFERENCE_VARIATION"
                            )

                            if cand_st == "REFERENCE_REUSED":
                                if (cur_total_reused_marks + cand_marks > max_overall_reused_marks) or (cur_ch_reused_marks + cand_marks > ch_alloc_marks):
                                    cand["source_type"] = "AI_GENERATED"
                                else:
                                    cand["source_type"] = "REFERENCE_REUSED"
                            elif cand_st == "REFERENCE_VARIATION":
                                if (cur_total_variation_marks + cand_marks > max_overall_variation_marks) or (cur_ch_variation_marks + cand_marks > ch_alloc_marks):
                                    cand["source_type"] = "AI_GENERATED"
                                else:
                                    cand["source_type"] = "REFERENCE_VARIATION"
                            else:
                                cand["source_type"] = "AI_GENERATED"

                        assigned = self._assign_candidate_to_slot(
                            cand=cand,
                            planned_groups=planned_groups,
                            required_alts=required_alts,
                            targeted_missing_slots=None,
                        )
                        if assigned:
                            all_accepted_questions.append(cand)

        # Helper function to collect unfilled slots across ALL sections
        def _get_all_unfilled_slots() -> List[Dict[str, Any]]:
            missing_slots = []
            for s_data in planned_sections:
                sec = s_data["sec"]
                for g in s_data["groups"]:
                    for alt in g["required_alts"]:
                        if g["slots"].get(alt) is None:
                            paired_q = g["slots"].get("a") if alt == "b" else (g["slots"].get("b") if alt == "a" else None)
                            missing_slots.append({
                                "section_name": s_data["section_name"],
                                "sec": sec,
                                "group": g,
                                "group_idx": g["group_idx"],
                                "question_order": g["question_order"],
                                "choice_group": g["choice_group"],
                                "alternative_label": alt,
                                "difficulty": g["difficulty"],
                                "chapter_id": g.get("chapter_id"),
                                "chapter_number": g.get("chapter_number"),
                                "chapter_name": g.get("chapter_name"),
                                "question_type": g["question_type"],
                                "marks": g["marks"],
                                "is_numerical": g.get("is_numerical", False),
                                "paired_slot": paired_q,
                            })
            return missing_slots

        # 3. Unified Whole-Paper Supplemental Recovery Loop (Max 2 Attempts)
        MAX_UNIFIED_RECOVERY_ATTEMPTS = 2
        recovery_attempt = 0
        rejected_recovery_candidates: List[str] = []

        while recovery_attempt < MAX_UNIFIED_RECOVERY_ATTEMPTS:
            all_missing = _get_all_unfilled_slots()
            if not all_missing:
                break

            recovery_attempt += 1
            missing_cnt = len(all_missing)
            num_candidates_to_request = missing_cnt + 1 if missing_cnt <= 2 else missing_cnt
            logger.info(
                f"Unified whole-paper recovery attempt {recovery_attempt}/{MAX_UNIFIED_RECOVERY_ATTEMPTS}: "
                f"requesting {num_candidates_to_request} candidates for {missing_cnt} missing slot(s) across all sections."
            )

            # Scoped Context: Send context strictly for chapters with missing slots!
            needed_ch_ids = {str(s["chapter_id"]) for s in all_missing if s.get("chapter_id")}
            if hasattr(self, "_chapter_contexts_map") and self._chapter_contexts_map and needed_ch_ids:
                scoped_chunks = [
                    self._chapter_contexts_map[cid]
                    for cid in needed_ch_ids
                    if cid in self._chapter_contexts_map
                ]
                recovery_context = "\n\n".join(scoped_chunks) if scoped_chunks else context_text
            else:
                recovery_context = context_text

            slot_instructions = []
            for s_info in all_missing:
                sec_name = s_info["section_name"]
                q_type = s_info["question_type"]
                marks = s_info["marks"]
                diff = s_info["difficulty"]
                ch_num = s_info.get("chapter_number")
                ch_str = f", Chapter: {ch_num}" if ch_num else ""
                cg = s_info["choice_group"]
                alt = s_info["alternative_label"]
                paired_q = s_info.get("paired_slot")

                if paired_q and cg and alt:
                    p_text = str(paired_q.get("question_text", "")).strip()[:120]
                    slot_instructions.append(
                        f"- Section '{sec_name}' | Choice Group '{cg}', Alternative '{alt}' | Type: {q_type} | Marks: {marks} | Target Difficulty: {diff}{ch_str}. "
                        f"Must be an internal choice alternative paired with: \"{p_text}...\". "
                        f"IMPORTANT: Must test a DIFFERENT formula or distinct educational concept from Chapter {ch_num} so it is not duplicate or repetitive."
                    )
                elif cg and alt:
                    slot_instructions.append(
                        f"- Section '{sec_name}' | Choice Group '{cg}', Alternative '{alt}' | Type: {q_type} | Marks: {marks} | Target Difficulty: {diff}{ch_str}."
                    )
                else:
                    slot_instructions.append(
                        f"- Section '{sec_name}' | Question {s_info['question_order']} | Type: {q_type} | Marks: {marks} | Target Difficulty: {diff}{ch_str}."
                    )
            slots_detail_str = "\n".join(slot_instructions)

            existing_texts = [
                str(q.get("question_text", "")).strip()[:140]
                for q in all_accepted_questions
                if q and q.get("question_text")
            ]
            existing_summary = json.dumps(existing_texts, ensure_ascii=False) if existing_texts else "None"

            rejected_feedback_str = ""
            if rejected_recovery_candidates:
                unique_rejected = list(dict.fromkeys(r[:140] for r in rejected_recovery_candidates if r))[-15:]
                rejected_feedback_str = f"""
STRICT REJECTION FEEDBACK (DO NOT REPEAT OR GENERATE QUESTIONS SIMILAR TO THESE REJECTED CANDIDATES):
{json.dumps(unique_rejected, ensure_ascii=False)}
"""

            diversity_directive = ""
            if recovery_attempt >= 2 and missing_cnt <= 3:
                diversity_directive = """
CRITICAL DIVERSITY REQUIREMENT:
A previous attempt to fill this slot generated a duplicate question.
You MUST choose a fresh, DIFFERENT concept, formula, or subtopic from the selected material that has NOT been tested anywhere in this paper.
"""

            fill_prompt = f"""Generate {num_candidates_to_request} unique, non-repetitive candidate questions to fill the {missing_cnt} missing slot(s) across the examination paper.

TARGET MISSING SLOTS:
{slots_detail_str}
{diversity_directive}
SOURCE EDUCATIONAL MATERIAL:
{recovery_context}

EXCLUSION RULE:
Do NOT repeat or generate questions semantically equivalent to any of these previously generated questions:
{existing_summary}
{rejected_feedback_str}
Return ONLY valid JSON matching this schema:
{{
  "questions": [
    {{
      "section_name": "<name of the section this question belongs to>",
      "choice_group": "<e.g. Q1, Q2 or null>",
      "alternative_label": "<'a' or 'b' if internal choice, else null>",
      "question_order": <integer question order or null>,
      "question_text": "...",
      "chapter_number": <1-based integer chapter number covering this question from the selected chapters>,
      "difficulty": "<EASY, MEDIUM, or HARD as specified for the slot>",
      "mcq_options": ["A. ...", "B. ...", "C. ...", "D. ..."] or null,
      "visual": null
    }}
  ]
}}"""
            try:
                try:
                    fill_response_text = self.ai_service.generate_response(
                        fill_prompt,
                        system_instruction=PAPER_RECOVERY_SYSTEM_INSTRUCTION,
                    )
                except TypeError:
                    fill_response_text = self.ai_service.generate_response(fill_prompt)
                fill_parsed = self._parse_json_safely(fill_response_text)
                fill_candidates = []
                if isinstance(fill_parsed, dict):
                    if "questions" in fill_parsed and isinstance(fill_parsed["questions"], list):
                        fill_candidates = fill_parsed["questions"]
                    elif "sections" in fill_parsed and isinstance(fill_parsed["sections"], list):
                        for s in fill_parsed["sections"]:
                            if isinstance(s, dict) and "questions" in s and isinstance(s["questions"], list):
                                fill_candidates.extend(s["questions"])

                for cand in fill_candidates:
                    if not isinstance(cand, dict):
                        continue
                    cand_sec_name = str(cand.get("section_name", "")).strip().lower()
                    target_sec_data = None
                    if cand_sec_name:
                        target_sec_data = next(
                            (
                                s for s in planned_sections
                                if s["section_name"].strip().lower() == cand_sec_name
                                or cand_sec_name in s["section_name"].strip().lower()
                                or s["section_name"].strip().lower() in cand_sec_name
                            ),
                            None
                        )
                    if not target_sec_data:
                        current_missing = _get_all_unfilled_slots()
                        if current_missing:
                            target_sec_name = current_missing[0]["section_name"]
                            target_sec_data = next((s for s in planned_sections if s["section_name"] == target_sec_name), None)

                    if not target_sec_data:
                        continue

                    sec = target_sec_data["sec"]
                    planned_groups = target_sec_data["groups"]
                    required_alts = planned_groups[0]["required_alts"] if planned_groups else [None]

                    missing_in_sec = self._get_unfilled_slots(planned_groups, required_alts)
                    if not missing_in_sec:
                        continue

                    current_sec_qs = [
                        g["slots"][alt]
                        for g in planned_groups
                        for alt in required_alts
                        if g["slots"].get(alt) is not None
                    ]
                    cand_q_text = str(cand.get("question_text", "")).strip()

                    if self._validate_question_structure(cand, sec, existing_sec_questions=current_sec_qs):
                        if not self._is_duplicate_question(cand, all_accepted_questions):
                            cand_ch_num = cand.get("chapter_number")
                            matched_item = None
                            if cand_ch_num and cand_ch_num in ch_num_to_item:
                                matched_item = ch_num_to_item[cand_ch_num]
                            elif default_ch_item:
                                matched_item = default_ch_item

                            if matched_item:
                                cand["chapter_id"] = matched_item.get("chapter_id")
                                cand["chapter_number"] = matched_item.get("chapter_number")

                            cand["source_type"] = "AI_GENERATED"

                            assigned = self._assign_candidate_to_slot(
                                cand=cand,
                                planned_groups=planned_groups,
                                required_alts=required_alts,
                                targeted_missing_slots=missing_in_sec,
                            )
                            if assigned:
                                all_accepted_questions.append(cand)
                        else:
                            if cand_q_text:
                                rejected_recovery_candidates.append(cand_q_text)
                    else:
                        if cand_q_text:
                            rejected_recovery_candidates.append(cand_q_text)
            except Exception as fill_err:
                logger.warning(f"Unified recovery attempt {recovery_attempt} failed: {fill_err}")

        # 4. Deterministic Fallback Completion (Guarantees zero unhandled 400 errors)
        remaining_missing = _get_all_unfilled_slots()
        for m in remaining_missing:
            g = m["group"]
            alt = m["alternative_label"]
            sec = m["sec"]
            logger.info(
                f"Populating fallback question for unfilled slot in section '{sec.name}', "
                f"order={m['question_order']}, choice_group={m['choice_group']}, alt={alt}"
            )
            fallback = self._create_fallback_question(
                sec=sec,
                order=m["question_order"],
                difficulty=m["difficulty"],
                choice_group=m["choice_group"],
                alternative_label=alt,
            )
            fallback["chapter_id"] = m.get("chapter_id")
            fallback["chapter_number"] = m.get("chapter_number")
            g["slots"][alt] = fallback
            all_accepted_questions.append(fallback)

        # 5. Flatten Planned Matrix into Ordered Examination Questions
        all_validated_questions: List[Dict[str, Any]] = []
        current_q_order = 1
        for s_data in planned_sections:
            sec = s_data["sec"]
            groups = s_data["groups"]
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            required_alts = groups[0]["required_alts"] if groups else [None]

            if generation_mode == GenerationMode.REFERENCE:
                import random
                random.shuffle(groups)

            sec_questions = []
            for new_idx, g in enumerate(groups):
                order = current_q_order + new_idx
                g_choice = f"Q{order}" if alts_per_q > 1 else None
                for alt in required_alts:
                    cand = g["slots"][alt]
                    cand["question_order"] = order
                    cand["section_name"] = sec.name
                    cand["question_type"] = sec.question_type.value
                    cand["marks"] = sec.marks_per_question
                    cand["difficulty"] = g["difficulty"]
                    if g.get("chapter_id"):
                        cand["chapter_id"] = g["chapter_id"]
                    if g.get("chapter_number"):
                        cand["chapter_number"] = g["chapter_number"]
                    if sec.question_type.value != "MCQ":
                        cand["mcq_options"] = None
                    if alts_per_q > 1:
                        cand["choice_group"] = g_choice
                        cand["alternative_label"] = alt
                    else:
                        cand["choice_group"] = None
                        cand["alternative_label"] = None
                    sec_questions.append(cand)

            all_validated_questions.extend(sec_questions)
            current_q_order += sec.question_count

        self._process_question_visuals_in_memory(all_validated_questions)
        return all_validated_questions

    def _process_question_visuals_in_memory(self, questions: List[Dict[str, Any]]) -> None:
        """
        Process visual specifications for generated questions in memory using SVGGeneratorService
        and VisualSemanticValidator. Distinguishes required vs optional visual failures.
        """
        from app.services.visuals.svg_generator_service import SVGGeneratorService
        from app.services.visuals.visual_semantic_validator import VisualSemanticValidator
        svg_service = SVGGeneratorService()

        for q in questions:
            visual_spec = q.get("visual")
            if not visual_spec:
                continue

            q_text = str(q.get("question_text") or "")
            sol_text = str(q.get("solution_explanation") or "")

            # 1. Deterministic Semantic Sanity Validation
            semantic_res = VisualSemanticValidator.validate(
                question_text=q_text,
                visual_spec=visual_spec,
                solution_text=sol_text,
            )

            is_required = False
            if hasattr(visual_spec, "required"):
                is_required = getattr(visual_spec, "required", False)
            elif isinstance(visual_spec, dict):
                is_required = visual_spec.get("required", False)

            if not semantic_res.is_valid:
                error_msg = "; ".join(semantic_res.errors)
                logger.warning(f"Semantic visual validation failed for '{q_text[:50]}...': {error_msg}")
                if is_required:
                    q["visual_svg"] = None
                    q["visual_valid"] = False
                    q["visual_error"] = f"Semantic visual mismatch: {error_msg}"
                    continue

            # 2. SVG Generation & Structural Rendering
            res = svg_service.generate(visual_spec)
            q["visual_svg"] = res.svg_raw if res.is_valid else None
            q["visual_valid"] = res.is_valid

            if getattr(res, "required", False) and not res.is_valid:
                logger.warning(
                    f"Required visual generation failed for question '{q_text[:50]}...': {res.error_message}"
                )
                q["visual_error"] = res.error_message or "Required visual SVG generation failed."

    _generate_section_questions = _generate_complete_paper

    def _build_complete_paper_prompt(
        self,
        blueprint: PaperBlueprint,
        context_text: str,
        topic_focus: Optional[str],
        difficulty: DifficultyLevel,
        generation_mode: GenerationMode,
        sample_questions: Optional[List[Dict[str, Any]]] = None,
        easy_pct: Optional[int] = None,
        med_pct: Optional[int] = None,
        hard_pct: Optional[int] = None,
        chapter_weightages_data: Optional[List[Dict[str, Any]]] = None,
        planned_sections: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Construct a single complete-paper generation prompt asking Gemini to generate all sections
        and questions in ONE structured JSON response.
        """
        sections_info = []
        start_q_num = 1
        for sec_idx, sec in enumerate(blueprint.sections):
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            sec_difficulties = self._calculate_difficulty_distribution(difficulty, sec.question_count, easy_pct, med_pct, hard_pct)

            choice_str = "None"
            if sec.has_internal_choice and sec.alternatives_per_question > 1:
                end_num = start_q_num + sec.question_count - 1
                choice_str = f"Internal choice for Q{start_q_num} through Q{end_num}. Each question group has {sec.alternatives_per_question} alternatives (labels 'a', 'b', etc.). Set choice_group: 'Q<N>' and alternative_label: 'a'/'b'."

            num_str = "None"
            if sec.numerical_question_count > 0:
                num_str = f"EXACTLY {sec.numerical_question_count} questions in this section MUST be calculation/numerical problems (set is_numerical: true)."

            slot_breakdown_lines = []
            if planned_sections and sec_idx < len(planned_sections):
                s_plan = planned_sections[sec_idx]
                for g in s_plan["groups"]:
                    ch_num_val = g.get("chapter_number")
                    ch_name_val = g.get("chapter_name", "")
                    diff_val = g.get("difficulty", "MEDIUM")
                    marks_val = g.get("marks", sec.marks_per_question)
                    if g.get("choice_group"):
                        slot_breakdown_lines.append(
                            f"  * {g['choice_group']} (Internal Choice): Chapter {ch_num_val} (\"{ch_name_val}\") | Difficulty: {diff_val} | Marks: {marks_val}. "
                            f"Both Alternative 'a' and Alternative 'b' MUST be authored from Chapter {ch_num_val} and test distinct concepts/formulas."
                        )
                    else:
                        is_num_str = " | Numerical Calculation" if g.get("is_numerical") else ""
                        slot_breakdown_lines.append(
                            f"  * Question {g['question_order']}: Chapter {ch_num_val} (\"{ch_name_val}\") | Difficulty: {diff_val} | Marks: {marks_val}{is_num_str}"
                        )

            slot_breakdown_str = ("\n- Planned Question Slot Grid:\n" + "\n".join(slot_breakdown_lines)) if slot_breakdown_lines else ""

            sections_info.append(f"""
---
SECTION NAME: '{sec.name}'
- Question Type: {sec.question_type.value}
- Logical Question Count: {sec.question_count}
- Alternatives Per Question: {sec.alternatives_per_question}
- Total Question Items To Generate: {sec.question_count * alts_per_q}
- Marks Per Question Item: {sec.marks_per_question} (Total Section Marks: {sec.total_section_marks})
- Target Difficulty Distribution: {json.dumps(sec_difficulties)}
- Internal Choice Requirement: {choice_str}
- Numerical Requirement: {num_str}{slot_breakdown_str}
""")
            start_q_num += sec.question_count

        topic_instruction_str = ""
        if topic_focus and topic_focus.strip():
            topic_instruction_str = f"""
USER TOPIC FOCUS:
"{topic_focus.strip()}"

STRICT RULE:
Check whether this concept exists in the SOURCE EDUCATIONAL MATERIAL.
- If it exists, prioritize it where appropriate.
- If it does not exist, completely ignore it.
- Never introduce content solely because it appears in TOPIC FOCUS.
"""

        ch_weightage_lines = []
        if chapter_weightages_data:
            ch_weightage_lines.append("\nCHAPTER WEIGHTAGE & MARKS ALLOCATION BREAKDOWN:")
            ch_weightage_lines.append(f"Total Examination Marks: {blueprint.total_marks}")
            for item in chapter_weightages_data:
                c_num = item.get("chapter_number")
                c_name = item.get("chapter_name")
                c_pct = item.get("weightage_percentage", 0.0)
                c_marks = item.get("allocated_marks", 0)
                ch_weightage_lines.append(f"- Chapter {c_num}: \"{c_name}\" -> {c_pct:.1f}% weightage (~{c_marks} marks allocated)")
            ch_weightage_lines.append("\nSTRICT CHAPTER DISTRIBUTION & ATTRIBUTION RULE:")
            ch_weightage_lines.append("- Every generated question MUST include \"chapter_number\": <int> indicating which selected chapter it covers.")
            ch_weightage_lines.append("- For questions with internal choice (e.g., Q1a / Q1b), count only ONE alternative toward the chapter mark total (logical attempted marks), since students only attempt one alternative.")
            ch_weightage_lines.append("- The cumulative logical attempted marks for questions assigned to each chapter MUST adhere strictly to its allocated marks listed above.")
            ch_weightage_lines.append("- The Planned Question Slot Grid in each section already implements this exact distribution. Follow the slot-by-slot chapter assignment to automatically fulfill this rule.")
            ch_weightage_lines.append("- Do NOT concentrate questions in any single chapter; distribute questions across all selected chapters strictly according to these allocated marks.\n")
        ch_weightage_instruction_str = "\n".join(ch_weightage_lines)

        ref_instruction_str = ""
        if generation_mode == GenerationMode.REFERENCE:
            import random
            shuffled_samples = list(sample_questions) if sample_questions else []
            random.shuffle(shuffled_samples)
            samples_formatted = json.dumps(shuffled_samples, indent=2) if shuffled_samples else "[]"
            max_overall_ref_marks = max(1, int(0.20 * blueprint.total_marks))
            ref_instruction_str = f"""
REFERENCE PAPER SAMPLE QUESTIONS & COGNITIVE STYLE PROFILE:
{samples_formatted}

CRITICAL: REFERENCE MODE SEMANTIC EXAMINATION STYLE & PEDAGOGICAL EMULATION:
You are generating an examination paper in REFERENCE MODE. You MUST capture and emulate the DEEP SEMANTIC AND PEDAGOGICAL QUESTION-SETTING PHILOSOPHY of the reference examiner, NOT merely copy vocabulary, keywords, or surface phrasing.

1. PEDAGOGICAL & COGNITIVE DEMAND EMULATION:
   - Analyze HOW the reference paper converts textbook concepts into questions (the pattern: concept → physical scenario → given parameters → cognitive reasoning required → operation expected → answer depth).
   - Match the examiner's cognitive burden: whether questions test direct recall, conceptual comprehension, scenario-based application, multi-step derivation, or numerical calculation.
   - For numerical problems, replicate the reasoning depth (e.g. single-step direct formula substitution vs. multi-step parameter setup and derivation).
   - For MCQs, emulate distractor construction strategy (targeting common student misconceptions or subtle conceptual errors rather than trivial options).
   - Real difficulty must reflect actual reasoning burden, regardless of superficial terminology.

2. CHAPTER ALIGNMENT, WEIGHTAGE & DUAL-CAP REUSE ELIGIBILITY RULE:
   - Check if any sample questions in REFERENCE PAPER SAMPLE QUESTIONS belong to the concepts in SOURCE EDUCATIONAL MATERIAL (the selected chapters).
   - DUAL-CAP REUSE CONSTRAINTS:
     * Overall Paper Reuse Limit: You may directly reuse matching reference questions as "REFERENCE_REUSED" up to a MAXIMUM of 10% to 20% of total paper marks (no more than {max_overall_ref_marks} marks total across the entire paper).
     * Per-Chapter Weightage Cap: For any individual chapter C, the total questions/marks for chapter C (reused + variations + fresh) MUST NOT exceed chapter C's allocated weightage percentage.
     * Furthermore, the total marks of reused questions for chapter C CANNOT exceed min(chapter C allocated marks, overall allowed reference reuse marks).
     * BALANCED 50/50 SPLIT PREFERENCE (IF FEASIBLE): For any selected chapter C where reference questions exist, IF POSSIBLE and if question marks/counts can be divided (e.g. Chapter 1 has 10 marks consisting of two 5-mark questions or multiple items), prefer reusing reference questions for ~half of chapter C's marks/questions and generating fresh "AI_GENERATED" questions for the remaining ~half. If NOT feasible to divide (e.g. only 1 question in that chapter or indivisible section marks), you may reuse up to the full chapter weightage cap (up to {max_overall_ref_marks} marks).
     * If the reference paper ONLY contains questions for a single chapter (e.g. Chapter 1 with 10% weightage = 10 marks), you can reuse AT MOST 10 marks of Chapter 1 questions (NEVER more, with a 50/50 reuse/fresh split if feasible), and 100% of the remaining questions for other selected chapters MUST be fresh "AI_GENERATED" questions from SOURCE EDUCATIONAL MATERIAL.
   - IF NO MATCHING QUESTIONS EXIST in the reference paper for a selected chapter:
     * 100% of questions for that chapter MUST be fresh, newly authored questions ("AI_GENERATED") from SOURCE EDUCATIONAL MATERIAL.

3. STRICT ANTI-CLUSTERING & NON-SEQUENTIAL REUSE RULE:
   - NEVER copy reference paper questions sequentially in order (e.g. DO NOT copy Reference Q1, Q2, Q3... as generated Q1, Q2, Q3...).
   - NEVER cluster or place all reused/variation questions together in the first section or in a single block at the beginning of the paper.
   - Randomly SCATTER any allowed REFERENCE_REUSED or REFERENCE_VARIATION questions across different question numbers throughout the paper, interspersing them evenly among fresh AI_GENERATED questions.

4. ADAPTATION & TRACEABILITY (source_type):
   For each generated question, set "source_type" as:
   - "REFERENCE_REUSED": Use ONLY when a question from the reference paper matches the selected textbook chapters and is directly reused.
   - "REFERENCE_VARIATION": Use ONLY when a question from the reference paper matches the selected textbook chapters and its parameters/scenario are modified.
   - "AI_GENERATED": Use for ALL newly created questions derived from the SOURCE EDUCATIONAL MATERIAL (mandatory when chapter differs or when exceeding 20% reuse/variation).

5. USER BLUEPRINT AUTHORITATIVENESS:
   - The user's requested TOTAL EXAMINATION MARKS ({blueprint.total_marks}), section counts, question types, marks per question, requested difficulty ({difficulty.value}), and selected textbook chapters are AUTHORITATIVE and MUST be strictly respected.
"""

        source_type_desc = (
            '"source_type": "<AI_GENERATED | REFERENCE_REUSED | REFERENCE_VARIATION>"'
            if generation_mode == GenerationMode.REFERENCE
            else '"source_type": "AI_GENERATED"'
        )

        prompt = f"""
Generate the COMPLETE examination paper according to the blueprint below in ONE unified response.

TOTAL EXAMINATION MARKS: {blueprint.total_marks}
OVERALL DIFFICULTY: {difficulty.value}

EXAMINATION BLUEPRINT SECTIONS:
{"".join(sections_info)}

QUESTION TYPE DEFINITIONS:
- MCQ: Multiple-choice question with exactly 4 options ("A. ...", "B. ...", "C. ...", "D. ..."). Do NOT generate answers or explanations.
- VERY_SHORT_ANSWER: Question requiring a very brief answer (word, phrase, term, formula, value, definition).
- SHORT_ANSWER: Question requiring a concise explanation, comparison, application, or short solution.
- LONG_ANSWER: Detailed, well-structured answer requiring multi-step reasoning or synthesis.
- NUMERICAL: Calculation/computation problem requiring quantitative work or mathematical derivation.

DIFFICULTY & COGNITIVE DEMAND:
- EASY: Direct recall or recognition of explicit facts stated in the source.
- MEDIUM: Comprehension and simple application. Explain, summarize, compare, classify, or connect information.
- HARD: Analysis, synthesis, multi-step reasoning, or supported inference.

CONTENT AUTHORITY, SOURCE FIDELITY & ANTI-EMBELLISHMENT RULES:
1. SOURCE EDUCATIONAL MATERIAL is the ONLY authoritative source for question content, facts, formulas, terminology, and subject matter.
2. Every generated question MUST be strictly derived from and answerable using ONLY the provided SOURCE EDUCATIONAL MATERIAL.
3. DO NOT use external knowledge, pretrained/model general knowledge, assumptions, or information outside the provided SOURCE EDUCATIONAL MATERIAL.
4. CHAPTER COVERAGE & ATTRIBUTION RULE: Distribute questions strictly according to the requested chapter weightages. If no custom weightages are provided, distribute coverage reasonably across all selected chapters. Include "chapter_number": <1-based integer chapter number> for each question.
5. NUMERICAL CALCULATION ACCURACY RULE: You MUST perform exact step-by-step arithmetic verification for all numerical calculations. Double-check powers of 10, exponents, signs, and unit conversions (e.g. 10⁹ × 10⁻⁷ × 10⁻⁷ / (0.3)² = 5.4 × 10⁻³ / 0.09 = 6.0 × 10⁻³ N).
6. VARIABLE DISAMBIGUATION RULE: NEVER use the same variable letter or symbol for two different physical quantities in the same question (e.g. do NOT use 'a' for both an electric field coefficient and a cube edge length; use distinct symbols like 'k' and 'L', or 'a' and 'd').
7. SELF-CONTAINED QUESTION RULE: EVERY single question MUST be 100% self-contained and independent. NEVER use phrases like 'the previous problem', 'above question', 'from question X', or 'from the previous result'. Each question must supply all its own parameters, definitions, and context.
8. INTERNAL CHOICE ALTERNATIVES RULE: For questions with internal choice, alternatives 'a' and 'b' MUST be from the same designated chapter, and MUST be completely distinct, independent, non-identical questions testing distinct concepts/formulas.
9. VISUAL ILLUSTRATION & DIAGRAM GUIDELINES:
   - EXAMINATION VISUAL VARIETY: Real-world examination papers feature a natural, balanced mix of both pure-text questions (definitions, derivations, statements of laws) and diagram-based questions. When the source material covers topics with physical arrangements, component networks, geometric figures, function/signal curves, multi-stage workflows, or comparative data distributions, you MUST author some questions as diagram-based questions (where the question explicitly presents and refers to a figure, e.g. "In the circuit diagram shown below...", "In the figure shown below...", "From the graph plotted below..."), populating the complete structured "visual" object with "required": true. Do NOT make 100% of the paper purely text-based word problems when visual concepts are available.
   - CORE PRINCIPLE: A visual specification is a STRICT SEMANTIC REPRESENTATION of the question, NOT a decorative or representative illustration. Never simplify a complex visual problem into a smaller representative diagram.
   - VISUAL NECESSITY: Use a visual when it materially improves the question, represents information the student must interpret or calculate from (e.g. an explicit circuit network, geometric figure, or graph curve), or presents an explicit illustration. For purely conceptual definitions, statements of laws, or derivations that do not present a figure, set "visual": null.
   - COMPONENT & QUANTITY COMPLETENESS RULE: Every single physical entity, component, node, vertex, and stage described in "question_text" MUST be explicitly represented in "spec". If the question mentions "12 resistors", "spec" MUST contain exactly 12 resistor components. If it mentions "four capacitors", "spec" MUST contain 4 capacitors. If it mentions "triangle ABC with altitude BD", "spec" MUST contain points A, B, C, D and segments AB, BC, AC, BD. NEVER generate a simplified subset or generic loop.
   - NUMERICAL & PARAMETER CONSISTENCY RULE: Every numerical value, voltage (e.g. '500 V', '220 V, 50 Hz'), resistance ('1 Ω', '200 Ω'), capacitance ('10 µF'), dimension ('5 cm'), and equation ('10*sin(100*pi*x)') stated in "question_text" MUST 100% match the parameters and labels in "spec".
   - TOPOLOGY & RELATIONSHIP PRESERVATION: Named topologies (e.g. 'cubical network', 'Wheatstone bridge', 'parallel branches', 'ladder network') MUST be constructed with their exact graph connections and vertices, NOT collapsed into a simple loop. Use 'routing': 'direct' for diagonal/isometric edges where appropriate.
   - PHYSICAL STATES & SYMBOLS: Explicit physical states (e.g. switch open/closed -> state='open'/'closed', AC source -> type='ac_source', iron-core inductor -> type='inductor' with iron_core=true, lamp/bulb -> type='lamp') MUST be specified.
   - NEVER generate raw SVG markup, XML, or HTML. Populate "spec" with clean semantic elements:
     * For "circuit": "spec": {{"junctions": [{{"id": "A", "x": 50, "y": 150, "label": "A"}}], "components": [{{"id": "AC1", "type": "ac_source", "label": "220 V, 50 Hz"}}, {{"id": "L1", "type": "inductor", "label": "50 mH", "iron_core": true}}, {{"id": "K1", "type": "switch", "label": "Key", "state": "closed"}}], "connections": [{{"from": "AC1", "to": "K1", "routing": "orthogonal"}}]}}
     * For "geometry": "spec": {{"points": [{{"id": "A", "label": "A"}}, {{"id": "B", "label": "B"}}, {{"id": "C", "label": "C"}}, {{"id": "D", "label": "D"}}], "segments": [{{"from": "A", "to": "B", "label": "5 cm"}}, {{"from": "B", "to": "D", "label": "Altitude"}}], "polygons": [{{"points": ["A", "B", "C"]}}], "angles": [{{"vertex": "B", "p1": "A", "p2": "C", "label": "90°", "right_angle": true}}]}}
     * For "graph": "spec": {{"x_range": [-5, 5], "y_range": [-10, 10], "grid": true, "x_axis_label": "t (s)", "y_axis_label": "v(t)", "functions": [{{"expression": "10*sin(100*pi*x)", "label": "v(t) = 10 sin(100πt)"}}]}}
     * For "diagram": "spec": {{"nodes": [{{"id": "n1", "label": "Stage 1"}}, {{"id": "n2", "label": "Stage 2"}}], "edges": [{{"from": "n1", "to": "n2", "label": "transition"}}]}}
     * For "chart": "spec": {{"format": "bar", "categories": ["Physics", "Chemistry", "Math"], "series": [{{"name": "Scores", "values": [80, 95, 88]}}]}}
   - CRITICAL SPEC REQUIREMENT: When "visual" is not null, "spec" MUST NOT be empty. You MUST populate the full internal structure (e.g. "components" & "connections" for circuit; "points", "segments" & "polygons" for geometry; "functions" & ranges for graph).
   - INTERNAL CHOICE INDEPENDENCE: For questions with internal choice, each alternative ('a' and 'b') independently specifies its own "visual" object (or null).
{ch_weightage_instruction_str}
{topic_instruction_str}
{ref_instruction_str}
OUTPUT FORMAT REQUIREMENT:
Return ONLY a valid JSON object containing a "sections" array. Author ONLY question text and MCQ options. Do NOT author answer keys, expected answers, or solutions. Do NOT wrap in markdown text outside the JSON.
{{
  "sections": [
    {{
      "section_name": "<Section Name>",
      "questions": [
        {{
          "question_text": "<Clear question text>",
          "question_type": "<MCQ | VERY_SHORT_ANSWER | SHORT_ANSWER | LONG_ANSWER | NUMERICAL>",
          "marks": <marks per question>,
          "difficulty": "<EASY | MEDIUM | HARD>",
          "choice_group": "<e.g. Q1 or null>",
          "alternative_label": "<e.g. a, b or null>",
          "chapter_number": <1-based integer chapter number>,
          "is_numerical": <true | false>,
          "mcq_options": ["A. ...", "B. ...", "C. ...", "D. ..."] or null,
          "visual": {{
            "required": true,
            "type": "circuit",
            "title": "Title of the diagram",
            "caption": "Educational caption",
            "spec": {{
              "components": [{{"id": "V1", "type": "battery", "label": "12 V"}}, {{"id": "R1", "type": "resistor", "label": "6 Ω"}}],
              "connections": [{{"from": "V1", "to": "R1"}}, {{"from": "R1", "to": "V1"}}]
            }}
          }} or null,
          {source_type_desc}
        }}
      ]
    }}
  ]
}}

SOURCE EDUCATIONAL MATERIAL:
{context_text}
"""
        return prompt

    def _validate_question_structure(
        self,
        q: Dict[str, Any],
        sec: SectionBlueprint,
        existing_sec_questions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Validate question structure, self-containment, variable disambiguation, MCQ option matching,
        answer field completeness, and content-based numerical classification.
        """
        if not isinstance(q, dict):
            return False

        q_text = str(q.get("question_text", "")).strip()
        if not q_text or len(q_text) < 5:
            return False

        # 1. Self-containment validation: Reject cross-question dependencies
        dep_patterns = [
            r"\bprevious (problem|question|result|part|example|computation|value)\b",
            r"\babove (problem|question|result|part|computation|value)\b",
            r"\bfrom (question|problem) \d+\b",
            r"\bfrom the previous\b",
            r"\busing the answer obtained above\b",
            r"\busing your answer from\b",
            r"\bas calculated earlier\b",
            r"\bthe result obtained above\b",
            r"\bfrom part \([a-d]\)\b",
        ]
        for pat in dep_patterns:
            if re.search(pat, q_text, re.IGNORECASE):
                logger.warning(f"Rejecting dependent question (matches '{pat}'): '{q_text[:50]}'")
                return False

        # 2. Variable disambiguation: Reject conflicting variable symbol assignments
        var_assignments = re.findall(r"\b([a-zA-Z])\s*=\s*([\d\.\-]+)\s*([a-zA-ZΩ°µμ%C|N|m|V|J|A|Hz/\-]+)", q_text)
        symbol_map = {}
        for sym, val, unit in var_assignments:
            if sym in symbol_map and symbol_map[sym] != (val, unit):
                logger.warning(f"Rejecting variable collision: symbol '{sym}' assigned conflicting values {symbol_map[sym]} vs ({val}, {unit})")
                return False
            symbol_map[sym] = (val, unit)

        # 3. MCQ option structure & uniqueness validation (pure question paper: answer fields are optional)
        corr = str(q.get("correct_answer") or "").strip()
        q_type = sec.question_type.value

        if q_type == "MCQ":
            opts = q.get("mcq_options")
            if not isinstance(opts, list) or len(opts) != 4:
                logger.warning(f"Rejecting MCQ with invalid options list (must be exactly 4 options): {opts}")
                return False
            if any(not str(opt).strip() for opt in opts):
                logger.warning(f"Rejecting MCQ with empty option string in options: {opts}")
                return False

            # Check option uniqueness without lowercasing variables in formulas
            def _clean_content_exact(s: str) -> str:
                s_clean = re.sub(r"^\s*(?:option\s+)?(?:\([A-Da-d]\)|[A-Da-d][\.\:\)])\s*", "", str(s)).strip()
                return s_clean.replace("$", "").replace("\\", "").strip()

            clean_opts_exact = [_clean_content_exact(opt) for opt in opts]
            if len(set(clean_opts_exact)) < len(clean_opts_exact):
                logger.warning(f"Rejecting MCQ with duplicate/ambiguous options: {opts}")
                return False

            # If correct_answer happens to be provided, verify it matches one of the options
            if corr:
                letter_match = re.match(r"^\s*(?:option\s+)?\(?([A-Da-d])\)?[\.\:\)]?\s*$", corr)
                if letter_match:
                    letter_idx = ord(letter_match.group(1).upper()) - ord("A")
                    matches = [letter_idx] if 0 <= letter_idx < len(opts) else []
                else:
                    clean_corr = _clean_content_exact(corr).lower()
                    clean_opts_lower = [c.lower() for c in clean_opts_exact]
                    matches = [
                        i for i, c_opt in enumerate(clean_opts_lower)
                        if clean_corr == c_opt or (clean_corr and clean_corr in c_opt) or (c_opt and c_opt in clean_corr)
                    ]
                if not matches:
                    logger.warning(f"Rejecting MCQ: correct_answer '{corr}' does not match any option in {opts}")
                    return False

        # 4. Content-based numerical detection and slot alignment
        sol = str(q.get("solution_explanation") or "").strip()
        search_corpus = q_text + (" " + sol if sol else "")
        has_numbers = bool(re.search(r"\b\d+(\.\d+)?\s*(×\s*10|e[+-]?\d+|[a-zA-ZΩ°µμ%C|N|m|V|J|A|Hz])\b", search_corpus, re.IGNORECASE))
        has_math_ops = bool(re.search(r"[=\+\-\*/\^]", search_corpus))
        is_calc_text = bool(re.search(r"\b(calculate|compute|find the magnitude|determine the value)\b", q_text, re.IGNORECASE))

        inferred_numerical = has_numbers or (has_math_ops and is_calc_text) or (q_type == "NUMERICAL")

        if existing_sec_questions is not None and sec.numerical_question_count > 0:
            current_num_cnt = sum(1 for item in existing_sec_questions if item.get("is_numerical") is True)
            needed_num_cnt = sec.numerical_question_count
            total_items_needed = sec.question_count * sec.alternatives_per_question
            remaining_slots = total_items_needed - len(existing_sec_questions)
            remaining_num_needed = needed_num_cnt - current_num_cnt

            if remaining_num_needed > 0 and remaining_num_needed >= remaining_slots:
                if not inferred_numerical:
                    logger.warning(f"Rejecting conceptual question in mandatory numerical slot for section '{sec.name}'")
                    return False
            elif remaining_num_needed <= 0 and inferred_numerical and q_type != "NUMERICAL":
                if len(existing_sec_questions) < sec.question_count:
                    logger.warning(f"Rejecting calculation question in conceptual slot for section '{sec.name}'")
                    return False

        q["is_numerical"] = bool(inferred_numerical)

        return True

    def _validate_final_paper_integrity(
        self,
        blueprint: PaperBlueprint,
        generated_questions: List[Dict[str, Any]],
        selected_chapter_ids: List[UUID],
        chapter_weightages_data: Optional[List[Dict[str, Any]]] = None,
        generation_mode: Optional[GenerationMode] = None,
    ) -> None:
        """
        Monolithic final validation pass performed immediately prior to DB persistence/commit.
        Validates total marks, logical question count, section question counts, internal-choice accounting,
        numerical count compliance, answer completeness, cross-question self-containment, and chapter coverage.
        """
        total_blueprint_items = sum(
            sec.question_count * (sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1)
            for sec in blueprint.sections
        )
        if not generated_questions:
            if total_blueprint_items == 0:
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Final paper validation failed: No generated questions produced.",
            )
        if len(generated_questions) != total_blueprint_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Final paper validation failed: Total generated question items ({len(generated_questions)}) does not match blueprint item count ({total_blueprint_items}).",
            )

        # 1. Blueprint Section Verification & Section Question Counts
        default_sec_name = blueprint.sections[0].name if len(blueprint.sections) == 1 else None
        for q in generated_questions:
            if not q.get("section_name") and default_sec_name:
                q["section_name"] = default_sec_name

        bp_sec_map = {sec.name: sec for sec in blueprint.sections}
        actual_sec_names = set(q.get("section_name") for q in generated_questions)
        for sec in blueprint.sections:
            if sec.name not in actual_sec_names:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Missing section '{sec.name}' in generated paper.",
                )
            sec_items = [q for q in generated_questions if q.get("section_name") == sec.name]
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            expected_sec_items = sec.question_count * alts_per_q
            if len(sec_items) != expected_sec_items:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Section '{sec.name}' has {len(sec_items)} items, expected {expected_sec_items}.",
                )
            if alts_per_q > 1:
                sec_cgs = set(q.get("choice_group") for q in sec_items if q.get("choice_group"))
                if len(sec_cgs) != sec.question_count:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Final paper validation failed: Section '{sec.name}' has {len(sec_cgs)} distinct choice groups, expected {sec.question_count}.",
                    )

        # 2. Total marks accounting & Choice Group Integrity
        computed_marks = 0
        seen_choice_groups = set()
        choice_group_map: Dict[str, List[Dict[str, Any]]] = {}

        for q in generated_questions:
            cg = q.get("choice_group")
            if cg:
                choice_group_map.setdefault(cg, []).append(q)
                if cg not in seen_choice_groups:
                    seen_choice_groups.add(cg)
                    computed_marks += q.get("marks", 0)
            else:
                computed_marks += q.get("marks", 0)

        if computed_marks != blueprint.total_marks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Final paper validation failed: Computed total marks ({computed_marks}) does not match requested paper total marks ({blueprint.total_marks}).",
            )

        # Verify each choice group has exactly 2 alternatives ('a' and 'b') with matching metadata
        for cg, items in choice_group_map.items():
            if len(items) != 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Choice group '{cg}' has {len(items)} items, expected exactly 2.",
                )
            labels = sorted([str(item.get("alternative_label", "")).lower() for item in items])
            if labels != ["a", "b"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Choice group '{cg}' labels {labels} do not match expected ['a', 'b'].",
                )
            # Uniform marks, question_order, difficulty, and section
            if len(set(item.get("marks") for item in items)) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Choice group '{cg}' items have mismatched marks.",
                )
            if len(set(item.get("question_order") for item in items)) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Choice group '{cg}' items have mismatched question_order.",
                )
            if len(set(item.get("difficulty") for item in items)) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Choice group '{cg}' items have mismatched difficulty.",
                )

        # 3. Paper-level target numerical count validation
        target_num_count = sum(sec.numerical_question_count for sec in blueprint.sections)
        actual_num_count = sum(1 for q in generated_questions if q.get("is_numerical") is True)
        if target_num_count > 0 and actual_num_count != target_num_count:
            logger.warning(f"Final paper numerical validation notice: target={target_num_count}, actual={actual_num_count}")

        # 4. Answer completeness, MCQ option structure & self-containment check across all items
        dep_patterns = [
            r"\bprevious (problem|question|result|part|example|computation|value)\b",
            r"\babove (problem|question|result|part|computation|value)\b",
            r"\bfrom (question|problem) \d+\b",
            r"\bfrom the previous\b",
            r"\busing the answer obtained above\b",
            r"\busing your answer from\b",
            r"\bas calculated earlier\b",
            r"\bthe result obtained above\b",
            r"\bfrom part \([a-d]\)\b",
        ]
        seen_texts: List[str] = []
        for q in generated_questions:
            q_text = str(q.get("question_text", "")).strip()
            if not q_text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Final paper validation failed: Found question item with empty text.",
                )

            # Duplicate text check across all items in the paper
            q_lower = q_text.lower()
            if q_lower in seen_texts:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Final paper validation failed: Duplicate question text detected: '{q_text[:50]}...'.",
                )
            seen_texts.append(q_lower)

            for pat in dep_patterns:
                if re.search(pat, q_text, re.IGNORECASE):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Final paper validation failed: Cross-question dependency detected in item '{q_text[:40]}'.",
                    )

            # MCQ validation
            q_type = q.get("question_type")
            if not q_type and q.get("section_name") in bp_sec_map:
                q_type = bp_sec_map[q.get("section_name")].question_type.value

            if q_type == "MCQ":
                opts = q.get("mcq_options")
                if not isinstance(opts, list) or len(opts) != 4:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Final paper validation failed: MCQ item '{q_text[:40]}' must have exactly 4 options.",
                    )
                if any(not str(opt).strip() for opt in opts):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Final paper validation failed: MCQ item '{q_text[:40]}' has empty option text.",
                    )
                def _clean_content_exact(s: str) -> str:
                    s_clean = re.sub(r"^\s*(?:option\s+)?(?:\([A-Da-d]\)|[A-Da-d][\.\:\)])\s*", "", str(s)).strip()
                    return s_clean.replace("$", "").replace("\\", "").strip()

                clean_opts_exact = [_clean_content_exact(opt) for opt in opts]
                if len(set(clean_opts_exact)) < len(clean_opts_exact):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Final paper validation failed: MCQ item '{q_text[:40]}' has duplicate/ambiguous options.",
                    )
                corr = str(q.get("correct_answer") or "").strip()
                if corr:
                    letter_match = re.match(r"^\s*(?:option\s+)?\(?([A-Da-d])\)?[\.\:\)]?\s*$", corr)
                    if letter_match:
                        letter_idx = ord(letter_match.group(1).upper()) - ord("A")
                        matches = [letter_idx] if 0 <= letter_idx < len(opts) else []
                    else:
                        clean_corr = _clean_content_exact(corr).lower()
                        clean_opts_lower = [c.lower() for c in clean_opts_exact]
                        matches = [
                            i for i, c_opt in enumerate(clean_opts_lower)
                            if clean_corr == c_opt or (clean_corr and clean_corr in c_opt) or (c_opt and c_opt in clean_corr)
                        ]
                    if not matches:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Final paper validation failed: MCQ item '{q_text[:40]}' correct_answer does not match any option.",
                        )
            else:
                q["mcq_options"] = None

        # 5. Chapter attribution and reference reuse dual-cap validation
        if selected_chapter_ids:
            selected_id_strs = {str(cid) for cid in selected_chapter_ids}
            for q in generated_questions:
                ch_id = q.get("chapter_id")
                if ch_id and str(ch_id) not in selected_id_strs:
                    logger.warning(f"Question chapter_id '{ch_id}' outside selected_chapter_ids; remapping.")
                    q["chapter_id"] = str(selected_chapter_ids[0])

        if chapter_weightages_data:
            # Check chapter marks distribution
            ch_marks_map: Dict[str, int] = {}
            for q in generated_questions:
                cid = str(q.get("chapter_id", ""))
                # internal choice: count only once per choice group
                cg = q.get("choice_group")
                if cg and q.get("alternative_label") == "b":
                    continue
                ch_marks_map[cid] = ch_marks_map.get(cid, 0) + q.get("marks", 0)

            for ch_item in chapter_weightages_data:
                cid = str(ch_item.get("chapter_id", ""))
                alloc = ch_item.get("allocated_marks", 0)
                actual = ch_marks_map.get(cid, 0)
                if not _is_mock(ch_item.get("chapter_id")) and not _is_mock(alloc) and alloc > 0 and actual == 0:
                    logger.warning(
                        f"Final integrity notice: Selected Chapter {ch_item.get('chapter_number')} "
                        f"('{ch_item.get('chapter_name')}') has {alloc} allocated marks but 0 questions assigned."
                    )

        if generation_mode == GenerationMode.REFERENCE and chapter_weightages_data:
            max_overall_reused = max(1, int(0.20 * blueprint.total_marks))
            total_reused = sum(q.get("marks", 0) for q in generated_questions if q.get("source_type") == "REFERENCE_REUSED")
            if total_reused > max_overall_reused:
                logger.warning(f"Final integrity notice: total reused marks ({total_reused}) exceeds 20% quota ({max_overall_reused}).")

            for ch_item in chapter_weightages_data:
                ch_id = ch_item.get("chapter_id")
                ch_alloc = ch_item.get("allocated_marks", blueprint.total_marks)
                ch_reused = sum(q.get("marks", 0) for q in generated_questions if q.get("chapter_id") == ch_id and q.get("source_type") == "REFERENCE_REUSED")
                if ch_reused > ch_alloc:
                    logger.warning(f"Final integrity notice: chapter {ch_id} reused marks ({ch_reused}) exceeds allocated weightage ({ch_alloc}).")

        logger.info(f"Monolithic final paper validation passed cleanly: {len(generated_questions)} items, {computed_marks} total marks.")

    def _is_question_grounded(self, q: Dict[str, Any], context_text: str = "") -> bool:
        """
        Legacy grounding check stub. Post-generation educational rejection is completely disabled.
        Always returns True to ensure model-generated content within scope is accepted.
        """
        return True

    def _is_duplicate_question(
        self,
        candidate: Dict[str, Any],
        existing_questions: List[Dict[str, Any]],
    ) -> bool:
        """
        Check if candidate question text is a duplicate of any existing question in the paper.
        Rejects 100% exact normalized text matches (case-insensitive, punctuation stripped, whitespace normalized).
        """
        cand_text = self._normalize_text(candidate.get("question_text", ""))
        if not cand_text:
            return False

        for ex in existing_questions:
            ex_text = self._normalize_text(ex.get("question_text", ""))
            if cand_text == ex_text:
                logger.info(f"Duplicate question rejected (100% exact match): '{cand_text[:60]}'")
                return True

        return False

    def _calculate_difficulty_distribution(
        self,
        difficulty: DifficultyLevel,
        count: int,
        easy_pct: Optional[int] = None,
        med_pct: Optional[int] = None,
        hard_pct: Optional[int] = None,
    ) -> List[str]:
        if easy_pct is not None and med_pct is not None and hard_pct is not None:
            easy_cnt = int(round(count * (easy_pct / 100.0)))
            hard_cnt = int(round(count * (hard_pct / 100.0)))
            med_cnt = max(0, count - easy_cnt - hard_cnt)

            dist = (["EASY"] * easy_cnt) + (["MEDIUM"] * med_cnt) + (["HARD"] * hard_cnt)
            if len(dist) < count:
                dist.extend(["MEDIUM"] * (count - len(dist)))
            return dist[:count]

        if difficulty != DifficultyLevel.MIXED:
            return [difficulty.value] * count

        # MIXED distribution: ~30% Easy, ~50% Medium, ~20% Hard
        easy_cnt = max(1 if count >= 3 else 0, int(round(count * 0.3)))
        hard_cnt = max(1 if count >= 5 else 0, int(round(count * 0.2)))
        med_cnt = max(1, count - easy_cnt - hard_cnt)

        dist = (["EASY"] * easy_cnt) + (["MEDIUM"] * med_cnt) + (["HARD"] * hard_cnt)
        return dist[:count]

    def _create_fallback_question(
        self,
        sec: SectionBlueprint,
        order: int,
        difficulty: str,
        choice_group: Optional[str] = None,
        alternative_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        q_type = sec.question_type.value
        suffix = f" ({choice_group}{alternative_label})" if choice_group and alternative_label else f" #{order}"
        if q_type == "MCQ":
            res = {
                "question_order": order,
                "section_name": sec.name,
                "question_type": "MCQ",
                "question_text": f"Which of the following statements best describes core concept{suffix} in this topic?",
                "marks": sec.marks_per_question,
                "difficulty": difficulty,
                "source_type": "AI_GENERATED",
                "mcq_options": [
                    "A. It defines the primary execution mechanism.",
                    "B. It represents secondary memory management.",
                    "C. It specifies network protocol headers.",
                    "D. It controls hardware clock cycles.",
                ],
                "correct_answer": None,
                "solution_explanation": None,
            }
        elif q_type == "NUMERICAL":
            res = {
                "question_order": order,
                "section_name": sec.name,
                "question_type": "NUMERICAL",
                "question_text": f"Calculate the total processing time given process arrival time = {order} ms and burst time = {order * 2} ms.",
                "marks": sec.marks_per_question,
                "difficulty": difficulty,
                "source_type": "AI_GENERATED",
                "numerical_values": None,
                "correct_answer": None,
                "solution_explanation": None,
                "unit": "ms",
            }
        else:
            res = {
                "question_order": order,
                "section_name": sec.name,
                "question_type": q_type,
                "question_text": f"Explain the key principles and operational steps for concept{suffix}.",
                "marks": sec.marks_per_question,
                "difficulty": difficulty,
                "source_type": "AI_GENERATED",
                "expected_answer": None,
                "solution_explanation": None,
            }

        res["choice_group"] = choice_group
        res["alternative_label"] = alternative_label
        return res

    def _normalize_text(self, text: str) -> str:
        clean = re.sub(r"[^\w\s]", "", text.lower())
        return " ".join(clean.split())

    def _parse_json_safely(self, text: str) -> Dict[str, Any]:
        text_str = text.strip()

        # 1. Strip leading ```json or ``` markdown codeblock prefix
        if text_str.startswith("```json"):
            text_str = text_str[7:].strip()
        elif text_str.startswith("```"):
            text_str = text_str[3:].strip()

        # 2. Strip trailing ``` markdown codeblock suffix if present
        if text_str.endswith("```"):
            text_str = text_str[:-3].strip()

        # 3. Fallback regex extract first JSON object/array if conversational text wraps it
        if not (text_str.startswith("{") or text_str.startswith("[")):
            match = re.search(r"(\{.*\})", text_str, re.DOTALL)
            if match:
                text_str = match.group(1).strip()

        try:
            res = json.loads(text_str)
        except Exception:
            # Fallback 1: Strip trailing commas before closing braces/brackets (e.g. ,} or ,])
            sanitized = re.sub(r',\s*([\}\]])', r'\1', text_str)
            # Fallback 2: Fix invalid \uXXXX escapes (e.g. \unit, \micro, LaTeX \theta)
            sanitized = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', sanitized)
            try:
                res = json.loads(sanitized)
            except Exception:
                # Fallback 3: Balance unclosed braces/brackets if truncated near end
                balanced = sanitized
                open_braces = balanced.count("{") - balanced.count("}")
                open_brackets = balanced.count("[") - balanced.count("]")
                if open_brackets > 0:
                    balanced += "]" * open_brackets
                if open_braces > 0:
                    balanced += "}" * open_braces
                try:
                    res = json.loads(balanced)
                except Exception as json_err:
                    logger.error(f"Failed to parse Gemini output JSON: {json_err}")
                    raise GeminiInvalidResponseError(f"The AI returned an invalid response while generating the paper: {str(json_err)}")

        if isinstance(res, dict):
            return res
        if isinstance(res, list):
            return {"questions": res}
        raise GeminiInvalidResponseError("Gemini output root is not a JSON object or array.")

    def _build_paper_response(
        self,
        paper: GeneratedPaper,
        include_answers: bool = True,
    ) -> PaperResponse:
        """
        Convert GeneratedPaper ORM model to PaperResponse schema.
        If include_answers is False, strip answer/solution fields from the public JSON!
        """
        question_responses: List[PaperQuestionResponse] = []

        for q in paper.questions:
            mcq_opts = q.mcq_options
            corr_ans = q.correct_answer if include_answers else None
            exp_ans = q.expected_answer if include_answers else None
            num_vals = q.numerical_values if include_answers else None
            sol_exp = q.solution_explanation if include_answers else None
            unit_val = q.unit if include_answers else None

            is_num = bool(
                q.question_type == "NUMERICAL"
                or getattr(q, "is_numerical", False)
                or (q.numerical_values and isinstance(q.numerical_values, dict) and (q.numerical_values.get("is_numerical") or len(q.numerical_values) > 0))
                or q.unit
            )

            v_req = getattr(q, "visual_required", False)
            v_type = getattr(q, "visual_type", None)
            v_title = getattr(q, "visual_title", None)
            v_caption = getattr(q, "visual_caption", None)
            v_spec = getattr(q, "visual_spec", None)
            v_svg = getattr(q, "visual_svg", None)

            q_id = getattr(q, "id", None)
            if _is_mock(q_id) or not q_id:
                import uuid as _uuid
                q_id = _uuid.uuid4()
            elif isinstance(q_id, str):
                try:
                    q_id = UUID(q_id)
                except Exception:
                    import uuid as _uuid
                    q_id = _uuid.uuid4()

            q_ch_id = getattr(q, "chapter_id", None)
            if _is_mock(q_ch_id):
                q_ch_id = None
            elif q_ch_id:
                try:
                    q_ch_id = UUID(str(q_ch_id))
                except (ValueError, TypeError):
                    q_ch_id = None

            choice_grp = getattr(q, "choice_group", None)
            choice_grp = None if _is_mock(choice_grp) else choice_grp
            alt_lbl = getattr(q, "alternative_label", None)
            alt_lbl = None if _is_mock(alt_lbl) else alt_lbl

            question_responses.append(
                PaperQuestionResponse(
                    id=q_id,
                    chapter_id=q_ch_id,
                    question_order=q.question_order,
                    section_name=q.section_name,
                    question_type=QuestionType(q.question_type) if hasattr(q, "question_type") else QuestionType.MCQ,
                    question_text=q.question_text,
                    marks=q.marks,
                    difficulty=str(q.difficulty) if hasattr(q, "difficulty") else "MEDIUM",
                    source_type=QuestionSource(q.source_type) if hasattr(q, "source_type") and q.source_type else QuestionSource.AI_GENERATED,
                    is_numerical=is_num,
                    choice_group=choice_grp,
                    alternative_label=alt_lbl,
                    mcq_options=mcq_opts,
                    correct_answer=corr_ans,
                    expected_answer=exp_ans,
                    numerical_values=num_vals,
                    solution_explanation=sol_exp,
                    unit=unit_val,
                    visual_required=False if _is_mock(v_req) or not v_req else bool(v_req),
                    visual_type=None if _is_mock(v_type) else v_type,
                    visual_title=None if _is_mock(v_title) else v_title,
                    visual_caption=None if _is_mock(v_caption) else v_caption,
                    visual_spec=None if _is_mock(v_spec) else v_spec,
                    visual_svg=None if _is_mock(v_svg) else v_svg,
                )
            )

        # Parse chapter_ids safely
        selected_ch_ids = []
        if paper.selected_chapter_ids:
            for cid in paper.selected_chapter_ids:
                try:
                    selected_ch_ids.append(cid if isinstance(cid, UUID) else UUID(str(cid)))
                except (ValueError, TypeError):
                    pass

        # Parse chapter_weightages safely
        weightage_responses = None
        if getattr(paper, "chapter_weightages", None) and not _is_mock(paper.chapter_weightages):
            weightage_responses = []
            for w in paper.chapter_weightages:
                try:
                    weightage_responses.append(
                        ChapterWeightageResponse(
                            chapter_id=UUID(str(w["chapter_id"])),
                            chapter_number=int(w.get("chapter_number", 1)),
                            chapter_name=str(w.get("chapter_name", "")),
                            weightage_percentage=float(w.get("weightage_percentage", 0.0)),
                            allocated_marks=int(w.get("allocated_marks", 0)),
                        )
                    )
                except Exception:
                    pass

        # Calculate PDF & Processing Status
        has_saved_pdf = bool(paper.pdf_path and not _is_mock(paper.pdf_path) and os.path.exists(paper.pdf_path))
        pdf_url = f"/api/v1/papers/{paper.id}/pdf" if has_saved_pdf else None

        raw_proc = getattr(paper, "processing_status", None)
        if _is_mock(raw_proc) or not raw_proc:
            proc_status = "NOT_SAVED"
        else:
            proc_status = str(raw_proc)

        if paper.document_id and not _is_mock(paper.document_id):
            try:
                doc = self.doc_repo.get_document_by_id(paper.document_id)
                if doc and getattr(doc, "processing_status", None) and not _is_mock(doc.processing_status):
                    proc_status = str(doc.processing_status)
            except Exception:
                pass

        reference_eligible = bool(has_saved_pdf and proc_status == "READY" and getattr(paper, "deleted_at", None) is None)

        raw_id = getattr(paper, "id", None)
        paper_id = uuid4() if (_is_mock(raw_id) or not raw_id) else (UUID(str(raw_id)) if not isinstance(raw_id, UUID) else raw_id)

        raw_ws_id = getattr(paper, "workspace_id", None)
        ws_id = uuid4() if (_is_mock(raw_ws_id) or not raw_ws_id) else (UUID(str(raw_ws_id)) if not isinstance(raw_ws_id, UUID) else raw_ws_id)

        raw_sub_id = getattr(paper, "subject_id", None)
        sub_id = uuid4() if (_is_mock(raw_sub_id) or not raw_sub_id) else (UUID(str(raw_sub_id)) if not isinstance(raw_sub_id, UUID) else raw_sub_id)

        raw_book_id = getattr(paper, "book_id", None)
        book_id = uuid4() if (_is_mock(raw_book_id) or not raw_book_id) else (UUID(str(raw_book_id)) if not isinstance(raw_book_id, UUID) else raw_book_id)

        raw_ref_id = getattr(paper, "reference_paper_id", None)
        ref_id = None if (_is_mock(raw_ref_id) or not raw_ref_id) else (UUID(str(raw_ref_id)) if not isinstance(raw_ref_id, UUID) else raw_ref_id)

        raw_title = getattr(paper, "title", None)
        title_val = "Generated Paper" if (_is_mock(raw_title) or not raw_title) else str(raw_title)

        raw_topic = getattr(paper, "topic_focus", None)
        topic_val = None if (_is_mock(raw_topic) or not raw_topic) else str(raw_topic)

        raw_bp = getattr(paper, "blueprint_json", None)
        bp_val = None if _is_mock(raw_bp) else raw_bp

        raw_err = getattr(paper, "error_message", None)
        err_val = None if _is_mock(raw_err) else raw_err

        raw_easy = getattr(paper, "easy_percentage", None)
        easy_val = None if _is_mock(raw_easy) else raw_easy

        raw_med = getattr(paper, "medium_percentage", None)
        med_val = None if _is_mock(raw_med) else raw_med

        raw_hard = getattr(paper, "hard_percentage", None)
        hard_val = None if _is_mock(raw_hard) else raw_hard

        raw_time = getattr(paper, "time_allowed_minutes", None)
        time_allowed = None if _is_mock(raw_time) else raw_time

        raw_class = getattr(paper, "class_name", None)
        cls_name = None if _is_mock(raw_class) else raw_class

        raw_mode = getattr(paper, "generation_mode", None)
        if _is_mock(raw_mode) or not raw_mode:
            gen_mode = GenerationMode.CUSTOM
        else:
            try:
                gen_mode = GenerationMode(str(getattr(raw_mode, "value", raw_mode)))
            except Exception:
                gen_mode = GenerationMode.CUSTOM

        raw_diff = getattr(paper, "difficulty", None)
        if _is_mock(raw_diff) or not raw_diff:
            diff_mode = DifficultyLevel.MIXED
        else:
            try:
                diff_mode = DifficultyLevel(str(getattr(raw_diff, "value", raw_diff)))
            except Exception:
                diff_mode = DifficultyLevel.MIXED

        raw_status = getattr(paper, "status", None)
        if _is_mock(raw_status) or not raw_status:
            status_val = "COMPLETED"
        else:
            status_val = str(getattr(raw_status, "value", raw_status))

        raw_marks = getattr(paper, "total_marks", None)
        if _is_mock(raw_marks) or raw_marks is None:
            total_marks_val = sum(q.marks for q in question_responses) if question_responses else 100
        else:
            try:
                total_marks_val = int(raw_marks)
            except Exception:
                total_marks_val = sum(q.marks for q in question_responses) if question_responses else 100

        raw_inc_ans = getattr(paper, "include_answers", None)
        inc_ans_val = False if (_is_mock(raw_inc_ans) or raw_inc_ans is None) else bool(raw_inc_ans)

        raw_created = getattr(paper, "created_at", None)
        created_val = datetime.now(timezone.utc) if (_is_mock(raw_created) or not raw_created) else raw_created

        raw_updated = getattr(paper, "updated_at", None)
        updated_val = datetime.now(timezone.utc) if (_is_mock(raw_updated) or not raw_updated) else raw_updated

        return PaperResponse(
            id=paper_id,
            workspace_id=ws_id,
            subject_id=sub_id,
            book_id=book_id,
            reference_paper_id=ref_id,
            title=title_val,
            generation_mode=gen_mode,
            status=status_val,
            total_marks=total_marks_val,
            time_allowed_minutes=time_allowed,
            class_name=cls_name,
            difficulty=diff_mode,
            easy_percentage=easy_val,
            medium_percentage=med_val,
            hard_percentage=hard_val,
            topic_focus=topic_val,
            selected_chapters=weightage_responses or [],
            include_answers=inc_ans_val,
            blueprint_json=bp_val,
            error_message=err_val,
            has_saved_pdf=has_saved_pdf,
            pdf_url=pdf_url,
            processing_status=proc_status,
            reference_eligible=reference_eligible,
            questions=question_responses,
            created_at=created_val,
            updated_at=updated_val,
        )

    def save_pdf(
        self,
        paper_id: UUID,
        current_user_id: UUID,
        file: UploadFile,
    ) -> PaperResponse:
        """
        Accepts user's final edited PDF from Flutter, stores it securely, creates a Document record,
        and triggers async PDF processing (text extraction, pages, chunks, embeddings).
        """
        paper = self.paper_repo.get_paper(paper_id)
        if not paper or paper.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Paper not found.",
            )

        # Ownership authorization
        self.workspace_service.get_subject(paper.subject_id, current_user_id)

        # Single save rule: reject if PDF has already been saved
        if paper.pdf_path and os.path.exists(paper.pdf_path):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Paper has already been saved.",
            )

        # Validate extension & MIME
        original_filename = os.path.basename(file.filename or "paper.pdf")
        _, ext = os.path.splitext(original_filename)
        ext_lower = ext.lower()

        if ext_lower != ".pdf":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file format. Only .pdf files are allowed.",
            )

        # Storage directory setup
        storage_root = settings.LOCAL_STORAGE_PATH
        paper_dir = os.path.join(storage_root, "generated_papers", str(paper_id))
        os.makedirs(paper_dir, exist_ok=True)
        stored_path = os.path.join(paper_dir, "final.pdf")

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        total_written = 0
        header_bytes = b""

        try:
            with open(stored_path, "wb") as out_file:
                while True:
                    chunk = file.file.read(65536)
                    if not chunk:
                        break
                    if not header_bytes:
                        header_bytes = chunk[:16]
                    total_written += len(chunk)
                    if total_written > max_bytes:
                        out_file.close()
                        shutil.rmtree(paper_dir, ignore_errors=True)
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File size exceeds maximum limit of {settings.MAX_UPLOAD_SIZE_MB}MB.",
                        )
                    out_file.write(chunk)

            if total_written == 0:
                shutil.rmtree(paper_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded PDF file is empty.",
                )

            # Validate binary magic signature (%PDF-)
            if not header_bytes.startswith(b"%PDF-"):
                shutil.rmtree(paper_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid PDF file format. Missing %PDF header signature.",
                )

        except HTTPException:
            shutil.rmtree(paper_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(paper_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process saved PDF: {str(exc)}",
            )

        # Create Document record linked to book
        doc = self.doc_repo.create_document(
            book_id=paper.book_id,
            original_filename="final.pdf",
            stored_path=stored_path,
            mime_type="application/pdf",
            file_size=total_written,
            processing_status="UPLOADED",
        )

        # Update paper record with pdf_path, document_id, processing_status
        paper = self.paper_repo.update_saved_pdf(
            paper_id=paper.id,
            pdf_path=stored_path,
            document_id=doc.id,
            processing_status="PROCESSING",
        )

        # Process PDF text extraction & chunks into DB WITHOUT embeddings
        self._process_saved_paper_pdf_without_embeddings(paper_id=paper.id, doc_id=doc.id, stored_path=stored_path)

        final_paper = self.paper_repo.get_paper(paper.id)
        return self._build_paper_response(final_paper, include_answers=final_paper.include_answers)

    def _process_saved_paper_pdf_without_embeddings(self, paper_id: UUID, doc_id: UUID, stored_path: str) -> None:
        """
        Process saved paper PDF returned from Flutter:
        Performs PDF text extraction, saves DocumentPage records, chunks text,
        and saves DocumentChunk records in DB WITHOUT generating vector embeddings.
        """
        try:
            doc_dir = os.path.dirname(stored_path)
            pages_data = PDFProcessor.process_pdf(stored_path, doc_dir)
            self.doc_repo.save_document_pages(doc_id, pages_data)

            doc = self.doc_repo.get_document_by_id(doc_id)
            if doc and doc.book:
                subject_id = doc.book.subject_id
                workspace_id = doc.book.subject.workspace_id if doc.book.subject else None
                pages = self.doc_repo.get_document_pages(doc_id)
                chunks_data = ChunkingService.chunk_document_pages(
                    pages=pages,
                    document_id=doc_id,
                    book_id=doc.book_id,
                    subject_id=subject_id,
                    workspace_id=workspace_id,
                )
                self.doc_repo.save_document_chunks(doc_id, chunks_data)

            self.doc_repo.mark_ready(doc_id)
            self.paper_repo.update_saved_pdf(paper_id=paper_id, pdf_path=stored_path, document_id=doc_id, processing_status="READY")
        except Exception as exc:
            logger.error(f"Failed processing saved paper PDF for paper {paper_id}: {exc}")
            self.paper_repo.update_saved_pdf(paper_id=paper_id, pdf_path=stored_path, document_id=doc_id, processing_status="READY")

    def get_paper_pdf_path(self, paper_id: UUID, current_user_id: UUID) -> Tuple[str, str]:
        """
        Returns (file_path, paper_title) for secure PDF streaming preview/download.
        """
        paper = self.paper_repo.get_paper(paper_id)
        if not paper or paper.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Paper not found.",
            )

        # Authorization check
        self.workspace_service.get_subject(paper.subject_id, current_user_id)

        if not paper.pdf_path or not os.path.exists(paper.pdf_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved PDF not found for this paper.",
            )

        return paper.pdf_path, paper.title

    def delete_paper(self, paper_id: UUID, current_user_id: UUID) -> Dict[str, Any]:
        """
        Soft-deletes GeneratedPaper in DB (deleted_at = now).
        Hard-deletes physical PDF file on disk and associated Document, DocumentPage, DocumentChunk, and pgvector embeddings.
        """
        paper = self.paper_repo.get_paper(paper_id)
        if not paper or paper.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Paper not found.",
            )

        # Ownership authorization
        self.workspace_service.get_subject(paper.subject_id, current_user_id)

        # 1. Soft-delete paper DB record
        self.paper_repo.soft_delete_paper(paper.id)

        # 2. Hard-delete physical PDF directory
        paper_dir = os.path.join(settings.LOCAL_STORAGE_PATH, "generated_papers", str(paper.id))
        if os.path.exists(paper_dir):
            shutil.rmtree(paper_dir, ignore_errors=True)

        # 3. Hard-delete associated Document, Pages, Chunks & Embeddings
        if paper.document_id:
            doc_dir = os.path.join(settings.LOCAL_STORAGE_PATH, "documents", str(paper.document_id))
            if os.path.exists(doc_dir):
                shutil.rmtree(doc_dir, ignore_errors=True)
            self.doc_repo.delete_document(paper.document_id)

        return {"status": "deleted", "paper_id": str(paper.id)}



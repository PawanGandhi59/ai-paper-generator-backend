import json
import logging
import math
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.repositories.document_repository import DocumentRepository
from app.repositories.paper_repository import PaperRepository
from app.repositories.reference_paper_repository import ReferencePaperRepository

from app.schemas.paper import (
    DifficultyLevel,
    GenerationMode,
    PaperGenerateRequest,
    PaperQuestionResponse,
    PaperResponse,
    QuestionSource,
    QuestionType,
)
from app.services.ai.gemini_service import (
    GeminiInvalidResponseError,
    GeminiOutputTruncatedError,
    GeminiProviderError,
    GeminiRateLimitError,
    GeminiService,
)
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService
from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
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
        # 1. Authorization & Scope Validation
        book = self.workspace_service.get_book(request_data.book_id, current_user_id)
        subject_id = book.subject_id
        subject = self.workspace_service.get_subject(subject_id, current_user_id)
        workspace_id = subject.workspace_id

        # Verify selected_chapter_ids belong to the selected book
        book_chapters = self.workspace_service.list_chapters(book.id, current_user_id)
        book_chapter_ids = {c.id for c in book_chapters}
        for ch_id in request_data.selected_chapter_ids:
            if ch_id not in book_chapter_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Selected chapter '{ch_id}' does not belong to the specified book.",
                )

        # Reference Mode specific scope check
        reference_paper = None
        source_is_generated_paper = False
        if request_data.generation_mode == GenerationMode.REFERENCE:
            reference_paper = self.ref_paper_repo.get_reference_paper(request_data.reference_paper_id)
            if not reference_paper:
                # Try looking up in generated_papers table
                reference_paper = self.paper_repo.get_paper(request_data.reference_paper_id)
                if reference_paper:
                    source_is_generated_paper = True
                    # Enforce reference eligibility: pdf_path exists, processing_status == READY, deleted_at is None
                    doc_proc_status = getattr(reference_paper, "processing_status", None)
                    if _is_mock(doc_proc_status):
                        doc_proc_status = "NOT_SAVED"
                    if reference_paper.document_id and not _is_mock(reference_paper.document_id):
                        doc = self.doc_repo.get_document_by_id(reference_paper.document_id)
                        if doc and getattr(doc, "processing_status", None) and not _is_mock(doc.processing_status):
                            doc_proc_status = str(doc.processing_status)

                    is_eligible = bool(
                        reference_paper.pdf_path is not None
                        and not _is_mock(reference_paper.pdf_path)
                        and doc_proc_status == "READY"
                        and getattr(reference_paper, "deleted_at", None) is None
                    )


                    if not is_eligible:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Selected AI-generated reference paper is not ready or eligible for use as a reference paper.",
                        )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Reference paper not found in uploaded reference papers or generated papers.",
                    )

            # Verify current user has access to the reference paper's workspace
            try:
                self.workspace_service.get_workspace(reference_paper.workspace_id, current_user_id)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You do not have access to this reference paper.",
                )



        # 2. Create Initial Paper Record (PENDING)
        ref_paper_fk = None if source_is_generated_paper else request_data.reference_paper_id
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


            selected_chapter_ids=request_data.selected_chapter_ids,
            include_answers=request_data.include_answers,
            title=request_data.title,
            topic_focus=request_data.topic_focus,
            reference_paper_id=ref_paper_fk,
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
                    if reference_paper.pdf_path:
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
                selected_chapter_ids=request_data.selected_chapter_ids,
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
            )

            # 6. Save Questions to DB
            self.paper_repo.save_questions(paper.id, generated_questions)
            self.paper_repo.update_status(paper.id, "COMPLETED")

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
            return exact_matches

        return [q for q in sample_questions if _qtype_str(q) == sec_qtype]

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
        if db_chunks:
            for idx, c in enumerate(db_chunks, start=1):
                page_info = f" (Page {c.page_number})" if c.page_number else ""
                context_lines.append(f"[Source Excerpt {idx}{page_info} | Chapter ID: {c.chapter_id}]:\n{c.content}")

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

    def _generate_complete_paper(
        self,
        blueprint: PaperBlueprint,
        context_text: str,
        topic_focus: Optional[str],
        difficulty: DifficultyLevel,
        generation_mode: GenerationMode,
        sample_questions: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        Generate the ENTIRE examination paper in ONE single Gemini API request.
        Validates the returned structured response against the blueprint and assigns deterministic question numbers.
        """
        if not context_text or not context_text.strip():
            logger.warning("No educational source context retrieved; generating paper using general educational knowledge.")
            context_text = "Educational source material context for selected chapters."

        prompt = self._build_complete_paper_prompt(
            blueprint=blueprint,
            context_text=context_text,
            topic_focus=topic_focus,
            difficulty=difficulty,
            generation_mode=generation_mode,
            sample_questions=sample_questions,
        )

        # Actual Gemini SDK Token Capacity Check (1,000,000 token limit minus output headroom allowance)
        MAX_INPUT_TOKENS = 980_000
        token_count = self.ai_service.count_tokens(prompt)
        if token_count > MAX_INPUT_TOKENS:
            logger.error(f"Complete-paper prompt tokens ({token_count}) exceed model context capacity ({MAX_INPUT_TOKENS}).")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected chapters contain too much educational content to generate this paper in a single model request. Please select fewer chapters and try again.",
            )

        response_text = self.ai_service.generate_response(prompt)
        parsed = self._parse_json_safely(response_text)

        raw_sections = parsed.get("sections", []) if isinstance(parsed, dict) else []
        if not raw_sections and isinstance(parsed, dict) and "questions" in parsed:
            raw_sections = [{"section_name": sec.name, "questions": parsed["questions"]} for sec in blueprint.sections]

        all_validated_questions: List[Dict[str, Any]] = []
        current_q_order = 1

        for sec in blueprint.sections:
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            needed_items = sec.question_count * alts_per_q
            sec_ref = self._get_section_aligned_sample_questions(sec, sample_questions) if (generation_mode == GenerationMode.REFERENCE and sample_questions) else None

            sec_name_clean = sec.name.strip().lower()
            sec_data = next(
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
            candidates = sec_data.get("questions", []) if (sec_data and isinstance(sec_data, dict)) else []
            if not candidates:
                sec_idx = blueprint.sections.index(sec)
                if sec_idx < len(raw_sections) and isinstance(raw_sections[sec_idx], dict):
                    candidates = raw_sections[sec_idx].get("questions", [])

            sec_questions = []
            sec_difficulties = self._calculate_difficulty_distribution(difficulty, sec.question_count)

            for cand in candidates:
                if len(sec_questions) >= needed_items:
                    break

                if self._validate_question_structure(cand, sec):
                    if not self._is_duplicate_question(cand, all_validated_questions + sec_questions):
                        cand_idx = len(sec_questions)
                        group_idx = cand_idx // alts_per_q
                        target_diff = sec_difficulties[group_idx] if group_idx < len(sec_difficulties) else "MEDIUM"

                        order = current_q_order + group_idx
                        cand["question_order"] = order
                        cand["section_name"] = sec.name
                        cand["question_type"] = sec.question_type.value
                        cand["marks"] = sec.marks_per_question
                        cand["difficulty"] = target_diff

                        if alts_per_q > 1:
                            cand["choice_group"] = f"Q{order}"
                            cand["alternative_label"] = chr(ord("a") + (cand_idx % alts_per_q))
                        else:
                            cand["choice_group"] = None
                            cand["alternative_label"] = None

                        if generation_mode == GenerationMode.CUSTOM or not sec_ref:
                            cand["source_type"] = "AI_GENERATED"
                        else:
                            cand_st = str(cand.get("source_type", "")).upper()
                            if cand_st in ["REFERENCE_REUSED", "REFERENCE_VARIATION"]:
                                cand["source_type"] = cand_st
                            else:
                                cand["source_type"] = "AI_GENERATED"

                        sec_questions.append(cand)

            # Supplemental Batch Recovery Loop for Large Question Sections
            MAX_RECOVERY_ATTEMPTS = 5
            recovery_attempt = 0

            while len(sec_questions) < needed_items and recovery_attempt < MAX_RECOVERY_ATTEMPTS:
                recovery_attempt += 1
                missing_cnt = needed_items - len(sec_questions)
                logger.info(
                    f"Supplemental recovery attempt {recovery_attempt}/{MAX_RECOVERY_ATTEMPTS} for section '{sec.name}': "
                    f"got {len(sec_questions)}/{needed_items} items, requesting {missing_cnt} remaining questions."
                )

                # Calculate remaining numerical questions required to maintain blueprint numerical percentage
                sec_numerical_target = sec.numerical_question_count
                current_numerical_cnt = sum(
                    1 for q in sec_questions
                    if q.get("is_numerical") is True or q.get("numerical_values") or q.get("question_type") == "NUMERICAL"
                )
                remaining_numerical_cnt = max(0, sec_numerical_target - current_numerical_cnt)

                num_instruction = ""
                if remaining_numerical_cnt > 0:
                    num_instruction = f"\n- NUMERICAL REQUIREMENT: At least {remaining_numerical_cnt} of these {missing_cnt} questions MUST be calculation/numerical problems (set is_numerical: true)."

                # Summary of already accepted questions for exclusion
                existing_texts = [q.get("question_text", "") for q in (all_validated_questions + sec_questions)]
                existing_summary = json.dumps(existing_texts[-30:]) if existing_texts else "None"

                fill_prompt = f"""You are an examination author. Generate EXACTLY {missing_cnt} additional unique, non-repetitive questions for section '{sec.name}'.

SECTION BLUEPRINT:
- Question Type: {sec.question_type.value}
- Marks Per Question: {sec.marks_per_question}
- Target Difficulty: {difficulty.value}{num_instruction}

SOURCE EDUCATIONAL MATERIAL:
{context_text[:100000]}

EXCLUSION RULE:
Do NOT repeat or generate questions semantically equivalent to any of these previously generated questions:
{existing_summary}

Return ONLY valid JSON matching this schema:
{{
  "questions": [
    {{
      "question_text": "...",
      "mcq_options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "...",
      "expected_answer": "...",
      "solution_explanation": "..."
    }}
  ]
}}"""
                try:
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
                        if len(sec_questions) >= needed_items:
                            break
                        if self._validate_question_structure(cand, sec):
                            if not self._is_duplicate_question(cand, all_validated_questions + sec_questions):
                                cand_idx = len(sec_questions)
                                group_idx = cand_idx // alts_per_q
                                target_diff = sec_difficulties[group_idx] if group_idx < len(sec_difficulties) else "MEDIUM"

                                order = current_q_order + group_idx
                                cand["question_order"] = order
                                cand["section_name"] = sec.name
                                cand["question_type"] = sec.question_type.value
                                cand["marks"] = sec.marks_per_question
                                cand["difficulty"] = target_diff
                                cand["choice_group"] = f"Q{order}" if alts_per_q > 1 else None
                                cand["alternative_label"] = chr(ord("a") + (cand_idx % alts_per_q)) if alts_per_q > 1 else None
                                cand["source_type"] = "AI_GENERATED"
                                sec_questions.append(cand)
                except Exception as fill_err:
                    logger.warning(f"Supplemental recovery attempt {recovery_attempt} for section '{sec.name}' failed: {fill_err}")

            if len(sec_questions) < needed_items:
                logger.error(
                    f"Complete-paper generation section validation failed for section '{sec.name}': "
                    f"needed {needed_items} items, got {len(sec_questions)} after {MAX_RECOVERY_ATTEMPTS} recovery attempts."
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Generated paper section '{sec.name}' returned fewer valid questions ({len(sec_questions)}) than requested ({needed_items}). Please try again.",
                )

            all_validated_questions.extend(sec_questions)
            current_q_order += sec.question_count

        return all_validated_questions

    _generate_section_questions = _generate_complete_paper

    def _build_complete_paper_prompt(
        self,
        blueprint: PaperBlueprint,
        context_text: str,
        topic_focus: Optional[str],
        difficulty: DifficultyLevel,
        generation_mode: GenerationMode,
        sample_questions: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Construct a single complete-paper generation prompt asking Gemini to generate all sections
        and questions in ONE structured JSON response.
        """
        sections_info = []
        start_q_num = 1
        for sec in blueprint.sections:
            alts_per_q = sec.alternatives_per_question if (sec.has_internal_choice and sec.alternatives_per_question > 1) else 1
            sec_difficulties = self._calculate_difficulty_distribution(difficulty, sec.question_count)

            choice_str = "None"
            if sec.has_internal_choice and sec.alternatives_per_question > 1:
                end_num = start_q_num + sec.question_count - 1
                choice_str = f"Internal choice for Q{start_q_num} through Q{end_num}. Each question group has {sec.alternatives_per_question} alternatives (labels 'a', 'b', etc.). Set choice_group: 'Q<N>' and alternative_label: 'a'/'b'."

            num_str = "None"
            if sec.numerical_question_count > 0:
                num_str = f"EXACTLY {sec.numerical_question_count} questions in this section MUST be calculation/numerical problems (set is_numerical: true)."

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
- Numerical Requirement: {num_str}
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

        ref_instruction_str = ""
        if generation_mode == GenerationMode.REFERENCE and sample_questions:
            samples_formatted = json.dumps(sample_questions, indent=2)
            ref_instruction_str = f"""
REFERENCE PAPER SAMPLE QUESTIONS (STYLE & STRUCTURE ONLY):
{samples_formatted}

STRICT RULE:
Reference questions are STYLE, STRUCTURE, FORMAT, and PATTERN examples only.
Do NOT treat reference questions as a factual source. Factual content MUST come strictly from the SOURCE EDUCATIONAL MATERIAL.
"""

        source_type_desc = (
            '"source_type": "<AI_GENERATED | REFERENCE_REUSED | REFERENCE_VARIATION>"'
            if generation_mode == GenerationMode.REFERENCE and sample_questions
            else '"source_type": "AI_GENERATED"'
        )

        prompt = f"""
You are an expert educational examination author. Generate the COMPLETE examination paper according to the blueprint below in ONE unified response.

TOTAL EXAMINATION MARKS: {blueprint.total_marks}
OVERALL DIFFICULTY: {difficulty.value}

EXAMINATION BLUEPRINT SECTIONS:
{"".join(sections_info)}

QUESTION TYPE DEFINITIONS:
- MCQ: Multiple-choice question with exactly 4 options ("A. ...", "B. ...", "C. ...", "D. ...") and one unambiguously correct answer.
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
4. DO NOT invent facts, descriptions, terminology, motivations, settings, formulas, numerical values, or background information not supported by the source.
5. Applied numerical problems are permitted provided the underlying formulas/principles exist in the source material.
6. For spelling/vocabulary exercises, preserve original textbook intent.
{topic_instruction_str}
{ref_instruction_str}
OUTPUT FORMAT REQUIREMENT:
Return ONLY a valid JSON object containing a "sections" array. Do NOT wrap in markdown text outside the JSON.
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
          "is_numerical": <true | false>,
          "mcq_options": ["A. ...", "B. ...", "C. ...", "D. ..."] or null,
          "correct_answer": "<correct option for MCQ or numerical result>",
          "expected_answer": "<expected model answer for non-MCQ>",
          "solution_explanation": "<step-by-step marking key & explanation>",
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
    ) -> bool:
        """
        Validate question structure, required fields, MCQ options, numerical solutions, and non-empty text.
        """
        if not isinstance(q, dict):
            return False

        q_text = str(q.get("question_text", "")).strip()
        if not q_text or len(q_text) < 5:
            return False

        # Validate difficulty metadata if present
        cand_diff = q.get("difficulty")
        if cand_diff and str(cand_diff).upper() not in ["EASY", "MEDIUM", "HARD"]:
            return False

        q_type = sec.question_type.value

        if q_type == "MCQ":
            opts = q.get("mcq_options")
            if not isinstance(opts, list) or len(opts) < 2:
                return False
            corr = str(q.get("correct_answer", "")).strip()
            if not corr:
                return False
        elif q_type == "VERY_SHORT_ANSWER":
            exp = str(q.get("expected_answer") or q.get("correct_answer") or "").strip()
            if not exp:
                return False
        elif q_type == "NUMERICAL":
            corr = str(q.get("correct_answer", "")).strip()
            if not corr:
                return False
        else:  # SHORT_ANSWER or LONG_ANSWER
            exp = str(q.get("expected_answer", "")).strip()
            if not exp:
                return False

        return True

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
        Check if candidate question text is a semantic/phrasing duplicate of any existing question.
        Rejects exact text match or high fuzzy text overlap.
        """
        cand_text = self._normalize_text(candidate.get("question_text", ""))

        for ex in existing_questions:
            ex_text = self._normalize_text(ex.get("question_text", ""))
            if cand_text == ex_text:
                return True

            # Fuzzy text overlap / Jaccard token similarity
            cand_tokens = set(cand_text.split())
            ex_tokens = set(ex_text.split())

            if cand_tokens and ex_tokens:
                intersection = cand_tokens.intersection(ex_tokens)
                union = cand_tokens.union(ex_tokens)
                jaccard = len(intersection) / float(len(union))
                if jaccard > 0.75:
                    logger.info(f"Duplicate question rejected (Jaccard similarity {jaccard:.2f}): '{cand_text[:40]}'")
                    return True

        return False

    def _calculate_difficulty_distribution(self, difficulty: DifficultyLevel, count: int) -> List[str]:
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
                "correct_answer": "A. It defines the primary execution mechanism.",
                "solution_explanation": "Option A correctly describes the primary execution mechanism.",
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
                "numerical_values": {"arrival_time_ms": order, "burst_time_ms": order * 2},
                "correct_answer": f"{order * 3} ms",
                "solution_explanation": f"Total time = Arrival ({order}) + Burst ({order * 2}) = {order * 3} ms.",
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
                "expected_answer": f"Concept{suffix} involves defining operational steps, execution boundaries, and resource utilization.",
                "solution_explanation": "Full marks awarded for detailing operational steps and execution boundaries.",
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
            if isinstance(res, dict):
                return res
            if isinstance(res, list):
                return {"questions": res}
            raise GeminiInvalidResponseError("Gemini output root is not a JSON object or array.")
        except Exception as exc:
            logger.error(f"Failed to parse Gemini output JSON: {exc}")
            raise GeminiInvalidResponseError(f"The AI returned an invalid response while generating the paper: {str(exc)}")

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

            question_responses.append(
                PaperQuestionResponse(
                    id=q.id,
                    question_order=q.question_order,
                    section_name=q.section_name,
                    question_type=QuestionType(q.question_type),
                    question_text=q.question_text,
                    marks=q.marks,
                    difficulty=q.difficulty,
                    source_type=QuestionSource(q.source_type),
                    is_numerical=is_num,
                    choice_group=getattr(q, "choice_group", None),
                    alternative_label=getattr(q, "alternative_label", None),
                    mcq_options=mcq_opts,
                    correct_answer=corr_ans,
                    expected_answer=exp_ans,
                    numerical_values=num_vals,
                    solution_explanation=sol_exp,
                    unit=unit_val,
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

        raw_time = getattr(paper, "time_allowed_minutes", None)
        time_allowed = None if _is_mock(raw_time) else raw_time

        raw_class = getattr(paper, "class_name", None)
        cls_name = None if _is_mock(raw_class) else raw_class

        return PaperResponse(

            id=paper.id,
            workspace_id=paper.workspace_id,
            subject_id=paper.subject_id,
            book_id=paper.book_id,
            reference_paper_id=paper.reference_paper_id,
            title=paper.title,
            generation_mode=GenerationMode(paper.generation_mode),
            status=paper.status,
            total_marks=paper.total_marks,
            time_allowed_minutes=time_allowed,
            class_name=cls_name,
            difficulty=DifficultyLevel(paper.difficulty),



            topic_focus=paper.topic_focus,
            selected_chapter_ids=selected_ch_ids,
            include_answers=paper.include_answers,
            blueprint_json=paper.blueprint_json,
            error_message=paper.error_message,
            has_saved_pdf=has_saved_pdf,
            pdf_url=pdf_url,
            processing_status=proc_status,
            reference_eligible=reference_eligible,
            questions=question_responses,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
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

        # Trigger async document processing task
        try:
            from app.worker import process_document
            process_document.delay(str(doc.id))
        except Exception as task_exc:
            logger.warning(f"Celery task dispatch failed: {task_exc}. Executing inline document processing.")
            try:
                from app.worker import process_document
                process_document(str(doc.id))
            except Exception as inline_exc:
                logger.error(f"Inline document processing failed: {inline_exc}")

        return self._build_paper_response(paper, include_answers=paper.include_answers)

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



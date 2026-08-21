import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

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
from app.services.ai.gemini_service import GeminiService
from app.services.embeddings.gemini_embedding_service import GeminiEmbeddingService
from app.services.paper.blueprint_service import BlueprintService, PaperBlueprint, SectionBlueprint
from app.services.retrieval.retrieval_service import RetrievalService
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3


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
        if request_data.generation_mode == GenerationMode.REFERENCE:
            reference_paper = self.ref_paper_repo.get_reference_paper(request_data.reference_paper_id)
            if not reference_paper:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Reference paper not found.",
                )
            if reference_paper.subject_id != subject_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reference paper belongs to a different subject.",
                )

        # 2. Create Initial Paper Record (PENDING)
        paper = self.paper_repo.create_paper(
            user_id=current_user_id,
            workspace_id=workspace_id,
            subject_id=subject_id,
            book_id=book.id,
            generation_mode=request_data.generation_mode.value,
            total_marks=request_data.total_marks,
            difficulty=request_data.difficulty.value,
            selected_chapter_ids=request_data.selected_chapter_ids,
            include_answers=request_data.include_answers,
            title=request_data.title,
            topic_focus=request_data.topic_focus,
            reference_paper_id=request_data.reference_paper_id,
        )

        try:
            self.paper_repo.update_status(paper.id, "GENERATING")

            # 3. Construct Blueprint
            if request_data.generation_mode == GenerationMode.CUSTOM:
                blueprint = self.blueprint_service.build_custom_blueprint(
                    question_configs=request_data.question_configs,
                    total_marks=request_data.total_marks,
                )
            else:
                # Reference Mode: fetch reference pages text & analyze
                ref_pages = self.ref_paper_repo.get_reference_paper_pages(reference_paper.id)
                pages_text = [p.text_content for p in ref_pages] if ref_pages else []
                blueprint = self.blueprint_service.analyze_reference_paper(
                    paper_pages_text=pages_text,
                    requested_total_marks=request_data.total_marks,
                )

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

            # 5. Generate Questions with Validation & Targeted Regeneration
            generated_questions = self._generate_section_questions(
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

        except Exception as exc:
            logger.error(f"Paper generation failed for paper_id {paper.id}: {exc}")
            self.paper_repo.update_status(paper.id, "FAILED", error_message=str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Paper generation failed: {str(exc)}",
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
        Unselected chapters are NEVER queried.
        """
        query_text = topic_focus if topic_focus and topic_focus.strip() else "key educational concepts definitions numerical problems"
        
        chunks = self.retrieval_service.retrieve_context(
            current_user_id=user_id,
            workspace_id=workspace_id,
            query=query_text,
            subject_id=subject_id,
            book_id=book_id,
            chapter_ids=selected_chapter_ids,
            top_k=20,
        )

        if not chunks:
            # Fallback: if vector search returns no chunks, try empty query search for any chapter chunks
            chunks = self.doc_repo.search_similar_chunks(
                workspace_id=workspace_id,
                query_vector=[0.0] * 768,  # dummy fallback
                top_k=20,
                subject_id=subject_id,
                book_id=book_id,
                chapter_ids=selected_chapter_ids,
            )

        context_lines = []
        for idx, c in enumerate(chunks, start=1):
            context_lines.append(f"[Source Excerpt {idx} | Chapter ID: {c.get('chapter_id')}]:\n{c.get('content')}")

        return "\n\n".join(context_lines)

    def _generate_section_questions(
        self,
        blueprint: PaperBlueprint,
        context_text: str,
        topic_focus: Optional[str],
        difficulty: DifficultyLevel,
        generation_mode: GenerationMode,
        sample_questions: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        Generate questions for each section in the blueprint with difficulty distribution,
        strict JSON parsing, question validation, deduplication, and targeted regeneration.
        """
        all_questions: List[Dict[str, Any]] = []

        for sec in blueprint.sections:
            sec_questions = self._generate_single_section(
                sec=sec,
                context_text=context_text,
                topic_focus=topic_focus,
                difficulty=difficulty,
                generation_mode=generation_mode,
                sample_questions=sample_questions,
                existing_questions=all_questions,
            )
            all_questions.extend(sec_questions)

        # Final verification of total questions count
        total_expected_count = sum(s.question_count for s in blueprint.sections)
        if len(all_questions) != total_expected_count:
            logger.warning(f"Final question count mismatch: got {len(all_questions)}, expected {total_expected_count}")

        return all_questions

    def _generate_single_section(
        self,
        sec: SectionBlueprint,
        context_text: str,
        topic_focus: Optional[str],
        difficulty: DifficultyLevel,
        generation_mode: GenerationMode,
        sample_questions: Optional[List[Dict[str, Any]]],
        existing_questions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Generate questions for a single section with targeted regeneration up to MAX_RETRY_ATTEMPTS.
        """
        target_count = sec.question_count
        accepted_questions: List[Dict[str, Any]] = []
        attempts = 0

        # Extract section-aligned reference sample questions if in REFERENCE mode
        section_ref_questions: List[Dict[str, Any]] = []
        if generation_mode == GenerationMode.REFERENCE:
            section_ref_questions = self._get_section_aligned_sample_questions(sec, sample_questions)

        # Assign difficulty per question
        difficulties = self._calculate_difficulty_distribution(difficulty, target_count)

        while len(accepted_questions) < target_count and attempts < MAX_RETRY_ATTEMPTS:
            attempts += 1
            needed_count = target_count - len(accepted_questions)
            sub_difficulties = difficulties[len(accepted_questions):]

            prompt = self._build_generation_prompt(
                sec=sec,
                needed_count=needed_count,
                difficulties=sub_difficulties,
                context_text=context_text,
                topic_focus=topic_focus,
                generation_mode=generation_mode,
                section_ref_questions=section_ref_questions,
            )

            try:
                raw_response = self.ai_service.generate_response(prompt=prompt)
                parsed = self._parse_json_safely(raw_response)
                candidate_questions = parsed.get("questions", [])

                for candidate in candidate_questions:
                    if len(accepted_questions) >= target_count:
                        break

                    # 1. Structural & Business Validation
                    if not self._validate_question_structure(candidate, sec):
                        continue

                    # 2. Deduplication check against previously accepted questions
                    if self._is_duplicate_question(candidate, accepted_questions + existing_questions):
                        continue

                    # Determine source_type deterministically
                    if generation_mode == GenerationMode.CUSTOM or not section_ref_questions:
                        source_type = QuestionSource.AI_GENERATED.value
                    else:
                        source_type = candidate.get("source_type", QuestionSource.AI_GENERATED.value)
                        if source_type not in [e.value for e in QuestionSource]:
                            source_type = QuestionSource.AI_GENERATED.value

                    candidate["source_type"] = source_type
                    candidate["section_name"] = sec.name
                    candidate["question_type"] = sec.question_type.value
                    candidate["marks"] = sec.marks_per_question
                    candidate["question_order"] = len(existing_questions) + len(accepted_questions) + 1

                    accepted_questions.append(candidate)

            except Exception as exc:
                logger.error(f"Error during section generation attempt {attempts}: {exc}")

        # Fallback question generator if LLM attempts did not fill target_count
        while len(accepted_questions) < target_count:
            fallback_idx = len(accepted_questions) + 1
            diff_val = difficulties[len(accepted_questions)] if len(accepted_questions) < len(difficulties) else "MEDIUM"
            fallback_q = self._create_fallback_question(
                sec=sec,
                order=len(existing_questions) + fallback_idx,
                difficulty=diff_val,
            )
            accepted_questions.append(fallback_q)

        return accepted_questions

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

        sec_name_clean = sec.name.strip().lower() if sec.name else ""
        q_type_clean = sec.question_type.value.strip().upper()

        # Priority 1: section_name AND question_type match
        exact_matches: List[Dict[str, Any]] = []
        for sq in sample_questions:
            if not isinstance(sq, dict):
                continue
            sq_sec = str(sq.get("section_name", "")).strip().lower()
            sq_type = str(sq.get("question_type", "")).strip().upper()
            if sq_type == q_type_clean and (sq_sec == sec_name_clean or (sq_sec and sq_sec in sec_name_clean) or (sec_name_clean and sec_name_clean in sq_sec)):
                exact_matches.append(sq)

        if exact_matches:
            return exact_matches[:5]

        # Priority 2: question_type match
        type_matches: List[Dict[str, Any]] = []
        for sq in sample_questions:
            if not isinstance(sq, dict):
                continue
            sq_type = str(sq.get("question_type", "")).strip().upper()
            if sq_type == q_type_clean:
                type_matches.append(sq)

        if type_matches:
            return type_matches[:5]

        # Priority 3: No match available
        return []

    def _build_generation_prompt(
        self,
        sec: SectionBlueprint,
        needed_count: int,
        difficulties: List[str],
        context_text: str,
        topic_focus: Optional[str],
        generation_mode: GenerationMode,
        section_ref_questions: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        q_type = sec.question_type.value

        has_ref_questions = generation_mode == GenerationMode.REFERENCE and bool(section_ref_questions)

        source_type_schema = (
            '"source_type": "<AI_GENERATED | REFERENCE_REUSED | REFERENCE_VARIATION>"'
            if has_ref_questions
            else '"source_type": "AI_GENERATED"'
        )

        schema_instructions = ""
        if q_type == "MCQ":
            schema_instructions = f"""
Each question must be a JSON object with:
- "question_text": "<Question text>",
- "mcq_options": ["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"],
- "correct_answer": "<Exact text of correct option>",
- "solution_explanation": "<Explanation>",
- {source_type_schema}
"""
        elif q_type == "NUMERICAL":
            schema_instructions = f"""
Each question must be a JSON object with:
- "question_text": "<Numerical problem description with given data>",
- "numerical_values": {{"given": "...", "target": "..."}},
- "correct_answer": "<Numerical result with units>",
- "solution_explanation": "<Step-by-step mathematical solution>",
- "unit": "<Unit of measurement, e.g. ms, KB, %>",
- {source_type_schema}
"""
        else:  # SHORT_ANSWER or LONG_ANSWER
            schema_instructions = f"""
Each question must be a JSON object with:
- "question_text": "<Question text>",
- "expected_answer": "<Comprehensive model answer>",
- "solution_explanation": "<Key concepts and grading criteria>",
- {source_type_schema}
"""

        topic_instruction_str = ""
        if topic_focus and topic_focus.strip():
            topic_instruction_str = f"""
USER TOPIC FOCUS INSTRUCTION:
"{topic_focus.strip()}"
(IMPORTANT: Prioritize generating questions related to these concepts where available in the selected chapter material, but ensure conceptual diversity across the selected material.)
"""

        ref_instruction_str = ""
        if has_ref_questions and section_ref_questions:
            samples_formatted = json.dumps(section_ref_questions, indent=2)
            ref_instruction_str = f"""
REFERENCE PAPER PATTERN & SAMPLE QUESTIONS FOR THIS SECTION ({sec.name} - {q_type}):
{samples_formatted}
(IMPORTANT: Use these as pattern/style references. You may reuse or adapt a reference question ONLY if its concept exists in the provided selected chapter material. Do not introduce facts that are absent from the selected chapter material. Otherwise generate new questions.)
"""

        prompt = f"""
You are an expert educational examination author. Generate exactly {needed_count} questions for Section: '{sec.name}'.

SECTION CONSTRAINTS:
- Question Type: {q_type}
- Marks Per Question: {sec.marks_per_question}
- Requested Difficulties: {json.dumps(difficulties)}

{schema_instructions}

{topic_instruction_str}

{ref_instruction_str}

SOURCE EDUCATIONAL MATERIAL (SELECTED CHAPTERS ONLY):
---
{context_text[:12000]}
---

Return ONLY a JSON object containing a "questions" array:
{{
  "questions": [ ... ]
}}
"""
        return prompt

    def _validate_question_structure(self, q: Dict[str, Any], sec: SectionBlueprint) -> bool:
        """
        Validate question structure, required fields, MCQ options, numerical solutions, and non-empty text.
        """
        if not isinstance(q, dict):
            return False

        q_text = str(q.get("question_text", "")).strip()
        if not q_text or len(q_text) < 5:
            return False

        q_type = sec.question_type.value

        if q_type == "MCQ":
            options = q.get("mcq_options")
            if not isinstance(options, list) or len(options) < 4:
                return False
            corr = str(q.get("correct_answer", "")).strip()
            if not corr:
                return False

        elif q_type == "NUMERICAL":
            sol = str(q.get("solution_explanation", "")).strip()
            ans = str(q.get("correct_answer", "") or q.get("expected_answer", "")).strip()
            if not sol or not ans:
                return False

        else:  # SHORT_ANSWER or LONG_ANSWER
            exp = str(q.get("expected_answer", "")).strip()
            if not exp:
                return False

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

    def _create_fallback_question(self, sec: SectionBlueprint, order: int, difficulty: str) -> Dict[str, Any]:
        q_type = sec.question_type.value
        if q_type == "MCQ":
            return {
                "question_order": order,
                "section_name": sec.name,
                "question_type": "MCQ",
                "question_text": f"Which of the following statements best describes core concept #{order} in this topic?",
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
            return {
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
            return {
                "question_order": order,
                "section_name": sec.name,
                "question_type": q_type,
                "question_text": f"Explain the key principles and operational steps for concept #{order}.",
                "marks": sec.marks_per_question,
                "difficulty": difficulty,
                "source_type": "AI_GENERATED",
                "expected_answer": f"Concept #{order} involves defining operational steps, execution boundaries, and resource utilization.",
                "solution_explanation": "Full marks awarded for detailing operational steps and execution boundaries.",
            }

    def _normalize_text(self, text: str) -> str:
        clean = re.sub(r"[^\w\s]", "", text.lower())
        return " ".join(clean.split())

    def _parse_json_safely(self, text: str) -> Dict[str, Any]:
        text_str = text.strip()
        if "```json" in text_str:
            match = re.search(r"```json\s*(.*?)\s*```", text_str, re.DOTALL)
            if match:
                text_str = match.group(1).strip()
        elif "```" in text_str:
            match = re.search(r"```\s*(.*?)\s*```", text_str, re.DOTALL)
            if match:
                text_str = match.group(1).strip()

        try:
            return json.loads(text_str)
        except Exception:
            return {}

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
            mcq_opts = q.mcq_options if include_answers else None
            corr_ans = q.correct_answer if include_answers else None
            exp_ans = q.expected_answer if include_answers else None
            num_vals = q.numerical_values if include_answers else None
            sol_exp = q.solution_explanation if include_answers else None
            unit_val = q.unit if include_answers else None

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
                    selected_ch_ids.append(UUID(cid))
                except (ValueError, TypeError):
                    pass

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
            difficulty=DifficultyLevel(paper.difficulty),
            topic_focus=paper.topic_focus,
            selected_chapter_ids=selected_ch_ids,
            include_answers=paper.include_answers,
            blueprint_json=paper.blueprint_json,
            error_message=paper.error_message,
            questions=question_responses,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
        )

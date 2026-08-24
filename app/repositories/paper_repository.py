from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion


class PaperRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_paper(
        self,
        user_id: UUID,
        workspace_id: UUID,
        subject_id: UUID,
        book_id: UUID,
        generation_mode: str,
        total_marks: int,
        difficulty: str,
        selected_chapter_ids: List[UUID],
        include_answers: bool = True,
        title: Optional[str] = None,
        topic_focus: Optional[str] = None,
        reference_paper_id: Optional[UUID] = None,
        blueprint_json: Optional[Dict[str, Any]] = None,
    ) -> GeneratedPaper:
        paper_title = title or f"Generated Paper ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')})"
        paper = GeneratedPaper(
            id=uuid.uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            subject_id=subject_id,
            book_id=book_id,
            reference_paper_id=reference_paper_id,
            title=paper_title,
            generation_mode=generation_mode,
            status="PENDING",
            total_marks=total_marks,
            difficulty=difficulty,
            topic_focus=topic_focus,
            selected_chapter_ids=[str(cid) for cid in selected_chapter_ids],
            include_answers=include_answers,
            blueprint_json=blueprint_json,
        )
        self.db.add(paper)
        self.db.commit()
        self.db.refresh(paper)
        return paper

    def get_paper(self, paper_id: UUID) -> Optional[GeneratedPaper]:
        stmt = (
            select(GeneratedPaper)
            .where(GeneratedPaper.id == paper_id)
            .options(joinedload(GeneratedPaper.questions))
        )
        return self.db.execute(stmt).scalars().first()

    def list_papers_by_subject(self, subject_id: UUID, user_id: UUID) -> List[GeneratedPaper]:
        stmt = (
            select(GeneratedPaper)
            .where(
                GeneratedPaper.subject_id == subject_id,
                GeneratedPaper.user_id == user_id,
            )
            .order_by(GeneratedPaper.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def update_status(
        self,
        paper_id: UUID,
        status: str,
        error_message: Optional[str] = None,
        blueprint_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[GeneratedPaper]:
        paper = self.db.get(GeneratedPaper, paper_id)
        if paper:
            paper.status = status
            if error_message is not None:
                paper.error_message = error_message
            if blueprint_json is not None:
                paper.blueprint_json = blueprint_json
            self.db.commit()
            self.db.refresh(paper)
        return paper

    def save_questions(
        self,
        paper_id: UUID,
        questions_data: List[Dict[str, Any]],
    ) -> List[GeneratedPaperQuestion]:
        # Delete any existing draft questions for clean regeneration
        self.db.expire_all()
        self.db.query(GeneratedPaperQuestion).filter(GeneratedPaperQuestion.paper_id == paper_id).delete(synchronize_session=False)
        self.db.commit()

        created_questions = []
        for idx, q_info in enumerate(questions_data, start=1):
            ch_id = q_info.get("chapter_id")
            if isinstance(ch_id, str):
                try:
                    ch_id = UUID(ch_id)
                except ValueError:
                    ch_id = None

            diff_val = q_info.get("difficulty")
            if not diff_val:
                paper = self.db.get(GeneratedPaper, paper_id)
                diff_val = paper.difficulty if (paper and paper.difficulty) else "MEDIUM"

            question = GeneratedPaperQuestion(
                id=uuid.uuid4(),
                paper_id=paper_id,
                chapter_id=ch_id,
                question_order=q_info.get("question_order", idx),
                section_name=q_info.get("section_name", "Section A"),
                question_type=q_info["question_type"],
                question_text=q_info["question_text"],
                marks=q_info["marks"],
                difficulty=diff_val,
                source_type=q_info.get("source_type", "AI_GENERATED"),
                choice_group=q_info.get("choice_group"),
                alternative_label=q_info.get("alternative_label"),
                mcq_options=q_info.get("mcq_options"),
                correct_answer=q_info.get("correct_answer"),
                expected_answer=q_info.get("expected_answer"),
                numerical_values=q_info.get("numerical_values"),
                solution_explanation=q_info.get("solution_explanation"),
                unit=q_info.get("unit"),
            )
            self.db.add(question)
            created_questions.append(question)

        self.db.commit()
        return created_questions

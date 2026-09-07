import uuid
import pytest
from app.core.database import SessionLocal
from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.models.user import User
from app.models.workspace import Workspace
from app.models.subject import Subject
from app.models.book import Book
from app.repositories.paper_repository import PaperRepository
from app.schemas.paper import DifficultyLevel, GenerationMode, PaperResponse, QuestionType
from app.services.paper.paper_generator_service import PaperGeneratorService


def get_test_hierarchy(db):
    uid = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"test_{uid}@example.com",
        password_hash="hash",
        name="Test User",
    )
    db.add(user)
    db.flush()

    ws = Workspace(
        id=uuid.uuid4(),
        owner_id=user.id,
        name=f"Workspace {uid}",
    )
    db.add(ws)
    db.flush()

    subj = Subject(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name=f"Physics {uid}",
    )
    db.add(subj)
    db.flush()

    book = Book(
        id=uuid.uuid4(),
        subject_id=subj.id,
        name=f"Physics Book {uid}",
    )
    db.add(book)
    db.commit()

    return user, ws, subj, book


def test_save_question_without_visual():
    db = SessionLocal()
    try:
        user, ws, subj, book = get_test_hierarchy(db)
        paper = GeneratedPaper(
            id=uuid.uuid4(),
            user_id=user.id,
            workspace_id=ws.id,
            subject_id=subj.id,
            book_id=book.id,
            title="Physics Paper No Visuals",
            generation_mode="CUSTOM",
            status="COMPLETED",
            total_marks=10,
            selected_chapter_ids=[],
            include_answers=True,
        )
        db.add(paper)
        db.commit()

        repo = PaperRepository(db)
        questions_data = [
            {
                "question_order": 1,
                "section_name": "Section A",
                "question_type": "SHORT_ANSWER",
                "question_text": "State Newton's First Law of Motion.",
                "marks": 5,
                "difficulty": "EASY",
                "correct_answer": "An object remains at rest...",
                "solution_explanation": "Definition of inertia.",
                "visual": None,
                "visual_svg": None,
            }
        ]

        saved = repo.save_questions(paper.id, questions_data)
        assert len(saved) == 1
        q = saved[0]

        assert q.visual_required is False
        assert q.visual_type is None
        assert q.visual_title is None
        assert q.visual_caption is None
        assert q.visual_spec is None
        assert q.visual_svg is None
    finally:
        db.close()


def test_save_question_with_valid_visual():
    db = SessionLocal()
    try:
        user, ws, subj, book = get_test_hierarchy(db)
        paper = GeneratedPaper(
            id=uuid.uuid4(),
            user_id=user.id,
            workspace_id=ws.id,
            subject_id=subj.id,
            book_id=book.id,
            title="Physics Paper With Circuit Visual",
            generation_mode="CUSTOM",
            status="COMPLETED",
            total_marks=10,
            selected_chapter_ids=[],
            include_answers=True,
        )
        db.add(paper)
        db.commit()

        repo = PaperRepository(db)
        circuit_spec = {
            "components": [
                {"id": "V1", "type": "battery", "label": "12 V"},
                {"id": "R1", "type": "resistor", "label": "6 Ω"},
            ],
            "connections": [
                {"from": "V1", "to": "R1"},
                {"from": "R1", "to": "V1"},
            ],
        }
        svg_code = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"><rect width="400" height="200"/></svg>'

        questions_data = [
            {
                "question_order": 1,
                "section_name": "Section A",
                "question_type": "NUMERICAL",
                "question_text": "Calculate current in the circuit shown.",
                "marks": 5,
                "difficulty": "MEDIUM",
                "correct_answer": "2 A",
                "solution_explanation": "I = 12 / 6 = 2 A.",
                "visual": {
                    "required": True,
                    "type": "circuit",
                    "title": "DC Circuit",
                    "caption": "Simple series circuit",
                    "spec": circuit_spec,
                },
                "visual_svg": svg_code,
            }
        ]

        saved = repo.save_questions(paper.id, questions_data)
        assert len(saved) == 1
        q = saved[0]

        # Verify fields persisted in DB
        assert q.visual_required is True
        assert q.visual_type == "circuit"
        assert q.visual_title == "DC Circuit"
        assert q.visual_caption == "Simple series circuit"
        assert q.visual_spec == circuit_spec
        assert q.visual_svg == svg_code
    finally:
        db.close()


def test_save_question_with_required_visual_failure():
    db = SessionLocal()
    try:
        user, ws, subj, book = get_test_hierarchy(db)
        paper = GeneratedPaper(
            id=uuid.uuid4(),
            user_id=user.id,
            workspace_id=ws.id,
            subject_id=subj.id,
            book_id=book.id,
            title="Physics Paper Failing Visual",
            generation_mode="CUSTOM",
            status="COMPLETED",
            total_marks=10,
            selected_chapter_ids=[],
            include_answers=True,
        )
        db.add(paper)
        db.commit()

        repo = PaperRepository(db)
        questions_data = [
            {
                "question_order": 1,
                "section_name": "Section A",
                "question_type": "SHORT_ANSWER",
                "question_text": "Calculate something with broken visual.",
                "marks": 5,
                "difficulty": "HARD",
                "correct_answer": "Answer",
                "solution_explanation": "Explanation",
                "visual": {
                    "required": True,
                    "type": "geometry",
                    "title": "Failed Triangle",
                    "spec": {"points": []},
                },
                "visual_svg": None,  # Failed generation produces None
            }
        ]

        saved = repo.save_questions(paper.id, questions_data)
        assert len(saved) == 1
        q = saved[0]

        assert q.visual_required is True
        assert q.visual_type == "geometry"
        assert q.visual_title == "Failed Triangle"
        assert q.visual_svg is None  # Remains None and is not falsely marked as success
    finally:
        db.close()


def test_internal_choice_independent_visual_persistence():
    db = SessionLocal()
    try:
        user, ws, subj, book = get_test_hierarchy(db)
        paper = GeneratedPaper(
            id=uuid.uuid4(),
            user_id=user.id,
            workspace_id=ws.id,
            subject_id=subj.id,
            book_id=book.id,
            title="Paper with Internal Choice Visuals",
            generation_mode="CUSTOM",
            status="COMPLETED",
            total_marks=10,
            selected_chapter_ids=[],
            include_answers=True,
        )
        db.add(paper)
        db.commit()

        repo = PaperRepository(db)
        circuit_svg = '<svg xmlns="http://www.w3.org/2000/svg" id="circuit_svg"></svg>'
        geom_svg = '<svg xmlns="http://www.w3.org/2000/svg" id="geometry_svg"></svg>'

        questions_data = [
            {
                "question_order": 1,
                "section_name": "Section A",
                "question_type": "NUMERICAL",
                "question_text": "Alternative A: Circuit calculation.",
                "marks": 5,
                "difficulty": "HARD",
                "choice_group": "Q1",
                "alternative_label": "a",
                "correct_answer": "2 A",
                "solution_explanation": "Ohm's law.",
                "visual": {
                    "required": True,
                    "type": "circuit",
                    "title": "Circuit A",
                    "spec": {"components": [{"id": "R1", "type": "resistor"}]},
                },
                "visual_svg": circuit_svg,
            },
            {
                "question_order": 1,
                "section_name": "Section A",
                "question_type": "NUMERICAL",
                "question_text": "Alternative B: Geometry calculation.",
                "marks": 5,
                "difficulty": "HARD",
                "choice_group": "Q1",
                "alternative_label": "b",
                "correct_answer": "10 cm",
                "solution_explanation": "Pythagoras.",
                "visual": {
                    "required": True,
                    "type": "geometry",
                    "title": "Triangle B",
                    "spec": {"points": [{"id": "A"}, {"id": "B"}]},
                },
                "visual_svg": geom_svg,
            },
        ]

        saved = repo.save_questions(paper.id, questions_data)
        assert len(saved) == 2

        q_a = saved[0]
        q_b = saved[1]

        assert q_a.choice_group == "Q1"
        assert q_a.alternative_label == "a"
        assert q_a.visual_type == "circuit"
        assert q_a.visual_svg == circuit_svg

        assert q_b.choice_group == "Q1"
        assert q_b.alternative_label == "b"
        assert q_b.visual_type == "geometry"
        assert q_b.visual_svg == geom_svg
    finally:
        db.close()


def test_build_paper_response_contains_visual_fields():
    db = SessionLocal()
    try:
        user, ws, subj, book = get_test_hierarchy(db)
        paper = GeneratedPaper(
            id=uuid.uuid4(),
            user_id=user.id,
            workspace_id=ws.id,
            subject_id=subj.id,
            book_id=book.id,
            title="API Response Paper",
            generation_mode="CUSTOM",
            status="COMPLETED",
            total_marks=10,
            selected_chapter_ids=[],
            include_answers=True,
        )
        db.add(paper)
        db.commit()

        repo = PaperRepository(db)
        svg_code = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>'
        questions_data = [
            {
                "question_order": 1,
                "section_name": "Section A",
                "question_type": "SHORT_ANSWER",
                "question_text": "Find velocity from graph.",
                "marks": 5,
                "difficulty": "MEDIUM",
                "correct_answer": "5 m/s",
                "solution_explanation": "Slope of line.",
                "visual": {
                    "required": True,
                    "type": "graph",
                    "title": "Velocity Graph",
                    "caption": "v vs t",
                    "spec": {"x_range": [0, 5], "y_range": [0, 25]},
                },
                "visual_svg": svg_code,
            }
        ]
        repo.save_questions(paper.id, questions_data)

        service = PaperGeneratorService(db=db)
        paper_obj = repo.get_paper(paper.id)
        response = service._build_paper_response(paper_obj, include_answers=True)

        assert isinstance(response, PaperResponse)
        assert len(response.questions) == 1

        q_resp = response.questions[0]
        assert q_resp.visual_required is True
        assert q_resp.visual_type == "graph"
        assert q_resp.visual_title == "Velocity Graph"
        assert q_resp.visual_caption == "v vs t"
        assert q_resp.visual_spec == {"x_range": [0, 5], "y_range": [0, 25]}
        assert q_resp.visual_svg == svg_code
    finally:
        db.close()

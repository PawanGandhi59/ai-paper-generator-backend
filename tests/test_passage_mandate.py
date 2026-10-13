from unittest.mock import MagicMock
import pytest

from app.schemas.paper import QuestionType
from app.services.paper.blueprint_service import SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_phantom_passage_rejection():
    """Verify that placeholder passage stems lacking actual passages are rejected."""
    svc = PaperGeneratorService(db=MagicMock())
    sec = SectionBlueprint(
        name="SECTION - E",
        question_type=QuestionType.SHORT_ANSWER,
        reasoning_style="PASSAGE_BASED_ANALYSIS",
        question_count=2,
        marks_per_question=2,
        total_section_marks=4,
    )

    # 1. Phantom passage placeholder (the exact issue reported by the user)
    phantom_cand = {
        "question_text": (
            "Read the passage regarding the historical formulation of electric charge conservation and "
            "Coulomb's torsion balance experiments, then answer the following question: "
            "Explain how Coulomb utilized his torsion balance to establish the inverse-square distance dependence."
        ),
        "marks": 2,
    }
    assert svc._validate_question_structure(phantom_cand, sec) is False

    # 2. Complete, self-contained stimulus passage followed by question prompt
    valid_cand = {
        "question_text": (
            "[Case Study: Coulomb's Torsion Balance and Electrostatic Forces]\n"
            "In 1785, French physicist Charles-Augustin de Coulomb conducted groundbreaking quantitative experiments "
            "to establish the fundamental law of electrostatic interaction. He designed an extraordinarily sensitive "
            "torsion balance consisting of a thin silver wire suspending a horizontal insulating needle with a small pith ball. "
            "When another charged sphere was introduced, electrostatic repulsion twisted the suspension fiber. By measuring "
            "the precise mechanical angle of twist required to balance the electrical repulsion at various measured separation distances, "
            "Coulomb demonstrated that the electrostatic force varies inversely with the square of the distance between point charges.\n\n"
            "Based on the above passage, answer the following question:\n"
            "Explain how Coulomb utilized his torsion balance measurements to establish the inverse-square distance relationship."
        ),
        "marks": 2,
    }
    assert svc._validate_question_structure(valid_cand, sec) is True
    assert valid_cand["reasoning_style"] == "PASSAGE_BASED_ANALYSIS"

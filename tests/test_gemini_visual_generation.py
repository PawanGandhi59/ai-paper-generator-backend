import json
import pytest
from pydantic import ValidationError

from app.schemas.paper import (
    DifficultyLevel,
    GeminiCompletePaperSchema,
    GeminiGeneratedQuestionSchema,
    GeminiSectionQuestionsSchema,
    GenerationMode,
    QuestionType,
)
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_complete_paper_prompt_contains_visual_instructions():
    blueprint = PaperBlueprint(
        total_marks=20,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.MCQ,
                question_count=2,
                marks_per_question=5,
                total_section_marks=10,
                alternatives_per_question=1,
            ),
            SectionBlueprint(
                name="Section B",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=1,
                marks_per_question=10,
                total_section_marks=10,
                alternatives_per_question=2,  # Internal choice
            ),
        ],
    )

    service = PaperGeneratorService(db=None)
    prompt = service._build_complete_paper_prompt(
        blueprint=blueprint,
        context_text="Physics Chapter 1: Electric charges and circuits.",
        topic_focus="Electric Circuits",
        difficulty=DifficultyLevel.MIXED,
        generation_mode=GenerationMode.CUSTOM,
    )

    assert "VISUAL ILLUSTRATION & DIAGRAM GUIDELINES" in prompt
    assert "visual" in prompt
    assert "circuit" in prompt
    assert "geometry" in prompt
    assert "graph" in prompt
    assert "diagram" in prompt
    assert "chart" in prompt
    assert "NEVER generate raw SVG" in prompt or "NEVER return raw SVG" in prompt or "raw SVG" in prompt
    assert "INTERNAL CHOICE INDEPENDENCE" in prompt


def test_gemini_complete_paper_schema_with_null_visuals():
    payload = {
        "sections": [
            {
                "section_name": "Section A",
                "questions": [
                    {
                        "question_text": "What is the SI unit of electric charge?",
                        "question_type": "MCQ",
                        "marks": 1,
                        "difficulty": "EASY",
                        "mcq_options": ["A. Ampere", "B. Coulomb", "C. Volt", "D. Ohm"],
                        "correct_answer": "B. Coulomb",
                        "solution_explanation": "The SI unit of charge is the Coulomb (C).",
                        "is_numerical": False,
                        "visual": None,
                    }
                ],
            }
        ]
    }

    parsed = GeminiCompletePaperSchema(**payload)
    assert len(parsed.sections) == 1
    assert parsed.sections[0].questions[0].visual is None


def test_gemini_complete_paper_schema_with_diverse_visuals():
    payload = {
        "sections": [
            {
                "section_name": "Physics & Geometry Section",
                "questions": [
                    {
                        "question_text": "Find total current in the DC circuit shown.",
                        "question_type": "NUMERICAL",
                        "marks": 3,
                        "difficulty": "MEDIUM",
                        "correct_answer": "2 A",
                        "solution_explanation": "I = V/R = 12 / 6 = 2 A.",
                        "is_numerical": True,
                        "visual": {
                            "required": True,
                            "type": "circuit",
                            "title": "Series Circuit",
                            "caption": "12V battery and 6 ohm resistor",
                            "spec": {
                                "components": [
                                    {"id": "V1", "type": "battery", "label": "12 V"},
                                    {"id": "R1", "type": "resistor", "label": "6 Ω"},
                                ],
                                "connections": [
                                    {"from": "V1", "to": "R1", "show_current": True},
                                    {"from": "R1", "to": "V1"},
                                ],
                            },
                        },
                    },
                    {
                        "question_text": "Calculate length of hypotenuse AC in right-angled triangle ABC.",
                        "question_type": "NUMERICAL",
                        "marks": 4,
                        "difficulty": "MEDIUM",
                        "correct_answer": "10 cm",
                        "solution_explanation": "AC = sqrt(6^2 + 8^2) = 10 cm.",
                        "is_numerical": True,
                        "visual": {
                            "required": True,
                            "type": "geometry",
                            "title": "Triangle ABC",
                            "caption": "Right triangle with base 6cm and height 8cm",
                            "spec": {
                                "points": [
                                    {"id": "A", "label": "A"},
                                    {"id": "B", "label": "B"},
                                    {"id": "C", "label": "C"},
                                ],
                                "segments": [
                                    {"from": "A", "to": "B", "label": "6 cm"},
                                    {"from": "B", "to": "C", "label": "8 cm"},
                                ],
                                "polygons": [
                                    {"points": ["A", "B", "C"]}
                                ],
                                "angles": [
                                    {"vertex": "B", "p1": "A", "p2": "C", "right_angle": True}
                                ],
                            },
                        },
                    },
                    {
                        "question_text": "Determine velocity at t = 3s from the graph.",
                        "question_type": "SHORT_ANSWER",
                        "marks": 3,
                        "difficulty": "MEDIUM",
                        "correct_answer": "11 m/s",
                        "solution_explanation": "v(3) = 3(3) + 2 = 11 m/s.",
                        "is_numerical": True,
                        "visual": {
                            "required": True,
                            "type": "graph",
                            "title": "Velocity-Time Graph",
                            "spec": {
                                "x_range": [0, 10],
                                "y_range": [0, 40],
                                "x_axis_label": "t (s)",
                                "y_axis_label": "v (m/s)",
                                "functions": [
                                    {"expression": "3*x + 2", "label": "v(t) = 3t + 2"}
                                ],
                            },
                        },
                    },
                ],
            }
        ]
    }

    parsed = GeminiCompletePaperSchema(**payload)
    questions = parsed.sections[0].questions
    assert len(questions) == 3
    assert questions[0].visual.type == "circuit"
    assert questions[1].visual.type == "geometry"
    assert questions[2].visual.type == "graph"


def test_gemini_internal_choice_independent_visual_generation():
    payload = {
        "sections": [
            {
                "section_name": "Section with Internal Choices",
                "questions": [
                    {
                        "question_text": "Option A: Calculate current through R1.",
                        "question_type": "NUMERICAL",
                        "marks": 5,
                        "difficulty": "HARD",
                        "choice_group": "Q4",
                        "alternative_label": "a",
                        "correct_answer": "1.5 A",
                        "solution_explanation": "I = 9V / 6Ω = 1.5 A.",
                        "visual": {
                            "required": True,
                            "type": "circuit",
                            "title": "Circuit for Q4(a)",
                            "spec": {
                                "components": [
                                    {"id": "V1", "type": "battery", "label": "9 V"},
                                    {"id": "R1", "type": "resistor", "label": "6 Ω"},
                                ],
                                "connections": [
                                    {"from": "V1", "to": "R1"},
                                    {"from": "R1", "to": "V1"},
                                ],
                            },
                        },
                    },
                    {
                        "question_text": "Option B: State and explain Coulomb's Law in electrostatics.",
                        "question_type": "LONG_ANSWER",
                        "marks": 5,
                        "difficulty": "HARD",
                        "choice_group": "Q4",
                        "alternative_label": "b",
                        "correct_answer": "F = k * q1 * q2 / r^2",
                        "solution_explanation": "Statement and mathematical formulation of Coulomb's Law.",
                        "visual": None,  # Option B has NO visual
                    },
                ],
            }
        ]
    }

    parsed = GeminiCompletePaperSchema(**payload)
    questions = parsed.sections[0].questions
    assert len(questions) == 2
    assert questions[0].choice_group == "Q4"
    assert questions[0].alternative_label == "a"
    assert questions[0].visual is not None
    assert questions[0].visual.type == "circuit"

    assert questions[1].choice_group == "Q4"
    assert questions[1].alternative_label == "b"
    assert questions[1].visual is None


def test_gemini_schema_rejects_malformed_visual_specification():
    payload = {
        "sections": [
            {
                "section_name": "Invalid Section",
                "questions": [
                    {
                        "question_text": "Sample question",
                        "question_type": "SHORT_ANSWER",
                        "marks": 2,
                        "difficulty": "EASY",
                        "correct_answer": "Answer",
                        "solution_explanation": "Explanation",
                        "visual": {
                            "required": True,
                            "type": "circuit",
                            "spec": {
                                "components": [{"id": "R1", "type": "resistor"}],
                                "connections": [{"from": "R1", "to": "NON_EXISTENT_COMPONENT"}],
                            },
                        },
                    }
                ],
            }
        ]
    }

    with pytest.raises(ValidationError) as exc:
        GeminiCompletePaperSchema(**payload)
    assert "undefined target component" in str(exc.value)

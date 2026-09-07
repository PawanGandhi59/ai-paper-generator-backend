import json
import pytest
from app.schemas.visuals import GeminiVisualRequirementSchema
from app.services.paper.paper_generator_service import PaperGeneratorService
from app.services.visuals.svg_generator_service import SVGGeneratorService, is_valid_svg_xml


def test_geometry_visual_semantic_coordinates_synthesis():
    """
    Test that Gemini can provide geometry points without x/y coordinates
    and GeometryBuilder safely auto-synthesizes coordinates and renders valid SVG.
    """
    service = SVGGeneratorService()
    geom_req = GeminiVisualRequirementSchema(
        required=True,
        type="geometry",
        title="Triangle ABC",
        caption="Triangle with AB=5cm, AC=4cm and angle A=60°",
        spec={
            "points": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "segments": [
                {"from": "A", "to": "B", "label": "5 cm"},
                {"from": "A", "to": "C", "label": "4 cm"},
            ],
            "polygons": [
                {"points": ["A", "B", "C"]}
            ],
            "angles": [
                {"vertex": "A", "p1": "B", "p2": "C", "label": "60°"}
            ],
        },
    )

    res = service.generate(geom_req)
    assert res.is_valid is True
    assert res.required is True
    assert len(res.svg_raw) > 0
    assert is_valid_svg_xml(res.svg_raw) is True
    assert "<polygon" in res.svg_raw
    assert "Triangle ABC" in res.svg_raw


def test_circuit_visual_generation():
    """
    Test realistic circuit specification rendering.
    """
    service = SVGGeneratorService()
    circ_req = GeminiVisualRequirementSchema(
        required=True,
        type="circuit",
        title="12V Resistor Circuit",
        caption="A 12 V battery connected to a 6 Ω resistor",
        spec={
            "components": [
                {"id": "V1", "type": "battery", "label": "12 V"},
                {"id": "R1", "type": "resistor", "label": "6 Ω"},
            ],
            "connections": [
                {"from": "V1", "to": "R1", "show_current": True, "label": "I = 2A"},
                {"from": "R1", "to": "V1"},
            ],
        },
    )

    res = service.generate(circ_req)
    assert res.is_valid is True
    assert res.required is True
    assert is_valid_svg_xml(res.svg_raw) is True
    assert "12 V" in res.svg_raw
    assert "6 Ω" in res.svg_raw


def test_graph_visual_generation():
    """
    Test realistic graph specification rendering.
    """
    service = SVGGeneratorService()
    graph_req = GeminiVisualRequirementSchema(
        required=True,
        type="graph",
        title="Parabola Graph",
        caption="Plot of y = x^2 - 4",
        spec={
            "x_range": [-3, 3],
            "y_range": [-5, 5],
            "grid": True,
            "x_axis_label": "x",
            "y_axis_label": "y",
            "functions": [
                {"expression": "x**2 - 4", "label": "y = x^2 - 4"}
            ],
        },
    )

    res = service.generate(graph_req)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw) is True
    assert "<path" in res.svg_raw or "<polyline" in res.svg_raw or "<line" in res.svg_raw


def test_diagram_visual_generation():
    """
    Test realistic process diagram specification rendering.
    """
    service = SVGGeneratorService()
    diag_req = GeminiVisualRequirementSchema(
        required=True,
        type="diagram",
        title="Data Pipeline",
        spec={
            "nodes": [
                {"id": "in", "label": "Input"},
                {"id": "proc", "label": "Processing"},
                {"id": "out", "label": "Output"},
            ],
            "edges": [
                {"from": "in", "to": "proc", "label": "raw data"},
                {"from": "proc", "to": "out", "label": "result"},
            ],
        },
    )

    res = service.generate(diag_req)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw) is True
    assert "Input" in res.svg_raw
    assert "Processing" in res.svg_raw
    assert "Output" in res.svg_raw


def test_chart_visual_generation_with_series_adapter():
    """
    Test Gemini ChartDataSpec with categories and series list rendering correctly.
    """
    service = SVGGeneratorService()
    chart_req = GeminiVisualRequirementSchema(
        required=True,
        type="chart",
        title="Student Marks",
        spec={
            "format": "bar",
            "categories": ["Math", "Physics", "Chemistry"],
            "series": [
                {"name": "Marks", "values": [85.0, 90.0, 78.0]}
            ],
            "x_axis_label": "Subjects",
            "y_axis_label": "Score",
        },
    )

    res = service.generate(chart_req)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw) is True
    assert "Math" in res.svg_raw
    assert "Physics" in res.svg_raw
    assert "Chemistry" in res.svg_raw


def test_paper_generator_service_in_memory_visual_processing():
    """
    Test that PaperGeneratorService processes question visuals in memory,
    attaching visual_svg and distinguishing required vs optional visual failures.
    """
    generator = PaperGeneratorService(db=None)

    questions = [
        {
            "question_text": "What is the speed of light?",
            "visual": None,
        },
        {
            "question_text": "Calculate current in circuit shown.",
            "visual": {
                "required": True,
                "type": "circuit",
                "title": "Series Circuit",
                "spec": {
                    "components": [
                        {"id": "V1", "type": "battery", "label": "9 V"},
                        {"id": "R1", "type": "resistor", "label": "3 Ω"},
                    ],
                    "connections": [
                        {"from": "V1", "to": "R1"},
                        {"from": "R1", "to": "V1"},
                    ],
                },
            },
        },
        {
            "question_text": "Question with invalid required visual type.",
            "visual": {
                "required": True,
                "type": "unsupported_type",
                "spec": {},
            },
        },
    ]

    generator._process_question_visuals_in_memory(questions)

    # 1. No visual
    assert questions[0].get("visual_svg") is None
    assert questions[0].get("visual_valid") is None

    # 2. Valid required visual
    assert questions[1].get("visual_valid") is True
    assert questions[1].get("visual_svg") is not None
    assert is_valid_svg_xml(questions[1]["visual_svg"]) is True

    # 3. Invalid required visual
    assert questions[2].get("visual_valid") is False
    assert questions[2].get("visual_svg") is None
    assert "visual_error" in questions[2]


def test_visual_fields_lifetime_through_complete_generation_pipeline():
    """
    Verify the complete lifetime of visual_svg, visual_valid, and visual_error
    at the return point of _generate_complete_paper().
    """
    from unittest.mock import MagicMock
    from app.schemas.paper import DifficultyLevel, GenerationMode, QuestionType
    from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint

    blueprint = PaperBlueprint(
        total_marks=10,
        sections=[
            SectionBlueprint(
                name="Physics Section",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=2,
                marks_per_question=5,
                total_section_marks=10,
                alternatives_per_question=1,
            )
        ],
    )

    mock_gemini_response = {
        "sections": [
            {
                "section_name": "Physics Section",
                "questions": [
                    {
                        "question_text": "Calculate the current in the DC circuit shown.",
                        "question_type": "SHORT_ANSWER",
                        "marks": 5,
                        "difficulty": "MEDIUM",
                        "correct_answer": "2 A",
                        "solution_explanation": "I = V/R = 12/6 = 2 A.",
                        "visual": {
                            "required": True,
                            "type": "circuit",
                            "title": "DC Circuit",
                            "caption": "12V Battery with 6 ohm resistor",
                            "spec": {
                                "components": [
                                    {"id": "V1", "type": "battery", "label": "12 V"},
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
                        "question_text": "Question with failing required visual.",
                        "question_type": "SHORT_ANSWER",
                        "marks": 5,
                        "difficulty": "MEDIUM",
                        "correct_answer": "Answer",
                        "solution_explanation": "Explanation",
                        "visual": {
                            "required": True,
                            "type": "unsupported_visual_type",
                            "spec": {},
                        },
                    },
                ],
            }
        ]
    }

    service = PaperGeneratorService(db=None)
    service.ai_service = MagicMock()
    service.ai_service.count_tokens.return_value = 100
    service.ai_service.generate_response.return_value = json.dumps(mock_gemini_response)

    # Execute _generate_complete_paper
    generated = service._generate_complete_paper(
        blueprint=blueprint,
        context_text="Physics context",
        topic_focus=None,
        difficulty=DifficultyLevel.MIXED,
        generation_mode=GenerationMode.CUSTOM,
        sample_questions=None,
    )

    # 1. Exact object type check
    assert isinstance(generated, list)
    assert len(generated) == 2
    assert isinstance(generated[0], dict)
    assert isinstance(generated[1], dict)

    # 2. Verify visual_svg, visual_valid on Question 1
    q1 = generated[0]
    assert "visual_svg" in q1
    assert "visual_valid" in q1
    assert q1["visual_valid"] is True
    assert isinstance(q1["visual_svg"], str)
    assert len(q1["visual_svg"]) > 0
    assert "<svg" in q1["visual_svg"] and "</svg>" in q1["visual_svg"]
    assert "12 V" in q1["visual_svg"]
    assert "6 Ω" in q1["visual_svg"]

    # 3. Verify visual_error on Question 2 (failing required visual)
    q2 = generated[1]
    assert "visual_valid" in q2
    assert q2["visual_valid"] is False
    assert q2["visual_svg"] is None
    assert "visual_error" in q2
    assert len(q2["visual_error"]) > 0


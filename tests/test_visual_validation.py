import pytest
from pydantic import ValidationError

from app.schemas.paper import GeminiGeneratedQuestionSchema
from app.schemas.visuals import (
    GeminiVisualRequirementSchema,
    validate_math_expression_safety,
    validate_visual_spec_semantics,
)


def test_question_with_no_visual():
    q = GeminiGeneratedQuestionSchema(
        question_text="State Archimedes Principle.",
        correct_answer="An object immersed in fluid experiences upward buoyant force equal to fluid weight.",
        solution_explanation="Definition of Archimedes Principle.",
        visual=None,
    )
    assert q.visual is None

    # Explicit required=False
    q_opt = GeminiGeneratedQuestionSchema(
        question_text="State Ohm's Law.",
        correct_answer="V = IR",
        solution_explanation="Relationship between voltage, current, and resistance.",
        visual=GeminiVisualRequirementSchema(required=False),
    )
    assert q_opt.visual is not None
    assert q_opt.visual.required is False


def test_valid_diagram_specification():
    spec_data = {
        "nodes": [
            {"id": "solid", "label": "Solid"},
            {"id": "liquid", "label": "Liquid"},
            {"id": "gas", "label": "Gas"},
        ],
        "edges": [
            {"from": "solid", "to": "liquid", "label": "Melting"},
            {"from": "liquid", "to": "gas", "label": "Evaporation"},
        ],
    }
    visual_req = GeminiVisualRequirementSchema(
        required=True,
        type="diagram",
        title="Phase Transition",
        spec=spec_data,
    )
    assert visual_req.required is True
    assert visual_req.type == "diagram"


def test_valid_chart_specification():
    spec_data = {
        "format": "bar",
        "categories": ["Week 1", "Week 2", "Week 3"],
        "series": [
            {"name": "Growth (cm)", "values": [2.5, 5.0, 8.5]}
        ],
        "x_axis_label": "Time",
        "y_axis_label": "Height",
    }
    visual_req = GeminiVisualRequirementSchema(
        required=True,
        type="chart",
        title="Plant Growth",
        spec=spec_data,
    )
    assert visual_req.type == "chart"


def test_valid_geometry_specification():
    spec_data = {
        "points": [
            {"id": "A", "label": "A"},
            {"id": "B", "label": "B"},
            {"id": "C", "label": "C"},
        ],
        "segments": [
            {"from": "A", "to": "B", "label": "6 cm"},
            {"from": "B", "to": "C", "label": "8 cm"},
            {"from": "A", "to": "C", "label": "10 cm"},
        ],
        "polygons": [
            {"points": ["A", "B", "C"], "fill_color": "#EBF8FF"}
        ],
        "angles": [
            {"vertex": "B", "p1": "A", "p2": "C", "label": "90°", "right_angle": True}
        ],
    }
    visual_req = GeminiVisualRequirementSchema(
        required=True,
        type="geometry",
        title="Right Triangle",
        spec=spec_data,
    )
    assert visual_req.type == "geometry"


def test_valid_circuit_specification():
    spec_data = {
        "components": [
            {"id": "V1", "type": "battery", "label": "12 V"},
            {"id": "R1", "type": "resistor", "label": "6 Ω"},
        ],
        "connections": [
            {"from": "V1", "to": "R1", "show_current": True, "label": "I = 2A"},
            {"from": "R1", "to": "V1"},
        ],
    }
    visual_req = GeminiVisualRequirementSchema(
        required=True,
        type="circuit",
        title="DC Series Circuit",
        spec=spec_data,
    )
    assert visual_req.type == "circuit"


def test_valid_graph_specification():
    spec_data = {
        "x_range": [-5, 5],
        "y_range": [-10, 10],
        "grid": True,
        "x_axis_label": "x",
        "y_axis_label": "y",
        "functions": [
            {"expression": "2*x + 1", "label": "y = 2x + 1"}
        ],
        "points": [
            {"x": 0, "y": 1, "label": "(0, 1)"}
        ],
    }
    visual_req = GeminiVisualRequirementSchema(
        required=True,
        type="graph",
        title="Linear Graph",
        spec=spec_data,
    )
    assert visual_req.type == "graph"


def test_internal_choice_independent_visual_requirements():
    # Q4(a) has circuit visual
    alt_a = GeminiGeneratedQuestionSchema(
        question_text="Calculate total resistance in this circuit.",
        correct_answer="6 Ω",
        solution_explanation="Series sum R1 + R2.",
        visual=GeminiVisualRequirementSchema(
            required=True,
            type="circuit",
            title="Circuit A",
            spec={
                "components": [
                    {"id": "R1", "type": "resistor", "label": "2 Ω"},
                    {"id": "R2", "type": "resistor", "label": "4 Ω"},
                ],
                "connections": [
                    {"from": "R1", "to": "R2"},
                ],
            },
        ),
    )

    # Q4(b) has geometry visual
    alt_b = GeminiGeneratedQuestionSchema(
        question_text="Find hypotenuse AC in right triangle ABC.",
        correct_answer="5 cm",
        solution_explanation="Pythagorean theorem 3² + 4² = 25.",
        visual=GeminiVisualRequirementSchema(
            required=True,
            type="geometry",
            title="Triangle B",
            spec={
                "points": [
                    {"id": "A", "label": "A"},
                    {"id": "B", "label": "B"},
                    {"id": "C", "label": "C"},
                ],
                "segments": [
                    {"from": "A", "to": "B", "label": "3 cm"},
                    {"from": "B", "to": "C", "label": "4 cm"},
                ],
            },
        ),
    )

    assert alt_a.visual.type == "circuit"
    assert alt_b.visual.type == "geometry"
    assert alt_a.visual.title == "Circuit A"
    assert alt_b.visual.title == "Triangle B"


def test_rejection_of_raw_svg_in_gemini_schema():
    with pytest.raises(ValidationError):
        GeminiVisualRequirementSchema(
            required=True,
            type="raw_svg",  # raw_svg is disallowed for Gemini
            spec={"code": "<svg></svg>"},
        )


def test_rejection_of_unknown_visual_type():
    with pytest.raises(ValidationError):
        GeminiVisualRequirementSchema(
            required=True,
            type="3d_model",  # invalid
            spec={},
        )


def test_rejection_when_required_true_but_missing_type_or_spec():
    with pytest.raises(ValidationError) as exc1:
        GeminiVisualRequirementSchema(required=True, type=None, spec={"nodes": []})
    assert "visual.type is required" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        GeminiVisualRequirementSchema(required=True, type="circuit", spec=None)
    assert "visual.spec dictionary is required" in str(exc2.value)


def test_rejection_of_diagram_with_invalid_node_references():
    with pytest.raises(ValidationError) as exc:
        GeminiVisualRequirementSchema(
            required=True,
            type="diagram",
            spec={
                "nodes": [
                    {"id": "A", "label": "Node A"}
                ],
                "edges": [
                    {"from": "A", "to": "UNKNOWN_NODE"}
                ],
            },
        )
    assert "unknown target node 'UNKNOWN_NODE'" in str(exc.value)


def test_rejection_of_chart_with_inconsistent_data():
    with pytest.raises(ValidationError) as exc:
        GeminiVisualRequirementSchema(
            required=True,
            type="chart",
            spec={
                "categories": ["A", "B", "C"],  # 3 categories
                "series": [
                    {"name": "Series 1", "values": [10.0, 20.0]}  # 2 values != 3
                ],
            },
        )
    assert "has 2 values, but categories list has 3 items" in str(exc.value)


def test_rejection_of_geometry_with_invalid_references():
    with pytest.raises(ValidationError) as exc:
        GeminiVisualRequirementSchema(
            required=True,
            type="geometry",
            spec={
                "points": [
                    {"id": "A", "label": "A"},
                    {"id": "B", "label": "B"},
                ],
                "segments": [
                    {"from": "A", "to": "UNDEFINED_POINT"}
                ],
            },
        )
    assert "Segment references undefined end point 'UNDEFINED_POINT'" in str(exc.value)


def test_rejection_of_circuit_with_duplicate_component_ids_and_invalid_connection():
    # Duplicate component ID
    with pytest.raises(ValidationError) as exc1:
        GeminiVisualRequirementSchema(
            required=True,
            type="circuit",
            spec={
                "components": [
                    {"id": "R1", "type": "resistor"},
                    {"id": "R1", "type": "resistor"},
                ],
                "connections": [],
            },
        )
    assert "Duplicate circuit component ID 'R1'" in str(exc1.value)

    # Self-connection
    with pytest.raises(ValidationError) as exc2:
        GeminiVisualRequirementSchema(
            required=True,
            type="circuit",
            spec={
                "components": [
                    {"id": "R1", "type": "resistor"},
                ],
                "connections": [
                    {"from": "R1", "to": "R1"},
                ],
            },
        )
    assert "cannot connect component 'R1' to itself" in str(exc2.value)


def test_rejection_of_graph_with_invalid_ranges_or_unsafe_expressions():
    # Invalid x_range (x_min >= x_max)
    with pytest.raises(ValidationError) as exc1:
        GeminiVisualRequirementSchema(
            required=True,
            type="graph",
            spec={
                "x_range": [10, 5],
                "y_range": [-5, 5],
                "functions": [],
            },
        )
    assert "x_min must be strictly less than x_max" in str(exc1.value)

    # Unsafe expression with eval() or __import__
    with pytest.raises(ValidationError) as exc2:
        GeminiVisualRequirementSchema(
            required=True,
            type="graph",
            spec={
                "x_range": [-5, 5],
                "y_range": [-5, 5],
                "functions": [
                    {"expression": "__import__('os').system('ls')"}
                ],
            },
        )
    assert "Disallowed function call" in str(exc2.value) or "Disallowed" in str(exc2.value)

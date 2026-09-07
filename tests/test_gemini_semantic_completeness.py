from app.schemas.paper import (
    DifficultyLevel,
    GeminiCompletePaperSchema,
    GeminiGeneratedQuestionSchema,
    GenerationMode,
    QuestionType,
)
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.schemas.visuals import GeminiVisualRequirementSchema
from app.services.paper.paper_generator_service import PaperGeneratorService
from app.services.visuals.svg_generator_service import SVGGeneratorService, is_valid_svg_xml


def test_complete_paper_prompt_contains_semantic_completeness_rules():
    """
    Verify that the paper generation prompt contains the Phase 4C semantic completeness,
    quantity/count matching, numerical consistency, and topology preservation rules.
    """
    service = PaperGeneratorService(db=None)
    blueprint = PaperBlueprint(
        total_marks=20,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.NUMERICAL,
                question_count=2,
                marks_per_question=5,
                total_section_marks=10,
                has_internal_choice=False,
            )
        ]
    )
    prompt = service._build_complete_paper_prompt(
        blueprint=blueprint,
        context_text="Circuit and Geometry sample content",
        topic_focus="Cubical resistor network and AC circuits",
        difficulty=DifficultyLevel.MIXED,
        generation_mode=GenerationMode.CUSTOM,
    )

    # Core principle
    assert "STRICT SEMANTIC REPRESENTATION" in prompt
    assert "Never simplify a complex visual problem" in prompt

    # Completeness rules
    assert "COMPONENT & QUANTITY COMPLETENESS RULE" in prompt
    assert "If the question mentions \"12 resistors\", \"spec\" MUST contain exactly 12 resistor components" in prompt
    assert "NUMERICAL & PARAMETER CONSISTENCY RULE" in prompt
    assert "TOPOLOGY & RELATIONSHIP PRESERVATION" in prompt
    assert "QUESTION ↔ SOLUTION ↔ VISUAL TRI-CONSISTENCY" in prompt
    assert "PHYSICAL STATES & SYMBOLS" in prompt


def test_geometry_triangle_with_altitude_semantic_spec():
    """
    Verify that a complete geometry spec with right triangle ABC and altitude BD validates and renders cleanly.
    """
    service = SVGGeneratorService()
    geom_spec = GeminiVisualRequirementSchema(
        required=True,
        type="geometry",
        title="Triangle ABC with Altitude BD",
        caption="Right triangle ABC with altitude BD drawn to hypotenuse AC.",
        spec={
            "points": [
                {"id": "A", "x": 50, "y": 250, "label": "A"},
                {"id": "B", "x": 200, "y": 250, "label": "B"},
                {"id": "C", "x": 200, "y": 100, "label": "C"},
                {"id": "D", "x": 125, "y": 175, "label": "D"},
            ],
            "segments": [
                {"from": "A", "to": "B", "label": "4 cm"},
                {"from": "B", "to": "C", "label": "3 cm"},
                {"from": "A", "to": "C", "label": "5 cm"},
                {"from": "B", "to": "D", "label": "Altitude h", "style": "dashed"},
            ],
            "polygons": [
                {"points": ["A", "B", "C"]}
            ],
            "angles": [
                {"vertex": "B", "p1": "A", "p2": "C", "right_angle": True}
            ]
        }
    )
    res = service.generate(geom_spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert ">A<" in res.svg_raw and ">B<" in res.svg_raw and ">C<" in res.svg_raw and ">D<" in res.svg_raw
    assert "Altitude h" in res.svg_raw
    assert "4 cm" in res.svg_raw


def test_graph_non_generic_equation_semantic_spec():
    """
    Verify that non-generic equation v(t) = 10 sin(100*pi*x) with explicit axis titles renders cleanly.
    """
    service = SVGGeneratorService()
    graph_spec = GeminiVisualRequirementSchema(
        required=True,
        type="graph",
        title="AC Voltage Waveform v(t)",
        caption="Sinusoidal alternating voltage v(t) = 10 sin(100πt) with 10 V peak.",
        spec={
            "x_range": [0, 0.04],
            "y_range": [-12, 12],
            "grid": True,
            "x_axis_label": "t (s)",
            "y_axis_label": "v(t) (V)",
            "functions": [
                {
                    "expression": "10 * sin(100 * pi * x)",
                    "label": "v(t) = 10 sin(100πt)",
                    "color": "#E53E3E",
                }
            ],
            "points": [
                {"x": 0.005, "y": 10.0, "label": "Peak (5ms, 10V)"}
            ]
        }
    )
    res = service.generate(graph_spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert "t (s)" in res.svg_raw
    assert "v(t) (V)" in res.svg_raw
    assert "v(t) = 10 sin(100πt)" in res.svg_raw


def test_chart_multi_category_multi_series_semantic_spec():
    """
    Verify multi-category, multi-series chart representation.
    """
    service = SVGGeneratorService()
    chart_spec = GeminiVisualRequirementSchema(
        required=True,
        type="chart",
        title="Class Performance Across Subjects",
        spec={
            "format": "bar",
            "categories": ["Term 1", "Term 2", "Term 3"],
            "series": [
                {"name": "Physics", "values": [75.0, 82.0, 88.0]},
                {"name": "Chemistry", "values": [80.0, 78.0, 85.0]},
            ],
            "x_axis_label": "Examinations",
            "y_axis_label": "Mean Score (%)",
        }
    )
    res = service.generate(chart_spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert "Term 1" in res.svg_raw
    assert "Term 2" in res.svg_raw
    assert "Term 3" in res.svg_raw
    assert "Examinations" in res.svg_raw
    assert "Mean Score (%)" in res.svg_raw


def test_diagram_four_stage_process_semantic_spec():
    """
    Verify 4-stage thermodynamic process diagram.
    """
    service = SVGGeneratorService()
    diag_spec = GeminiVisualRequirementSchema(
        required=True,
        type="diagram",
        title="Carnot Cycle 4-Stage Process",
        spec={
            "nodes": [
                {"id": "S1", "label": "1. Isothermal Expansion"},
                {"id": "S2", "label": "2. Adiabatic Expansion"},
                {"id": "S3", "label": "3. Isothermal Compression"},
                {"id": "S4", "label": "4. Adiabatic Compression"},
            ],
            "edges": [
                {"from": "S1", "to": "S2", "label": "Q_in at T_H"},
                {"from": "S2", "to": "S3", "label": "W_out"},
                {"from": "S3", "to": "S4", "label": "Q_out at T_C"},
                {"from": "S4", "to": "S1", "label": "W_in"},
            ]
        }
    )
    res = service.generate(diag_spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert "Isothermal" in res.svg_raw
    assert "Expansion" in res.svg_raw
    assert "Adiabatic" in res.svg_raw
    assert "Compression" in res.svg_raw
    assert "Q_in at T_H" in res.svg_raw


def test_internal_choice_independent_semantic_visuals():
    """
    Verify that Question Alternatives A and B maintain independent complete visual specs.
    """
    alt_a = GeminiGeneratedQuestionSchema(
        question_text="In the circuit shown below, calculate the current through the 6 Ω resistor.",
        correct_answer="2 A",
        solution_explanation="Using Ohm's law V = IR, I = 12 / 6 = 2 A.",
        choice_group="Q4",
        alternative_label="a",
        visual=GeminiVisualRequirementSchema(
            required=True,
            type="circuit",
            title="DC Circuit",
            spec={
                "components": [
                    {"id": "V1", "type": "battery", "label": "12 V"},
                    {"id": "R1", "type": "resistor", "label": "6 Ω"}
                ],
                "connections": [
                    {"from": "V1", "to": "R1"},
                    {"from": "R1", "to": "V1"}
                ]
            }
        )
    )

    alt_b = GeminiGeneratedQuestionSchema(
        question_text="For the parabola shown in the figure, determine the vertex coordinates.",
        correct_answer="(0, -4)",
        solution_explanation="The function is y = x^2 - 4. The minimum occurs at x = 0 with y = -4.",
        choice_group="Q4",
        alternative_label="b",
        visual=GeminiVisualRequirementSchema(
            required=True,
            type="graph",
            title="Parabola Graph",
            spec={
                "x_range": [-3, 3],
                "y_range": [-5, 5],
                "functions": [
                    {"expression": "x**2 - 4", "label": "y = x^2 - 4"}
                ]
            }
        )
    )

    assert alt_a.visual is not None and alt_a.visual.type == "circuit"
    assert alt_b.visual is not None and alt_b.visual.type == "graph"
    assert alt_a.visual.title == "DC Circuit"
    assert alt_b.visual.title == "Parabola Graph"

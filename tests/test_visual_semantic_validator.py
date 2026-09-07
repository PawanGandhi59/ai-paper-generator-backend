import pytest
from app.schemas.visuals import GeminiVisualRequirementSchema
from app.services.paper.paper_generator_service import PaperGeneratorService
from app.services.visuals.visual_semantic_validator import VisualSemanticValidator


def test_q2_failure_12_resistors_vs_3_resistors():
    """
    Regression Test for Q2 Failure:
    Question specifies a cubical network with 12 resistors, but visual spec has only 3.
    Validator MUST detect failure.
    """
    q_text = "In the circuit diagram shown below, a battery of emf 10 V is connected across the diagonally opposite corners of a cubical network consisting of 12 resistors each of resistance 1 Ω. Determine the equivalent resistance."
    sol_text = "Due to the symmetry of the cubical network with 12 resistors, Req = (5/6)R = 5/6 Ω."
    visual_spec = {
        "required": True,
        "type": "circuit",
        "title": "Cubical Resistor Network",
        "spec": {
            "components": [
                {"id": "V1", "type": "battery", "label": "10 V"},
                {"id": "R1", "type": "resistor", "label": "1 Ω"},
                {"id": "R2", "type": "resistor", "label": "1 Ω"},
                {"id": "R3", "type": "resistor", "label": "1 Ω"},
            ],
            "connections": [
                {"from": "V1", "to": "R1"},
                {"from": "R1", "to": "R2"},
                {"from": "R2", "to": "R3"},
                {"from": "R3", "to": "V1"},
            ]
        }
    }

    res = VisualSemanticValidator.validate(
        question_text=q_text,
        visual_spec=visual_spec,
        solution_text=sol_text,
    )

    assert res.is_valid is False
    assert len(res.errors) > 0
    assert any("cubical network" in err or "12" in err for err in res.errors)


def test_q2_correct_12_resistors_cubical_network():
    """
    Regression Test for Q2 Correct Case:
    Question specifies 12-resistor cubical network, and visual contains 12 resistors.
    Validator MUST pass.
    """
    q_text = "In the circuit diagram shown below, a battery of emf 10 V is connected across the diagonally opposite corners of a cubical network consisting of 12 resistors each of resistance 1 Ω. Determine the equivalent resistance."
    sol_text = "Due to symmetry of 12 resistors, Req = (5/6)R."
    visual_spec = {
        "required": True,
        "type": "circuit",
        "title": "Cubical Resistor Network",
        "spec": {
            "components": [{"id": f"R{i}", "type": "resistor", "label": "1 Ω"} for i in range(1, 13)] + [
                {"id": "V1", "type": "battery", "label": "10 V"}
            ],
            "connections": [
                {"from": "R1", "to": "R2"}
            ]
        }
    }

    res = VisualSemanticValidator.validate(
        question_text=q_text,
        visual_spec=visual_spec,
        solution_text=sol_text,
    )

    assert res.is_valid is True
    assert len(res.errors) == 0


def test_q3_failure_missing_switch_and_iron_core():
    """
    Regression Test for Q3 Failure:
    Question specifies AC source, bulb, inductor, closed key, and iron rod.
    Visual omits the switch and iron_core=true.
    Validator MUST detect failure.
    """
    q_text = "A light bulb and an open coil inductor are connected to an ac source through a key. The switch is closed and after some time, an iron rod is inserted into the interior of the inductor. Explain how the glow of the light bulb changes."
    visual_spec = {
        "required": True,
        "type": "circuit",
        "title": "Lamp and Inductor AC Circuit",
        "spec": {
            "components": [
                {"id": "V1", "type": "lamp", "label": "Bulb"},
                {"id": "L1", "type": "inductor", "label": "Inductor", "iron_core": False},
                {"id": "AC1", "type": "ac_source", "label": "AC Source"},
            ],
            "connections": [
                {"from": "AC1", "to": "V1"},
                {"from": "V1", "to": "L1"},
                {"from": "L1", "to": "AC1"},
            ]
        }
    }

    res = VisualSemanticValidator.validate(
        question_text=q_text,
        visual_spec=visual_spec,
    )

    assert res.is_valid is False
    assert len(res.errors) >= 1
    # Should catch either missing switch/key or missing iron core
    error_str = " ".join(res.errors).lower()
    assert "switch" in error_str or "key" in error_str or "iron" in error_str


def test_q3_correct_ac_switch_lamp_iron_core():
    """
    Regression Test for Q3 Correct Case:
    Visual contains ac_source, switch (closed), lamp, and inductor with iron_core=True.
    Validator MUST pass.
    """
    q_text = "A light bulb and an open coil inductor are connected to an ac source through a key. The switch is closed and after some time, an iron rod is inserted into the interior of the inductor. Explain how the glow of the light bulb changes."
    visual_spec = {
        "required": True,
        "type": "circuit",
        "title": "Lamp and Inductor AC Circuit",
        "spec": {
            "components": [
                {"id": "B1", "type": "lamp", "label": "Bulb"},
                {"id": "K1", "type": "switch", "label": "Key", "state": "closed"},
                {"id": "L1", "type": "inductor", "label": "Inductor", "iron_core": True},
                {"id": "AC1", "type": "ac_source", "label": "AC Source"},
            ],
            "connections": [
                {"from": "AC1", "to": "K1"},
                {"from": "K1", "to": "L1"},
                {"from": "L1", "to": "B1"},
                {"from": "B1", "to": "AC1"},
            ]
        }
    }

    res = VisualSemanticValidator.validate(
        question_text=q_text,
        visual_spec=visual_spec,
    )

    assert res.is_valid is True
    assert len(res.errors) == 0


def test_four_capacitors_count_mismatch():
    """
    Question specifies a network of four 10 µF capacitors, but visual has only 3.
    """
    q_text = "A network of four 10 µF capacitors is connected to a 500 V supply. Determine the equivalent capacitance."
    visual_spec = {
        "required": True,
        "type": "circuit",
        "spec": {
            "components": [
                {"id": "V1", "type": "battery", "label": "500 V"},
                {"id": "C1", "type": "capacitor", "label": "10 µF"},
                {"id": "C2", "type": "capacitor", "label": "10 µF"},
                {"id": "C3", "type": "capacitor", "label": "10 µF"},
            ],
            "connections": []
        }
    }

    res = VisualSemanticValidator.validate(question_text=q_text, visual_spec=visual_spec)
    assert res.is_valid is False
    assert any("4 capacitors" in err or "capacitor" in err for err in res.errors)


def test_geometry_triangle_missing_altitude_point():
    """
    Question specifies triangle ABC with altitude BD, but visual points only contain A, B, C (missing D).
    """
    q_text = "In a right triangle ABC with altitude BD to hypotenuse AC, determine the length of BD."
    visual_spec = {
        "required": True,
        "type": "geometry",
        "spec": {
            "points": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "segments": [
                {"from": "A", "to": "B"},
                {"from": "B", "to": "C"},
                {"from": "A", "to": "C"},
            ]
        }
    }

    res = VisualSemanticValidator.validate(question_text=q_text, visual_spec=visual_spec)
    assert res.is_valid is False
    assert any("D" in err for err in res.errors)


def test_chart_category_count_mismatch():
    """
    Question specifies data across 5 subjects, but chart has only 3 categories.
    """
    q_text = "The bar chart shows student examination data across 5 subjects. Analyze the variance."
    visual_spec = {
        "required": True,
        "type": "chart",
        "spec": {
            "format": "bar",
            "categories": ["Physics", "Chemistry", "Math"],
            "series": [{"name": "Marks", "values": [80, 90, 85]}]
        }
    }

    res = VisualSemanticValidator.validate(question_text=q_text, visual_spec=visual_spec)
    assert res.is_valid is False
    assert any("5 categories" in err or "categories" in err for err in res.errors)


def test_diagram_stage_count_mismatch():
    """
    Question specifies a 4-stage process, but diagram contains only 2 nodes.
    """
    q_text = "Explain the thermodynamic efficiency of a four-stage process shown in the block diagram."
    visual_spec = {
        "required": True,
        "type": "diagram",
        "spec": {
            "nodes": [
                {"id": "1", "label": "Stage 1"},
                {"id": "2", "label": "Stage 2"},
            ],
            "edges": []
        }
    }

    res = VisualSemanticValidator.validate(question_text=q_text, visual_spec=visual_spec)
    assert res.is_valid is False
    assert any("stage" in err for err in res.errors)


def test_in_memory_visual_processing_handles_required_mismatch():
    """
    Verify that PaperGeneratorService._process_question_visuals_in_memory marks required visual
    failures without persisting invalid SVGs.
    """
    service = PaperGeneratorService(db=None)
    questions = [
        {
            "question_text": "A cubical network of 12 resistors each of 1 Ω is connected to a 10 V battery.",
            "visual": {
                "required": True,
                "type": "circuit",
                "spec": {
                    "components": [
                        {"id": "V1", "type": "battery", "label": "10 V"},
                        {"id": "R1", "type": "resistor", "label": "1 Ω"},
                        {"id": "R2", "type": "resistor", "label": "1 Ω"},
                    ],
                    "connections": []
                }
            }
        }
    ]

    service._process_question_visuals_in_memory(questions)
    q = questions[0]
    assert q.get("visual_valid") is False
    assert q.get("visual_svg") is None
    assert "Semantic visual mismatch" in q.get("visual_error", "")


def test_generic_count_inductors_and_lamps_generalization():
    """
    Verify generic count extraction for components other than resistors/capacitors
    (e.g., three inductors vs 1 inductor, two lamps vs 1 lamp).
    """
    # 3 inductors vs 1
    q_ind = "Three identical 25 mH inductors are connected in series with an AC supply."
    spec_ind = {
        "required": True,
        "type": "circuit",
        "spec": {
            "components": [
                {"id": "L1", "type": "inductor", "label": "25 mH"}
            ],
            "connections": []
        }
    }
    res_ind = VisualSemanticValidator.validate(question_text=q_ind, visual_spec=spec_ind)
    assert res_ind.is_valid is False
    assert any("3 inductors" in err or "inductor" in err for err in res_ind.errors)

    # 2 lamps vs 1
    q_lamp = "Two identical lamps are connected across a 12 V cell."
    spec_lamp = {
        "required": True,
        "type": "circuit",
        "spec": {
            "components": [
                {"id": "B1", "type": "lamp", "label": "Bulb 1"}
            ],
            "connections": []
        }
    }
    res_lamp = VisualSemanticValidator.validate(question_text=q_lamp, visual_spec=spec_lamp)
    assert res_lamp.is_valid is False
    assert any("2 lamps" in err or "lamp" in err for err in res_lamp.errors)


def test_source_voltage_numerical_mismatch_warning():
    """
    Verify that an unambiguous source voltage mismatch generates a warning.
    """
    q_text = "A circuit is connected to a 500 V supply with four 10 µF capacitors."
    spec = {
        "required": True,
        "type": "circuit",
        "spec": {
            "components": [
                {"id": "V1", "type": "battery", "label": "100 V"},
                {"id": "C1", "type": "capacitor", "label": "10 µF"},
                {"id": "C2", "type": "capacitor", "label": "10 µF"},
                {"id": "C3", "type": "capacitor", "label": "10 µF"},
                {"id": "C4", "type": "capacitor", "label": "10 µF"},
            ],
            "connections": []
        }
    }
    res = VisualSemanticValidator.validate(question_text=q_text, visual_spec=spec)
    assert any("500" in w for w in res.warnings)


def test_internal_choice_independent_in_memory_processing():
    """
    Verify that Alternative A (valid) and Alternative B (semantic mismatch) in an internal choice
    group are validated independently by PaperGeneratorService._process_question_visuals_in_memory.
    """
    service = PaperGeneratorService(db=None)
    questions = [
        {
            "question_text": "In the circuit below with a 12 V battery and 6 Ω resistor, find the current.",
            "choice_group": "Q4",
            "alternative_label": "a",
            "visual": {
                "required": True,
                "type": "circuit",
                "spec": {
                    "components": [
                        {"id": "V1", "type": "battery", "label": "12 V"},
                        {"id": "R1", "type": "resistor", "label": "6 Ω"},
                    ],
                    "connections": [
                        {"from": "V1", "to": "R1"},
                        {"from": "R1", "to": "V1"}
                    ]
                }
            }
        },
        {
            "question_text": "A cubical network consists of 12 resistors each of resistance 1 Ω.",
            "choice_group": "Q4",
            "alternative_label": "b",
            "visual": {
                "required": True,
                "type": "circuit",
                "spec": {
                    "components": [
                        {"id": "V1", "type": "battery", "label": "10 V"},
                        {"id": "R1", "type": "resistor", "label": "1 Ω"},
                    ],
                    "connections": []
                }
            }
        }
    ]

    service._process_question_visuals_in_memory(questions)
    alt_a = questions[0]
    alt_b = questions[1]

    # Alternative A must be valid with rendered SVG
    assert alt_a.get("visual_valid") is True
    assert alt_a.get("visual_svg") is not None
    assert "<svg" in alt_a.get("visual_svg")

    # Alternative B must fail without rendered SVG
    assert alt_b.get("visual_valid") is False
    assert alt_b.get("visual_svg") is None
    assert "Semantic visual mismatch" in alt_b.get("visual_error", "")


def test_optional_visual_mismatch_non_destructive():
    """
    Verify that for required=False visuals, a semantic mismatch does NOT destroy visual_svg
    or cause hard failures.
    """
    service = PaperGeneratorService(db=None)
    questions = [
        {
            "question_text": "A cubical network consists of 12 resistors each of 1 Ω.",
            "visual": {
                "required": False,
                "type": "circuit",
                "spec": {
                    "components": [
                        {"id": "V1", "type": "battery", "label": "10 V"},
                        {"id": "R1", "type": "resistor", "label": "1 Ω"},
                    ],
                    "connections": []
                }
            }
        }
    ]

    service._process_question_visuals_in_memory(questions)
    q = questions[0]
    # For optional visuals, SVG rendering is preserved rather than destroyed
    assert q.get("visual_valid") is True
    assert q.get("visual_svg") is not None
    assert "<svg" in q.get("visual_svg")


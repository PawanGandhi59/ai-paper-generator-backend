import pytest
from app.schemas.visuals import (
    CircuitComponent,
    CircuitConnection,
    CircuitData,
    CircuitJunction,
    GeminiVisualRequirementSchema,
)
from app.services.visuals.builders.circuit_builder import CircuitBuilder
from app.services.visuals.svg_generator_service import SVGGeneratorService, is_valid_svg_xml


def test_ac_source_schema_validation():
    """
    Verify that ComponentType accepts ac_source and validates correctly.
    """
    comp = CircuitComponent(id="AC1", type="ac_source", label="220 V, 50 Hz", x=100, y=100)
    assert comp.type == "ac_source"
    assert comp.label == "220 V, 50 Hz"


def test_iron_core_schema_validation():
    """
    Verify that iron_core attribute is optional, defaults to False, and accepts True.
    """
    comp_air = CircuitComponent(id="L1", type="inductor", label="50 mH")
    assert comp_air.iron_core is False

    comp_iron = CircuitComponent(id="L2", type="inductor", label="50 mH", iron_core=True)
    assert comp_iron.iron_core is True


def test_routing_schema_validation():
    """
    Verify that routing defaults to orthogonal and accepts direct.
    """
    conn_default = CircuitConnection(**{"from": "A", "to": "B"})
    assert conn_default.routing == "orthogonal"

    conn_direct = CircuitConnection(**{"from": "A", "to": "B", "routing": "direct"})
    assert conn_direct.routing == "direct"


def test_ac_source_svg_symbol():
    """
    Verify that ac_source renders with a circular boundary and sine wave path.
    """
    builder = CircuitBuilder()
    data = {
        "components": [
            {"id": "AC1", "type": "ac_source", "label": "220 V, 50 Hz", "x": 100, "y": 100}
        ],
        "connections": []
    }
    svg = builder.render({"title": "AC Source Test", "data": data})
    assert is_valid_svg_xml(svg)
    assert "<circle" in svg
    assert "220 V, 50 Hz" in svg
    assert "M " in svg and "Q " in svg  # Sine wave path


def test_inductor_svg_symbol_air_vs_iron_core():
    """
    Verify that inductor renders coil arcs, and iron_core=True adds parallel lines.
    """
    builder = CircuitBuilder()
    data_air = {
        "components": [
            {"id": "L1", "type": "inductor", "label": "Air Coil", "iron_core": False, "x": 100, "y": 100}
        ]
    }
    svg_air = builder.render({"title": "Air Inductor", "data": data_air})
    assert is_valid_svg_xml(svg_air)
    assert "Air Coil" in svg_air
    assert "A 6 6" in svg_air  # Coil arc

    data_iron = {
        "components": [
            {"id": "L2", "type": "inductor", "label": "Iron Choke", "iron_core": True, "x": 100, "y": 100}
        ]
    }
    svg_iron = builder.render({"title": "Iron Inductor", "data": data_iron})
    assert is_valid_svg_xml(svg_iron)
    assert "Iron Choke" in svg_iron
    assert "A 6 6" in svg_iron
    # Verify presence of parallel iron core lines
    assert 'y1="88.0" x2="124.0" y2="88.0"' in svg_iron or 'stroke-width="2"' in svg_iron


def test_wheatstone_bridge_direct_routing():
    """
    Verify that a Wheatstone bridge with diamond branches and direct routing renders clean diagonal wires.
    """
    service = SVGGeneratorService()
    spec = GeminiVisualRequirementSchema(
        required=True,
        type="circuit",
        title="Wheatstone Bridge Circuit",
        spec={
            "junctions": [
                {"id": "A", "x": 50, "y": 150, "label": "A"},
                {"id": "B", "x": 200, "y": 50, "label": "B"},
                {"id": "C", "x": 350, "y": 150, "label": "C"},
                {"id": "D", "x": 200, "y": 250, "label": "D"}
            ],
            "components": [
                {"id": "R1", "type": "resistor", "label": "R1 = 2 Ω", "x": 125, "y": 100},
                {"id": "R2", "type": "resistor", "label": "R2 = 4 Ω", "x": 275, "y": 100},
                {"id": "R3", "type": "resistor", "label": "R3 = 3 Ω", "x": 125, "y": 200},
                {"id": "R4", "type": "resistor", "label": "R4 = 6 Ω", "x": 275, "y": 200},
                {"id": "G1", "type": "generic", "label": "Galvanometer", "x": 200, "y": 150},
                {"id": "V1", "type": "battery", "label": "10 V", "x": 200, "y": 320}
            ],
            "connections": [
                {"from": "A", "to": "R1", "routing": "direct"},
                {"from": "R1", "to": "B", "routing": "direct"},
                {"from": "B", "to": "R2", "routing": "direct"},
                {"from": "R2", "to": "C", "routing": "direct"},
                {"from": "A", "to": "R3", "routing": "direct"},
                {"from": "R3", "to": "D", "routing": "direct"},
                {"from": "D", "to": "R4", "routing": "direct"},
                {"from": "R4", "to": "C", "routing": "direct"},
                {"from": "B", "to": "G1", "routing": "direct"},
                {"from": "G1", "to": "D", "routing": "direct"},
                {"from": "A", "to": "V1", "routing": "orthogonal"},
                {"from": "V1", "to": "C", "routing": "orthogonal"}
            ]
        }
    )
    res = service.generate(spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert "Wheatstone Bridge Circuit" in res.svg_raw
    assert "Galvanometer" in res.svg_raw
    assert "R1 = 2 Ω" in res.svg_raw
    assert "R4 = 6 Ω" in res.svg_raw


def test_12_resistor_cubical_network_faithful_reconstruction():
    """
    Verify complete 12-resistor cubical network with 8 vertices, 12 resistors,
    and a battery connected across diagonally opposite vertices (A, G).
    """
    service = SVGGeneratorService()
    # 8 isometric 3D cube vertices
    # Front square: A=(100, 250), B=(250, 250), C=(250, 100), D=(100, 100)
    # Back square (offset by dx=60, dy=-40): E=(160, 210), F=(310, 210), G=(310, 60), H=(160, 60)
    cube_spec = GeminiVisualRequirementSchema(
        required=True,
        type="circuit",
        title="Cubical Resistor Network (12 Resistors)",
        caption="12 identical 1 Ω resistors along the edges of a cube with battery across diagonal corners A and G.",
        spec={
            "junctions": [
                {"id": "A", "x": 100, "y": 250, "label": "A"},
                {"id": "B", "x": 250, "y": 250, "label": "B"},
                {"id": "C", "x": 250, "y": 100, "label": "C"},
                {"id": "D", "x": 100, "y": 100, "label": "D"},
                {"id": "E", "x": 160, "y": 210, "label": "E"},
                {"id": "F", "x": 310, "y": 210, "label": "F"},
                {"id": "G", "x": 310, "y": 60, "label": "G"},
                {"id": "H", "x": 160, "y": 60, "label": "H"},
            ],
            "components": [
                # 4 Front face resistors
                {"id": "R_AB", "type": "resistor", "label": "1 Ω", "x": 175, "y": 250},
                {"id": "R_BC", "type": "resistor", "label": "1 Ω", "x": 250, "y": 175},
                {"id": "R_CD", "type": "resistor", "label": "1 Ω", "x": 175, "y": 100},
                {"id": "R_DA", "type": "resistor", "label": "1 Ω", "x": 100, "y": 175},
                # 4 Back face resistors
                {"id": "R_EF", "type": "resistor", "label": "1 Ω", "x": 235, "y": 210},
                {"id": "R_FG", "type": "resistor", "label": "1 Ω", "x": 310, "y": 135},
                {"id": "R_GH", "type": "resistor", "label": "1 Ω", "x": 235, "y": 60},
                {"id": "R_HE", "type": "resistor", "label": "1 Ω", "x": 160, "y": 135},
                # 4 Connecting depth resistors
                {"id": "R_AE", "type": "resistor", "label": "1 Ω", "x": 130, "y": 230},
                {"id": "R_BF", "type": "resistor", "label": "1 Ω", "x": 280, "y": 230},
                {"id": "R_CG", "type": "resistor", "label": "1 Ω", "x": 280, "y": 80},
                {"id": "R_DH", "type": "resistor", "label": "1 Ω", "x": 130, "y": 80},
                # Diagonal battery supply
                {"id": "V1", "type": "battery", "label": "10 V", "x": 205, "y": 320},
            ],
            "connections": [
                # Front face connections
                {"from": "A", "to": "R_AB", "routing": "orthogonal"},
                {"from": "R_AB", "to": "B", "routing": "orthogonal"},
                {"from": "B", "to": "R_BC", "routing": "orthogonal"},
                {"from": "R_BC", "to": "C", "routing": "orthogonal"},
                {"from": "C", "to": "R_CD", "routing": "orthogonal"},
                {"from": "R_CD", "to": "D", "routing": "orthogonal"},
                {"from": "D", "to": "R_DA", "routing": "orthogonal"},
                {"from": "R_DA", "to": "A", "routing": "orthogonal"},
                # Back face connections
                {"from": "E", "to": "R_EF", "routing": "orthogonal"},
                {"from": "R_EF", "to": "F", "routing": "orthogonal"},
                {"from": "F", "to": "R_FG", "routing": "orthogonal"},
                {"from": "R_FG", "to": "G", "routing": "orthogonal"},
                {"from": "G", "to": "R_GH", "routing": "orthogonal"},
                {"from": "R_GH", "to": "H", "routing": "orthogonal"},
                {"from": "H", "to": "R_HE", "routing": "orthogonal"},
                {"from": "R_HE", "to": "E", "routing": "orthogonal"},
                # Depth connections (direct diagonal routing for isometric projection)
                {"from": "A", "to": "R_AE", "routing": "direct"},
                {"from": "R_AE", "to": "E", "routing": "direct"},
                {"from": "B", "to": "R_BF", "routing": "direct"},
                {"from": "R_BF", "to": "F", "routing": "direct"},
                {"from": "C", "to": "R_CG", "routing": "direct"},
                {"from": "R_CG", "to": "G", "routing": "direct"},
                {"from": "D", "to": "R_DH", "routing": "direct"},
                {"from": "R_DH", "to": "H", "routing": "direct"},
                # Battery connections across corners A and G
                {"from": "A", "to": "V1", "routing": "orthogonal"},
                {"from": "V1", "to": "G", "routing": "orthogonal"},
            ]
        }
    )
    res = service.generate(cube_spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)

    # Verify all 8 vertices are rendered as text labels
    for vertex in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        assert f">{vertex}<" in res.svg_raw

    # Verify battery and resistors are present
    assert "10 V" in res.svg_raw
    assert res.svg_raw.count(">1 Ω<") == 12

    # Verify direct lines are generated for depth edges
    assert "<line" in res.svg_raw


def test_ac_source_switch_lamp_iron_core_circuit():
    """
    Verify complete realistic AC series circuit with AC Source, closed switch,
    lamp (bulb), and iron-core inductor.
    """
    service = SVGGeneratorService()
    spec = GeminiVisualRequirementSchema(
        required=True,
        type="circuit",
        title="AC Lamp and Inductor Experiment",
        caption="AC source connected in series with a closed key, a lamp, and an iron-core inductor.",
        spec={
            "components": [
                {"id": "AC1", "type": "ac_source", "label": "220 V, 50 Hz", "x": 100, "y": 200},
                {"id": "K1", "type": "switch", "label": "Key", "state": "closed", "x": 200, "y": 200},
                {"id": "L1", "type": "inductor", "label": "Iron Inductor", "iron_core": True, "x": 300, "y": 100},
                {"id": "B1", "type": "lamp", "label": "Bulb", "x": 100, "y": 100},
            ],
            "connections": [
                {"from": "AC1", "to": "K1", "routing": "orthogonal"},
                {"from": "K1", "to": "L1", "routing": "orthogonal"},
                {"from": "L1", "to": "B1", "routing": "orthogonal"},
                {"from": "B1", "to": "AC1", "routing": "orthogonal"},
            ]
        }
    )
    res = service.generate(spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert "220 V, 50 Hz" in res.svg_raw
    assert "Key" in res.svg_raw
    assert "Iron Inductor" in res.svg_raw
    assert "Bulb" in res.svg_raw


def test_backward_compatibility_with_legacy_circuit_specs():
    """
    Verify that legacy circuit specifications without iron_core or routing fields
    continue to render smoothly with 100% backward compatibility.
    """
    service = SVGGeneratorService()
    legacy_spec = {
        "required": True,
        "type": "circuit",
        "title": "Legacy DC Circuit",
        "spec": {
            "components": [
                {"id": "V1", "type": "battery", "label": "12 V"},
                {"id": "R1", "type": "resistor", "label": "6 Ω"}
            ],
            "connections": [
                {"from": "V1", "to": "R1"},
                {"from": "R1", "to": "V1"}
            ]
        }
    }
    res = service.generate(legacy_spec)
    assert res.is_valid is True
    assert is_valid_svg_xml(res.svg_raw)
    assert "Legacy DC Circuit" in res.svg_raw
    assert "12 V" in res.svg_raw
    assert "6 Ω" in res.svg_raw

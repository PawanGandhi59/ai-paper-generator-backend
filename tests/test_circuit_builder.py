import pytest
from app.schemas.visuals import VisualRequiredSpec
from app.services.visuals import CircuitBuilder, GeneratedSVGResult, SVGGeneratorService


def test_circuit_builder_simple_battery_resistor():
    builder = CircuitBuilder()

    spec = {
        "title": "Simple Circuit",
        "caption": "Basic DC circuit with 12V battery and 6 ohm resistor",
        "spec_data": {
            "components": [
                {"id": "V1", "type": "battery", "x": 100, "y": 200, "label": "12 V"},
                {"id": "R1", "type": "resistor", "x": 300, "y": 100, "label": "6 Ω"},
            ],
            "connections": [
                {"from": "V1", "to": "R1", "show_current": True, "label": "I = 2 A"},
                {"from": "R1", "to": "V1"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert isinstance(svg_output, str)
    assert "<svg" in svg_output
    assert "</svg>" in svg_output
    assert 'viewBox="' in svg_output
    assert "Simple Circuit" in svg_output
    assert "12 V" in svg_output
    assert "6 Ω" in svg_output
    assert "I = 2 A" in svg_output
    assert 'marker-end="url(#arrow_current)"' in svg_output


def test_circuit_builder_series_and_instruments():
    builder = CircuitBuilder()

    spec = {
        "title": "Series Circuit with Ammeter and Voltmeter",
        "spec_data": {
            "components": [
                {"id": "V1", "type": "battery", "x": 100, "y": 200, "label": "24 V"},
                {"id": "A1", "type": "ammeter", "x": 200, "y": 100, "label": "Ammeter"},
                {"id": "R1", "type": "resistor", "x": 350, "y": 100, "label": "10 Ω"},
                {"id": "V_meter", "type": "voltmeter", "x": 350, "y": 200, "label": "Voltmeter"},
            ],
            "connections": [
                {"from": "V1", "to": "A1"},
                {"from": "A1", "to": "R1"},
                {"from": "R1", "to": "V1"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "Ammeter" in svg_output
    assert "Voltmeter" in svg_output
    assert "10 Ω" in svg_output


def test_circuit_builder_switch_and_lamp():
    builder = CircuitBuilder()

    spec = {
        "title": "Switched Lamp Circuit",
        "spec_data": {
            "components": [
                {"id": "CELL1", "type": "cell", "x": 100, "y": 150, "label": "1.5 V"},
                {"id": "SW1", "type": "switch", "x": 250, "y": 100, "label": "S1", "state": "open"},
                {"id": "L1", "type": "lamp", "x": 400, "y": 150, "label": "Lamp L1"},
            ],
            "connections": [
                {"from": "CELL1", "to": "SW1"},
                {"from": "SW1", "to": "L1"},
                {"from": "L1", "to": "CELL1"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "Lamp L1" in svg_output
    assert "S1 (open)" in svg_output


def test_circuit_builder_parallel_circuit_with_junctions():
    builder = CircuitBuilder()

    spec = {
        "title": "Parallel Resistor Circuit",
        "spec_data": {
            "junctions": [
                {"id": "J1", "x": 200, "y": 100, "label": "J1"},
                {"id": "J2", "x": 200, "y": 300, "label": "J2"},
            ],
            "components": [
                {"id": "V1", "type": "battery", "x": 80, "y": 200, "label": "9 V"},
                {"id": "R1", "type": "resistor", "x": 280, "y": 150, "label": "R1 = 100 Ω"},
                {"id": "R2", "type": "resistor", "x": 280, "y": 250, "label": "R2 = 200 Ω"},
            ],
            "connections": [
                {"from": "V1", "to": "J1"},
                {"from": "J1", "to": "R1"},
                {"from": "J1", "to": "R2"},
                {"from": "R1", "to": "J2"},
                {"from": "R2", "to": "J2"},
                {"from": "J2", "to": "V1"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert 'circle cx="' in svg_output  # Junction dots
    assert "R1 = 100 Ω" in svg_output
    assert "R2 = 200 Ω" in svg_output


def test_circuit_builder_automatic_position_synthesis():
    builder = CircuitBuilder()

    spec = {
        "title": "Auto Layout Circuit",
        "spec_data": {
            "components": [
                {"id": "V1", "type": "battery", "label": "9V"},
                {"id": "R1", "type": "resistor", "label": "R1"},
                {"id": "L1", "type": "lamp", "label": "L1"},
            ],
            "connections": [
                {"from": "V1", "to": "R1"},
                {"from": "R1", "to": "L1"},
                {"from": "L1", "to": "V1"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "Auto Layout Circuit" in svg_output
    assert "R1" in svg_output
    assert "L1" in svg_output


def test_svg_generator_service_circuit_integration():
    service = SVGGeneratorService()

    spec = VisualRequiredSpec(
        visual_required=True,
        visual_type="circuit",
        title="Physics Exam Circuit Question",
        caption="Calculate equivalent resistance between terminals",
        spec_data={
            "components": [
                {"id": "V1", "type": "battery", "x": 100, "y": 180, "label": "6 V"},
                {"id": "R1", "type": "resistor", "x": 280, "y": 180, "label": "3 Ω"},
            ],
            "connections": [
                {"from": "V1", "to": "R1", "show_current": True},
                {"from": "R1", "to": "V1"},
            ],
        },
    )

    result = service.generate(spec)

    assert isinstance(result, GeneratedSVGResult)
    assert result.is_valid is True
    assert result.title == "Physics Exam Circuit Question"
    assert result.caption == "Calculate equivalent resistance between terminals"
    assert "<svg" in result.svg_raw
    assert "</svg>" in result.svg_raw
    assert "6 V" in result.svg_raw
    assert "3 Ω" in result.svg_raw

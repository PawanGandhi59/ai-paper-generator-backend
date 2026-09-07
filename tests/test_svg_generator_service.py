import pytest
from app.schemas.visuals import VisualRequiredSpec
from app.services.visuals import (
    GeneratedSVGResult,
    SVGGeneratorService,
    SVGRenderer,
)
from app.services.visuals.svg_renderer import VisualSpec


def test_svg_generator_service_diagram_generation():
    service = SVGGeneratorService()

    spec = VisualRequiredSpec(
        visual_required=True,
        visual_type="diagram",
        format="flowchart",
        title="Sample Logic Flowchart",
        caption="A simple step-by-step logic diagram",
        spec_data={
            "nodes": [
                {"id": "n1", "label": "Start Process", "shape": "rounded"},
                {"id": "n2", "label": "Check Condition", "shape": "diamond"},
                {"id": "n3", "label": "Execute Task", "shape": "rectangle"},
            ],
            "edges": [
                {"from": "n1", "to": "n2", "label": "init"},
                {"from": "n2", "to": "n3", "label": "if True"},
            ],
        },
    )

    result = service.generate(spec)

    assert isinstance(result, GeneratedSVGResult)
    assert result.is_valid is True
    assert result.title == "Sample Logic Flowchart"
    assert result.caption == "A simple step-by-step logic diagram"
    assert "<svg" in result.svg_raw
    assert "</svg>" in result.svg_raw
    assert "Start Process" in result.svg_raw
    assert "Check" in result.svg_raw
    assert "Condition" in result.svg_raw


def test_svg_generator_service_chart_generation():
    service = SVGGeneratorService()

    spec = VisualRequiredSpec(
        visual_required=True,
        visual_type="chart",
        format="bar",
        title="Student Marks Distribution",
        caption="Average marks across subjects",
        spec_data={
            "x_label": "Subject",
            "y_label": "Marks",
            "categories": ["Physics", "Chemistry", "Math"],
            "values": [85.0, 90.5, 78.0],
        },
    )

    result = service.generate(spec)

    assert isinstance(result, GeneratedSVGResult)
    assert result.is_valid is True
    assert result.title == "Student Marks Distribution"
    assert "<svg" in result.svg_raw
    assert "</svg>" in result.svg_raw
    assert "Physics" in result.svg_raw
    assert "Chemistry" in result.svg_raw


def test_svg_generator_service_raw_svg_support():
    service = SVGGeneratorService()

    raw_xml = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="red"/></svg>'
    spec = VisualRequiredSpec(
        visual_required=True,
        visual_type="raw_svg",
        title="Custom Raw SVG",
        raw_svg_code=raw_xml,
    )

    result = service.generate(spec)

    assert result.is_valid is True
    assert result.svg_raw == raw_xml
    assert result.title == "Custom Raw SVG"


def test_svg_generator_service_unsupported_type_handled_cleanly():
    service = SVGGeneratorService()

    spec = {
        "visual_type": "unknown_unsupported_type",
        "title": "Invalid Spec",
        "spec_data": {},
    }

    result = service.generate(spec)

    assert isinstance(result, GeneratedSVGResult)
    assert result.is_valid is False
    assert result.svg_raw == ""
    assert result.title == "Invalid Spec"


def test_svg_generator_service_legacy_visual_spec_compatibility():
    service = SVGGeneratorService()

    legacy_spec = VisualSpec(
        id="legacy_1",
        type="chart",
        format="pie",
        title="Budget Allocation",
        data={
            "categories": ["Rent", "Food", "Savings"],
            "values": [400.0, 200.0, 300.0],
        },
    )

    result = service.generate(legacy_spec)

    assert result.is_valid is True
    assert "Budget Allocation" in result.svg_raw
    assert "Rent" in result.svg_raw

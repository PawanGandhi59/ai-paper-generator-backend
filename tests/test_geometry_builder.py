import pytest
from app.schemas.visuals import VisualRequiredSpec
from app.services.visuals import GeometryBuilder, SVGGeneratorService, GeneratedSVGResult


def test_geometry_builder_triangle_rendering():
    builder = GeometryBuilder()

    spec = {
        "title": "Right-Angled Triangle ABC",
        "caption": "Triangle with right angle at vertex A",
        "spec_data": {
            "points": [
                {"id": "A", "x": 50, "y": 200, "label": "A"},
                {"id": "B", "x": 250, "y": 200, "label": "B"},
                {"id": "C", "x": 50, "y": 50, "label": "C"},
            ],
            "segments": [
                {"from": "A", "to": "B", "label": "base = 8 cm", "style": "solid"},
                {"from": "A", "to": "C", "label": "height = 6 cm", "style": "solid"},
                {"from": "B", "to": "C", "label": "hypotenuse = 10 cm", "style": "solid"},
            ],
            "polygons": [
                {"points": ["A", "B", "C"], "fill_color": "#EBF8FF"}
            ],
            "angles": [
                {"vertex": "A", "p1": "B", "p2": "C", "label": "90°", "right_angle": True}
            ],
        },
    }

    svg_output = builder.render(spec)

    assert isinstance(svg_output, str)
    assert "<svg" in svg_output
    assert "</svg>" in svg_output
    assert 'viewBox="' in svg_output
    assert "Right-Angled Triangle ABC" in svg_output
    assert "polygon points=" in svg_output
    assert "polyline points=" in svg_output  # right angle indicator
    assert "base = 8 cm" in svg_output
    assert "height = 6 cm" in svg_output
    assert "hypotenuse = 10 cm" in svg_output


def test_geometry_builder_circle_and_radius():
    builder = GeometryBuilder()

    spec = {
        "title": "Circle with Radius",
        "spec_data": {
            "points": [
                {"id": "O", "x": 150, "y": 150, "label": "O (Center)"},
                {"id": "P", "x": 250, "y": 150, "label": "P"},
            ],
            "segments": [
                {"from": "O", "to": "P", "label": "r = 5 cm", "style": "dashed"}
            ],
            "circles": [
                {"center": "O", "radius": 100.0, "label": "Circle C1"}
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "circle cx=" in svg_output
    assert 'stroke-dasharray="6,4"' in svg_output
    assert "r = 5 cm" in svg_output


def test_geometry_builder_vectors_and_dashed_construction_lines():
    builder = GeometryBuilder()

    spec = {
        "title": "Vector Projection",
        "spec_data": {
            "points": [
                {"id": "O", "x": 50, "y": 200},
                {"id": "A", "x": 200, "y": 100},
                {"id": "B", "x": 200, "y": 200},
            ],
            "segments": [
                {"from": "O", "to": "A", "label": "v", "arrow": "end"},
                {"from": "A", "to": "B", "label": "projection", "style": "dashed"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert 'marker-end="url(#arrow_geom)"' in svg_output
    assert 'stroke-dasharray="6,4"' in svg_output


def test_geometry_builder_automatic_point_synthesis():
    builder = GeometryBuilder()

    # Spec missing explicit x, y point coordinates
    spec = {
        "title": "Auto Triangle",
        "spec_data": {
            "polygons": [
                {"points": ["P1", "P2", "P3"]}
            ],
            "segments": [
                {"from": "P1", "to": "P2", "label": "side 1"},
                {"from": "P2", "to": "P3", "label": "side 2"},
                {"from": "P3", "to": "P1", "label": "side 3"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "Auto Triangle" in svg_output
    assert "polygon points=" in svg_output
    assert "side 1" in svg_output


def test_svg_generator_service_geometry_integration():
    service = SVGGeneratorService()

    spec = VisualRequiredSpec(
        visual_required=True,
        visual_type="geometry",
        title="Service Integration Geometry",
        caption="Geometric diagram generated via global service",
        spec_data={
            "points": [
                {"id": "X", "x": 60, "y": 180, "label": "X"},
                {"id": "Y", "x": 220, "y": 180, "label": "Y"},
                {"id": "Z", "x": 140, "y": 60, "label": "Z"},
            ],
            "polygons": [
                {"points": ["X", "Y", "Z"], "fill_color": "#E6FFFA"}
            ],
        },
    )

    result = service.generate(spec)

    assert isinstance(result, GeneratedSVGResult)
    assert result.is_valid is True
    assert result.title == "Service Integration Geometry"
    assert result.caption == "Geometric diagram generated via global service"
    assert "<svg" in result.svg_raw
    assert "</svg>" in result.svg_raw
    assert "polygon points=" in result.svg_raw

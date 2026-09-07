import pytest
from app.schemas.visuals import VisualRequiredSpec
from app.services.visuals import GeneratedSVGResult, GraphBuilder, SVGGeneratorService


def test_graph_builder_safe_expression_evaluator():
    builder = GraphBuilder()

    # Valid mathematical expressions
    assert builder.eval_expression("2*x + 1", 3.0) == 7.0
    assert builder.eval_expression("x**2 - 4", 3.0) == 5.0
    assert abs(builder.eval_expression("sin(x)", 0.0) - 0.0) < 1e-6
    assert abs(builder.eval_expression("cos(x)", 0.0) - 1.0) < 1e-6
    assert builder.eval_expression("sqrt(x)", 16.0) == 4.0

    # Unsafe or invalid expressions must be rejected safely
    assert builder.eval_expression("__import__('os').system('ls')", 1.0) is None
    assert builder.eval_expression("eval('1+1')", 1.0) is None
    assert builder.eval_expression("open('/etc/passwd').read()", 1.0) is None
    assert builder.eval_expression("1 / 0", 0.0) is None


def test_graph_builder_linear_function_plot():
    builder = GraphBuilder()

    spec = {
        "title": "Graph of y = 2x + 1",
        "caption": "Linear equation plot across x in [-5, 5]",
        "spec_data": {
            "x_range": [-5, 5],
            "y_range": [-5, 10],
            "grid": True,
            "x_axis_label": "x",
            "y_axis_label": "y",
            "functions": [
                {"expression": "2*x + 1", "label": "y = 2x + 1", "color": "#3182CE"}
            ],
        },
    }

    svg_output = builder.render(spec)

    assert isinstance(svg_output, str)
    assert "<svg" in svg_output
    assert "</svg>" in svg_output
    assert 'viewBox="' in svg_output
    assert "Graph of y = 2x + 1" in svg_output
    assert "y = 2x + 1" in svg_output
    assert "path d=" in svg_output
    assert 'marker-end="url(#arrow_axis)"' in svg_output


def test_graph_builder_nonlinear_functions_and_points():
    builder = GraphBuilder()

    spec = {
        "title": "Parabola and Points",
        "spec_data": {
            "x_range": [-4, 4],
            "y_range": [-5, 12],
            "grid": True,
            "functions": [
                {"expression": "x**2 - 4", "label": "y = x² - 4", "color": "#DD6B20"}
            ],
            "points": [
                {"x": 0, "y": -4, "label": "Vertex (0, -4)"},
                {"x": 2, "y": 0, "label": "Root (2, 0)"},
                {"x": -2, "y": 0, "label": "Root (-2, 0)"},
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "Vertex (0, -4)" in svg_output
    assert "Root (2, 0)" in svg_output
    assert "circle cx=" in svg_output


def test_graph_builder_line_segments():
    builder = GraphBuilder()

    spec = {
        "title": "Polygon Vertices Plot",
        "spec_data": {
            "x_range": [0, 10],
            "y_range": [0, 10],
            "segments": [
                {"x1": 1, "y1": 1, "x2": 5, "y2": 8, "label": "Segment AB", "style": "solid"}
            ],
        },
    }

    svg_output = builder.render(spec)

    assert "<svg" in svg_output
    assert "Segment AB" in svg_output
    assert "line x1=" in svg_output


def test_svg_generator_service_graph_integration():
    service = SVGGeneratorService()

    spec = VisualRequiredSpec(
        visual_required=True,
        visual_type="graph",
        title="Physics Motion Graph",
        caption="Velocity-time graph v(t) = 5*t",
        spec_data={
            "x_range": [0, 10],
            "y_range": [0, 50],
            "x_axis_label": "Time (s)",
            "y_axis_label": "Velocity (m/s)",
            "functions": [
                {"expression": "5*x", "label": "v(t) = 5t", "color": "#319795"}
            ],
        },
    )

    result = service.generate(spec)

    assert isinstance(result, GeneratedSVGResult)
    assert result.is_valid is True
    assert result.title == "Physics Motion Graph"
    assert result.caption == "Velocity-time graph v(t) = 5*t"
    assert "<svg" in result.svg_raw
    assert "</svg>" in result.svg_raw
    assert "Time (s)" in result.svg_raw
    assert "Velocity (m/s)" in result.svg_raw

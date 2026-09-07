import ast
import math
from typing import Any, Dict, List, Literal, Optional, Set, Union
from pydantic import BaseModel, Field, model_validator

# Canonical Gemini-facing visual types (strictly excludes raw_svg)
GeminiVisualType = Literal[
    "diagram",       # Flowchart, sequence, tree, process, classification
    "chart",         # Bar, line, pie, histogram
    "geometry",      # Geometric shapes, triangles, angles, polygons
    "circuit",       # Schematic circuits (resistors, capacitors, sources, switches)
    "graph",         # 2D function plots f(x), coordinate axes, curves
]

# Internal Visual Type (includes internal backend raw_svg)
VisualType = Literal[
    "diagram",
    "chart",
    "circuit",
    "geometry",
    "graph",
    "raw_svg",
]


# ==============================================================================
# 1. Diagram Specification Schemas
# ==============================================================================
class DiagramNodeData(BaseModel):
    id: str = Field(..., description="Unique node identifier")
    label: str = Field(..., description="Text label inside node")
    shape: Optional[str] = Field("box", description="Node shape: box, circle, diamond, rounded")


class DiagramEdgeData(BaseModel):
    from_node: str = Field(..., alias="from", description="Origin node ID")
    to_node: str = Field(..., alias="to", description="Target node ID")
    label: Optional[str] = Field(None, description="Optional edge label")

    model_config = {"populate_by_name": True}


class DiagramData(BaseModel):
    nodes: List[DiagramNodeData] = Field(default_factory=list, description="List of diagram nodes")
    edges: List[DiagramEdgeData] = Field(default_factory=list, description="List of diagram edges connecting nodes")


# ==============================================================================
# 2. Chart Specification Schemas
# ==============================================================================
class ChartSeriesData(BaseModel):
    name: str = Field("Series", description="Series label name")
    values: List[float] = Field(default_factory=list, description="Numeric data points")


class ChartDataSpec(BaseModel):
    format: Optional[str] = Field("bar", description="Chart format: bar, line, pie, histogram")
    categories: List[str] = Field(default_factory=list, description="Category labels")
    series: List[ChartSeriesData] = Field(default_factory=list, description="Data series")
    x_axis_label: Optional[str] = Field(None, description="Horizontal axis title")
    y_axis_label: Optional[str] = Field(None, description="Vertical axis title")


# ==============================================================================
# 3. Geometry Specification Schemas
# ==============================================================================
class GeometryPoint(BaseModel):
    id: Optional[str] = Field(None, description="Unique point identifier e.g. 'A', 'B', 'P1'")
    x: Optional[float] = Field(None, description="X coordinate")
    y: Optional[float] = Field(None, description="Y coordinate")
    label: Optional[str] = Field(None, description="Optional text label to display near point")
    show_point: bool = Field(True, description="Whether to render a dot at point coordinates")


class GeometrySegment(BaseModel):
    from_point: str = Field(..., alias="from", description="Origin point ID")
    to_point: str = Field(..., alias="to", description="Target point ID")
    label: Optional[str] = Field(None, description="Segment length or label e.g. '5 cm'")
    style: Literal["solid", "dashed", "dotted"] = Field("solid", description="Line stroke style")
    arrow: Literal["none", "end", "both"] = Field("none", description="Arrowhead style for vectors/rays")

    model_config = {"populate_by_name": True}


class GeometryPolygon(BaseModel):
    points: List[str] = Field(default_factory=list, description="Ordered list of point IDs forming polygon e.g. ['A', 'B', 'C']")
    label: Optional[str] = Field(None, description="Polygon name or label e.g. 'Triangle ABC'")
    fill_color: Optional[str] = Field(None, description="Optional background fill color e.g. '#EBF8FF'")


class GeometryCircle(BaseModel):
    center: str = Field(..., description="Center point ID")
    radius: float = Field(..., description="Radius length in viewport units")
    label: Optional[str] = Field(None, description="Circle label e.g. 'r = 5 cm'")
    fill_color: Optional[str] = Field(None, description="Optional fill color")


class GeometryAngle(BaseModel):
    vertex: str = Field(..., description="Vertex point ID")
    p1: str = Field(..., description="First arm point ID")
    p2: str = Field(..., description="Second arm point ID")
    label: Optional[str] = Field(None, description="Angle label e.g. '90°' or 'θ'")
    right_angle: bool = Field(False, description="Whether to draw a square right-angle symbol")


class GeometryData(BaseModel):
    points: List[GeometryPoint] = Field(default_factory=list, description="Points in geometry figure")
    segments: List[GeometrySegment] = Field(default_factory=list, description="Line segments, rays, or vectors")
    polygons: List[GeometryPolygon] = Field(default_factory=list, description="Closed polygons (triangles, rectangles)")
    circles: List[GeometryCircle] = Field(default_factory=list, description="Circles and arcs")
    angles: List[GeometryAngle] = Field(default_factory=list, description="Angles and right-angle indicators")


# ==============================================================================
# 4. Circuit Specification Schemas
# ==============================================================================
ComponentType = Literal[
    "battery",
    "cell",
    "ac_source",
    "resistor",
    "capacitor",
    "switch",
    "lamp",
    "diode",
    "ammeter",
    "voltmeter",
    "inductor",
    "ground",
    "generic",
]


class CircuitComponent(BaseModel):
    id: str = Field(..., description="Unique component ID e.g. 'R1', 'V1', 'L1'")
    type: ComponentType = Field("resistor", description="Electrical component symbol type")
    x: Optional[float] = Field(None, description="X coordinate")
    y: Optional[float] = Field(None, description="Y coordinate")
    label: Optional[str] = Field(None, description="Component value or label e.g. '10 Ω', '12 V'")
    orientation: Literal["horizontal", "vertical"] = Field("horizontal", description="Drawing orientation")
    state: Optional[Literal["open", "closed"]] = Field("open", description="State for switches")
    iron_core: Optional[bool] = Field(False, description="Whether inductor has iron core indication")


class CircuitConnection(BaseModel):
    from_comp: str = Field(..., alias="from", description="Origin component ID or junction ID")
    to_comp: str = Field(..., alias="to", description="Target component ID or junction ID")
    label: Optional[str] = Field(None, description="Optional wire label e.g. 'I = 2 A'")
    show_current: bool = Field(False, description="Whether to draw current direction arrow")
    routing: Optional[Literal["orthogonal", "direct"]] = Field("orthogonal", description="Wire path routing style")

    model_config = {"populate_by_name": True}


class CircuitJunction(BaseModel):
    id: str = Field(..., description="Junction node ID e.g. 'J1'")
    x: float = Field(..., description="X coordinate")
    y: float = Field(..., description="Y coordinate")
    label: Optional[str] = Field(None, description="Optional node label")


class CircuitData(BaseModel):
    components: List[CircuitComponent] = Field(default_factory=list, description="Circuit components")
    connections: List[CircuitConnection] = Field(default_factory=list, description="Wire connections between components")
    junctions: List[CircuitJunction] = Field(default_factory=list, description="Junction nodes")


# ==============================================================================
# 5. Graph Specification Schemas
# ==============================================================================
class GraphPoint(BaseModel):
    x: float = Field(..., description="X coordinate in mathematical grid space")
    y: float = Field(..., description="Y coordinate in mathematical grid space")
    label: Optional[str] = Field(None, description="Optional label for the point e.g. 'A(2, 3)'")
    color: Optional[str] = Field("#E53E3E", description="Point dot color")
    show_point: bool = Field(True, description="Whether to draw a dot at the coordinates")


class GraphSegment(BaseModel):
    x1: float = Field(..., description="Start X coordinate")
    y1: float = Field(..., description="Start Y coordinate")
    x2: float = Field(..., description="End X coordinate")
    y2: float = Field(..., description="End Y coordinate")
    label: Optional[str] = Field(None, description="Segment label")
    style: Literal["solid", "dashed", "dotted"] = Field("solid", description="Stroke style")
    color: Optional[str] = Field("#3182CE", description="Stroke color")


class GraphFunction(BaseModel):
    expression: str = Field(..., description="Mathematical expression in x e.g. '2*x + 1', 'x**2 - 4', 'sin(x)'")
    label: Optional[str] = Field(None, description="Legend or curve label e.g. 'y = 2x + 1'")
    color: Optional[str] = Field("#3182CE", description="Curve color")
    samples: int = Field(200, description="Number of sample points along x_range")
    stroke_width: float = Field(2.5, description="Stroke line width")


class GraphData(BaseModel):
    x_range: List[float] = Field(default=[-5.0, 5.0], description="[x_min, x_max] bounds")
    y_range: List[float] = Field(default=[-5.0, 5.0], description="[y_min, y_max] bounds")
    grid: bool = Field(True, description="Whether to render background grid lines")
    x_axis_label: str = Field("x", description="Label for horizontal X axis")
    y_axis_label: str = Field("y", description="Label for vertical Y axis")
    x_step: Optional[float] = Field(None, description="Tick step along X axis")
    y_step: Optional[float] = Field(None, description="Tick step along Y axis")
    points: List[GraphPoint] = Field(default_factory=list, description="Plotted points")
    segments: List[GraphSegment] = Field(default_factory=list, description="Line segments")
    functions: List[GraphFunction] = Field(default_factory=list, description="Plotted function curves")


# ==============================================================================
# 6. AST Mathematical Expression Validator
# ==============================================================================
ALLOWED_MATH_FUNCTIONS = {
    "sin", "cos", "tan", "sqrt", "abs", "exp", "log", "ln", "asin", "acos", "atan"
}
ALLOWED_MATH_CONSTANTS = {"pi", "e", "x"}


def validate_math_expression_safety(expr_str: str) -> None:
    """
    Validates that a mathematical expression string contains ONLY safe mathematical
    syntax and functions without executing arbitrary Python code. Raises ValueError if invalid.
    """
    if not expr_str or not expr_str.strip():
        raise ValueError("Mathematical expression cannot be empty.")

    clean_expr = expr_str.replace("^", "**").strip()
    try:
        tree = ast.parse(clean_expr, mode="eval")
    except SyntaxError as syn_err:
        raise ValueError(f"Syntax error in mathematical expression '{expr_str}': {syn_err}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Constant, ast.UnaryOp, ast.BinOp, ast.Load)):
            continue
        elif isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.BitXor, ast.USub, ast.UAdd)):
            continue
        elif isinstance(node, ast.Name):
            if node.id not in ALLOWED_MATH_CONSTANTS and node.id not in ALLOWED_MATH_FUNCTIONS:
                raise ValueError(f"Disallowed variable or constant '{node.id}' in expression '{expr_str}'. Allowed: {ALLOWED_MATH_CONSTANTS}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_MATH_FUNCTIONS:
                func_name = node.func.id if isinstance(node.func, ast.Name) else "complex expression"
                raise ValueError(f"Disallowed function call '{func_name}' in expression '{expr_str}'. Allowed functions: {ALLOWED_MATH_FUNCTIONS}")
            if len(node.args) != 1:
                raise ValueError(f"Function '{node.func.id}' in expression '{expr_str}' must take exactly 1 argument.")
        else:
            raise ValueError(f"Unsafe or disallowed syntax element '{type(node).__name__}' in mathematical expression '{expr_str}'.")


# ==============================================================================
# 7. Semantic Visual Specification Validator
# ==============================================================================
def validate_visual_spec_semantics(visual_type: str, spec_data: Dict[str, Any]) -> None:
    """
    Performs type-specific semantic validation on structured visual specifications
    WITHOUT rendering SVG. Raises ValueError if specification is invalid or malformed.
    """
    if not isinstance(spec_data, dict):
        raise ValueError(f"Visual spec data must be a dictionary, got {type(spec_data).__name__}.")

    if visual_type == "diagram":
        diag = DiagramData(**spec_data)
        node_ids: Set[str] = set()
        for node in diag.nodes:
            if node.id in node_ids:
                raise ValueError(f"Duplicate diagram node ID '{node.id}' found.")
            node_ids.add(node.id)

        for edge in diag.edges:
            if node_ids:
                if edge.from_node not in node_ids:
                    raise ValueError(f"Diagram edge references unknown source node '{edge.from_node}'.")
                if edge.to_node not in node_ids:
                    raise ValueError(f"Diagram edge references unknown target node '{edge.to_node}'.")

    elif visual_type == "chart":
        chart = ChartDataSpec(**spec_data)
        cat_len = len(chart.categories)
        for s in chart.series:
            if cat_len > 0 and len(s.values) > 0 and len(s.values) != cat_len:
                raise ValueError(f"Chart series '{s.name}' has {len(s.values)} values, but categories list has {cat_len} items.")

    elif visual_type == "geometry":
        geom = GeometryData(**spec_data)
        point_ids: Set[str] = set()
        for p in geom.points:
            if p.id in point_ids:
                raise ValueError(f"Duplicate geometry point ID '{p.id}' found.")
            point_ids.add(p.id)

        # Validate polygon vertex points if explicit points are supplied
        for poly in geom.polygons:
            if len(poly.points) < 3:
                raise ValueError(f"Polygon must have at least 3 vertices, got {len(poly.points)}.")
            if point_ids:
                for pt_id in poly.points:
                    if pt_id not in point_ids:
                        raise ValueError(f"Polygon references undefined point ID '{pt_id}'.")

        # Validate segments
        for seg in geom.segments:
            if seg.from_point == seg.to_point:
                raise ValueError(f"Geometry segment cannot have identical start and end point '{seg.from_point}'.")
            if point_ids:
                if seg.from_point not in point_ids:
                    raise ValueError(f"Segment references undefined start point '{seg.from_point}'.")
                if seg.to_point not in point_ids:
                    raise ValueError(f"Segment references undefined end point '{seg.to_point}'.")

        # Validate circles
        for circ in geom.circles:
            if circ.radius <= 0:
                raise ValueError(f"Circle radius must be strictly positive, got {circ.radius}.")
            if point_ids and circ.center not in point_ids:
                raise ValueError(f"Circle center references undefined point '{circ.center}'.")

        # Validate angles
        for ang in geom.angles:
            if point_ids:
                if ang.vertex not in point_ids or ang.p1 not in point_ids or ang.p2 not in point_ids:
                    raise ValueError(f"Angle at vertex '{ang.vertex}' references undefined point IDs.")

    elif visual_type == "circuit":
        circ = CircuitData(**spec_data)
        comp_ids: Set[str] = set()
        for comp in circ.components:
            if comp.id in comp_ids:
                raise ValueError(f"Duplicate circuit component ID '{comp.id}' found.")
            comp_ids.add(comp.id)

        junc_ids: Set[str] = set()
        for junc in circ.junctions:
            if junc.id in junc_ids or junc.id in comp_ids:
                raise ValueError(f"Duplicate circuit junction/component ID '{junc.id}' found.")
            junc_ids.add(junc.id)

        valid_nodes = comp_ids.union(junc_ids)
        for conn in circ.connections:
            if conn.from_comp == conn.to_comp:
                raise ValueError(f"Circuit connection cannot connect component '{conn.from_comp}' to itself.")
            if valid_nodes:
                if conn.from_comp not in valid_nodes:
                    raise ValueError(f"Circuit connection references undefined source component/junction '{conn.from_comp}'.")
                if conn.to_comp not in valid_nodes:
                    raise ValueError(f"Circuit connection references undefined target component/junction '{conn.to_comp}'.")

    elif visual_type == "graph":
        graph = GraphData(**spec_data)
        if len(graph.x_range) != 2 or graph.x_range[0] >= graph.x_range[1]:
            raise ValueError(f"Invalid graph x_range: x_min must be strictly less than x_max, got {graph.x_range}.")
        if len(graph.y_range) != 2 or graph.y_range[0] >= graph.y_range[1]:
            raise ValueError(f"Invalid graph y_range: y_min must be strictly less than y_max, got {graph.y_range}.")

        for fn in graph.functions:
            validate_math_expression_safety(fn.expression)

    else:
        raise ValueError(f"Unsupported visual type '{visual_type}'. Allowed types: {list(GeminiVisualType.__args__)}.")


# ==============================================================================
# ==============================================================================
# 8. Gemini-Facing Visual Specification Schema & Requirement Schema
# ==============================================================================
class GeminiVisualSpecSchema(BaseModel):
    """
    Unified structured visual specification schema exposed directly to Gemini
    during native response_schema generation. Allows Gemini to populate exact
    component, geometry, graph, diagram, and chart payloads.
    """
    # Circuit fields
    components: Optional[List[CircuitComponent]] = Field(None, description="List of circuit components (resistors, capacitors, batteries, meters, switches)")
    connections: Optional[List[CircuitConnection]] = Field(None, description="List of wire connections between component IDs")
    junctions: Optional[List[CircuitJunction]] = Field(None, description="List of circuit junctions/nodes")

    # Geometry fields
    points: Optional[List[GeometryPoint]] = Field(None, description="List of points with IDs and labels")
    segments: Optional[List[GeometrySegment]] = Field(None, description="List of line segments connecting points")
    polygons: Optional[List[GeometryPolygon]] = Field(None, description="List of polygons formed by point IDs")
    circles: Optional[List[GeometryCircle]] = Field(None, description="List of circles with center point and radius")
    angles: Optional[List[GeometryAngle]] = Field(None, description="List of angles at vertices")

    # Graph fields
    x_range: Optional[List[float]] = Field(None, description="[x_min, x_max] coordinate domain")
    y_range: Optional[List[float]] = Field(None, description="[y_min, y_max] coordinate range")
    grid: Optional[bool] = Field(True, description="Whether to show coordinate grid")
    x_axis_label: Optional[str] = Field(None, description="X-axis title")
    y_axis_label: Optional[str] = Field(None, description="Y-axis title")
    functions: Optional[List[GraphFunction]] = Field(None, description="List of mathematical functions to plot")

    # Diagram fields
    nodes: Optional[List[DiagramNodeData]] = Field(None, description="List of diagram nodes")
    edges: Optional[List[DiagramEdgeData]] = Field(None, description="List of directed edges")

    # Chart fields
    format: Optional[str] = Field("bar", description="Chart format: bar, line, pie")
    categories: Optional[List[str]] = Field(None, description="Category names")
    series: Optional[List[ChartSeriesData]] = Field(None, description="Data series")


class GeminiVisualRequirementSchema(BaseModel):
    """
    Structured Gemini visual requirement schema for generated questions.
    Attached as an optional field on each question item in complete paper generation.
    """
    required: bool = Field(False, description="Whether a visual illustration is genuinely required to solve the question")
    type: Optional[GeminiVisualType] = Field(None, description="Visual classification type: diagram, chart, geometry, circuit, graph")
    title: Optional[str] = Field(None, max_length=255, description="Title or header for the visual artifact")
    caption: Optional[str] = Field(None, description="Educational description or caption")
    spec: Optional[GeminiVisualSpecSchema] = Field(None, description="Structured semantic visual payload")

    @model_validator(mode="after")
    def validate_visual_payload(self) -> "GeminiVisualRequirementSchema":
        if not self.required:
            return self

        if not self.type:
            raise ValueError("visual.type is required when visual.required is True.")

        if self.spec is None:
            raise ValueError(f"visual.spec dictionary is required and cannot be empty when visual.required is True for type '{self.type}'.")

        spec_data = self.spec.model_dump(by_alias=True, exclude_none=True) if hasattr(self.spec, "model_dump") else self.spec
        if not isinstance(spec_data, dict) or not spec_data:
            raise ValueError(f"visual.spec dictionary is required and cannot be empty when visual.required is True for type '{self.type}'.")

        # Perform semantic validation
        validate_visual_spec_semantics(self.type, spec_data)
        return self


# ==============================================================================
# 9. Main Visual Required Specification (Internal / Legacy Compatibility)
# ==============================================================================
class VisualRequiredSpec(BaseModel):
    """
    Subject-agnostic visual specification structure used across internal services.
    """
    visual_required: bool = Field(False, description="Whether a visual diagram is required")
    visual_type: Optional[VisualType] = Field(None, description="Classification type of visual artifact")
    format: Optional[str] = Field(None, description="Format specifier e.g. flowchart, bar, line, pie, circuit")
    title: str = Field("Visual Diagram", description="Title or header for the visual artifact")
    caption: Optional[str] = Field(None, description="Educational description or caption")
    spec_data: Dict[str, Any] = Field(default_factory=dict, description="Structured visual data payload")
    raw_svg_code: Optional[str] = Field(None, description="Direct SVG XML string when visual_type == 'raw_svg'")

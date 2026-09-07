import ast
import html
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from app.schemas.visuals import (
    GraphData,
    GraphFunction,
    GraphPoint,
    GraphSegment,
)


class SafeExprEvaluator(ast.NodeVisitor):
    """
    AST-based safe evaluator for mathematical expressions in 'x'.
    Strictly forbids unsafe Python code, attribute access, imports, or general eval().
    """

    ALLOWED_FUNCTIONS = {
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "sqrt": math.sqrt,
        "abs": abs,
        "exp": math.exp,
        "log": math.log,
        "ln": math.log,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
    }

    ALLOWED_CONSTANTS = {
        "pi": math.pi,
        "e": math.e,
    }

    def __init__(self, x_val: float):
        self.x_val = x_val

    def visit_Expression(self, node: ast.Expression):
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    def visit_Name(self, node: ast.Name):
        name = node.id
        if name == "x":
            return self.x_val
        if name in self.ALLOWED_CONSTANTS:
            return self.ALLOWED_CONSTANTS[name]
        raise ValueError(f"Unsupported variable or constant: '{name}'")

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ValueError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right if right != 0 else float("nan")
        if isinstance(op, (ast.Pow, ast.BitXor)):
            return left ** right
        raise ValueError(f"Unsupported binary operator: {type(op)}")

    def visit_Call(self, node: ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are allowed")
        func_name = node.func.id
        if func_name not in self.ALLOWED_FUNCTIONS:
            raise ValueError(f"Unsupported math function: '{func_name}'")
        if len(node.args) != 1:
            raise ValueError(f"Function '{func_name}' expects exactly 1 argument")
        arg_val = self.visit(node.args[0])
        try:
            return self.ALLOWED_FUNCTIONS[func_name](arg_val)
        except (ValueError, OverflowError):
            return float("nan")

    def generic_visit(self, node):
        raise ValueError(f"Disallowed AST node: {type(node).__name__}")


class GraphBuilder:
    """
    Deterministic, subject-agnostic SVG rendering engine for 2D mathematical/scientific graphs.
    Generates self-contained, safe, scalable SVG strings for Cartesian coordinate axes,
    grid lines, numeric ticks, plotted points, line segments, and mathematical function curves.
    """

    @classmethod
    def eval_expression(cls, expr_str: str, x_val: float) -> Optional[float]:
        """
        Safely evaluates a mathematical expression string at a given x value using AST traversal.
        """
        clean_expr = expr_str.replace("^", "**").strip()
        try:
            tree = ast.parse(clean_expr, mode="eval")
            evaluator = SafeExprEvaluator(x_val)
            val = evaluator.visit(tree)
            if math.isnan(val) or math.isinf(val):
                return None
            return val
        except Exception:
            return None

    @classmethod
    def render(cls, spec: Any) -> str:
        """
        Main entry point for Graph SVG rendering.
        Accepts VisualSpec or raw dictionary payload.
        """
        title = getattr(spec, "title", None) or (spec.get("title") if isinstance(spec, dict) else "Graph Plot")
        caption = getattr(spec, "caption", None) or (spec.get("caption") if isinstance(spec, dict) else None)
        data_raw = getattr(spec, "data", None) or getattr(spec, "spec_data", None) or (spec.get("spec_data") or spec.get("data") if isinstance(spec, dict) else {})

        try:
            graph_data = GraphData(**data_raw) if isinstance(data_raw, dict) else data_raw
        except Exception:
            graph_data = GraphData()

        title_escaped = html.escape(str(title))
        caption_escaped = html.escape(str(caption)) if caption else None

        x_range = graph_data.x_range if len(graph_data.x_range) >= 2 else [-5.0, 5.0]
        y_range = graph_data.y_range if len(graph_data.y_range) >= 2 else [-5.0, 5.0]

        x_min, x_max = float(x_range[0]), float(x_range[1])
        y_min, y_max = float(y_range[0]), float(y_range[1])

        if x_min >= x_max:
            x_min, x_max = -5.0, 5.0
        if y_min >= y_max:
            y_min, y_max = -5.0, 5.0

        plot_width = 440.0
        plot_height = 300.0

        padding_left = 65.0
        padding_right = 35.0
        padding_top = 55.0
        padding_bottom = 50.0

        total_width = plot_width + padding_left + padding_right
        total_height = plot_height + padding_top + padding_bottom + (30.0 if caption else 0.0)

        # Mathematical (x, y) to SVG screen coordinates (X_svg, Y_svg)
        def transform(x: float, y: float) -> Tuple[float, float]:
            sx = padding_left + ((x - x_min) / (x_max - x_min)) * plot_width
            sy = padding_top + ((y_max - y) / (y_max - y_min)) * plot_height
            return sx, sy

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width:.1f} {total_height:.1f}" width="100%" height="{total_height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <defs>',
            '    <marker id="arrow_axis" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#1A202C"/>',
            '    </marker>',
            '  </defs>',
            f'  <text x="{total_width / 2.0:.1f}" y="35" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{title_escaped}</text>',
        ]

        # 1. Background Grid Lines
        if graph_data.grid:
            x_step = graph_data.x_step or cls._auto_step(x_min, x_max)
            y_step = graph_data.y_step or cls._auto_step(y_min, y_max)

            # X grid lines
            curr_x = math.ceil(x_min / x_step) * x_step
            while curr_x <= x_max:
                gx, _ = transform(curr_x, 0)
                svg_parts.append(
                    f'  <line x1="{gx:.1f}" y1="{padding_top:.1f}" x2="{gx:.1f}" y2="{padding_top + plot_height:.1f}" stroke="#EDF2F7" stroke-width="1.2"/>'
                )
                curr_x += x_step

            # Y grid lines
            curr_y = math.ceil(y_min / y_step) * y_step
            while curr_y <= y_max:
                _, gy = transform(0, curr_y)
                svg_parts.append(
                    f'  <line x1="{padding_left:.1f}" y1="{gy:.1f}" x2="{padding_left + plot_width:.1f}" y2="{gy:.1f}" stroke="#EDF2F7" stroke-width="1.2"/>'
                )
                curr_y += y_step

        # 2. Render Main Coordinate Axes
        origin_x, origin_y = transform(0.0, 0.0)

        # X-axis line (y = 0)
        axis_y = min(max(origin_y, padding_top), padding_top + plot_height)
        svg_parts.append(
            f'  <line x1="{padding_left - 10.0:.1f}" y1="{axis_y:.1f}" x2="{padding_left + plot_width + 15.0:.1f}" y2="{axis_y:.1f}" stroke="#1A202C" stroke-width="2" marker-end="url(#arrow_axis)"/>'
        )

        # Y-axis line (x = 0)
        axis_x = min(max(origin_x, padding_left), padding_left + plot_width)
        svg_parts.append(
            f'  <line x1="{axis_x:.1f}" y1="{padding_top + plot_height + 10.0:.1f}" x2="{axis_x:.1f}" y2="{padding_top - 15.0:.1f}" stroke="#1A202C" stroke-width="2" marker-end="url(#arrow_axis)"/>'
        )

        # Axis Name Labels
        x_label_escaped = html.escape(graph_data.x_axis_label)
        y_label_escaped = html.escape(graph_data.y_axis_label)
        svg_parts.append(
            f'  <text x="{padding_left + plot_width + 25.0:.1f}" y="{axis_y + 4.0:.1f}" font-size="14" font-weight="bold" fill="#1A202C">{x_label_escaped}</text>'
        )
        svg_parts.append(
            f'  <text x="{axis_x:.1f}" y="{padding_top - 22.0:.1f}" font-size="14" font-weight="bold" text-anchor="middle" fill="#1A202C">{y_label_escaped}</text>'
        )

        # 3. Numeric Ticks & Tick Labels
        x_step = graph_data.x_step or cls._auto_step(x_min, x_max)
        y_step = graph_data.y_step or cls._auto_step(y_min, y_max)

        # X Ticks
        curr_x = math.ceil(x_min / x_step) * x_step
        while curr_x <= x_max:
            if abs(curr_x) > 1e-6:
                tx, _ = transform(curr_x, 0)
                svg_parts.append(
                    f'  <line x1="{tx:.1f}" y1="{axis_y - 4.0:.1f}" x2="{tx:.1f}" y2="{axis_y + 4.0:.1f}" stroke="#1A202C" stroke-width="1.5"/>'
                )
                fmt_lbl = f"{curr_x:.1f}".rstrip("0").rstrip(".") if abs(curr_x - round(curr_x)) < 1e-4 else f"{curr_x:.1f}"
                svg_parts.append(
                    f'  <text x="{tx:.1f}" y="{axis_y + 18.0:.1f}" font-size="11" fill="#4A5568" text-anchor="middle">{fmt_lbl}</text>'
                )
            curr_x += x_step

        # Y Ticks
        curr_y = math.ceil(y_min / y_step) * y_step
        while curr_y <= y_max:
            if abs(curr_y) > 1e-6:
                _, ty = transform(0, curr_y)
                svg_parts.append(
                    f'  <line x1="{axis_x - 4.0:.1f}" y1="{ty:.1f}" x2="{axis_x + 4.0:.1f}" y2="{ty:.1f}" stroke="#1A202C" stroke-width="1.5"/>'
                )
                fmt_lbl = f"{curr_y:.1f}".rstrip("0").rstrip(".") if abs(curr_y - round(curr_y)) < 1e-4 else f"{curr_y:.1f}"
                svg_parts.append(
                    f'  <text x="{axis_x - 8.0:.1f}" y="{ty + 4.0:.1f}" font-size="11" fill="#4A5568" text-anchor="end">{fmt_lbl}</text>'
                )
            curr_y += y_step

        # Origin '0' Label
        if x_min <= 0 <= x_max and y_min <= 0 <= y_max:
            svg_parts.append(
                f'  <text x="{origin_x - 8.0:.1f}" y="{origin_y + 16.0:.1f}" font-size="11" font-weight="bold" fill="#718096" text-anchor="end">0</text>'
            )

        # 4. Render Function Curves
        for fn in graph_data.functions:
            samples = max(20, min(500, fn.samples))
            color = fn.color or "#3182CE"
            stroke_width = fn.stroke_width or 2.5
            path_segments = []

            for i in range(samples + 1):
                cur_x_val = x_min + (i / samples) * (x_max - x_min)
                cur_y_val = cls.eval_expression(fn.expression, cur_x_val)

                if cur_y_val is not None and (y_min - (y_max - y_min)) <= cur_y_val <= (y_max + (y_max - y_min)):
                    sx, sy = transform(cur_x_val, cur_y_val)
                    cmd = "M" if not path_segments else "L"
                    path_segments.append(f"{cmd} {sx:.1f} {sy:.1f}")

            if path_segments:
                d_attr = " ".join(path_segments)
                svg_parts.append(
                    f'  <path d="{d_attr}" fill="none" stroke="{color}" stroke-width="{stroke_width:.1f}" stroke-linecap="round"/>'
                )

            if fn.label:
                lbl_escaped = html.escape(fn.label)
                # Render curve legend label
                mid_x_val = (x_min + x_max) / 2.0
                mid_y_val = cls.eval_expression(fn.expression, mid_x_val)
                if mid_y_val is not None:
                    lx, ly = transform(mid_x_val, mid_y_val)
                    svg_parts.append(
                        f'  <text x="{lx + 8.0:.1f}" y="{ly - 10.0:.1f}" font-size="12" font-weight="bold" fill="{color}">{lbl_escaped}</text>'
                    )

        # 5. Render Line Segments
        for seg in graph_data.segments:
            sx1, sy1 = transform(seg.x1, seg.y1)
            sx2, sy2 = transform(seg.x2, seg.y2)
            color = seg.color or "#3182CE"
            dash_attr = ' stroke-dasharray="6,4"' if seg.style == "dashed" else ""
            svg_parts.append(
                f'  <line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" stroke="{color}" stroke-width="2.5"{dash_attr}/>'
            )
            if seg.label:
                mx = (sx1 + sx2) / 2.0
                my = (sy1 + sy2) / 2.0
                lbl_escaped = html.escape(seg.label)
                svg_parts.append(
                    f'  <text x="{mx:.1f}" y="{my - 8.0:.1f}" font-size="11" font-weight="bold" fill="{color}" text-anchor="middle">{lbl_escaped}</text>'
                )

        # 6. Render Plotted Points
        for pt in graph_data.points:
            px, py = transform(pt.x, pt.y)
            color = pt.color or "#E53E3E"
            if pt.show_point:
                svg_parts.append(
                    f'  <circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{color}" stroke="#FFFFFF" stroke-width="1.5"/>'
                )
            if pt.label:
                lbl_escaped = html.escape(pt.label)
                svg_parts.append(
                    f'  <text x="{px:.1f}" y="{py - 10.0:.1f}" font-size="12" font-weight="bold" fill="#1A202C" text-anchor="middle">{lbl_escaped}</text>'
                )

        if caption_escaped:
            svg_parts.append(
                f'  <text x="{total_width / 2.0:.1f}" y="{total_height - 15.0:.1f}" font-size="12" font-style="italic" text-anchor="middle" fill="#718096">{caption_escaped}</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)

    @classmethod
    def _auto_step(cls, v_min: float, v_max: float) -> float:
        rng = v_max - v_min
        if rng <= 0:
            return 1.0
        raw_step = rng / 8.0
        magnitude = 10 ** math.floor(math.log10(raw_step))
        residual = raw_step / magnitude
        if residual > 5:
            return 10 * magnitude
        if residual > 2:
            return 5 * magnitude
        return 2 * magnitude if residual > 1 else magnitude

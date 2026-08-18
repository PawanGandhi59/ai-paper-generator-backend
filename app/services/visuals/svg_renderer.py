import html
import math
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field


from pydantic import BaseModel, Field, field_validator


class DiagramNode(BaseModel):
    id: str = Field(..., description="Node unique identifier e.g. start, step1")
    label: str = Field(..., description="Text label inside node")
    shape: Literal["rectangle", "rounded", "diamond", "circle"] = Field("rectangle", description="Node shape")

    @field_validator("shape", mode="before")
    @classmethod
    def validate_shape(cls, v: Any) -> str:
        if v not in ["rectangle", "rounded", "diamond", "circle"]:
            return "rectangle"
        return str(v)


class DiagramEdge(BaseModel):
    from_node: str = Field(..., alias="from", description="Origin node ID")
    to_node: str = Field(..., alias="to", description="Target node ID")
    label: Optional[str] = Field("", description="Optional text label on edge arrow")

    model_config = {"populate_by_name": True}


class DiagramData(BaseModel):
    nodes: List[DiagramNode] = Field(default_factory=list, description="Nodes in the diagram")
    edges: List[DiagramEdge] = Field(default_factory=list, description="Edges/connections between nodes")


class ChartData(BaseModel):
    x_label: Optional[str] = Field("", description="Label for X axis")
    y_label: Optional[str] = Field("", description="Label for Y axis")
    categories: List[str] = Field(default_factory=list, description="Category names or X data labels")
    values: List[float] = Field(default_factory=list, description="Numerical values matching categories")

    @field_validator("values", mode="before")
    @classmethod
    def validate_values(cls, vals: Any) -> List[float]:
        if not isinstance(vals, list):
            return []
        cleaned = []
        for v in vals:
            try:
                val = float(v)
                if math.isnan(val) or math.isinf(val):
                    val = 0.0
                cleaned.append(val)
            except (ValueError, TypeError):
                cleaned.append(0.0)
        return cleaned


class VisualSpec(BaseModel):
    id: str = Field(..., description="Unique visual identifier")
    type: Literal["diagram", "chart"] = Field(..., description="Visual classification: diagram or chart")
    format: str = Field("flowchart", description="Format identifier: flowchart, tree, classification, sequence, bar, line, pie")
    title: str = Field(..., description="Title of the visual")
    caption: Optional[str] = Field(None, description="Caption or explanation")
    data: Dict[str, Any] = Field(default_factory=dict, description="DiagramData or ChartData dictionary")


def wrap_text_lines(text: str, max_chars_per_line: int) -> List[str]:
    """
    Deterministic word-wrapping for SVG text.
    Splits long labels into multiple lines without breaking words unnecessarily.
    """
    if not text:
        return [""]
    
    words = text.strip().split()
    if not words:
        return [""]

    lines = []
    current_words = []
    current_len = 0

    for word in words:
        w_len = len(word)
        if w_len > max_chars_per_line:
            if current_words:
                lines.append(" ".join(current_words))
                current_words = []
                current_len = 0
            for i in range(0, w_len, max_chars_per_line):
                lines.append(word[i:i + max_chars_per_line])
            continue

        space_needed = 1 if current_words else 0
        if current_len + w_len + space_needed <= max_chars_per_line:
            current_words.append(word)
            current_len += w_len + space_needed
        else:
            lines.append(" ".join(current_words))
            current_words = [word]
            current_len = w_len

    if current_words:
        lines.append(" ".join(current_words))

    return lines if lines else [""]


def compute_boundary_intersection(
    cx1: float, cy1: float, w1: float, h1: float, shape1: str,
    cx2: float, cy2: float, w2: float, h2: float, shape2: str
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Calculate exact perimeter intersection points between node 1 and node 2
    based on shape geometry (rectangle, rounded, circle, diamond).
    """
    def _intersect_node(cx: float, cy: float, w: float, h: float, shape: str, target_x: float, target_y: float) -> Tuple[float, float]:
        dx = target_x - cx
        dy = target_y - cy

        if dx == 0.0 and dy == 0.0:
            return (cx, cy)

        hw = w / 2.0
        hh = h / 2.0

        if shape == "circle":
            angle = math.atan2(dy, dx)
            return (cx + hw * math.cos(angle), cy + hh * math.sin(angle))
        elif shape == "diamond":
            t = 1.0 / (abs(dx / hw) + abs(dy / hh))
            return (cx + t * dx, cy + t * dy)
        else:  # rectangle or rounded
            t_x = abs(hw / dx) if dx != 0.0 else float("inf")
            t_y = abs(hh / dy) if dy != 0.0 else float("inf")
            t = min(t_x, t_y)
            return (cx + t * dx, cy + t * dy)

    p1 = _intersect_node(cx1, cy1, w1, h1, shape1, cx2, cy2)
    p2 = _intersect_node(cx2, cy2, w2, h2, shape2, cx1, cy1)
    return p1, p2




class SVGRenderer:
    """
    Pure Python SVG Renderer for validated educational visual specifications.
    Generates safe, clean, deterministic SVG strings without browser automation or external dependencies.
    Escapes all text to prevent XSS / script injection.
    """

    COLOR_PALETTE = [
        "#3182CE", "#38A169", "#DD6B20", "#805AD5", "#E53E3E",
        "#319795", "#D69E2E", "#4C51BF", "#B83280", "#2B6CB0"
    ]

    @classmethod
    def render(cls, spec: Union[VisualSpec, Dict[str, Any]]) -> str:
        if isinstance(spec, dict):
            spec = VisualSpec(**spec)

        v_type = spec.type

        if v_type == "diagram":
            return cls._render_diagram(spec)
        elif v_type == "chart":
            return cls._render_chart(spec)
        else:
            raise ValueError(f"Unsupported visual type for SVG rendering: {v_type}")

    @classmethod
    def _render_diagram(cls, spec: VisualSpec) -> str:
        data_raw = spec.data or {}
        nodes_raw = data_raw.get("nodes", [])
        edges_raw = data_raw.get("edges", [])

        nodes = []
        for n in nodes_raw:
            try:
                nodes.append(DiagramNode(**n) if isinstance(n, dict) else n)
            except Exception:
                continue

        edges = []
        for e in edges_raw:
            try:
                edges.append(DiagramEdge(**e) if isinstance(e, dict) else e)
            except Exception:
                continue

        title_escaped = html.escape(spec.title or "Diagram")

        if not nodes:
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100" width="100%" height="100">'
                f'<rect width="400" height="100" fill="#F7FAFC" rx="8"/>'
                f'<text x="200" y="55" font-size="14" font-family="sans-serif" text-anchor="middle" fill="#4A5568">{title_escaped}</text>'
                f'</svg>'
            )

        node_map = {n.id: n for n in nodes}

        # Calculate adaptive node dimensions & line wrapping for each node
        node_layout_info: Dict[str, Dict[str, Any]] = {}
        for n in nodes:
            shape = n.shape
            if shape == "diamond":
                max_chars = 14
            elif shape == "circle":
                max_chars = 16
            else:
                max_chars = 20

            lines = wrap_text_lines(n.label or n.id, max_chars_per_line=max_chars)
            num_lines = len(lines)
            max_line_len = max(len(l) for l in lines) if lines else 1

            if shape == "diamond":
                w = max(180.0, min(300.0, max_line_len * 11.0 + 60.0))
                h = max(110.0, num_lines * 22.0 + 50.0)
            elif shape == "circle":
                w = max(140.0, max_line_len * 10.0 + 50.0)
                h = max(140.0, num_lines * 22.0 + 50.0)
                side = max(w, h)
                w, h = side, side
            else:  # rectangle or rounded
                w = max(160.0, min(260.0, max_line_len * 8.5 + 40.0))
                h = max(55.0, num_lines * 18.0 + 24.0)

            node_layout_info[n.id] = {
                "width": w,
                "height": h,
                "lines": lines,
            }

        # Build graph topological layers
        in_degree = {n.id: 0 for n in nodes}
        adj = {n.id: [] for n in nodes}

        for e in edges:
            if e.from_node in adj and e.to_node in in_degree:
                adj[e.from_node].append(e.to_node)
                in_degree[e.to_node] += 1

        layers: List[List[str]] = []
        visited = set()
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        if not queue and nodes:
            queue = [nodes[0].id]

        current_layer = queue
        while current_layer:
            layers.append(current_layer)
            visited.update(current_layer)
            next_layer = []
            for nid in current_layer:
                for neighbor in adj.get(nid, []):
                    if neighbor not in visited and neighbor not in next_layer:
                        next_layer.append(neighbor)
            current_layer = next_layer

        unvisited = [n.id for n in nodes if n.id not in visited]
        if unvisited:
            layers.append(unvisited)

        # Spacing parameters
        x_gap = 50.0
        y_gap = 80.0

        layer_heights = []
        for layer in layers:
            lh = max(node_layout_info[nid]["height"] for nid in layer) if layer else 60.0
            layer_heights.append(lh)

        layer_widths = []
        for layer in layers:
            lw = sum(node_layout_info[nid]["width"] for nid in layer) + (len(layer) - 1) * x_gap if layer else 200.0
            layer_widths.append(lw)

        max_layer_width = max(layer_widths) if layer_widths else 600.0
        total_width = max(640.0, max_layer_width + 100.0)

        total_nodes_height = sum(layer_heights) + (len(layers) - 1) * y_gap if layers else 100.0
        total_height = max(380.0, total_nodes_height + 140.0)

        # Compute position coordinates
        node_positions: Dict[str, Dict[str, float]] = {}
        y_cursor = 80.0

        for l_idx, layer in enumerate(layers):
            layer_w = layer_widths[l_idx]
            lh = layer_heights[l_idx]
            start_x = (total_width - layer_w) / 2.0

            x_cursor = start_x
            for nid in layer:
                nw = node_layout_info[nid]["width"]
                nh = node_layout_info[nid]["height"]

                ny = y_cursor + (lh - nh) / 2.0
                nx = x_cursor

                node_positions[nid] = {
                    "x": nx,
                    "y": ny,
                    "w": nw,
                    "h": nh,
                    "cx": nx + nw / 2.0,
                    "cy": ny + nh / 2.0,
                }
                x_cursor += nw + x_gap

            y_cursor += lh + y_gap

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width:.1f} {total_height:.1f}" width="100%" height="{total_height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <defs>',
            '    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#4A5568"/>',
            '    </marker>',
            '  </defs>',
            f'  <text x="{total_width / 2.0:.1f}" y="38" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{title_escaped}</text>',
        ]

        # Render Edges with Exact Boundary Intersection Routing & Adaptive Label Cards
        for e in edges:
            p_from = node_positions.get(e.from_node)
            p_to = node_positions.get(e.to_node)
            if not p_from or not p_to:
                continue

            node_from = node_map[e.from_node]
            node_to = node_map[e.to_node]

            (x1, y1), (x2, y2) = compute_boundary_intersection(
                p_from["cx"], p_from["cy"], p_from["w"], p_from["h"], node_from.shape,
                p_to["cx"], p_to["cy"], p_to["w"], p_to["h"], node_to.shape
            )

            svg_parts.append(
                f'  <path d="M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}" stroke="#4A5568" stroke-width="2" marker-end="url(#arrow)" fill="none" />'
            )

            if e.label and e.label.strip():
                mx = (x1 + x2) / 2.0
                my = (y1 + y2) / 2.0
                lbl_text = e.label.strip()

                edge_lines = wrap_text_lines(lbl_text, max_chars_per_line=22)
                num_edge_lines = len(edge_lines)
                max_e_len = max(len(l) for l in edge_lines) if edge_lines else 1

                card_w = max(45.0, min(200.0, max_e_len * 7.5 + 18.0))
                card_h = max(18.0, num_edge_lines * 14.0 + 6.0)

                card_x = mx - card_w / 2.0
                card_y = my - card_h / 2.0

                svg_parts.append(
                    f'  <rect x="{card_x:.1f}" y="{card_y:.1f}" width="{card_w:.1f}" height="{card_h:.1f}" fill="#FFFFFF" fill-opacity="0.94" stroke="#CBD5E0" stroke-width="1" rx="4"/>'
                )

                first_lbl_y = my - (num_edge_lines * 14.0 / 2.0) + (14.0 * 0.75)
                svg_parts.append(
                    f'  <text x="{mx:.1f}" y="{first_lbl_y:.1f}" font-size="11" font-weight="500" fill="#4A5568" text-anchor="middle">'
                )
                for el_idx, el_line in enumerate(edge_lines):
                    el_escaped = html.escape(el_line)
                    if el_idx == 0:
                        svg_parts.append(f'    <tspan x="{mx:.1f}">{el_escaped}</tspan>')
                    else:
                        svg_parts.append(f'    <tspan x="{mx:.1f}" dy="14.0">{el_escaped}</tspan>')
                svg_parts.append('  </text>')


        # Render Nodes with Multiline <tspan> Text Wrapping
        for nid, pos in node_positions.items():
            node = node_map[nid]
            nx, ny = pos["x"], pos["y"]
            nw, nh = pos["w"], pos["h"]
            ncx, ncy = pos["cx"], pos["cy"]
            lines = node_layout_info[nid]["lines"]
            shape = node.shape

            if shape == "rounded":
                svg_parts.append(
                    f'  <rect x="{nx:.1f}" y="{ny:.1f}" width="{nw:.1f}" height="{nh:.1f}" rx="20" ry="20" fill="#EDF2F7" stroke="#4A5568" stroke-width="2"/>'
                )
            elif shape == "circle":
                rx = nw / 2.0
                ry = nh / 2.0
                svg_parts.append(
                    f'  <ellipse cx="{ncx:.1f}" cy="{ncy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="#E6FFFA" stroke="#319795" stroke-width="2"/>'
                )
            elif shape == "diamond":
                p1 = f"{ncx:.1f},{ny:.1f}"
                p2 = f"{nx + nw:.1f},{ncy:.1f}"
                p3 = f"{ncx:.1f},{ny + nh:.1f}"
                p4 = f"{nx:.1f},{ncy:.1f}"
                svg_parts.append(
                    f'  <polygon points="{p1} {p2} {p3} {p4}" fill="#FEFCBF" stroke="#D69E2E" stroke-width="2"/>'
                )
            else:  # rectangle
                svg_parts.append(
                    f'  <rect x="{nx:.1f}" y="{ny:.1f}" width="{nw:.1f}" height="{nh:.1f}" rx="6" ry="6" fill="#EBF8FF" stroke="#3182CE" stroke-width="2"/>'
                )

            # Draw Vertically Centered Multiline <tspan> Text
            num_lines = len(lines)
            line_height = 16.0
            total_text_h = num_lines * line_height
            first_line_y = ncy - (total_text_h / 2.0) + (line_height * 0.75)

            svg_parts.append(
                f'  <text x="{ncx:.1f}" y="{first_line_y:.1f}" font-size="13" font-weight="500" fill="#2D3748" text-anchor="middle">'
            )
            for l_idx, line in enumerate(lines):
                line_escaped = html.escape(line)
                if l_idx == 0:
                    svg_parts.append(f'    <tspan x="{ncx:.1f}">{line_escaped}</tspan>')
                else:
                    svg_parts.append(f'    <tspan x="{ncx:.1f}" dy="{line_height:.1f}">{line_escaped}</tspan>')
            svg_parts.append('  </text>')

        if spec.caption:
            caption_escaped = html.escape(spec.caption)
            svg_parts.append(
                f'  <text x="{total_width / 2.0:.1f}" y="{total_height - 20.0:.1f}" font-size="12" font-style="italic" text-anchor="middle" fill="#718096">{caption_escaped}</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)


    @classmethod
    def _render_chart(cls, spec: VisualSpec) -> str:
        data_raw = spec.data or {}
        try:
            chart_data = ChartData(**data_raw) if isinstance(data_raw, dict) else data_raw
        except Exception:
            chart_data = ChartData()

        categories = chart_data.categories or []
        values = chart_data.values or []
        fmt = spec.format
        title_escaped = html.escape(spec.title or "Chart")

        if not categories or not values or len(categories) != len(values):
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100" width="100%" height="100">'
                f'<rect width="400" height="100" fill="#F7FAFC" rx="8"/>'
                f'<text x="200" y="55" font-size="14" font-family="sans-serif" text-anchor="middle" fill="#4A5568">{title_escaped}</text>'
                f'</svg>'
            )

        if fmt == "pie":
            return cls._render_pie_chart(spec, categories, values)
        elif fmt == "line":
            return cls._render_line_chart(spec, chart_data, categories, values)
        else:  # bar
            return cls._render_bar_chart(spec, chart_data, categories, values)

    @classmethod
    def _render_bar_chart(cls, spec: VisualSpec, chart_data: ChartData, categories: List[str], values: List[float]) -> str:
        width = 660.0
        height = 430.0
        margin_top = 75.0
        margin_bottom = 75.0
        margin_left = 75.0
        margin_right = 45.0

        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        min_val = min(values) if values else 0.0
        max_val = max(values) if values else 1.0

        if min_val > 0:
            min_val = 0.0
        if max_val <= min_val:
            max_val = min_val + 1.0

        val_range = max_val - min_val
        baseline_y = margin_top + plot_h - ((0.0 - min_val) / val_range) * plot_h

        n = len(categories)
        bar_gap = 18.0
        bar_w = max(12.0, (plot_w - (n + 1) * bar_gap) / float(n))

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" width="100%" height="{height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            f'  <text x="{width / 2.0:.1f}" y="38" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{html.escape(spec.title)}</text>',
            f'  <line x1="{margin_left:.1f}" y1="{baseline_y:.1f}" x2="{margin_left + plot_w:.1f}" y2="{baseline_y:.1f}" stroke="#A0AEC0" stroke-width="2"/>',
            f'  <line x1="{margin_left:.1f}" y1="{margin_top:.1f}" x2="{margin_left:.1f}" y2="{margin_top + plot_h:.1f}" stroke="#CBD5E0" stroke-width="2"/>',
        ]

        # Y Axis Ticks
        num_ticks = 5
        for i in range(num_ticks + 1):
            val_tick = min_val + (val_range / float(num_ticks)) * i
            y_pos = margin_top + plot_h - ((val_tick - min_val) / val_range) * plot_h
            svg_parts.append(
                f'  <line x1="{margin_left - 5.0:.1f}" y1="{y_pos:.1f}" x2="{margin_left:.1f}" y2="{y_pos:.1f}" stroke="#A0AEC0" stroke-width="1"/>'
            )
            svg_parts.append(
                f'  <line x1="{margin_left:.1f}" y1="{y_pos:.1f}" x2="{margin_left + plot_w:.1f}" y2="{y_pos:.1f}" stroke="#EDF2F7" stroke-width="1"/>'
            )
            svg_parts.append(
                f'  <text x="{margin_left - 10.0:.1f}" y="{y_pos + 4.0:.1f}" font-size="11" fill="#718096" text-anchor="end">{val_tick:.1f}</text>'
            )

        # Draw Bars
        for idx, (cat, val) in enumerate(zip(categories, values)):
            bx = margin_left + bar_gap + idx * (bar_w + bar_gap)
            val_y = margin_top + plot_h - ((val - min_val) / val_range) * plot_h

            if val >= 0:
                by = val_y
                bh = baseline_y - val_y
                val_lbl_y = by - 6.0
            else:
                by = baseline_y
                bh = val_y - baseline_y
                val_lbl_y = by + bh + 14.0

            color = cls.COLOR_PALETTE[idx % len(cls.COLOR_PALETTE)]

            svg_parts.append(
                f'  <rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{max(2.0, bh):.1f}" fill="{color}" rx="4"/>'
            )
            val_str = f"{val:.2f}".rstrip('0').rstrip('.') if isinstance(val, float) else str(val)
            svg_parts.append(
                f'  <text x="{bx + bar_w / 2.0:.1f}" y="{val_lbl_y:.1f}" font-size="11" font-weight="bold" fill="#2D3748" text-anchor="middle">{val_str}</text>'
            )

            cat_escaped = html.escape(str(cat))
            if len(cat_escaped) > 8 or n > 6:
                cat_y = margin_top + plot_h + 18.0
                svg_parts.append(
                    f'  <text x="{bx + bar_w / 2.0:.1f}" y="{cat_y:.1f}" font-size="11" fill="#4A5568" text-anchor="end" transform="rotate(-35 {bx + bar_w / 2.0:.1f} {cat_y:.1f})">{cat_escaped}</text>'
                )
            else:
                cat_y = margin_top + plot_h + 20.0
                svg_parts.append(
                    f'  <text x="{bx + bar_w / 2.0:.1f}" y="{cat_y:.1f}" font-size="11" fill="#4A5568" text-anchor="middle">{cat_escaped}</text>'
                )

        if chart_data.x_label:
            svg_parts.append(
                f'  <text x="{margin_left + plot_w / 2.0:.1f}" y="{height - 12.0:.1f}" font-size="13" font-weight="500" fill="#4A5568" text-anchor="middle">{html.escape(chart_data.x_label)}</text>'
            )

        if chart_data.y_label:
            svg_parts.append(
                f'  <text x="20.0" y="{margin_top + plot_h / 2.0:.1f}" font-size="13" font-weight="500" fill="#4A5568" text-anchor="middle" transform="rotate(-90 20.0 {margin_top + plot_h / 2.0:.1f})">{html.escape(chart_data.y_label)}</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)

    @classmethod
    def _render_line_chart(cls, spec: VisualSpec, chart_data: ChartData, categories: List[str], values: List[float]) -> str:
        width = 660.0
        height = 430.0
        margin_top = 75.0
        margin_bottom = 75.0
        margin_left = 75.0
        margin_right = 45.0

        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        min_val = min(values) if values else 0.0
        max_val = max(values) if values else 1.0

        if min_val > 0:
            min_val = 0.0
        if max_val <= min_val:
            max_val = min_val + 1.0

        val_range = max_val - min_val
        n = len(categories)
        x_step = plot_w / (n - 1) if n > 1 else plot_w / 2.0

        points = []
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" width="100%" height="{height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            f'  <text x="{width / 2.0:.1f}" y="38" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{html.escape(spec.title)}</text>',
            f'  <line x1="{margin_left:.1f}" y1="{margin_top + plot_h:.1f}" x2="{margin_left + plot_w:.1f}" y2="{margin_top + plot_h:.1f}" stroke="#CBD5E0" stroke-width="2"/>',
            f'  <line x1="{margin_left:.1f}" y1="{margin_top:.1f}" x2="{margin_left:.1f}" y2="{margin_top + plot_h:.1f}" stroke="#CBD5E0" stroke-width="2"/>',
        ]

        # Y Ticks
        for i in range(6):
            val_tick = min_val + (val_range / 5.0) * i
            y_pos = margin_top + plot_h - ((val_tick - min_val) / val_range) * plot_h
            svg_parts.append(
                f'  <line x1="{margin_left:.1f}" y1="{y_pos:.1f}" x2="{margin_left + plot_w:.1f}" y2="{y_pos:.1f}" stroke="#EDF2F7" stroke-width="1"/>'
            )
            svg_parts.append(
                f'  <text x="{margin_left - 10.0:.1f}" y="{y_pos + 4.0:.1f}" font-size="11" fill="#718096" text-anchor="end">{val_tick:.1f}</text>'
            )

        for idx, (cat, val) in enumerate(zip(categories, values)):
            px = margin_left + (idx * x_step if n > 1 else plot_w / 2.0)
            py = margin_top + plot_h - ((val - min_val) / val_range) * plot_h
            points.append((px, py))
            cat_escaped = html.escape(str(cat))
            svg_parts.append(
                f'  <text x="{px:.1f}" y="{margin_top + plot_h + 20.0:.1f}" font-size="11" fill="#4A5568" text-anchor="middle">{cat_escaped}</text>'
            )

        pts_str = " ".join([f"{px:.1f},{py:.1f}" for px, py in points])
        svg_parts.append(
            f'  <polyline points="{pts_str}" fill="none" stroke="#3182CE" stroke-width="3"/>'
        )

        for (px, py), val in zip(points, values):
            val_str = f"{val:.2f}".rstrip('0').rstrip('.') if isinstance(val, float) else str(val)
            svg_parts.append(
                f'  <circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="#3182CE" stroke="#FFFFFF" stroke-width="2"/>'
            )
            svg_parts.append(
                f'  <text x="{px:.1f}" y="{py - 10.0:.1f}" font-size="11" font-weight="bold" fill="#2D3748" text-anchor="middle">{val_str}</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)

    @classmethod
    def _render_pie_chart(cls, spec: VisualSpec, categories: List[str], values: List[float]) -> str:
        width = 660.0
        height = 420.0
        cx = 240.0
        cy = 220.0
        r = 130.0

        pos_values = [max(0.0, float(v)) for v in values]
        total = sum(pos_values)

        title_escaped = html.escape(spec.title or "Pie Chart")

        if total <= 0:
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100" width="100%" height="100">'
                f'<rect width="400" height="100" fill="#F7FAFC" rx="8"/>'
                f'<text x="200" y="55" font-size="14" font-family="sans-serif" text-anchor="middle" fill="#4A5568">{title_escaped}</text>'
                f'</svg>'
            )

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" width="100%" height="{height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            f'  <text x="{width / 2.0:.1f}" y="38" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{title_escaped}</text>',
        ]

        current_angle = 0.0
        legend_x = 440.0
        legend_y = 90.0

        for idx, (cat, val) in enumerate(zip(categories, pos_values)):
            pct = val / total
            slice_angle = pct * 2.0 * math.pi
            start_angle = current_angle
            end_angle = current_angle + slice_angle
            current_angle = end_angle

            x1 = cx + r * math.cos(start_angle)
            y1 = cy + r * math.sin(start_angle)
            x2 = cx + r * math.cos(end_angle)
            y2 = cy + r * math.sin(end_angle)

            large_arc = 1 if slice_angle > math.pi else 0
            color = cls.COLOR_PALETTE[idx % len(cls.COLOR_PALETTE)]

            svg_parts.append(
                f'  <path d="M {cx:.1f} {cy:.1f} L {x1:.1f} {y1:.1f} A {r:.1f} {r:.1f} 0 {large_arc} 1 {x2:.1f} {y2:.1f} Z" fill="{color}" stroke="#FFFFFF" stroke-width="2"/>'
            )

            ly = legend_y + idx * 28.0
            val_str = f"{val:.2f}".rstrip('0').rstrip('.') if isinstance(val, float) else str(val)
            cat_escaped = html.escape(str(cat))
            svg_parts.append(
                f'  <rect x="{legend_x:.1f}" y="{ly:.1f}" width="14" height="14" fill="{color}" rx="3"/>'
            )
            svg_parts.append(
                f'  <text x="{legend_x + 22.0:.1f}" y="{ly + 12.0:.1f}" font-size="12" fill="#2D3748">{cat_escaped}: {val_str} ({pct*100.0:.1f}%)</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)


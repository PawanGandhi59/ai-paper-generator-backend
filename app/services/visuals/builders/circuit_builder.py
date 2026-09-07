import html
import math
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel

from app.schemas.visuals import (
    CircuitComponent,
    CircuitConnection,
    CircuitData,
    CircuitJunction,
)


class CircuitBuilder:
    """
    Deterministic, subject-agnostic SVG rendering engine for electrical circuits.
    Generates self-contained, safe, scalable SVG strings for schematic circuit diagrams
    including batteries, resistors, capacitors, switches, lamps, diodes, ammeters,
    voltmeters, inductors, grounds, wires, junctions, and labels.
    """

    @classmethod
    def render(cls, spec: Any) -> str:
        """
        Main entry point for Circuit SVG rendering.
        Accepts VisualSpec or raw dictionary payload.
        """
        title = getattr(spec, "title", None) or (spec.get("title") if isinstance(spec, dict) else "Circuit Diagram")
        caption = getattr(spec, "caption", None) or (spec.get("caption") if isinstance(spec, dict) else None)
        data_raw = getattr(spec, "data", None) or getattr(spec, "spec_data", None) or (spec.get("spec_data") or spec.get("data") if isinstance(spec, dict) else {})

        try:
            circuit_data = CircuitData(**data_raw) if isinstance(data_raw, dict) else data_raw
        except Exception:
            circuit_data = CircuitData()

        title_escaped = html.escape(str(title))
        caption_escaped = html.escape(str(caption)) if caption else None

        components = circuit_data.components or []
        connections = circuit_data.connections or []
        junctions = circuit_data.junctions or []

        # Auto-synthesize default positions if missing
        cls._ensure_component_positions(components, junctions)

        comp_map: Dict[str, CircuitComponent] = {c.id: c for c in components}
        junc_map: Dict[str, CircuitJunction] = {j.id: j for j in junctions}

        if not comp_map and not junc_map:
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120" width="100%" height="120">'
                f'<rect width="400" height="120" fill="#F7FAFC" rx="8"/>'
                f'<text x="200" y="65" font-size="14" font-family="sans-serif" text-anchor="middle" fill="#4A5568">{title_escaped}</text>'
                f'</svg>'
            )

        # Compute dynamic bounding box and viewport
        min_x, max_x, min_y, max_y = cls._compute_bounds(comp_map, junc_map)

        padding = 60.0
        header_height = 60.0
        footer_height = 40.0 if caption else 20.0

        fig_width = max(300.0, max_x - min_x)
        fig_height = max(200.0, max_y - min_y)

        total_width = fig_width + padding * 2
        total_height = fig_height + padding * 2 + header_height + footer_height

        offset_x = padding - min_x
        offset_y = padding + header_height - min_y

        def transform(x: float, y: float) -> Tuple[float, float]:
            return (x + offset_x, y + offset_y)

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width:.1f} {total_height:.1f}" width="100%" height="{total_height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <defs>',
            '    <marker id="arrow_current" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#E53E3E"/>',
            '    </marker>',
            '  </defs>',
            f'  <text x="{total_width / 2.0:.1f}" y="38" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{title_escaped}</text>',
        ]

        # 1. Render Wire Connections
        for conn in connections:
            p1 = cls._get_node_pos(conn.from_comp, comp_map, junc_map)
            p2 = cls._get_node_pos(conn.to_comp, comp_map, junc_map)
            if not p1 or not p2:
                continue

            x1, y1 = transform(p1[0], p1[1])
            x2, y2 = transform(p2[0], p2[1])

            marker_attr = ' marker-end="url(#arrow_current)"' if conn.show_current else ""
            routing_style = getattr(conn, "routing", None) or "orthogonal"

            if routing_style == "direct":
                # Direct straight-line connection for diagonal/isometric edges
                svg_parts.append(
                    f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#2D3748" stroke-width="2.5"{marker_attr}/>'
                )
            else:
                # Orthogonal routing for right-angled wire bends if points are offset on both axes
                if abs(x1 - x2) > 10.0 and abs(y1 - y2) > 10.0:
                    mid_x = x2
                    mid_y = y1
                    svg_parts.append(
                        f'  <path d="M {x1:.1f} {y1:.1f} L {mid_x:.1f} {mid_y:.1f} L {x2:.1f} {y2:.1f}" stroke="#2D3748" stroke-width="2.5" fill="none"{marker_attr}/>'
                    )
                else:
                    svg_parts.append(
                        f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#2D3748" stroke-width="2.5"{marker_attr}/>'
                    )

            if conn.label:
                mx = (x1 + x2) / 2.0
                my = (y1 + y2) / 2.0
                lbl_escaped = html.escape(conn.label.strip())
                svg_parts.append(
                    f'  <text x="{mx:.1f}" y="{my - 8.0:.1f}" font-size="11" font-weight="bold" fill="#E53E3E" text-anchor="middle">{lbl_escaped}</text>'
                )

        # 2. Render Junction Nodes
        for junc in junctions:
            jx, jy = transform(junc.x, junc.y)
            svg_parts.append(
                f'  <circle cx="{jx:.1f}" cy="{jy:.1f}" r="4.5" fill="#1A202C"/>'
            )
            if junc.label:
                lbl_escaped = html.escape(junc.label)
                svg_parts.append(
                    f'  <text x="{jx:.1f}" y="{jy - 8.0:.1f}" font-size="11" font-weight="bold" fill="#4A5568" text-anchor="middle">{lbl_escaped}</text>'
                )

        # 3. Render Components & Symbols
        for comp in components:
            if comp.x is None or comp.y is None:
                continue
            cx, cy = transform(comp.x, comp.y)
            symbol_svg = cls._render_component_symbol(comp, cx, cy)
            svg_parts.append(symbol_svg)

        if caption_escaped:
            svg_parts.append(
                f'  <text x="{total_width / 2.0:.1f}" y="{total_height - 18.0:.1f}" font-size="12" font-style="italic" text-anchor="middle" fill="#718096">{caption_escaped}</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)

    @classmethod
    def _render_component_symbol(cls, comp: CircuitComponent, cx: float, cy: float) -> str:
        parts = []
        ctype = comp.type
        lbl_escaped = html.escape(comp.label or comp.id)

        if ctype in ["resistor"]:
            # Zig-zag resistor
            parts.append(
                f'  <rect x="{cx - 25.0:.1f}" y="{cy - 12.0:.1f}" width="50.0" height="24.0" fill="#FFFFFF" stroke="#3182CE" stroke-width="2.5" rx="3"/>'
            )
            parts.append(
                f'  <path d="M {cx - 20.0:.1f} {cy:.1f} L {cx - 12.0:.1f} {cy - 6.0:.1f} L {cx - 4.0:.1f} {cy + 6.0:.1f} L {cx + 4.0:.1f} {cy - 6.0:.1f} L {cx + 12.0:.1f} {cy + 6.0:.1f} L {cx + 20.0:.1f} {cy:.1f}" stroke="#3182CE" stroke-width="2" fill="none"/>'
            )
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy - 18.0:.1f}" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype in ["battery", "cell"]:
            # Long thin line (+), short thick line (-)
            parts.append(
                f'  <rect x="{cx - 30.0:.1f}" y="{cy - 18.0:.1f}" width="60.0" height="36.0" fill="#FFFFFF" fill-opacity="0.9"/>'
            )
            parts.append(f'  <line x1="{cx - 12.0:.1f}" y1="{cy - 16.0:.1f}" x2="{cx - 12.0:.1f}" y2="{cy + 16.0:.1f}" stroke="#2D3748" stroke-width="3"/>')
            parts.append(f'  <line x1="{cx - 4.0:.1f}" y1="{cy - 10.0:.1f}" x2="{cx - 4.0:.1f}" y2="{cy + 10.0:.1f}" stroke="#2D3748" stroke-width="5"/>')
            if ctype == "battery":
                parts.append(f'  <line x1="{cx + 4.0:.1f}" y1="{cy - 16.0:.1f}" x2="{cx + 4.0:.1f}" y2="{cy + 16.0:.1f}" stroke="#2D3748" stroke-width="3"/>')
                parts.append(f'  <line x1="{cx + 12.0:.1f}" y1="{cy - 10.0:.1f}" x2="{cx + 12.0:.1f}" y2="{cy + 10.0:.1f}" stroke="#2D3748" stroke-width="5"/>')
            parts.append(f'  <text x="{cx - 20.0:.1f}" y="{cy - 18.0:.1f}" font-size="13" font-weight="bold" fill="#E53E3E">+</text>')
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy + 30.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype in ["ac_source"]:
            # AC Source: Circle with sine wave inside
            parts.append(
                f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="16.0" fill="#FFFFFF" stroke="#2D3748" stroke-width="2.5"/>'
            )
            parts.append(
                f'  <path d="M {cx - 9.0:.1f} {cy:.1f} Q {cx - 4.5:.1f} {cy - 7.0:.1f}, {cx:.1f} {cy:.1f} T {cx + 9.0:.1f} {cy:.1f}" stroke="#2D3748" stroke-width="2.5" fill="none"/>'
            )
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy + 30.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype in ["inductor"]:
            # Inductor: 4 arched coils
            parts.append(
                f'  <rect x="{cx - 26.0:.1f}" y="{cy - 16.0:.1f}" width="52.0" height="32.0" fill="#FFFFFF" fill-opacity="0.9"/>'
            )
            parts.append(
                f'  <path d="M {cx - 24.0:.1f} {cy:.1f} A 6 6 0 0 1 {cx - 12.0:.1f} {cy:.1f} A 6 6 0 0 1 {cx:.1f} {cy:.1f} A 6 6 0 0 1 {cx + 12.0:.1f} {cy:.1f} A 6 6 0 0 1 {cx + 24.0:.1f} {cy:.1f}" stroke="#4A5568" stroke-width="2.5" fill="none"/>'
            )
            if getattr(comp, "iron_core", False):
                # Parallel iron core lines above coil
                parts.append(
                    f'  <line x1="{cx - 24.0:.1f}" y1="{cy - 8.0:.1f}" x2="{cx + 24.0:.1f}" y2="{cy - 8.0:.1f}" stroke="#2D3748" stroke-width="2"/>'
                )
                parts.append(
                    f'  <line x1="{cx - 24.0:.1f}" y1="{cy - 12.0:.1f}" x2="{cx + 24.0:.1f}" y2="{cy - 12.0:.1f}" stroke="#2D3748" stroke-width="2"/>'
                )
                parts.append(
                    f'  <text x="{cx:.1f}" y="{cy - 18.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="middle">{lbl_escaped}</text>'
                )
            else:
                parts.append(
                    f'  <text x="{cx:.1f}" y="{cy - 14.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="middle">{lbl_escaped}</text>'
                )

        elif ctype == "capacitor":
            parts.append(f'  <line x1="{cx - 6.0:.1f}" y1="{cy - 14.0:.1f}" x2="{cx - 6.0:.1f}" y2="{cy + 14.0:.1f}" stroke="#319795" stroke-width="3.5"/>')
            parts.append(f'  <line x1="{cx + 6.0:.1f}" y1="{cy - 14.0:.1f}" x2="{cx + 6.0:.1f}" y2="{cy + 14.0:.1f}" stroke="#319795" stroke-width="3.5"/>')
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy - 20.0:.1f}" font-size="12" font-weight="bold" fill="#2C7A7B" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype == "switch":
            state = comp.state or "open"
            parts.append(f'  <circle cx="{cx - 15.0:.1f}" cy="{cy:.1f}" r="3.5" fill="#2D3748"/>')
            parts.append(f'  <circle cx="{cx + 15.0:.1f}" cy="{cy:.1f}" r="3.5" fill="#2D3748"/>')
            if state == "closed":
                parts.append(f'  <line x1="{cx - 15.0:.1f}" y1="{cy:.1f}" x2="{cx + 15.0:.1f}" y2="{cy:.1f}" stroke="#2D3748" stroke-width="2.5"/>')
            else:
                parts.append(f'  <line x1="{cx - 15.0:.1f}" y1="{cy:.1f}" x2="{cx + 12.0:.1f}" y2="{cy - 12.0:.1f}" stroke="#DD6B20" stroke-width="2.5"/>')
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy + 22.0:.1f}" font-size="12" font-weight="bold" fill="#D69E2E" text-anchor="middle">{lbl_escaped} ({state})</text>'
            )

        elif ctype == "lamp":
            parts.append(f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="16.0" fill="#FFFFF0" stroke="#D69E2E" stroke-width="2.5"/>')
            parts.append(f'  <line x1="{cx - 11.0:.1f}" y1="{cy - 11.0:.1f}" x2="{cx + 11.0:.1f}" y2="{cy + 11.0:.1f}" stroke="#D69E2E" stroke-width="2"/>')
            parts.append(f'  <line x1="{cx - 11.0:.1f}" y1="{cy + 11.0:.1f}" x2="{cx + 11.0:.1f}" y2="{cy - 11.0:.1f}" stroke="#D69E2E" stroke-width="2"/>')
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy - 22.0:.1f}" font-size="12" font-weight="bold" fill="#B7791F" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype in ["ammeter", "voltmeter"]:
            letter = "A" if ctype == "ammeter" else "V"
            color = "#805AD5" if ctype == "ammeter" else "#DD6B20"
            parts.append(f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="16.0" fill="#FFFFFF" stroke="{color}" stroke-width="2.5"/>')
            parts.append(f'  <text x="{cx:.1f}" y="{cy + 5.0:.1f}" font-size="14" font-weight="bold" fill="{color}" text-anchor="middle">{letter}</text>')
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy - 22.0:.1f}" font-size="12" font-weight="bold" fill="#4A5568" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype == "diode":
            parts.append(f'  <polygon points="{cx - 12.0:.1f},{cy - 12.0:.1f} {cx + 12.0:.1f},{cy:.1f} {cx - 12.0:.1f},{cy + 12.0:.1f}" fill="#4A5568"/>')
            parts.append(f'  <line x1="{cx + 12.0:.1f}" y1="{cy - 12.0:.1f}" x2="{cx + 12.0:.1f}" y2="{cy + 12.0:.1f}" stroke="#4A5568" stroke-width="3"/>')
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy - 18.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="middle">{lbl_escaped}</text>'
            )

        elif ctype == "ground":
            parts.append(f'  <line x1="{cx - 16.0:.1f}" y1="{cy:.1f}" x2="{cx + 16.0:.1f}" y2="{cy:.1f}" stroke="#2D3748" stroke-width="3"/>')
            parts.append(f'  <line x1="{cx - 10.0:.1f}" y1="{cy + 5.0:.1f}" x2="{cx + 10.0:.1f}" y2="{cy + 5.0:.1f}" stroke="#2D3748" stroke-width="2.5"/>')
            parts.append(f'  <line x1="{cx - 4.0:.1f}" y1="{cy + 10.0:.1f}" x2="{cx + 4.0:.1f}" y2="{cy + 10.0:.1f}" stroke="#2D3748" stroke-width="2"/>')

        else:
            # Generic component
            parts.append(
                f'  <rect x="{cx - 25.0:.1f}" y="{cy - 14.0:.1f}" width="50.0" height="28.0" fill="#EDF2F7" stroke="#4A5568" stroke-width="2" rx="4"/>'
            )
            parts.append(
                f'  <text x="{cx:.1f}" y="{cy + 4.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="middle">{lbl_escaped}</text>'
            )

        return "\n".join(parts)

    @classmethod
    def _compute_bounds(cls, comp_map: Dict[str, CircuitComponent], junc_map: Dict[str, CircuitJunction]) -> Tuple[float, float, float, float]:
        xs = [c.x for c in comp_map.values() if c.x is not None] + [j.x for j in junc_map.values()]
        ys = [c.y for c in comp_map.values() if c.y is not None] + [j.y for j in junc_map.values()]

        min_x = min(xs) if xs else 0.0
        max_x = max(xs) if xs else 400.0
        min_y = min(ys) if ys else 0.0
        max_y = max(ys) if ys else 250.0

        return min_x, max_x, min_y, max_y

    @classmethod
    def _get_node_pos(cls, node_id: str, comp_map: Dict[str, CircuitComponent], junc_map: Dict[str, CircuitJunction]) -> Optional[Tuple[float, float]]:
        if node_id in comp_map and comp_map[node_id].x is not None and comp_map[node_id].y is not None:
            return (comp_map[node_id].x, comp_map[node_id].y)
        if node_id in junc_map:
            return (junc_map[node_id].x, junc_map[node_id].y)
        return None

    @classmethod
    def _ensure_component_positions(cls, components: List[CircuitComponent], junctions: List[CircuitJunction]) -> None:
        """
        Auto-synthesizes coordinates for components if explicit x, y values are missing.
        Arranges components in a clean rectangular loop layout.
        """
        missing_comps = [c for c in components if c.x is None or c.y is None]
        if not missing_comps:
            return

        n = len(components)
        if n <= 2:
            positions = [(100.0, 100.0), (300.0, 100.0)]
        elif n == 3:
            positions = [(100.0, 100.0), (300.0, 100.0), (200.0, 250.0)]
        elif n == 4:
            positions = [(100.0, 100.0), (350.0, 100.0), (350.0, 250.0), (100.0, 250.0)]
        else:
            positions = []
            for i in range(n):
                angle = (i * 2.0 * math.pi / n) - (math.pi / 2.0)
                positions.append((250.0 + 150.0 * math.cos(angle), 200.0 + 120.0 * math.sin(angle)))

        for i, comp in enumerate(components):
            if comp.x is None or comp.y is None:
                pos = positions[i % len(positions)]
                comp.x = pos[0]
                comp.y = pos[1]

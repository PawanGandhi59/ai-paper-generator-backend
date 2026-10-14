import html
import math
import re
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

        # Check if bridge network topology (e.g. Wheatstone bridge) is indicated
        is_bridge = cls._is_bridge_topology(title, caption, components, connections, junctions)
        is_parallel = cls._is_parallel_topology(title, caption, components, connections)
        if is_bridge:
            cls._layout_bridge_network(components, connections, junctions)
        elif is_parallel:
            cls._layout_parallel_network(components, connections, junctions)
        else:
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

        is_vert = getattr(comp, "orientation", None) == "vertical"

        if ctype in ["resistor"]:
            if is_vert:
                # Vertical zig-zag resistor
                parts.append(
                    f'  <rect x="{cx - 12.0:.1f}" y="{cy - 25.0:.1f}" width="24.0" height="50.0" fill="#FFFFFF" stroke="#3182CE" stroke-width="2.5" rx="3"/>'
                )
                parts.append(
                    f'  <path d="M {cx:.1f} {cy - 20.0:.1f} L {cx - 6.0:.1f} {cy - 12.0:.1f} L {cx + 6.0:.1f} {cy - 4.0:.1f} L {cx - 6.0:.1f} {cy + 4.0:.1f} L {cx + 6.0:.1f} {cy + 12.0:.1f} L {cx:.1f} {cy + 20.0:.1f}" stroke="#3182CE" stroke-width="2" fill="none"/>'
                )
                parts.append(
                    f'  <text x="{cx + 18.0:.1f}" y="{cy + 4.0:.1f}" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="start">{lbl_escaped}</text>'
                )
            else:
                # Horizontal zig-zag resistor
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
            if is_vert:
                # Vertical battery: horizontal plates (top positive, bottom negative)
                parts.append(
                    f'  <rect x="{cx - 18.0:.1f}" y="{cy - 25.0:.1f}" width="36.0" height="50.0" fill="#FFFFFF" fill-opacity="0.9"/>'
                )
                parts.append(f'  <line x1="{cx - 16.0:.1f}" y1="{cy - 12.0:.1f}" x2="{cx + 16.0:.1f}" y2="{cy - 12.0:.1f}" stroke="#2D3748" stroke-width="3"/>')
                parts.append(f'  <line x1="{cx - 8.0:.1f}" y1="{cy - 4.0:.1f}" x2="{cx + 8.0:.1f}" y2="{cy - 4.0:.1f}" stroke="#2D3748" stroke-width="5"/>')
                if ctype == "battery":
                    parts.append(f'  <line x1="{cx - 16.0:.1f}" y1="{cy + 4.0:.1f}" x2="{cx + 16.0:.1f}" y2="{cy + 4.0:.1f}" stroke="#2D3748" stroke-width="3"/>')
                    parts.append(f'  <line x1="{cx - 8.0:.1f}" y1="{cy + 12.0:.1f}" x2="{cx + 8.0:.1f}" y2="{cy + 12.0:.1f}" stroke="#2D3748" stroke-width="5"/>')
                parts.append(f'  <text x="{cx + 20.0:.1f}" y="{cy - 10.0:.1f}" font-size="13" font-weight="bold" fill="#E53E3E">+</text>')
                parts.append(f'  <text x="{cx - 24.0:.1f}" y="{cy + 4.0:.1f}" font-size="12" font-weight="bold" fill="#2D3748" text-anchor="end">{lbl_escaped}</text>')
            else:
                # Horizontal battery
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

        elif ctype in ["ammeter", "voltmeter", "galvanometer"] or (ctype == "generic" and str(lbl_escaped).strip().upper() in ["G", "GALVANOMETER"]):
            is_galv = (ctype == "galvanometer") or (str(lbl_escaped).strip().upper() in ["G", "GALVANOMETER"])
            letter = "G" if is_galv else ("A" if ctype == "ammeter" else "V")
            color = "#805AD5" if is_galv else ("#3182CE" if ctype == "ammeter" else "#DD6B20")
            parts.append(f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="16.0" fill="#FFFFFF" stroke="{color}" stroke-width="2.5"/>')
            parts.append(f'  <text x="{cx:.1f}" y="{cy + 5.0:.1f}" font-size="14" font-weight="bold" fill="{color}" text-anchor="middle">{letter}</text>')
            if lbl_escaped and lbl_escaped.strip().upper() not in [letter, "A", "V", "G"]:
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

    @classmethod
    def _is_bridge_topology(
        cls,
        title: Optional[str],
        caption: Optional[str],
        components: List[CircuitComponent],
        connections: List[CircuitConnection],
        junctions: List[CircuitJunction],
    ) -> bool:
        t_str = f"{title or ''} {caption or ''}".lower()
        resistors = [c for c in components if c.type in ["resistor", "lamp"]]
        if len(resistors) < 4:
            return False

        # If caller already specified 4+ junctions and all components have explicit positions,
        # and has connections using those junctions, keep the caller's explicit layout.
        if len(junctions) >= 4 and all(c.x is not None and c.y is not None for c in components):
            j_ids = {j.id for j in junctions}
            conn_nodes = {conn.from_comp for conn in connections} | {conn.to_comp for conn in connections}
            if len(j_ids & conn_nodes) >= 4:
                return False

        if "wheatstone" in t_str or "bridge" in t_str:
            return True

        has_meter = any(
            c.type in ["galvanometer", "ammeter", "generic"]
            or str(c.label or "").upper().startswith("G")
            or c.id.upper().startswith("G")
            for c in components
        )
        has_source = any(
            c.type in ["battery", "dc_source", "cell", "ac_source"]
            or str(c.label or "").upper().startswith("E")
            or str(c.label or "").upper().startswith("V")
            or c.id.upper().startswith("V")
            for c in components
        )
        if len(resistors) == 4 and has_meter and has_source:
            return True

        return False

    @classmethod
    def _layout_bridge_network(
        cls,
        components: List[CircuitComponent],
        connections: List[CircuitConnection],
        junctions: List[CircuitJunction],
    ) -> None:
        """
        Synthesizes an authentic canonical Wheatstone bridge circuit layout:
        - Diamond network of 4 junction nodes: A (left), B (top), C (right), D (bottom)
        - 4 Bridge arms:
            Arm A-B (top-left): R1 (or P)
            Arm B-C (top-right): R2 (or Q)
            Arm A-D (bottom-left): R3 (or R)
            Arm D-C (bottom-right): R4 (or S)
        - Diagonal 1 (Galvanometer branch across B and D):
            Vertical central branch from node B -> Galvanometer (G) -> node D
        - Diagonal 2 (Battery / Source branch across A and C):
            External lower loop from node A -> Battery (E) -> node C (with key if present)
        """
        resistors = [c for c in components if c.type in ["resistor", "lamp"]]

        def _res_key(r: CircuitComponent) -> Tuple[int, str]:
            val = str(r.label or r.id).strip().upper()
            pqrs_map = {"P": 1, "Q": 2, "R": 3, "S": 4}
            first_char = val[0] if val else ""
            if first_char in pqrs_map:
                return (pqrs_map[first_char], val)
            digits = re.findall(r"\d+", val)
            num = int(digits[0]) if digits else 999
            return (num, val)

        resistors.sort(key=_res_key)
        r1, r2, r3, r4 = resistors[0], resistors[1], resistors[2], resistors[3]

        # Identify galvanometer / meter
        meter = next(
            (c for c in components if c.type in ["galvanometer"] or str(c.label or "").upper().startswith("G") or c.id.upper().startswith("G")),
            None,
        )
        if not meter:
            meter = next(
                (c for c in components if c.type in ["ammeter", "generic"] and c not in resistors),
                None,
            )
        if not meter:
            meter = CircuitComponent(id="G1", type="galvanometer", label="G")
            components.append(meter)
        else:
            meter.type = "galvanometer"
            if not meter.label or meter.label.strip().upper() in ["A", "AMMETER", "GENERIC", ""]:
                meter.label = "G"

        # Identify source
        source = next(
            (c for c in components if c.type in ["battery", "dc_source", "cell", "ac_source"] and c != meter and c not in resistors),
            None,
        )
        if not source:
            source = CircuitComponent(id="V1", type="battery", label="E")
            components.append(source)

        # Identify optional switch / key
        switch = next(
            (c for c in components if c.type in ["switch", "key"] and c != meter and c != source and c not in resistors),
            None,
        )

        # Canonical coordinates for Wheatstone Diamond
        r1.x = 145.0
        r1.y = 115.0
        r1.orientation = "horizontal"

        r2.x = 295.0
        r2.y = 115.0
        r2.orientation = "horizontal"

        r3.x = 145.0
        r3.y = 225.0
        r3.orientation = "horizontal"

        r4.x = 295.0
        r4.y = 225.0
        r4.orientation = "horizontal"

        meter.x = 220.0
        meter.y = 170.0
        meter.orientation = "vertical"

        source.orientation = "horizontal"
        if switch:
            source.x = 180.0
            source.y = 370.0
            switch.x = 260.0
            switch.y = 370.0
            switch.orientation = "horizontal"
        else:
            source.x = 220.0
            source.y = 370.0

        # Clear and build canonical junctions
        junctions.clear()
        j_a = CircuitJunction(id="J_A", x=70.0, y=170.0, label="A")
        j_b = CircuitJunction(id="J_B", x=220.0, y=60.0, label="B")
        j_c = CircuitJunction(id="J_C", x=370.0, y=170.0, label="C")
        j_d = CircuitJunction(id="J_D", x=220.0, y=280.0, label="D")
        j_bl = CircuitJunction(id="J_BL", x=70.0, y=370.0)
        j_br = CircuitJunction(id="J_BR", x=370.0, y=370.0)
        junctions.extend([j_a, j_b, j_c, j_d, j_bl, j_br])

        # Clear and build canonical connections
        connections.clear()
        # Arm 1: A -> R1 -> B
        connections.append(CircuitConnection(from_comp="J_A", to_comp=r1.id, routing="direct"))
        connections.append(CircuitConnection(from_comp=r1.id, to_comp="J_B", routing="direct"))

        # Arm 2: B -> R2 -> C
        connections.append(CircuitConnection(from_comp="J_B", to_comp=r2.id, routing="direct"))
        connections.append(CircuitConnection(from_comp=r2.id, to_comp="J_C", routing="direct"))

        # Arm 3: A -> R3 -> D
        connections.append(CircuitConnection(from_comp="J_A", to_comp=r3.id, routing="direct"))
        connections.append(CircuitConnection(from_comp=r3.id, to_comp="J_D", routing="direct"))

        # Arm 4: D -> R4 -> C
        connections.append(CircuitConnection(from_comp="J_D", to_comp=r4.id, routing="direct"))
        connections.append(CircuitConnection(from_comp=r4.id, to_comp="J_C", routing="direct"))

        # Diagonal 1: Galvanometer Branch B -> Galvanometer -> D
        connections.append(CircuitConnection(from_comp="J_B", to_comp=meter.id, routing="direct"))
        connections.append(CircuitConnection(from_comp=meter.id, to_comp="J_D", routing="direct"))

        # Diagonal 2: Source Branch A -> BL -> Battery -> (Switch) -> BR -> C
        connections.append(CircuitConnection(from_comp="J_A", to_comp="J_BL", routing="direct"))
        if switch:
            connections.append(CircuitConnection(from_comp="J_BL", to_comp=source.id, routing="direct"))
            connections.append(CircuitConnection(from_comp=source.id, to_comp=switch.id, routing="direct"))
            connections.append(CircuitConnection(from_comp=switch.id, to_comp="J_BR", routing="direct"))
        else:
            connections.append(CircuitConnection(from_comp="J_BL", to_comp=source.id, routing="direct"))
            connections.append(CircuitConnection(from_comp=source.id, to_comp="J_BR", routing="direct"))
        connections.append(CircuitConnection(from_comp="J_BR", to_comp="J_C", routing="direct"))

    @classmethod
    def _is_parallel_topology(
        cls,
        title: Optional[str],
        caption: Optional[str],
        components: List[CircuitComponent],
        connections: List[CircuitConnection],
    ) -> bool:
        t_str = f"{title or ''} {caption or ''}".lower()
        resistors = [c for c in components if c.type in ["resistor", "lamp"]]
        if len(resistors) < 2:
            return False
        if "parallel" in t_str:
            return True
        vertical_res = [c for c in resistors if getattr(c, "orientation", None) == "vertical"]
        if len(vertical_res) >= 2:
            return True
        srcs = [c for c in components if c.type in ["battery", "dc_source", "cell", "ac_source"]]
        if len(srcs) == 1 and all(r.x is None for r in resistors):
            src_id = srcs[0].id
            to_res = [conn.to_comp for conn in connections if conn.from_comp == src_id]
            if len(to_res) >= 2:
                return True
        return False

    @classmethod
    def _layout_parallel_network(
        cls,
        components: List[CircuitComponent],
        connections: List[CircuitConnection],
        junctions: List[CircuitJunction],
    ) -> None:
        """
        Synthesizes an authentic parallel ladder circuit layout:
        - Voltage source placed on the left oriented vertically
        - Resistors arranged side-by-side as vertical parallel rungs
        - Continuous horizontal top bus rail and bottom bus rail with explicit junction dots
        """
        srcs = [c for c in components if c.type in ["battery", "dc_source", "cell", "ac_source"]]
        resistors = [c for c in components if c.type in ["resistor", "lamp"]]
        other_comps = [c for c in components if c not in srcs and c not in resistors]

        src = srcs[0] if srcs else None
        if src:
            src.x = 80.0
            src.y = 190.0
            src.orientation = "vertical"

        spacing = 110.0
        start_r_x = 190.0

        for idx, r in enumerate(resistors):
            r.x = start_r_x + idx * spacing
            r.y = 190.0
            r.orientation = "vertical"

        for idx, c in enumerate(other_comps):
            c.x = start_r_x + (len(resistors) + idx) * spacing
            c.y = 190.0
            c.orientation = "vertical"

        all_vertical_comps = resistors + other_comps
        connections.clear()
        junctions.clear()

        y_top = 110.0
        y_bot = 270.0
        src_x = src.x if src else 80.0

        j_src_top = CircuitJunction(id="J_src_top", x=src_x, y=y_top)
        j_src_bot = CircuitJunction(id="J_src_bot", x=src_x, y=y_bot)
        junctions.extend([j_src_top, j_src_bot])

        if src:
            connections.append(CircuitConnection(from_comp="J_src_bot", to_comp=src.id, routing="direct"))
            connections.append(CircuitConnection(from_comp=src.id, to_comp="J_src_top", routing="direct"))

        prev_top_j = "J_src_top"
        prev_bot_j = "J_src_bot"

        for idx, comp in enumerate(all_vertical_comps):
            cx = comp.x or (start_r_x + idx * spacing)
            jt_id = f"J_top_{idx}"
            jb_id = f"J_bot_{idx}"
            jt = CircuitJunction(id=jt_id, x=cx, y=y_top)
            jb = CircuitJunction(id=jb_id, x=cx, y=y_bot)
            junctions.extend([jt, jb])

            connections.append(CircuitConnection(from_comp=prev_top_j, to_comp=jt_id, routing="direct"))
            connections.append(CircuitConnection(from_comp=prev_bot_j, to_comp=jb_id, routing="direct"))
            prev_top_j = jt_id
            prev_bot_j = jb_id

            connections.append(CircuitConnection(from_comp=jt_id, to_comp=comp.id, routing="direct"))
            connections.append(CircuitConnection(from_comp=comp.id, to_comp=jb_id, routing="direct"))


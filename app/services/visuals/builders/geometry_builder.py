import html
import math
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel

from app.schemas.visuals import (
    GeometryAngle,
    GeometryCircle,
    GeometryData,
    GeometryPoint,
    GeometryPolygon,
    GeometrySegment,
)


class GeometryBuilder:
    """
    Deterministic, subject-agnostic SVG rendering engine for 2D geometry figures.
    Generates self-contained, safe, scalable SVG strings for points, line segments,
    rays, vectors, polygons, circles, angles, right-angle indicators, and text labels.
    """

    @classmethod
    def render(cls, spec: Any) -> str:
        """
        Main entry point for Geometry SVG rendering.
        Accepts VisualSpec or raw dictionary payload.
        """
        title = getattr(spec, "title", None) or (spec.get("title") if isinstance(spec, dict) else "Geometry Figure")
        caption = getattr(spec, "caption", None) or (spec.get("caption") if isinstance(spec, dict) else None)
        data_raw = getattr(spec, "data", None) or getattr(spec, "spec_data", None) or (spec.get("spec_data") or spec.get("data") if isinstance(spec, dict) else {})

        try:
            geom_data = GeometryData(**data_raw) if isinstance(data_raw, dict) else data_raw
        except Exception:
            geom_data = GeometryData()

        title_escaped = html.escape(str(title))
        caption_escaped = html.escape(str(caption)) if caption else None

        points_map: Dict[str, GeometryPoint] = {p.id: p for p in geom_data.points}

        # Auto-synthesize default point coordinates if missing or incomplete
        cls._ensure_point_coordinates(geom_data, points_map)

        if not points_map:
            # Empty fallback visual
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120" width="100%" height="120">'
                f'<rect width="400" height="120" fill="#F7FAFC" rx="8"/>'
                f'<text x="200" y="65" font-size="14" font-family="sans-serif" text-anchor="middle" fill="#4A5568">{title_escaped}</text>'
                f'</svg>'
            )

        # Compute dynamic bounding box and viewport
        min_x, max_x, min_y, max_y = cls._compute_bounds(points_map, geom_data.circles)

        padding = 65.0
        header_height = 60.0
        footer_height = 40.0 if caption else 20.0

        fig_width = max(200.0, max_x - min_x)
        fig_height = max(150.0, max_y - min_y)

        total_width = fig_width + padding * 2
        total_height = fig_height + padding * 2 + header_height + footer_height

        # Coordinate transformation: map geometry (x, y) to SVG viewport (tx, ty)
        offset_x = padding - min_x
        offset_y = padding + header_height - min_y

        def transform(x: float, y: float) -> Tuple[float, float]:
            return (x + offset_x, y + offset_y)

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width:.1f} {total_height:.1f}" width="100%" height="{total_height:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <defs>',
            '    <marker id="arrow_geom" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2D3748"/>',
            '    </marker>',
            '  </defs>',
            f'  <text x="{total_width / 2.0:.1f}" y="38" font-size="18" font-weight="bold" text-anchor="middle" fill="#1A202C">{title_escaped}</text>',
        ]

        # 1. Render Polygons (Fills & Boundaries)
        for poly in geom_data.polygons:
            poly_pts = [points_map[pid] for pid in poly.points if pid in points_map]
            if len(poly_pts) >= 3:
                pts_str = " ".join([f"{transform(p.x, p.y)[0]:.1f},{transform(p.x, p.y)[1]:.1f}" for p in poly_pts])
                fill = poly.fill_color or "#EBF8FF"
                svg_parts.append(
                    f'  <polygon points="{pts_str}" fill="{fill}" fill-opacity="0.6" stroke="#3182CE" stroke-width="2.5" stroke-linejoin="round"/>'
                )

        # 2. Render Circles
        for circ in geom_data.circles:
            if circ.center in points_map:
                cp = points_map[circ.center]
                cx, cy = transform(cp.x, cp.y)
                fill = circ.fill_color or "none"
                svg_parts.append(
                    f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{circ.radius:.1f}" fill="{fill}" stroke="#319795" stroke-width="2"/>'
                )
                if circ.label:
                    lbl_escaped = html.escape(circ.label)
                    svg_parts.append(
                        f'  <text x="{cx + circ.radius / 2.0:.1f}" y="{cy - 8.0:.1f}" font-size="12" font-style="italic" fill="#2B6CB0" text-anchor="middle">{lbl_escaped}</text>'
                    )

        # 3. Render Line Segments / Rays / Vectors
        for seg in geom_data.segments:
            p_from = points_map.get(seg.from_point)
            p_to = points_map.get(seg.to_point)
            if not p_from or not p_to:
                continue

            x1, y1 = transform(p_from.x, p_from.y)
            x2, y2 = transform(p_to.x, p_to.y)

            dash_attr = ""
            if seg.style == "dashed":
                dash_attr = ' stroke-dasharray="6,4"'
            elif seg.style == "dotted":
                dash_attr = ' stroke-dasharray="2,3"'

            marker_attr = ""
            if seg.arrow in ["end", "both"]:
                marker_attr = ' marker-end="url(#arrow_geom)"'

            svg_parts.append(
                f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#2D3748" stroke-width="2"{dash_attr}{marker_attr}/>'
            )

            # Segment Label Placement
            if seg.label and seg.label.strip():
                mx = (x1 + x2) / 2.0
                my = (y1 + y2) / 2.0
                dx = x2 - x1
                dy = y2 - y1
                length = math.hypot(dx, dy)
                offset = 14.0
                if length > 0:
                    nx = -dy / length * offset
                    ny = dx / length * offset
                else:
                    nx, ny = 0.0, -offset

                lbl_escaped = html.escape(seg.label.strip())
                svg_parts.append(
                    f'  <text x="{mx + nx:.1f}" y="{my + ny + 4.0:.1f}" font-size="12" font-weight="500" fill="#2B6CB0" text-anchor="middle">{lbl_escaped}</text>'
                )

        # 4. Render Angles & Right-Angle Markers
        for ang in geom_data.angles:
            vp = points_map.get(ang.vertex)
            p1 = points_map.get(ang.p1)
            p2 = points_map.get(ang.p2)
            if not vp or not p1 or not p2:
                continue

            vx, vy = transform(vp.x, vp.y)
            x1, y1 = transform(p1.x, p1.y)
            x2, y2 = transform(p2.x, p2.y)

            v1x, v1y = x1 - vx, y1 - vy
            v2x, v2y = x2 - vx, y2 - vy

            len1 = math.hypot(v1x, v1y)
            len2 = math.hypot(v2x, v2y)

            if len1 > 0 and len2 > 0:
                u1x, u1y = v1x / len1, v1y / len1
                u2x, u2y = v2x / len2, v2y / len2

                if ang.right_angle:
                    size = 14.0
                    rx1, ry1 = vx + u1x * size, vy + u1y * size
                    rx2, ry2 = vx + u2x * size, vy + u2y * size
                    rcx, rcy = vx + (u1x + u2x) * size, vy + (u1y + u2y) * size
                    svg_parts.append(
                        f'  <polyline points="{rx1:.1f},{ry1:.1f} {rcx:.1f},{rcy:.1f} {rx2:.1f},{ry2:.1f}" fill="none" stroke="#E53E3E" stroke-width="1.8"/>'
                    )
                else:
                    arc_r = 22.0
                    ax1, ay1 = vx + u1x * arc_r, vy + u1y * arc_r
                    ax2, ay2 = vx + u2x * arc_r, vy + u2y * arc_r
                    svg_parts.append(
                        f'  <path d="M {ax1:.1f} {ay1:.1f} A {arc_r} {arc_r} 0 0 1 {ax2:.1f} {ay2:.1f}" fill="none" stroke="#DD6B20" stroke-width="1.8"/>'
                    )

                if ang.label:
                    bis_x = u1x + u2x
                    bis_y = u1y + u2y
                    bis_len = math.hypot(bis_x, bis_y)
                    if bis_len > 0:
                        lbl_dist = 32.0
                        lx = vx + (bis_x / bis_len) * lbl_dist
                        ly = vy + (bis_y / bis_len) * lbl_dist
                        lbl_escaped = html.escape(ang.label)
                        svg_parts.append(
                            f'  <text x="{lx:.1f}" y="{ly + 4.0:.1f}" font-size="12" font-weight="bold" fill="#DD6B20" text-anchor="middle">{lbl_escaped}</text>'
                        )

        # 5. Render Points & Point Labels
        for pid, pt in points_map.items():
            px, py = transform(pt.x, pt.y)

            if pt.show_point:
                svg_parts.append(
                    f'  <circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="#E53E3E" stroke="#FFFFFF" stroke-width="1.5"/>'
                )

            lbl = pt.label if pt.label is not None else pt.id
            if lbl:
                lbl_escaped = html.escape(lbl)
                svg_parts.append(
                    f'  <text x="{px:.1f}" y="{py - 10.0:.1f}" font-size="13" font-weight="bold" fill="#1A202C" text-anchor="middle">{lbl_escaped}</text>'
                )

        if caption_escaped:
            svg_parts.append(
                f'  <text x="{total_width / 2.0:.1f}" y="{total_height - 18.0:.1f}" font-size="12" font-style="italic" text-anchor="middle" fill="#718096">{caption_escaped}</text>'
            )

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)

    @classmethod
    def _compute_bounds(cls, points_map: Dict[str, GeometryPoint], circles: List[GeometryCircle]) -> Tuple[float, float, float, float]:
        xs = [p.x for p in points_map.values() if p.x is not None]
        ys = [p.y for p in points_map.values() if p.y is not None]

        for circ in circles:
            if circ.center in points_map and points_map[circ.center].x is not None and points_map[circ.center].y is not None:
                cp = points_map[circ.center]
                xs.append(cp.x - circ.radius)
                xs.append(cp.x + circ.radius)
                ys.append(cp.y - circ.radius)
                ys.append(cp.y + circ.radius)

        min_x = min(xs) if xs else 0.0
        max_x = max(xs) if xs else 300.0
        min_y = min(ys) if ys else 0.0
        max_y = max(ys) if ys else 200.0

        return min_x, max_x, min_y, max_y

    @classmethod
    def _ensure_point_coordinates(cls, geom_data: GeometryData, points_map: Dict[str, GeometryPoint]) -> None:
        """
        Auto-synthesizes coordinates for point IDs that lack explicit x, y coordinates or are referenced without definition.
        """
        referenced_pids: List[str] = []
        for poly in geom_data.polygons:
            for pid in poly.points:
                if pid not in referenced_pids:
                    referenced_pids.append(pid)
        for seg in geom_data.segments:
            if seg.from_point not in referenced_pids:
                referenced_pids.append(seg.from_point)
            if seg.to_point not in referenced_pids:
                referenced_pids.append(seg.to_point)
        for circ in geom_data.circles:
            if circ.center not in referenced_pids:
                referenced_pids.append(circ.center)
        for ang in geom_data.angles:
            for pid in [ang.vertex, ang.p1, ang.p2]:
                if pid not in referenced_pids:
                    referenced_pids.append(pid)

        # Include points defined in geom_data.points in order
        all_candidate_pids: List[str] = []
        for p in geom_data.points:
            if p.id not in all_candidate_pids:
                all_candidate_pids.append(p.id)
        for pid in referenced_pids:
            if pid not in all_candidate_pids:
                all_candidate_pids.append(pid)

        # Find points needing coordinate synthesis (either not in points_map or x/y is None)
        missing_pids = [
            pid for pid in all_candidate_pids
            if pid not in points_map or points_map[pid].x is None or points_map[pid].y is None
        ]

        if not missing_pids:
            return

        # Default layouts based on count of missing points
        if len(missing_pids) == 3:
            # Triangle ABC layout
            defaults = [
                (missing_pids[0], 50.0, 200.0),
                (missing_pids[1], 250.0, 200.0),
                (missing_pids[2], 50.0, 50.0),
            ]
        elif len(missing_pids) == 4:
            # Rectangle ABCD layout
            defaults = [
                (missing_pids[0], 50.0, 50.0),
                (missing_pids[1], 250.0, 50.0),
                (missing_pids[2], 250.0, 200.0),
                (missing_pids[3], 50.0, 200.0),
            ]
        else:
            # Regular polygon circle layout
            radius = 120.0
            cx, cy = 150.0, 150.0
            n = len(missing_pids)
            defaults = []
            for i, pid in enumerate(missing_pids):
                angle = (i * 2.0 * math.pi / n) - (math.pi / 2.0)
                defaults.append((pid, cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

        for pid, x, y in defaults:
            if pid in points_map:
                if points_map[pid].x is None:
                    points_map[pid].x = x
                if points_map[pid].y is None:
                    points_map[pid].y = y
            else:
                points_map[pid] = GeometryPoint(id=pid, x=x, y=y, label=pid)

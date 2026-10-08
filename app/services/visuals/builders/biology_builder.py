import html
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BiologyLabelOverride(BaseModel):
    target: str
    label: str


class BiologyBuilder:
    """
    Deterministic, high-fidelity SVG rendering engine for Biology educational visual artifacts.
    Supports:
    1. Genetic Punnett Squares (monohybrid, dihybrid, multi-allele crosses with gamete headers)
    2. Curated NCERT Textbook Anatomical, Cellular & Ecological Vector Templates:
       - nephron (functional unit of kidney with glomerulus, arterioles, tubules & peritubular capillaries)
       - human_heart (4 chambers, valves, major vessels)
       - stomata_open & stomata_closed (guard cells, pore, chloroplasts)
       - leaf_cross_section (epidermis, palisade, spongy mesophyll, stomata, vascular bundle)
       - neuron (cyton, dendrites, axon, myelin sheath, nerve endings)
       - reflex_arc (stimulus, receptor, sensory neuron, spinal cord, motor neuron, effector)
       - flower_anatomy (petals, sepals, stamen with filament/anther, pistil/carpel, ovary, ovule)
       - plant_cell (cell wall, vacuole, nucleus, chloroplasts, mitochondria)
       - digestive_system (mouth, oesophagus, stomach, liver, pancreas, intestines)
       - human_eye / myopia_correction (eyeball, cornea, crystalline lens, retina, optical rays, concave lens)
       - ecological_pyramid / energy_pyramid (stepped trapezoidal pyramid showing 10% law and 4 trophic tiers)
    3. Dynamic Label Masking (replaces anatomical names with 'A', 'B', 'C' without text clipping).
    """

    @classmethod
    def _render_callout_label(
        cls,
        ax: float,
        ay: float,
        tx: float,
        ty: float,
        display_text: str,
        masked: bool,
        preferred_anchor: Optional[str] = None,
    ) -> List[str]:
        """
        Shared rendering helper for biological leader lines and callout badges.
        Dynamically adjusts badge dimensions:
        - If masked and text length <= 2 (e.g. 'A', 'B', 'C'): renders a standard circular badge.
        - If masked and text length > 2 (e.g. 'Bowman's Capsule', 'Stigma'): renders a rounded pill that fully contains the text.
        - If not masked: renders crisp text with proper directional offset so text never overlaps or clips.
        """
        parts: List[str] = []
        # Leader line with red target dot at anatomical site
        parts.append(f'  <line x1="{ax:.1f}" y1="{ay:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="#718096" stroke-width="1.2" stroke-dasharray="2,2"/>')
        parts.append(f'  <circle cx="{ax:.1f}" cy="{ay:.1f}" r="3.5" fill="#E53E3E"/>')

        clean_text = html.escape(str(display_text).strip())
        t_len = len(clean_text)

        if masked and t_len <= 2:
            # Single-letter exam masking badge (e.g., 'A', 'B', '1')
            parts.append(f'  <circle cx="{tx:.1f}" cy="{ty:.1f}" r="14" fill="#3182CE"/>')
            parts.append(f'  <text x="{tx:.1f}" y="{ty + 5.0:.1f}" font-size="13" font-weight="bold" fill="#FFFFFF" text-anchor="middle">{clean_text}</text>')
        elif masked:
            # Multi-character badge: dynamic pill enclosing full text
            pill_w = max(50.0, t_len * 7.5 + 20.0)
            pill_h = 24.0
            rx = tx - pill_w / 2.0
            ry = ty - pill_h / 2.0
            parts.append(f'  <rect x="{rx:.1f}" y="{ry:.1f}" width="{pill_w:.1f}" height="{pill_h:.1f}" rx="12" fill="#EBF8FF" stroke="#3182CE" stroke-width="1.8"/>')
            parts.append(f'  <text x="{tx:.1f}" y="{ty + 4.5:.1f}" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">{clean_text}</text>')
        else:
            # Standard textbook label text
            anchor = preferred_anchor or ("start" if tx >= ax else "end")
            x_offset = 6.0 if anchor == "start" else (-6.0 if anchor == "end" else 0.0)
            parts.append(f'  <text x="{tx + x_offset:.1f}" y="{ty + 4.0:.1f}" font-size="12" font-weight="600" fill="#2D3748" text-anchor="{anchor}">{clean_text}</text>')

        return parts

    @classmethod
    def render(cls, spec: Any) -> str:
        """
        Main entry point for Biology SVG rendering.
        Accepts VisualSpec or raw dictionary payload.
        """
        title = getattr(spec, "title", None) or (spec.get("title") if isinstance(spec, dict) else "Biology Diagram")
        caption = getattr(spec, "caption", None) or (spec.get("caption") if isinstance(spec, dict) else None)
        data_raw = getattr(spec, "data", None) or getattr(spec, "spec_data", None) or (spec.get("spec_data") or spec.get("data") if isinstance(spec, dict) else {})

        template_id = str(data_raw.get("template") or data_raw.get("format") or "").lower().strip()
        label_overrides_raw = data_raw.get("biology_labels") or data_raw.get("labels") or []

        label_map: Dict[str, str] = {}
        for item in label_overrides_raw:
            if isinstance(item, dict):
                t = str(item.get("target", "")).lower().strip()
                l = str(item.get("label", "")).strip()
                if t and l:
                    label_map[t] = l
            elif hasattr(item, "target") and hasattr(item, "label"):
                t = str(item.target).lower().strip()
                l = str(item.label).strip()
                if t and l:
                    label_map[t] = l

        title_escaped = html.escape(str(title))
        caption_escaped = html.escape(str(caption)) if caption else None

        # Intelligent title-based override if mismatched template was specified
        t_low = title_escaped.lower()
        if "phototrop" in t_low or "tropism" in t_low:
            return cls._render_phototropism(title_escaped, caption_escaped, label_map)
        if "female" in t_low or ("reproductive" in t_low and "flower" not in t_low and "plant" not in t_low) or "uterus" in t_low:
            return cls._render_female_reproductive_system(title_escaped, caption_escaped, label_map)
        if "hypermetrop" in t_low or "hyperopia" in t_low or "farsighted" in t_low or "hypermetrop" in template_id:
            return cls._render_human_eye(title_escaped, caption_escaped, label_map, mode="hypermetropia")
        if ("eye" in t_low or "myop" in t_low) and template_id not in ["eye", "human_eye", "myopia", "myopic_eye", "myopia_correction"]:
            return cls._render_human_eye(title_escaped, caption_escaped, label_map, mode="myopia")

        # Route to appropriate biology visual generator
        if template_id in ["punnett_square", "punnett", "genetics_cross", "cross"]:
            return cls._render_punnett_square(title_escaped, caption_escaped, data_raw)
        elif template_id in ["phototropism", "phototropism_experiment", "phototropism_box", "plant_tropism", "tropism", "auxin_bending"]:
            return cls._render_phototropism(title_escaped, caption_escaped, label_map)
        elif template_id in ["female_reproductive_system", "human_reproductive_anatomy", "female_reproduction", "human_reproductive_system", "human_reproduction", "reproductive_system", "uterus", "ovary"]:
            return cls._render_female_reproductive_system(title_escaped, caption_escaped, label_map)
        elif template_id in ["stomata", "stomata_open", "open_stomata"]:
            return cls._render_stomata(title_escaped, caption_escaped, label_map, is_open=True)
        elif template_id in ["stomata_closed", "closed_stomata"]:
            return cls._render_stomata(title_escaped, caption_escaped, label_map, is_open=False)
        elif template_id in ["leaf", "leaf_cross_section", "leaf_anatomy"]:
            return cls._render_leaf_cross_section(title_escaped, caption_escaped, label_map)
        elif template_id in ["heart", "human_heart", "circulatory_system"]:
            return cls._render_human_heart(title_escaped, caption_escaped, label_map)
        elif template_id in ["neuron", "nerve_cell"]:
            return cls._render_neuron(title_escaped, caption_escaped, label_map)
        elif template_id in ["reflex_arc", "reflex_action"]:
            return cls._render_reflex_arc(title_escaped, caption_escaped, label_map)
        elif template_id in ["flower", "flower_anatomy", "flower_structure"]:
            return cls._render_flower(title_escaped, caption_escaped, label_map)
        elif template_id in ["plant_cell", "cell_structure", "cell"]:
            return cls._render_plant_cell(title_escaped, caption_escaped, label_map)
        elif template_id in ["digestive_system", "alimentary_canal"]:
            return cls._render_digestive_system(title_escaped, caption_escaped, label_map)
        elif template_id in ["hypermetropia", "hypermetropia_correction", "hyperopia", "farsightedness"]:
            return cls._render_human_eye(title_escaped, caption_escaped, label_map, mode="hypermetropia")
        elif template_id in ["eye", "human_eye", "myopia", "myopic_eye", "myopia_correction", "eye_defect"]:
            mode = "hypermetropia" if ("hypermetrop" in t_low or "farsighted" in t_low) else "myopia"
            return cls._render_human_eye(title_escaped, caption_escaped, label_map, mode=mode)
        elif template_id in ["pyramid", "energy_pyramid", "ecological_pyramid", "trophic_levels"]:
            return cls._render_ecological_pyramid(title_escaped, caption_escaped, label_map, data_raw)
        else:
            # Fallback based on title keywords
            if "hypermetrop" in t_low or "hyperopia" in t_low or "farsighted" in t_low:
                return cls._render_human_eye(title_escaped, caption_escaped, label_map, mode="hypermetropia")
            if "eye" in t_low or "myop" in t_low or "vision" in t_low:
                return cls._render_human_eye(title_escaped, caption_escaped, label_map, mode="myopia")
            if "pyramid" in t_low or "trophic" in t_low or "energy" in t_low:
                return cls._render_ecological_pyramid(title_escaped, caption_escaped, label_map, data_raw)
            if "reflex" in t_low:
                return cls._render_reflex_arc(title_escaped, caption_escaped, label_map)
            if "flower" in t_low:
                return cls._render_flower(title_escaped, caption_escaped, label_map)
            if "heart" in t_low:
                return cls._render_human_heart(title_escaped, caption_escaped, label_map)
            # Default canonical: nephron
            return cls._render_nephron(title_escaped, caption_escaped, label_map)

    # =========================================================================
    # 1. Punnett Square Generator
    # =========================================================================
    @classmethod
    def _render_punnett_square(cls, title: str, caption: Optional[str], data: Dict[str, Any]) -> str:
        # Sanitize caption typos (e.g. T1 -> Tt)
        clean_caption = caption
        if clean_caption:
            clean_caption = clean_caption.replace("T1", "Tt").replace("t1", "tt")

        # Sanitize parents if obvious typos exist
        parent1 = str(data.get("parent1") or "Tt").strip()
        parent2 = str(data.get("parent2") or "Tt").strip()
        if "T1" in parent1:
            parent1 = parent1.replace("T1", "Tt")
        if "T1" in parent2:
            parent2 = parent2.replace("T1", "Tt")
        if "RYYy" in parent1 or "RfYy" in parent1:
            parent1 = "RrYy"
        if "RYYy" in parent2 or "RfYy" in parent2:
            parent2 = "RrYy"

        gametes1 = data.get("gametes1")
        if not gametes1:
            gametes1 = ["RY", "Ry", "rY", "ry"] if len(parent1) == 4 else (list(parent1.replace(" ", "")) if len(parent1) == 2 else ["T", "t"])

        gametes2 = data.get("gametes2")
        if not gametes2:
            gametes2 = ["RY", "Ry", "rY", "ry"] if len(parent2) == 4 else (list(parent2.replace(" ", "")) if len(parent2) == 2 else ["T", "t"])

        def _combine_gametes(g1: str, g2: str) -> str:
            chars = list(str(g1).strip() + str(g2).strip())
            genes: Dict[str, List[str]] = {}
            for ch in chars:
                genes.setdefault(ch.upper(), []).append(ch)
            res = []
            for k in sorted(genes.keys()):
                res.extend(sorted(genes[k], key=lambda c: (not c.isupper(), c)))
            return "".join(res)

        # Build clean deterministic grid ensuring 100% biological accuracy (e.g. Ry x RY = RRYy)
        clean_grid: List[List[str]] = []
        for g2 in gametes2:
            row = []
            for g1 in gametes1:
                row.append(_combine_gametes(g1, g2))
            clean_grid.append(row)
        grid = clean_grid

        cols = len(gametes1)
        rows = len(gametes2)

        header_col_w = 80.0
        header_row_h = 60.0
        cell_w = 90.0
        cell_h = 70.0

        grid_total_w = header_col_w + cols * cell_w
        grid_total_h = header_row_h + rows * cell_h

        padding_x = 50.0
        top_offset = 80.0
        footer_h = 50.0 if clean_caption else 30.0

        svg_w = max(520.0, grid_total_w + padding_x * 2)
        svg_h = grid_total_h + top_offset + footer_h

        start_x = (svg_w - grid_total_w) / 2.0
        start_y = top_offset

        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" width="100%" height="{svg_h:.1f}" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            f'  <rect width="{svg_w:.1f}" height="{svg_h:.1f}" fill="#FFFFFF"/>',
            f'  <text x="{svg_w/2.0:.1f}" y="36" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            f'  <text x="{svg_w/2.0:.1f}" y="56" font-size="12" fill="#718096" text-anchor="middle">Cross: {html.escape(parent1)} × {html.escape(parent2)}</text>',
            f'  <text x="{start_x + header_col_w + (cols * cell_w)/2.0:.1f}" y="{start_y - 12:.1f}" font-size="12" font-weight="600" fill="#2B6CB0" text-anchor="middle">Female Gametes ♀</text>',
            f'  <text x="{start_x - 14.0:.1f}" y="{start_y + header_row_h + (rows * cell_h)/2.0:.1f}" font-size="12" font-weight="600" fill="#805AD5" text-anchor="middle" transform="rotate(-90, {start_x - 14.0:.1f}, {start_y + header_row_h + (rows * cell_h)/2.0:.1f})">Male Gametes ♂</text>',
        ]

        # Diagonal split top-left header cell
        tl_x = start_x
        tl_y = start_y
        parts.append(f'  <rect x="{tl_x:.1f}" y="{tl_y:.1f}" width="{header_col_w:.1f}" height="{header_row_h:.1f}" fill="#EDF2F7" stroke="#CBD5E0" stroke-width="1.5"/>')
        parts.append(f'  <line x1="{tl_x:.1f}" y1="{tl_y:.1f}" x2="{tl_x + header_col_w:.1f}" y2="{tl_y + header_row_h:.1f}" stroke="#A0AEC0" stroke-width="1.2"/>')
        parts.append(f'  <text x="{tl_x + header_col_w - 12.0:.1f}" y="{tl_y + 22.0:.1f}" font-size="13" font-weight="bold" fill="#2B6CB0" text-anchor="end">♀</text>')
        parts.append(f'  <text x="{tl_x + 12.0:.1f}" y="{tl_y + header_row_h - 12.0:.1f}" font-size="13" font-weight="bold" fill="#805AD5">♂</text>')

        # Column Gamete Headers (Top)
        for c_idx, g1 in enumerate(gametes1):
            cx = start_x + header_col_w + c_idx * cell_w
            cy = start_y
            parts.append(f'  <rect x="{cx:.1f}" y="{cy:.1f}" width="{cell_w:.1f}" height="{header_row_h:.1f}" fill="#EBF8FF" stroke="#CBD5E0" stroke-width="1.5"/>')
            parts.append(f'  <text x="{cx + cell_w/2.0:.1f}" y="{cy + header_row_h/2.0 + 6.0:.1f}" font-size="15" font-weight="bold" fill="#2B6CB0" text-anchor="middle">{html.escape(str(g1))}</text>')

        # Row Gamete Headers & Grid Cells
        for r_idx, g2 in enumerate(gametes2):
            rx = start_x
            ry = start_y + header_row_h + r_idx * cell_h
            parts.append(f'  <rect x="{rx:.1f}" y="{ry:.1f}" width="{header_col_w:.1f}" height="{cell_h:.1f}" fill="#FAF5FF" stroke="#CBD5E0" stroke-width="1.5"/>')
            parts.append(f'  <text x="{rx + header_col_w/2.0:.1f}" y="{ry + cell_h/2.0 + 6.0:.1f}" font-size="15" font-weight="bold" fill="#805AD5" text-anchor="middle">{html.escape(str(g2))}</text>')

            for c_idx in range(cols):
                cx = start_x + header_col_w + c_idx * cell_w
                cell_val = str(grid[r_idx][c_idx])
                cell_bg = "#FFFFFF" if (r_idx + c_idx) % 2 == 0 else "#F7FAFC"
                parts.append(f'  <rect x="{cx:.1f}" y="{ry:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" fill="{cell_bg}" stroke="#CBD5E0" stroke-width="1.5"/>')
                parts.append(f'  <text x="{cx + cell_w/2.0:.1f}" y="{ry + cell_h/2.0 + 6.0:.1f}" font-size="16" font-weight="bold" fill="#2D3748" text-anchor="middle">{html.escape(cell_val)}</text>')

        if clean_caption:
            parts.append(f'  <text x="{svg_w/2.0:.1f}" y="{svg_h - 18:.1f}" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{clean_caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 2. Nephron Structure Generator (Detailed with Capillaries & Arterioles)
    # =========================================================================
    @classmethod
    def _render_nephron(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            val = label_map.get(key.lower(), default)
            return val

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 520" width="100%" height="520" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="520" fill="#FFFFFF"/>',
            f'  <text x="380" y="34" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="52" font-size="12" fill="#718096" text-anchor="middle">Structure of a Nephron (Functional Unit of Kidney)</text>',
            '  <defs>',
            '    <linearGradient id="bowmanGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#FEFCBF" />',
            '      <stop offset="100%" stop-color="#FAF089" />',
            '    </linearGradient>',
            '  </defs>',
            # Renal Artery / Afferent Arteriole (Enters from left into glomerulus)
            '  <path d="M 50 135 C 80 135, 95 155, 115 170" fill="none" stroke="#E53E3E" stroke-width="7" stroke-linecap="round"/>',
            # Efferent Arteriole (Exits glomerulus, narrower diameter)
            '  <path d="M 145 170 C 160 145, 180 130, 210 135" fill="none" stroke="#E53E3E" stroke-width="4.5" stroke-linecap="round"/>',
            # Bowman's Capsule (C-shaped double-walled epithelial cup)
            '  <path d="M 120 135 C 85 155, 85 225, 120 245 C 165 265, 185 230, 180 195 C 175 165, 160 140, 120 135 Z" fill="url(#bowmanGrad)" stroke="#D69E2E" stroke-width="3"/>',
            # Glomerulus Capillary Tuft (Multiple interlaced micro-vascular loops inside cup)
            '  <path d="M 115 170 C 110 185, 120 205, 132 195 C 145 185, 125 175, 138 175 C 148 175, 150 195, 135 205 C 120 215, 130 220, 145 170" fill="none" stroke="#C53030" stroke-width="3.5" stroke-linecap="round"/>',
            '  <circle cx="132" cy="192" r="14" fill="#E53E3E" fill-opacity="0.3"/>',
            # Proximal Convoluted Tubule (PCT)
            '  <path d="M 170 230 C 200 270, 240 220, 260 270 C 280 310, 250 340, 230 350" fill="none" stroke="#ECC94B" stroke-width="14" stroke-linecap="round"/>',
            '  <path d="M 170 230 C 200 270, 240 220, 260 270 C 280 310, 250 340, 230 350" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            # Loop of Henle (Hairpin loop - descending and ascending)
            '  <path d="M 230 350 L 230 450 C 230 480, 290 480, 290 450 L 290 310" fill="none" stroke="#ECC94B" stroke-width="10" stroke-linecap="round"/>',
            '  <path d="M 230 350 L 230 450 C 230 480, 290 480, 290 450 L 290 310" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            # Distal Convoluted Tubule (DCT)
            '  <path d="M 290 310 C 310 250, 360 290, 400 250 C 430 220, 460 240, 500 240" fill="none" stroke="#ECC94B" stroke-width="14" stroke-linecap="round"/>',
            '  <path d="M 290 310 C 310 250, 360 290, 400 250 C 430 220, 460 240, 500 240" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            # Collecting Duct (Main vertical trunk)
            '  <path d="M 500 130 L 500 480" fill="none" stroke="#DD6B20" stroke-width="20" stroke-linecap="round"/>',
            '  <path d="M 500 130 L 500 480" fill="none" stroke="#C05621" stroke-width="2"/>',
            # Tributary branches into collecting duct
            '  <path d="M 500 190 L 540 170" fill="none" stroke="#DD6B20" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 500 330 L 540 310" fill="none" stroke="#DD6B20" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 500 410 L 540 390" fill="none" stroke="#DD6B20" stroke-width="12" stroke-linecap="round"/>',
            # Peritubular Capillary Network (Wrapping around PCT, descending along Henle, & venule)
            '  <path d="M 210 135 C 240 170, 250 240, 230 280 C 210 320, 215 380, 225 430" fill="none" stroke="#E53E3E" stroke-width="2.5" stroke-dasharray="4,2"/>',
            '  <path d="M 225 430 C 235 470, 285 470, 295 430 C 305 380, 310 320, 330 280 C 350 250, 400 270, 430 290" fill="none" stroke="#3182CE" stroke-width="2.5" stroke-dasharray="4,2"/>',
            '  <path d="M 430 290 L 470 310 L 510 315" fill="none" stroke="#3182CE" stroke-width="4" stroke-linecap="round"/>',
            '  <text x="515" y="319" font-size="11" font-weight="600" fill="#2B6CB0">Renal Venule</text>',
        ]

        labels = [
            ("afferent_arteriole", "Afferent Arteriole", 60, 135, 20, 85, "start"),
            ("efferent_arteriole", "Efferent Arteriole", 195, 135, 210, 85, "start"),
            ("glomerulus", "Glomerulus", 132, 185, 132, 85, "middle"),
            ("bowman_capsule", "Bowman's Capsule", 100, 225, 20, 280, "start"),
            ("proximal_convoluted_tubule", "Proximal Tubule (PCT)", 230, 250, 230, 180, "middle"),
            ("loop_of_henle", "Loop of Henle", 260, 465, 260, 500, "middle"),
            ("distal_convoluted_tubule", "Distal Tubule (DCT)", 380, 260, 380, 180, "middle"),
            ("collecting_duct", "Collecting Duct", 500, 200, 620, 200, "start"),
        ]

        for item in labels:
            key, def_txt, ax, ay, tx, ty = item[:6]
            pref_anch = item[6] if len(item) > 6 else None
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked, preferred_anchor=pref_anch))

        if caption:
            parts.append(f'  <text x="380" y="510" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 3. Human Heart Generator
    # =========================================================================
    @classmethod
    def _render_human_heart(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 540" width="100%" height="540" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="780" height="540" fill="#FFFFFF"/>',
            f'  <text x="390" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="390" y="50" font-size="12" fill="#718096" text-anchor="middle">Schematic Sectional View of the Human Heart</text>',
            '  <path d="M 290 160 C 210 160, 200 260, 220 340 C 240 420, 360 480, 390 490 C 420 480, 540 420, 560 340 C 580 260, 570 160, 490 160 C 430 160, 400 200, 390 210 C 380 200, 350 160, 290 160 Z" fill="#FEB2B2" stroke="#9B2C2C" stroke-width="4"/>',
            '  <path d="M 385 220 L 385 480 L 400 480 L 400 220 Z" fill="#C53030" stroke="#9B2C2C" stroke-width="2"/>',
            '  <path d="M 230 90 L 230 180" fill="none" stroke="#3182CE" stroke-width="24" stroke-linecap="round"/>',
            '  <path d="M 230 380 L 230 460" fill="none" stroke="#3182CE" stroke-width="20" stroke-linecap="round"/>',
            '  <path d="M 370 220 C 370 120, 470 90, 480 160" fill="none" stroke="#E53E3E" stroke-width="26" stroke-linecap="round"/>',
            '  <path d="M 400 110 L 400 80" fill="none" stroke="#E53E3E" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 430 110 L 430 80" fill="none" stroke="#E53E3E" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 460 115 L 460 85" fill="none" stroke="#E53E3E" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 350 240 C 350 160, 290 130, 260 125" fill="none" stroke="#4299E1" stroke-width="20" stroke-linecap="round"/>',
            '  <ellipse cx="300" cy="225" rx="55" ry="40" fill="#BEE3F8" stroke="#3182CE" stroke-width="2"/>',
            '  <ellipse cx="320" cy="355" rx="55" ry="60" fill="#90CDF4" stroke="#2B6CB0" stroke-width="2"/>',
            '  <ellipse cx="475" cy="225" rx="55" ry="40" fill="#FED7D7" stroke="#E53E3E" stroke-width="2"/>',
            '  <ellipse cx="460" cy="355" rx="55" ry="60" fill="#FEB2B2" stroke="#C53030" stroke-width="2"/>',
            '  <line x1="280" y1="270" x2="320" y2="280" stroke="#2B6CB0" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="460" y1="270" x2="500" y2="280" stroke="#C53030" stroke-width="3" stroke-linecap="round"/>',
        ]

        labels = [
            ("vena_cava", "Vena Cava", 230, 110, 100, 110),
            ("aorta", "Aorta", 430, 95, 590, 95),
            ("pulmonary_artery", "Pulmonary Artery", 270, 130, 100, 160),
            ("right_atrium", "Right Atrium", 300, 225, 100, 225),
            ("right_ventricle", "Right Ventricle", 320, 360, 100, 360),
            ("left_atrium", "Left Atrium", 475, 225, 660, 225),
            ("left_ventricle", "Left Ventricle", 460, 360, 660, 360),
            ("septum", "Septum", 390, 440, 390, 505),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="390" y="525" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 4. Stomata Apparatus Generator
    # =========================================================================
    @classmethod
    def _render_stomata(cls, title: str, caption: Optional[str], label_map: Dict[str, str], is_open: bool = True) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        subtitle = "Open Stomatal Pore (Turgid Guard Cells)" if is_open else "Closed Stomatal Pore (Flaccid Guard Cells)"
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 460" width="100%" height="460" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="720" height="460" fill="#FFFFFF"/>',
            f'  <text x="360" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            f'  <text x="360" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">{subtitle}</text>',
            '  <rect x="140" y="90" width="440" height="310" rx="20" fill="#F0FFF4" stroke="#9AE6B4" stroke-width="2"/>',
        ]

        if is_open:
            parts.extend([
                '  <path d="M 330 150 C 270 170, 260 290, 330 330 C 295 285, 295 195, 330 150 Z" fill="#68D391" stroke="#22543D" stroke-width="3"/>',
                '  <path d="M 390 150 C 450 170, 460 290, 390 330 C 425 285, 425 195, 390 150 Z" fill="#68D391" stroke="#22543D" stroke-width="3"/>',
                '  <ellipse cx="360" cy="240" rx="18" ry="55" fill="#2D3748" stroke="#1A202C" stroke-width="2"/>',
            ])
        else:
            parts.extend([
                '  <path d="M 350 150 C 300 170, 300 290, 350 330 C 335 290, 335 190, 350 150 Z" fill="#9AE6B4" stroke="#276749" stroke-width="3"/>',
                '  <path d="M 370 150 C 420 170, 420 290, 370 330 C 385 290, 385 190, 370 150 Z" fill="#9AE6B4" stroke="#276749" stroke-width="3"/>',
                '  <line x1="360" y1="160" x2="360" y2="320" stroke="#1A202C" stroke-width="2.5"/>',
            ])

        # Chloroplast organelles & Nuclei
        parts.extend([
            '  <circle cx="295" cy="210" r="4.5" fill="#22543D"/>',
            '  <circle cx="290" cy="240" r="4.5" fill="#22543D"/>',
            '  <circle cx="295" cy="270" r="4.5" fill="#22543D"/>',
            '  <circle cx="425" cy="210" r="4.5" fill="#22543D"/>',
            '  <circle cx="430" cy="240" r="4.5" fill="#22543D"/>',
            '  <circle cx="425" cy="270" r="4.5" fill="#22543D"/>',
            '  <circle cx="285" cy="180" r="8" fill="#E2E8F0" stroke="#4A5568" stroke-width="2"/>',
            '  <circle cx="435" cy="180" r="8" fill="#E2E8F0" stroke="#4A5568" stroke-width="2"/>',
        ])

        labels = [
            ("guard_cell", "Guard Cell", 290, 240, 110, 240),
            ("stomatal_pore", "Stomatal Pore", 360, 240, 360, 105),
            ("chloroplast", "Chloroplast", 430, 240, 600, 240),
            ("nucleus", "Nucleus", 435, 180, 600, 180),
            ("epidermal_cell", "Epidermal Cell", 220, 140, 110, 140),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="360" y="440" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 5. Leaf Cross Section Generator
    # =========================================================================
    @classmethod
    def _render_leaf_cross_section(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 480" width="100%" height="480" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="740" height="480" fill="#FFFFFF"/>',
            f'  <text x="370" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            '  <text x="370" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">Transverse Section of a Dicot Leaf</text>',
            '  <rect x="60" y="90" width="500" height="12" fill="#EBF8FF" stroke="#3182CE" stroke-width="1.5"/>',
            '  <rect x="60" y="102" width="500" height="24" fill="#EDF2F7" stroke="#718096" stroke-width="1.5"/>',
            '  <rect x="60" y="126" width="500" height="70" fill="#C6F6D5" stroke="#276749" stroke-width="1.5"/>',
            '  <rect x="60" y="196" width="500" height="120" fill="#E6FFFA" stroke="#234E52" stroke-width="1.5"/>',
            '  <circle cx="360" cy="256" r="32" fill="#FEFCBF" stroke="#D69E2E" stroke-width="2.5"/>',
            '  <path d="M 340 256 A 20 20 0 0 1 380 256 Z" fill="#E53E3E" stroke="#9B2C2C"/>',
            '  <path d="M 340 256 A 20 20 0 0 0 380 256 Z" fill="#3182CE" stroke="#2B6CB0"/>',
            '  <rect x="60" y="316" width="500" height="24" fill="#EDF2F7" stroke="#718096" stroke-width="1.5"/>',
            '  <rect x="60" y="340" width="500" height="10" fill="#EBF8FF" stroke="#3182CE" stroke-width="1.5"/>',
        ]

        labels = [
            ("waxy_cuticle", "Waxy Cuticle", 80, 95, 600, 95),
            ("upper_epidermis", "Upper Epidermis", 80, 112, 600, 112),
            ("chloroplast", "Chloroplast", 120, 140, 600, 140),
            ("palisade_mesophyll", "Palisade Mesophyll", 200, 170, 600, 170),
            ("vascular_bundle", "Vascular Bundle (Vein)", 360, 270, 600, 220),
            ("spongy_mesophyll", "Spongy Mesophyll", 220, 240, 600, 260),
            ("air_spaces", "Air Spaces", 140, 265, 600, 290),
            ("guard_cell", "Guard Cell", 240, 340, 600, 335),
            ("lower_epidermis", "Lower Epidermis", 120, 340, 600, 360),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="370" y="465" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 6. Neuron Structure Generator
    # =========================================================================
    @classmethod
    def _render_neuron(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 440" width="100%" height="440" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="440" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            '  <text x="380" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">Structure of a Motor Neuron</text>',
            '  <path d="M 170 210 L 130 150 M 170 210 L 100 190 M 170 210 L 110 240 M 170 210 L 140 280 M 170 210 L 180 285" stroke="#DD6B20" stroke-width="3" stroke-linecap="round"/>',
            '  <circle cx="170" cy="210" r="40" fill="#FEEBC8" stroke="#DD6B20" stroke-width="3"/>',
            '  <circle cx="170" cy="210" r="14" fill="#C05621"/>',
            '  <line x1="210" y1="210" x2="520" y2="210" stroke="#DD6B20" stroke-width="8" stroke-linecap="round"/>',
            '  <rect x="230" y="194" width="48" height="32" rx="8" fill="#FBD38D" stroke="#B7791F" stroke-width="2"/>',
            '  <rect x="290" y="194" width="48" height="32" rx="8" fill="#FBD38D" stroke="#B7791F" stroke-width="2"/>',
            '  <rect x="350" y="194" width="48" height="32" rx="8" fill="#FBD38D" stroke="#B7791F" stroke-width="2"/>',
            '  <rect x="410" y="194" width="48" height="32" rx="8" fill="#FBD38D" stroke="#B7791F" stroke-width="2"/>',
            '  <rect x="470" y="194" width="48" height="32" rx="8" fill="#FBD38D" stroke="#B7791F" stroke-width="2"/>',
            '  <path d="M 520 210 L 580 170 M 520 210 L 590 200 M 520 210 L 590 230 M 520 210 L 580 250" stroke="#DD6B20" stroke-width="3" stroke-linecap="round"/>',
            '  <circle cx="580" cy="170" r="4.5" fill="#C05621"/>',
            '  <circle cx="590" cy="200" r="4.5" fill="#C05621"/>',
            '  <circle cx="590" cy="230" r="4.5" fill="#C05621"/>',
            '  <circle cx="580" cy="250" r="4.5" fill="#C05621"/>',
        ]

        labels = [
            ("dendrite", "Dendrite", 110, 160, 60, 110),
            ("cell_body", "Cell Body (Cyton)", 170, 175, 170, 100),
            ("nucleus", "Nucleus", 170, 210, 170, 300),
            ("axon", "Axon", 330, 210, 330, 120),
            ("myelin_sheath", "Myelin Sheath", 374, 194, 374, 300),
            ("nerve_ending", "Nerve Endings", 585, 200, 660, 200),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="380" y="420" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 7. Reflex Arc Generator (Clean, anatomically authentic spinal pathway)
    # =========================================================================
    @classmethod
    def _render_reflex_arc(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 490" width="100%" height="490" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="490" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            '  <text x="380" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">Reflex Arc (Spinal Reflex Pathway)</text>',
            # Stimulus & Receptor (Skin / Finger)
            '  <rect x="70" y="160" width="90" height="60" rx="8" fill="#FEEBC8" stroke="#DD6B20" stroke-width="2"/>',
            '  <text x="115" y="195" font-size="12" font-weight="bold" fill="#C05621" text-anchor="middle">Heat Receptor</text>',
            '  <text x="115" y="210" font-size="10" fill="#7B341E" text-anchor="middle">(Skin in finger)</text>',
            # Effector (Arm Muscle)
            '  <rect x="70" y="290" width="90" height="60" rx="8" fill="#FED7D7" stroke="#E53E3E" stroke-width="2"/>',
            '  <text x="115" y="325" font-size="12" font-weight="bold" fill="#9B2C2C" text-anchor="middle">Effector</text>',
            '  <text x="115" y="340" font-size="10" fill="#7B341E" text-anchor="middle">(Arm Muscle)</text>',
            # Spinal Cord (Cross-section with butterfly grey matter)
            '  <ellipse cx="580" cy="250" rx="110" ry="90" fill="#EDF2F7" stroke="#A0AEC0" stroke-width="2"/>',
            '  <path d="M 530 200 C 560 215, 600 215, 630 200 C 600 240, 600 260, 630 300 C 600 285, 560 285, 530 300 C 550 260, 550 240, 530 200 Z" fill="#CBD5E0" stroke="#718096" stroke-width="2"/>',
            # Pathways: Sensory neuron (Blue afferent entering dorsal horn)
            '  <path d="M 160 190 C 260 130, 420 150, 530 200" fill="none" stroke="#3182CE" stroke-width="4" stroke-linecap="round"/>',
            # Sensory signal directional arrowhead (pointing towards spinal cord)
            '  <polygon points="335,145 315,138 322,145 315,152" fill="#3182CE"/>',
            # Relay / Interneuron (Orange - connecting dorsal to ventral horn inside grey matter)
            '  <path d="M 530 200 C 565 235, 565 265, 530 280" fill="none" stroke="#DD6B20" stroke-width="4.5" stroke-linecap="round"/>',
            # Relay neuron downward signal arrowhead
            '  <polygon points="530,250 523,235 530,240 537,235" fill="#DD6B20"/>',
            # Motor neuron (Red efferent exiting ventral horn towards effector muscle)
            '  <path d="M 530 280 C 420 350, 260 370, 160 320" fill="none" stroke="#E53E3E" stroke-width="4" stroke-linecap="round"/>',
            # Motor signal directional arrowhead (pointing leftwards towards effector muscle)
            '  <polygon points="310,364 330,356 323,364 330,372" fill="#E53E3E"/>',
            # Terminal motor arrowhead entering effector muscle
            '  <polygon points="160,320 178,312 172,320 178,328" fill="#E53E3E"/>',
        ]

        labels = [
            ("stimulus", "Stimulus (Heat)", 70, 170, 25, 115, "start"),
            ("receptor", "Receptor (Skin)", 150, 170, 150, 100, "middle"),
            ("sensory_neuron", "Sensory Neuron", 320, 145, 320, 95, "middle"),
            ("spinal_cord", "Spinal Cord", 580, 160, 580, 95, "middle"),
            ("relay_neuron", "Relay Neuron", 550, 240, 690, 240, "start"),
            ("motor_neuron", "Motor Neuron", 320, 350, 320, 405, "middle"),
            ("effector", "Effector (Muscle)", 160, 320, 160, 405, "middle"),
        ]

        for item in labels:
            key, def_txt, ax, ay, tx, ty = item[:6]
            pref_anch = item[6] if len(item) > 6 else None
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked, preferred_anchor=pref_anch))

        parts.append('  <text x="380" y="450" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">NCERT Pathway: Stimulus → Receptor (Skin) → Sensory Neuron → Spinal Cord → Motor Neuron → Effector</text>')
        if caption:
            parts.append(f'  <text x="380" y="470" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 8. Flower Anatomy Generator (Accurate filament pointer & clean labels)
    # =========================================================================
    @classmethod
    def _render_flower(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 500" width="100%" height="500" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="740" height="500" fill="#FFFFFF"/>',
            f'  <text x="370" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            '  <text x="370" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">Longitudinal Section of a Flower (Reproductive Parts)</text>',
            # Stem & Receptacle (Thalamus)
            '  <line x1="370" y1="420" x2="370" y2="470" stroke="#38A169" stroke-width="12" stroke-linecap="round"/>',
            '  <ellipse cx="370" cy="415" rx="50" ry="20" fill="#48BB78" stroke="#2F855A" stroke-width="2"/>',
            # Sepals (Green calyx)
            '  <path d="M 330 415 C 270 410, 250 370, 240 330 C 270 360, 310 390, 340 405 Z" fill="#68D391" stroke="#2F855A" stroke-width="2"/>',
            '  <path d="M 410 415 C 470 410, 490 370, 500 330 C 470 360, 430 390, 400 405 Z" fill="#68D391" stroke="#2F855A" stroke-width="2"/>',
            # Petals (Pink/Magenta corolla)
            '  <path d="M 330 405 C 190 360, 160 180, 240 120 C 300 200, 340 320, 350 370 Z" fill="#FBB6CE" stroke="#D53F8C" stroke-width="2"/>',
            '  <path d="M 410 405 C 550 360, 580 180, 500 120 C 440 200, 400 320, 390 370 Z" fill="#FBB6CE" stroke="#D53F8C" stroke-width="2"/>',
            # Pistil / Carpel (Ovary, Style, Stigma)
            '  <ellipse cx="370" cy="360" rx="40" ry="50" fill="#FEFCBF" stroke="#D69E2E" stroke-width="2"/>',
            '  <circle cx="370" cy="365" r="16" fill="#FAF089" stroke="#B7791F" stroke-width="2"/>',
            '  <circle cx="370" cy="365" r="6" fill="#D69E2E"/>',
            '  <line x1="370" y1="310" x2="370" y2="160" stroke="#D69E2E" stroke-width="10" stroke-linecap="round"/>',
            '  <path d="M 350 160 C 350 140, 390 140, 390 160 Z" fill="#ECC94B" stroke="#B7791F" stroke-width="2"/>',
            # Left Stamen (Stalk / Filament and Anther)
            '  <path d="M 345 370 C 310 320, 290 230, 290 170" fill="none" stroke="#A0AEC0" stroke-width="4.5" stroke-linecap="round"/>',
            '  <ellipse cx="290" cy="165" rx="14" ry="8" fill="#ECC94B" stroke="#D69E2E" stroke-width="2"/>',
            # Right Stamen
            '  <path d="M 395 370 C 430 320, 450 230, 450 170" fill="none" stroke="#A0AEC0" stroke-width="4.5" stroke-linecap="round"/>',
            '  <ellipse cx="450" cy="165" rx="14" ry="8" fill="#ECC94B" stroke="#D69E2E" stroke-width="2"/>',
        ]

        labels = [
            ("petal", "Petal", 230, 160, 110, 160),
            ("stigma", "Stigma", 370, 150, 240, 90),
            ("anther", "Anther", 290, 165, 140, 120),
            # Precise pointer to stamen stalk
            ("filament", "Filament", 290, 220, 140, 220),
            ("style", "Style", 370, 230, 500, 230),
            ("ovary", "Ovary", 370, 350, 560, 340),
            ("ovule", "Ovule", 370, 365, 560, 375),
            ("sepal", "Sepal", 250, 350, 140, 350),
            ("receptacle", "Receptacle", 370, 415, 560, 415),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="370" y="490" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 9. Plant Cell Structure Generator
    # =========================================================================
    @classmethod
    def _render_plant_cell(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 480" width="100%" height="480" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="740" height="480" fill="#FFFFFF"/>',
            f'  <text x="370" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            '  <text x="370" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">Anatomy of a Typical Plant Cell</text>',
            '  <polygon points="120,90 480,80 620,180 580,390 220,410 100,280" fill="#C6F6D5" stroke="#22543D" stroke-width="8"/>',
            '  <polygon points="125,95 475,85 612,182 573,383 223,403 107,278" fill="#E6FFFA" stroke="#276749" stroke-width="3"/>',
            '  <ellipse cx="340" cy="260" rx="140" ry="85" fill="#EBF8FF" stroke="#3182CE" stroke-width="2.5"/>',
            '  <circle cx="440" cy="180" r="35" fill="#FED7D7" stroke="#9B2C2C" stroke-width="2.5"/>',
            '  <circle cx="440" cy="180" r="12" fill="#742A2A"/>',
            '  <ellipse cx="200" cy="150" rx="22" ry="14" fill="#68D391" stroke="#22543D" stroke-width="1.5"/>',
            '  <ellipse cx="220" cy="350" rx="22" ry="14" fill="#68D391" stroke="#22543D" stroke-width="1.5" transform="rotate(30 220 350)"/>',
            '  <ellipse cx="480" cy="320" rx="22" ry="14" fill="#68D391" stroke="#22543D" stroke-width="1.5" transform="rotate(-15 480 320)"/>',
            '  <ellipse cx="280" cy="140" rx="18" ry="10" fill="#FED7D7" stroke="#C53030" stroke-width="1.5" transform="rotate(20 280 140)"/>',
            '  <ellipse cx="380" cy="380" rx="18" ry="10" fill="#FED7D7" stroke="#C53030" stroke-width="1.5"/>',
        ]

        labels = [
            ("cell_wall", "Cell Wall", 100, 250, 40, 180),
            ("cell_membrane", "Plasma Membrane", 110, 260, 40, 250),
            ("chloroplast", "Chloroplast", 200, 150, 120, 110),
            ("mitochondria", "Mitochondrion", 280, 140, 280, 75),
            ("nucleus", "Nucleus", 440, 180, 620, 150),
            ("vacuole", "Central Vacuole", 320, 270, 620, 250),
            ("cytoplasm", "Cytoplasm", 460, 360, 620, 360),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="370" y="470" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 10. Digestive System Generator
    # =========================================================================
    @classmethod
    def _render_digestive_system(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 540" width="100%" height="540" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="740" height="540" fill="#FFFFFF"/>',
            f'  <text x="370" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            '  <text x="370" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">Human Alimentary Canal (Digestive System)</text>',
            '  <path d="M 330 90 C 350 70, 390 70, 400 90 C 400 110, 370 120, 360 130" fill="none" stroke="#ED8936" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 360 130 L 360 230" fill="none" stroke="#ED8936" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 360 230 C 340 230, 300 240, 300 280 C 300 320, 360 330, 390 310" fill="#FEB2B2" stroke="#C53030" stroke-width="4"/>',
            '  <polygon points="410,210 470,250 390,260" fill="#C53030" stroke="#9B2C2C" stroke-width="3"/>',
            '  <ellipse cx="420" cy="265" rx="10" ry="7" fill="#68D391" stroke="#22543D" stroke-width="1.5"/>',
            '  <path d="M 350 310 C 380 305, 410 315, 430 310" fill="none" stroke="#ECC94B" stroke-width="8" stroke-linecap="round"/>',
            '  <path d="M 270 380 L 270 330 L 440 330 L 440 430 L 380 430 L 380 480" fill="none" stroke="#DD6B20" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>',
            '  <path d="M 320 370 Q 360 360 390 380 Q 340 400 380 410 Q 320 420 350 430" fill="none" stroke="#FEB2B2" stroke-width="14" stroke-linecap="round"/>',
            '  <line x1="380" y1="480" x2="380" y2="500" stroke="#C05621" stroke-width="10" stroke-linecap="round"/>',
        ]

        labels = [
            ("mouth", "Mouth (Buccal Cavity)", 360, 95, 200, 95),
            ("oesophagus", "Oesophagus (Food Pipe)", 360, 180, 200, 180),
            ("stomach", "Stomach", 330, 270, 180, 270),
            ("liver", "Liver", 440, 235, 560, 235),
            ("gall_bladder", "Gall Bladder", 420, 265, 560, 270),
            ("pancreas", "Pancreas", 410, 310, 560, 310),
            ("small_intestine", "Small Intestine", 360, 390, 560, 390),
            ("large_intestine", "Large Intestine", 440, 350, 560, 350),
            ("anus", "Anus", 380, 500, 560, 500),
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="370" y="530" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 11. Human Eye & Vision Defect Correction (Myopia & Hypermetropia)
    # =========================================================================
    @classmethod
    def _render_human_eye(cls, title: str, caption: Optional[str], label_map: Dict[str, str], mode: str = "myopia") -> str:
        """
        Renders authentic optical ray diagram for the human eye, showing image formation
        and correction using concave (myopia) or convex (hypermetropia) lenses.
        """
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        is_hyper = (mode == "hypermetropia")
        subtitle = "Ray Diagram: Hypermetropic Eye and Its Optical Correction (Convex Lens)" if is_hyper else "Ray Diagram: Myopic Eye and Its Optical Correction (Concave Lens)"

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 480" width="100%" height="480" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="480" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size=\"17\" font-weight=\"bold\" fill=\"#1A202C\" text-anchor=\"middle\">{title}</text>',
            f'  <text x="380" y="50" font-size=\"12\" fill=\"#718096\" text-anchor=\"middle\">{subtitle}</text>',
            '  <defs>',
            '    <linearGradient id="corneaGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#EBF8FF" />',
            '      <stop offset="100%" stop-color="#BEE3F8" />',
            '    </linearGradient>',
            '    <linearGradient id="lensGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#E2E8F0" />',
            '      <stop offset="100%" stop-color="#CBD5E0" />',
            '    </linearGradient>',
            '  </defs>',
            # Eyeball sphere (white sclera with yellow retina lining posterior)
            '  <ellipse cx="440" cy="240" rx="140" ry="130" fill="#F7FAFC" stroke="#4A5568" stroke-width="3"/>',
            '  <path d="M 440 110 A 140 130 0 0 1 580 240 A 140 130 0 0 1 440 370" fill="none" stroke="#F6E05E" stroke-width="7"/>',
            # Optic Nerve (exit at posterior bottom)
            '  <path d="M 570 260 L 640 280 L 640 310 L 550 280 Z" fill="#ED8936" stroke="#C05621" stroke-width="2"/>',
            # Cornea anterior bulge
            '  <path d="M 335 170 C 285 200, 285 280, 335 310" fill="url(#corneaGrad)" stroke="#3182CE" stroke-width="3"/>',
            # Crystalline Lens (Biconvex lens)
            '  <path d="M 360 180 C 375 200, 375 280, 360 300 C 345 280, 345 200, 360 180 Z" fill="url(#lensGrad)" stroke="#4A5568" stroke-width="2.5"/>',
            # Ciliary Muscles (Top and bottom suspensory ligaments)
            '  <path d="M 360 160 L 360 180" stroke="#C53030" stroke-width="8" stroke-linecap="round"/>',
            '  <path d="M 360 300 L 360 320" stroke="#C53030" stroke-width="8" stroke-linecap="round"/>',
            # Principal Optical Axis (Horizontal dashed centerline)
            '  <line x1="50" y1="240" x2="650" y2="240" stroke="#A0AEC0" stroke-width="1.5" stroke-dasharray="4,4"/>',
        ]

        if is_hyper:
            # Hypermetropia: Corrected by Convex Lens
            parts.extend([
                # Convex Corrective Lens placed in front of eye
                '  <path d="M 220 160 C 235 200, 235 280, 220 320 C 205 280, 205 200, 220 160 Z" fill="#EBF8FF" stroke="#3182CE" stroke-width="2.5"/>',
                # Near Object N
                '  <circle cx="70" cy="240" r="4.5" fill="#C53030"/>',
                '  <text x="70" y="260" font-size="11" font-weight="bold" fill="#C53030" text-anchor="middle">N (Near Object)</text>',
                # Diverging incident rays from N entering convex lens
                '  <line x1="70" y1="240" x2="220" y2="190" stroke="#E53E3E" stroke-width="2"/>',
                '  <line x1="70" y1="240" x2="220" y2="290" stroke="#E53E3E" stroke-width="2"/>',
                # Pre-converged rays passing from convex lens into eye lens
                '  <line x1="220" y1="190" x2="350" y2="195" stroke="#E53E3E" stroke-width="2"/>',
                '  <line x1="220" y1="290" x2="350" y2="285" stroke="#E53E3E" stroke-width="2"/>',
                # Corrected refracted rays focusing sharply ON retina
                '  <line x1="365" y1="195" x2="578" y2="240" stroke="#E53E3E" stroke-width="2"/>',
                '  <line x1="365" y1="285" x2="578" y2="240" stroke="#E53E3E" stroke-width="2"/>',
                '  <circle cx="578" cy="240" r="4.5" fill="#E53E3E"/>',
                '  <text x="578" y="260" font-size="11" font-weight="bold" fill="#E53E3E" text-anchor="middle">Corrected Focus on Retina</text>',
                # Dotted rays showing uncorrected hypermetropic focus (BEHIND retina)
                '  <line x1="365" y1="195" x2="640" y2="240" stroke="#718096" stroke-width="1.5" stroke-dasharray="3,3"/>',
                '  <line x1="365" y1="285" x2="640" y2="240" stroke="#718096" stroke-width="1.5" stroke-dasharray="3,3"/>',
                '  <circle cx="640" cy="240" r="3.5" fill="#718096"/>',
                '  <text x="640" y="260" font-size="11" font-weight="bold" fill="#718096" text-anchor="middle">Uncorrected Focus (Behind Retina)</text>',
            ])
            lens_label = ("convex_lens", "Convex Lens (Correction)", 220, 160, 140, 120)
        else:
            # Myopia: Corrected by Concave Lens
            parts.extend([
                # Concave Corrective Lens placed in front of eye
                '  <path d="M 210 160 C 220 200, 220 280, 210 320 L 230 320 C 220 280, 220 200, 230 160 Z" fill="#EBF8FF" stroke="#3182CE" stroke-width="2.5"/>',
                # Parallel incident rays from distant object
                '  <line x1="60" y1="190" x2="215" y2="190" stroke="#E53E3E" stroke-width="2"/>',
                '  <line x1="60" y1="290" x2="215" y2="290" stroke="#E53E3E" stroke-width="2"/>',
                # Diverging rays through concave lens
                '  <line x1="215" y1="190" x2="350" y2="185" stroke="#E53E3E" stroke-width="2"/>',
                '  <line x1="215" y1="290" x2="350" y2="295" stroke="#E53E3E" stroke-width="2"/>',
                # Converging refracted rays through eye lens focusing SHARPLY on the retina
                '  <line x1="365" y1="185" x2="578" y2="240" stroke="#E53E3E" stroke-width="2"/>',
                '  <line x1="365" y1="295" x2="578" y2="240" stroke="#E53E3E" stroke-width="2"/>',
                '  <circle cx="578" cy="240" r="4.5" fill="#E53E3E"/>',
                '  <text x="578" y="260" font-size="11" font-weight="bold" fill="#E53E3E" text-anchor="middle">Corrected Focus on Retina</text>',
                # Dotted rays showing uncorrected myopic focus (in front of retina)
                '  <line x1="365" y1="185" x2="505" y2="240" stroke="#718096" stroke-width="1.5" stroke-dasharray="3,3"/>',
                '  <line x1="365" y1="295" x2="505" y2="240" stroke="#718096" stroke-width="1.5" stroke-dasharray="3,3"/>',
                '  <circle cx="505" cy="240" r="3.5" fill="#718096"/>',
                '  <text x="505" y="222" font-size="11" font-weight="bold" fill="#718096" text-anchor="middle">Uncorrected Focus (In Front of Retina)</text>',
            ])
            lens_label = ("concave_lens", "Concave Lens (Correction)", 220, 160, 140, 120)

        labels = [
            ("cornea", "Cornea", 305, 220, 260, 120),
            ("crystalline_lens", "Crystalline Eye Lens", 360, 185, 360, 110),
            ("ciliary_muscle", "Ciliary Muscles", 360, 160, 460, 110),
            ("retina", "Retina", 560, 200, 650, 170),
            ("optic_nerve", "Optic Nerve", 610, 290, 680, 340),
            lens_label,
        ]

        for key, def_txt, ax, ay, tx, ty in labels:
            display_text = get_lbl(key, def_txt)
            masked = is_masked(key)
            parts.extend(cls._render_callout_label(ax, ay, tx, ty, display_text, masked))

        if caption:
            parts.append(f'  <text x="380" y="460" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 12. Ecological Pyramid Generator (Stepped Energy & Trophic Hierarchy)
    # =========================================================================
    @classmethod
    def _render_ecological_pyramid(cls, title: str, caption: Optional[str], label_map: Dict[str, str], data: Dict[str, Any]) -> str:
        """
        Renders an authentic stepped trapezoidal ecological pyramid demonstrating
        Lindeman's 10% law across 4 trophic levels (T1 -> T4).
        """
        def get_lbl(key: str, default: str) -> str:
            return label_map.get(key.lower(), default)

        def is_masked(key: str) -> bool:
            return key.lower() in label_map

        # Parse energy values or default to 10,000 J base
        series = data.get("series") or []
        base_val = 10000.0
        if series and isinstance(series, list) and len(series) > 0:
            raw_vals = series[0].get("values")
            if raw_vals and len(raw_vals) > 0:
                try:
                    v0 = float(raw_vals[0])
                    if v0 > 0:
                        base_val = v0
                except (ValueError, TypeError):
                    pass

        # Strictly enforce Lindeman's 10% Law: each trophic level gets exactly 10% of previous
        e1 = base_val
        e2 = e1 * 0.10
        e3 = e2 * 0.10
        e4 = e3 * 0.10

        def fmt_energy(e: float) -> str:
            if e >= 1 and e == int(e):
                return f"{int(e):,} J"
            elif e >= 1:
                return f"{e:,.1f} J"
            else:
                return f"{e:.2f} J"

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 490" width="100%" height="490" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="490" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Trophic Energy Pyramid: Lindeman&#x27;s 10% Law &amp; Progressive Energy Dissipation</text>',
            '  <defs>',
            '    <marker id="heatArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#E53E3E"/>',
            '    </marker>',
            '    <marker id="upArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#3182CE"/>',
            '    </marker>',
            '  </defs>',
        ]

        # 4 Tiers configuration (Bottom to Top)
        tiers = [
            {"tier": "T1", "name": "Producers (Autotrophs / Green Plants)", "energy": f"{fmt_energy(e1)}", "w": 520, "y": 350, "fill": "#C6F6D5", "stroke": "#276749"},
            {"tier": "T2", "name": "Primary Consumers (Herbivores)", "energy": f"{fmt_energy(e2)} (10%)", "w": 390, "y": 280, "fill": "#FEFCBF", "stroke": "#D69E2E"},
            {"tier": "T3", "name": "Secondary Consumers (Carnivores)", "energy": f"{fmt_energy(e3)} (1%)", "w": 260, "y": 210, "fill": "#FEEBC8", "stroke": "#DD6B20"},
            {"tier": "T4", "name": "Tertiary Consumers (Top Carnivores)", "energy": f"{fmt_energy(e4)} (0.1%)", "w": 130, "y": 140, "fill": "#FED7D7", "stroke": "#E53E3E"},
        ]

        for t in tiers:
            w = t["w"]
            y = t["y"]
            x = 380 - w / 2.0
            parts.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="70" rx="4" fill="{t["fill"]}" stroke="{t["stroke"]}" stroke-width="2.5"/>')
            parts.append(f'  <text x="380" y="{y + 28:.1f}" font-size="13" font-weight="bold" fill="#1A202C" text-anchor="middle">{t["tier"]}: {t["name"]}</text>')
            parts.append(f'  <text x="380" y="{y + 48:.1f}" font-size="12" font-weight="bold" fill="{t["stroke"]}" text-anchor="middle">Energy: {t["energy"]}</text>')

            # Right-side heat dissipation arrow (strictly uniform 90% heat loss at each tier)
            rx = x + w
            ry = y + 35
            parts.append(f'  <path d="M {rx:.1f} {ry:.1f} Q {rx + 30:.1f} {ry - 10:.1f} {rx + 50:.1f} {ry - 20:.1f}" fill="none" stroke="#E53E3E" stroke-width="2" stroke-dasharray="3,2" marker-end="url(#heatArrow)"/>')
            parts.append(f'  <text x="{rx + 55:.1f}" y="{ry - 18:.1f}" font-size="10" font-weight="bold" fill="#C53030" text-anchor="start">90% Heat Loss</text>')

        # Left-side upward 10% transfer arrow
        parts.append('  <line x1="80" y1="410" x2="80" y2="150" stroke="#3182CE" stroke-width="3" marker-end="url(#upArrow)"/>')
        parts.append('  <text x="70" y="280" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle" transform="rotate(-90 70 280)">10% Energy Transfer to Next Level</text>')

        if caption:
            parts.append(f'  <text x="380" y="465" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 13. Phototropism Experiment (Plant Shoot Bending in Dark Box)
    # =========================================================================
    @classmethod
    def _render_phototropism(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> Tuple[str, bool]:
            val = label_map.get(key.lower())
            return (val, True) if val else (default, False)

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 510" width="100%" height="510" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="510" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Phototropism: Response of Plant Shoot to Unilateral Directional Light</text>',
            '  <defs>',
            '    <marker id="lightRayArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#D69E2E"/>',
            '    </marker>',
            '    <linearGradient id="boxGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#2D3748"/>',
            '      <stop offset="100%" stop-color="#1A202C"/>',
            '    </linearGradient>',
            '    <linearGradient id="sunbeamGrad" x1="0%" y1="0%" x2="100%" y2="0%">',
            '      <stop offset="0%" stop-color="#FEFCBF" stop-opacity="0.0"/>',
            '      <stop offset="100%" stop-color="#FEFCBF" stop-opacity="0.45"/>',
            '    </linearGradient>',
            '  </defs>',
            # Dark Chamber (Outer wooden box)
            '  <rect x="130" y="80" width="450" height="370" rx="8" fill="url(#boxGrad)" stroke="#1A202C" stroke-width="3"/>',
            # Chamber floor
            '  <rect x="130" y="440" width="450" height="10" fill="#4A5568"/>',
            # Right-side Window / Slit (Allowing light to enter unilaterally)
            '  <rect x="575" y="140" width="10" height="120" fill="#FEFCBF" stroke="#ECC94B" stroke-width="2"/>',
            # Golden sunlight rays entering through window slit
            '  <polygon points="575,140 380,180 380,240 575,260" fill="url(#sunbeamGrad)"/>',
            '  <line x1="680" y1="130" x2="590" y2="160" stroke="#D69E2E" stroke-width="2.5" marker-end="url(#lightRayArrow)"/>',
            '  <line x1="680" y1="200" x2="590" y2="200" stroke="#D69E2E" stroke-width="2.5" marker-end="url(#lightRayArrow)"/>',
            '  <line x1="680" y1="270" x2="590" y2="240" stroke="#D69E2E" stroke-width="2.5" marker-end="url(#lightRayArrow)"/>',
            # External Sun / Light Source
            '  <circle cx="700" cy="200" r="28" fill="#ECC94B" stroke="#D69E2E" stroke-width="2.5"/>',
            '  <line x1="700" y1="160" x2="700" y2="148" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="700" y1="240" x2="700" y2="252" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="660" y1="200" x2="648" y2="200" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="740" y1="200" x2="752" y2="200" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="672" y1="172" x2="663" y2="163" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="728" y1="228" x2="737" y2="237" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="672" y1="228" x2="663" y2="237" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <line x1="728" y1="172" x2="737" y2="163" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            '  <text x="700" y="246" font-size="11" font-weight="bold" fill="#B7791F" text-anchor="middle">Light Source</text>',
            # Conical Flask / Pot with water/soil at bottom
            '  <path d="M 290 440 L 320 360 L 340 360 L 340 340 L 300 340 L 300 330 L 360 330 L 360 340 L 320 340 L 320 360 L 370 440 Z" fill="#E2E8F0" stroke="#CBD5E0" stroke-width="2"/>',
            '  <ellipse cx="330" cy="435" rx="35" ry="5" fill="#4A5568"/>',
            # Plant Shoot Stem: curves smoothly from base (330, 330) toward light window (490, 200)
            '  <path d="M 330 330 C 330 270, 360 230, 480 200" fill="none" stroke="#48BB78" stroke-width="12" stroke-linecap="round"/>',
            # Shaded side auxin indicator (left/upper contour of stem receives less light, auxin accumulates)
            '  <path d="M 324 330 C 324 266, 354 224, 476 194" fill="none" stroke="#2F855A" stroke-width="2.5" stroke-dasharray="4,2"/>',
            # Foliage leaves at the shoot tip, facing the light
            '  <path d="M 480 200 C 510 180, 525 195, 500 215 C 485 210, 475 205, 480 200 Z" fill="#38A169" stroke="#22543D" stroke-width="1.5"/>',
            '  <path d="M 480 200 C 495 170, 520 170, 510 195 Z" fill="#48BB78" stroke="#22543D" stroke-width="1.5"/>',
            '  <path d="M 470 205 C 485 225, 505 230, 490 215 Z" fill="#2F855A" stroke="#22543D" stroke-width="1.5"/>',
            # Plant Root: growing downwards / curving away from light (Positive geotropism)
            '  <path d="M 330 365 C 330 395, 320 415, 310 435" fill="none" stroke="#D69E2E" stroke-width="4" stroke-linecap="round"/>',
            '  <path d="M 330 380 C 340 400, 345 420, 345 435" fill="none" stroke="#D69E2E" stroke-width="3" stroke-linecap="round"/>',
            # Explanatory badge for Auxin mechanism
            '  <rect x="150" y="95" width="230" height="75" rx="6" fill="#1A202C" stroke="#48BB78" stroke-width="1.5"/>',
            '  <text x="265" y="115" font-size="12" font-weight="bold" fill="#68D391" text-anchor="middle">Auxin Differential Growth</text>',
            '  <text x="265" y="133" font-size="11" fill="#E2E8F0" text-anchor="middle">• Auxin diffuses to shaded side</text>',
            '  <text x="265" y="149" font-size="11" fill="#E2E8F0" text-anchor="middle">• Shaded cells elongate faster</text>',
            '  <text x="265" y="163" font-size="11" fill="#FEFCBF" text-anchor="middle">• Shoot curves toward light</text>',
        ]

        # Callouts with masking support
        lbl_shoot, m_shoot = get_lbl("shoot", "Shoot (Positive Phototropism)")
        lbl_auxin, m_auxin = get_lbl("auxin", "Auxin Accumulation on Shaded Side")
        lbl_window, m_window = get_lbl("window", "Aperture / Window in Dark Box")
        lbl_root, m_root = get_lbl("roots", "Roots (Positive Geotropism)")

        parts.extend(cls._render_callout_label(490.0, 195.0, 520.0, 120.0, lbl_shoot, m_shoot, preferred_anchor="start"))
        parts.extend(cls._render_callout_label(360.0, 240.0, 230.0, 220.0, lbl_auxin, m_auxin, preferred_anchor="end"))
        parts.extend(cls._render_callout_label(580.0, 190.0, 640.0, 290.0, lbl_window, m_window, preferred_anchor="start"))
        parts.extend(cls._render_callout_label(320.0, 420.0, 200.0, 420.0, lbl_root, m_root, preferred_anchor="end"))

        # Footer principle
        parts.append('  <text x="380" y="480" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">NCERT Principle: Shoot bends towards unilateral light (Positive Phototropism) mediated by Auxin</text>')
        if caption:
            parts.append(f'  <text x="380" y="498" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 14. Human Female Reproductive System
    # =========================================================================
    @classmethod
    def _render_female_reproductive_system(cls, title: str, caption: Optional[str], label_map: Dict[str, str]) -> str:
        def get_lbl(key: str, default: str) -> Tuple[str, bool]:
            val = label_map.get(key.lower())
            return (val, True) if val else (default, False)

        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 520" width="100%" height="520" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="520" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Human Female Reproductive System (Frontal Section)</text>',
            '  <defs>',
            '    <linearGradient id="uterusWallGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#FED7E2"/>',
            '      <stop offset="100%" stop-color="#FBB6CE"/>',
            '    </linearGradient>',
            '    <linearGradient id="ovaryGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
            '      <stop offset="0%" stop-color="#FEFCBF"/>',
            '      <stop offset="100%" stop-color="#FAF089"/>',
            '    </linearGradient>',
            '  </defs>',
            # Broad Ligament / Background anatomy
            '  <path d="M 230 220 C 230 330, 290 390, 340 390 L 420 390 C 470 390, 530 330, 530 220 Z" fill="#FFF5F7" fill-opacity="0.6"/>',
            # Ovarian Ligaments connecting ovaries to uterus
            '  <path d="M 230 250 C 260 240, 290 230, 320 225" fill="none" stroke="#ED64A6" stroke-width="3"/>',
            '  <path d="M 530 250 C 500 240, 470 230, 440 225" fill="none" stroke="#ED64A6" stroke-width="3"/>',
            # Left Ovary (Almond shaped)
            '  <ellipse cx="210" cy="250" rx="30" ry="20" fill="url(#ovaryGrad)" stroke="#D69E2E" stroke-width="2.5"/>',
            '  <circle cx="210" cy="250" r="8" fill="#ECC94B" stroke="#B7791F" stroke-width="1.5"/>',
            # Right Ovary (Almond shaped)
            '  <ellipse cx="550" cy="250" rx="30" ry="20" fill="url(#ovaryGrad)" stroke="#D69E2E" stroke-width="2.5"/>',
            '  <circle cx="550" cy="250" r="8" fill="#ECC94B" stroke="#B7791F" stroke-width="1.5"/>',
            # Left Fallopian Tube (Oviduct)
            # Extends from upper uterus (320, 160), arches upwards and outwards to (180, 130), then curves down over ovary with fimbriae (190, 225)
            '  <path d="M 320 160 C 250 140, 160 140, 160 200 C 160 225, 180 235, 195 230" fill="none" stroke="#D53F8C" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 320 160 C 250 140, 160 140, 160 200 C 160 225, 180 235, 195 230" fill="none" stroke="#FFF5F7" stroke-width="6" stroke-linecap="round"/>',
            # Fimbriated funnel grasping ovary
            '  <path d="M 180 215 C 190 225, 200 230, 205 235 M 175 225 C 185 235, 195 238, 200 242 M 170 220 C 180 228, 190 232, 195 235" stroke="#D53F8C" stroke-width="2.5" stroke-linecap="round"/>',
            # Right Fallopian Tube (Oviduct)
            '  <path d="M 440 160 C 510 140, 600 140, 600 200 C 600 225, 580 235, 565 230" fill="none" stroke="#D53F8C" stroke-width="12" stroke-linecap="round"/>',
            '  <path d="M 440 160 C 510 140, 600 140, 600 200 C 600 225, 580 235, 565 230" fill="none" stroke="#FFF5F7" stroke-width="6" stroke-linecap="round"/>',
            # Fimbriae right
            '  <path d="M 580 215 C 570 225, 560 230, 555 235 M 585 225 C 575 235, 565 238, 560 242 M 590 220 C 580 228, 570 232, 565 235" stroke="#D53F8C" stroke-width="2.5" stroke-linecap="round"/>',
            # Uterus (Outer Myometrium / Muscular Wall)
            '  <path d="M 320 160 C 350 135, 410 135, 440 160 C 470 210, 440 310, 415 360 L 345 360 C 320 310, 290 210, 320 160 Z" fill="url(#uterusWallGrad)" stroke="#B83280" stroke-width="3"/>',
            # Uterus Cavity (Inverted triangle lined with vascular endometrium)
            '  <path d="M 340 175 C 360 160, 400 160, 420 175 C 435 220, 415 280, 395 320 L 365 320 C 345 280, 325 220, 340 175 Z" fill="#FFF5F7" stroke="#ED64A6" stroke-width="2"/>',
            # Cervix (Neck of uterus)
            '  <rect x="345" y="360" width="70" height="45" fill="#FED7E2" stroke="#B83280" stroke-width="2.5"/>',
            '  <line x1="380" y1="360" x2="380" y2="405" stroke="#D53F8C" stroke-width="4"/>',
            # Vagina (Fibromuscular tube)
            '  <path d="M 345 405 L 340 470 L 420 470 L 415 405 Z" fill="#FBB6CE" stroke="#B83280" stroke-width="2.5"/>',
            '  <line x1="380" y1="405" x2="380" y2="470" stroke="#97266D" stroke-width="3" stroke-dasharray="4,3"/>',
        ]

        # Callouts with masking support
        lbl_tube, m_tube = get_lbl("oviduct", "Oviduct / Fallopian Tube (Site of Fertilisation)")
        if not m_tube and "fallopian_tube" in label_map:
            lbl_tube, m_tube = get_lbl("fallopian_tube", "Oviduct / Fallopian Tube")
        lbl_ovary, m_ovary = get_lbl("ovary", "Ovary (Production of Ova & Estrogen)")
        lbl_uterus, m_uterus = get_lbl("uterus", "Uterus (Site of Implantation & Fetal Development)")
        lbl_cervix, m_cervix = get_lbl("cervix", "Cervix")
        lbl_vagina, m_vagina = get_lbl("vagina", "Vagina (Birth Canal)")

        parts.extend(cls._render_callout_label(170.0, 160.0, 90.0, 120.0, lbl_tube, m_tube, preferred_anchor="end"))
        parts.extend(cls._render_callout_label(210.0, 250.0, 90.0, 250.0, lbl_ovary, m_ovary, preferred_anchor="end"))
        parts.extend(cls._render_callout_label(380.0, 220.0, 630.0, 170.0, lbl_uterus, m_uterus, preferred_anchor="start"))
        parts.extend(cls._render_callout_label(415.0, 380.0, 520.0, 380.0, lbl_cervix, m_cervix, preferred_anchor="start"))
        parts.extend(cls._render_callout_label(420.0, 440.0, 520.0, 440.0, lbl_vagina, m_vagina, preferred_anchor="start"))

        # Footer note
        parts.append('  <text x="380" y="495" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">NCERT Pathway: Ovary → Oviduct (Fertilisation) → Uterus (Implantation) → Cervix → Vagina</text>')
        if caption:
            parts.append(f'  <text x="380" y="512" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

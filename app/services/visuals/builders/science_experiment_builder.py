import html
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class ScienceExperimentBuilder:
    """
    Deterministic, high-fidelity SVG rendering engine for Physics & Chemistry
    experimental laboratory apparatus and classical phenomenon diagrams:
    1. glass_slab_refraction: Optical refraction through a rectangular glass block
       with normals, angles of incidence/refraction/emergence, and lateral displacement (d).
    2. magnetic_field_wire: Concentric circular magnetic field lines around a straight
       current-carrying conductor on a horizontal cardboard plane (Right-Hand Thumb Rule).
    3. water_electrolysis: Laboratory apparatus for the electrolysis of water showing
       plastic mug, carbon electrodes, 6V battery, and 2:1 volume collection of H2 and O2.
    """

    @classmethod
    def render(cls, spec: Any) -> str:
        """
        Main entry point for Science Experiment SVG rendering.
        Accepts VisualSpec or raw dictionary payload.
        """
        title = getattr(spec, "title", None) or (spec.get("title") if isinstance(spec, dict) else "Experimental Setup")
        caption = getattr(spec, "caption", None) or (spec.get("caption") if isinstance(spec, dict) else None)
        data_raw = getattr(spec, "data", None) or getattr(spec, "spec_data", None) or (spec.get("spec_data") or spec.get("data") if isinstance(spec, dict) else {})

        template_id = str(data_raw.get("template") or data_raw.get("format") or "").lower().strip()
        title_escaped = html.escape(str(title))
        caption_escaped = html.escape(str(caption)) if caption else None

        t_low = title_escaped.lower()
        if template_id in ["glass_prism", "prism", "prism_refraction", "prism_dispersion", "dispersion", "triangular_prism"] or "prism" in t_low or "dispersion" in t_low:
            return cls._render_glass_prism(title_escaped, caption_escaped, data_raw)
        elif template_id in ["glass_slab", "glass_slab_refraction", "refraction_slab", "lateral_displacement"] or "slab" in t_low or "refraction" in t_low or "glass" in t_low:
            return cls._render_glass_slab_refraction(title_escaped, caption_escaped, data_raw)
        elif template_id in ["magnetic_field_wire", "magnetic_field", "straight_wire", "oersted"] or "magnetic" in t_low or "wire" in t_low or "conductor" in t_low:
            return cls._render_magnetic_field_wire(title_escaped, caption_escaped, data_raw)
        elif template_id in ["water_electrolysis", "electrolysis", "electrolysis_of_water"] or "electrolysis" in t_low or "water" in t_low:
            return cls._render_water_electrolysis(title_escaped, caption_escaped, data_raw)
        else:
            # Default fallback for science experiments: Glass slab refraction
            return cls._render_glass_slab_refraction(title_escaped, caption_escaped, data_raw)

    # =========================================================================
    # 1. Refraction through a Rectangular Glass Slab
    # =========================================================================
    @classmethod
    def _render_glass_slab_refraction(cls, title: str, caption: Optional[str], data: Dict[str, Any]) -> str:
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 500" width="100%" height="500" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="500" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Refraction of Light through a Rectangular Glass Slab &amp; Lateral Displacement</text>',
            '  <defs>',
            '    <marker id="rayArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#E53E3E"/>',
            '    </marker>',
            '    <linearGradient id="glassGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
            '      <stop offset="0%" stop-color="#EBF8FF" stop-opacity="0.8"/>',
            '      <stop offset="100%" stop-color="#BEE3F8" stop-opacity="0.9"/>',
            '    </linearGradient>',
            '  </defs>',
            # Rectangular Glass Slab ABCD
            '  <rect x="180" y="160" width="400" height="180" fill="url(#glassGrad)" stroke="#3182CE" stroke-width="2.5" rx="2"/>',
            '  <text x="200" y="185" font-size="13" font-weight="bold" fill="#2B6CB0">Glass Slab (Optically Denser Medium, n₂)</text>',
            '  <text x="200" y="145" font-size="12" font-weight="600" fill="#718096">Air (Rarer Medium, n₁)</text>',
            '  <text x="200" y="370" font-size="12" font-weight="600" fill="#718096">Air (Rarer Medium, n₁)</text>',
            # Slab Corner Labels
            '  <text x="170" y="155" font-size="13" font-weight="bold" fill="#2D3748">A</text>',
            '  <text x="590" y="155" font-size="13" font-weight="bold" fill="#2D3748">B</text>',
            '  <text x="590" y="355" font-size="13" font-weight="bold" fill="#2D3748">C</text>',
            '  <text x="170" y="355" font-size="13" font-weight="bold" fill="#2D3748">D</text>',
            # Normal N1-N1' at top interface (x = 340)
            '  <line x1="340" y1="90" x2="340" y2="230" stroke="#718096" stroke-width="1.5" stroke-dasharray="4,3"/>',
            '  <text x="345" y="105" font-size="12" font-weight="600" fill="#4A5568">N₁</text>',
            '  <text x="345" y="225" font-size="12" font-weight="600" fill="#4A5568">N₁\'</text>',
            # Normal N2-N2' at bottom interface (x = 420)
            '  <line x1="420" y1="270" x2="420" y2="410" stroke="#718096" stroke-width="1.5" stroke-dasharray="4,3"/>',
            '  <text x="425" y="285" font-size="12" font-weight="600" fill="#4A5568">N₂</text>',
            '  <text x="425" y="405" font-size="12" font-weight="600" fill="#4A5568">N₂\'</text>',
            # Point of Incidence O (340, 160) and Point of Emergence O' (420, 340)
            '  <circle cx="340" cy="160" r="4" fill="#E53E3E"/>',
            '  <circle cx="420" cy="340" r="4" fill="#E53E3E"/>',
            '  <text x="325" y="155" font-size="13" font-weight="bold" fill="#C53030">O</text>',
            '  <text x="430" y="335" font-size="13" font-weight="bold" fill="#C53030">O\'</text>',
            # 1. Incident Ray: (220, 70) to (340, 160)
            '  <line x1="220" y1="70" x2="280" y2="115" stroke="#E53E3E" stroke-width="2.5" marker-end="url(#rayArrow)"/>',
            '  <line x1="280" y1="115" x2="340" y2="160" stroke="#E53E3E" stroke-width="2.5"/>',
            '  <text x="210" y="65" font-size="12" font-weight="bold" fill="#C53030">Incident Ray</text>',
            # 2. Refracted Ray: (340, 160) to (420, 340) (Bends towards normal)
            '  <line x1="340" y1="160" x2="380" y2="250" stroke="#E53E3E" stroke-width="2.5" marker-end="url(#rayArrow)"/>',
            '  <line x1="380" y1="250" x2="420" y2="340" stroke="#E53E3E" stroke-width="2.5"/>',
            '  <text x="390" y="245" font-size="12" font-weight="bold" fill="#C53030">Refracted Ray</text>',
            # 3. Emergent Ray: (420, 340) to (540, 430) (Bends away from normal, parallel to incident)
            '  <line x1="420" y1="340" x2="480" y2="385" stroke="#E53E3E" stroke-width="2.5" marker-end="url(#rayArrow)"/>',
            '  <line x1="480" y1="385" x2="540" y2="430" stroke="#E53E3E" stroke-width="2.5"/>',
            '  <text x="545" y="445" font-size="12" font-weight="bold" fill="#C53030">Emergent Ray</text>',
            # 4. Straight extension of original incident ray (dashed grey line)
            '  <line x1="340" y1="160" x2="580" y2="340" stroke="#A0AEC0" stroke-width="1.8" stroke-dasharray="4,4"/>',
            '  <line x1="580" y1="340" x2="680" y2="415" stroke="#A0AEC0" stroke-width="1.8" stroke-dasharray="4,4"/>',
            # Lateral Displacement (Perpendicular distance d between emergent ray and original ray path)
            '  <line x1="510" y1="407" x2="550" y2="354" stroke="#805AD5" stroke-width="2"/>',
            '  <circle cx="510" cy="407" r="3" fill="#805AD5"/>',
            '  <circle cx="550" cy="354" r="3" fill="#805AD5"/>',
            '  <text x="545" y="390" font-size="12" font-weight="bold" fill="#805AD5">Lateral Displacement (d)</text>',
            # Angle arcs & labels
            '  <path d="M 310 137 A 40 40 0 0 1 340 120" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="315" y="125" font-size="12" font-weight="bold" fill="#B7791F">i</text>',
            '  <path d="M 340 190 A 30 30 0 0 1 352 187" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="348" y="205" font-size="12" font-weight="bold" fill="#B7791F">r</text>',
            '  <path d="M 420 370 A 30 30 0 0 1 450 362" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="440" y="380" font-size="12" font-weight="bold" fill="#B7791F">e</text>',
            '  <text x="380" y="475" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">Law: Angle of Incidence (i) = Angle of Emergence (e) | Emergent Ray || Incident Ray</text>',
        ]

        if caption:
            parts.append(f'  <text x="380" y="492" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 2. Magnetic Field Lines around a Straight Current-Carrying Conductor
    # =========================================================================
    @classmethod
    def _render_magnetic_field_wire(cls, title: str, caption: Optional[str], data: Dict[str, Any]) -> str:
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 500" width="100%" height="500" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="500" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Concentric Magnetic Field Lines around a Straight Wire (Right-Hand Thumb Rule)</text>',
            '  <defs>',
            '    <marker id="magArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#2B6CB0"/>',
            '    </marker>',
            '    <marker id="currentArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#E53E3E"/>',
            '    </marker>',
            '  </defs>',
            # Horizontal Cardboard Base (Perspective parallelogram plane)
            '  <polygon points="160,250 560,250 640,360 240,360" fill="#F7FAFC" stroke="#CBD5E0" stroke-width="2.5"/>',
            '  <text x="210" y="275" font-size="12" font-weight="bold" fill="#718096">Cardboard Plane</text>',
            # Concentric Magnetic Field Ellipses centered at (400, 305)
            # Loop 1 (Inner, r=40, ry=20)
            '  <ellipse cx="400" cy="305" rx="55" ry="24" fill="none" stroke="#3182CE" stroke-width="2.2"/>',
            '  <path d="M 400 329 L 415 329" stroke="#3182CE" stroke-width="2.2" marker-end="url(#magArrow)"/>',
            # Loop 2 (Middle, rx=105, ry=46)
            '  <ellipse cx="400" cy="305" rx="105" ry="46" fill="none" stroke="#3182CE" stroke-width="2.2"/>',
            '  <path d="M 400 351 L 418 351" stroke="#3182CE" stroke-width="2.2" marker-end="url(#magArrow)"/>',
            '  <path d="M 400 259 L 382 259" stroke="#3182CE" stroke-width="2.2" marker-end="url(#magArrow)"/>',
            # Loop 3 (Outer, rx=160, ry=70)
            '  <ellipse cx="400" cy="305" rx="160" ry="70" fill="none" stroke="#3182CE" stroke-width="2.2"/>',
            '  <path d="M 400 375 L 420 375" stroke="#3182CE" stroke-width="2.2" marker-end="url(#magArrow)"/>',
            '  <path d="M 400 235 L 380 235" stroke="#3182CE" stroke-width="2.2" marker-end="url(#magArrow)"/>',
            # Magnetic Compass Needle at point (470, 320)
            '  <circle cx="475" cy="320" r="14" fill="#FFFFFF" stroke="#4A5568" stroke-width="1.8"/>',
            '  <polygon points="475,308 480,320 470,320" fill="#E53E3E"/>',
            '  <polygon points="475,332 480,320 470,320" fill="#4A5568"/>',
            '  <text x="495" y="324" font-size="11" font-weight="bold" fill="#2D3748">Compass Needle (N/S)</text>',
            # Vertical Thick Copper Wire passing through hole at (400, 305)
            # Wire below cardboard
            '  <line x1="400" y1="305" x2="400" y2="440" stroke="#DD6B20" stroke-width="9" stroke-linecap="round"/>',
            # Hole in cardboard
            '  <ellipse cx="400" cy="305" rx="8" ry="4" fill="#2D3748"/>',
            # Wire above cardboard
            '  <line x1="400" y1="90" x2="400" y2="305" stroke="#DD6B20" stroke-width="9" stroke-linecap="round"/>',
            # Current arrow (Upwards current flow I)
            '  <line x1="400" y1="180" x2="400" y2="130" stroke="#E53E3E" stroke-width="3" marker-end="url(#currentArrow)"/>',
            '  <text x="420" y="150" font-size="14" font-weight="bold" fill="#C53030">Current Flow (I ↑)</text>',
            # Explanatory Text Callouts
            '  <rect x="60" y="130" width="220" height="90" rx="8" fill="#EBF8FF" stroke="#3182CE" stroke-width="1.5"/>',
            '  <text x="170" y="155" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">Right-Hand Thumb Rule</text>',
            '  <text x="170" y="175" font-size="11" fill="#2D3748" text-anchor="middle">• Thumb points along Current (I)</text>',
            '  <text x="170" y="195" font-size="11" fill="#2D3748" text-anchor="middle">• Fingers encircle along Field (B)</text>',
            '  <text x="170" y="210" font-size="11" fill="#2D3748" text-anchor="middle">• Field strength ∝ 1 / distance (r)</text>',
            '  <text x="400" y="80" font-size="13" font-weight="bold" fill="#2D3748" text-anchor="middle">Thick Straight Copper Conductor</text>',
            '  <text x="380" y="475" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">Pattern: Concentric circular field loops centered on the wire | Direction: Anti-clockwise</text>',
        ]

        if caption:
            parts.append(f'  <text x="380" y="492" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 3. Laboratory Apparatus: Electrolysis of Water (2:1 H2 to O2 ratio)
    # =========================================================================
    @classmethod
    def _render_water_electrolysis(cls, title: str, caption: Optional[str], data: Dict[str, Any]) -> str:
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 520" width="100%" height="520" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="520" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Experimental Setup: Electrolysis of Acidified Water (2H₂O → 2H₂ + O₂)</text>',
            '  <defs>',
            '    <linearGradient id="waterGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
            '      <stop offset="0%" stop-color="#EBF8FF" stop-opacity="0.7"/>',
            '      <stop offset="100%" stop-color="#BEE3F8" stop-opacity="0.9"/>',
            '    </linearGradient>',
            '  </defs>',
            # Plastic Mug / Beaker (Beveled vessel from y=120 to y=360)
            '  <path d="M 230 140 L 250 360 L 510 360 L 530 140 Z" fill="url(#waterGrad)" stroke="#4A5568" stroke-width="3"/>',
            '  <ellipse cx="380" cy="140" rx="150" ry="20" fill="#EDF2F7" stroke="#4A5568" stroke-width="2.5"/>',
            # Acidified water meniscus level inside mug (y = 180)
            '  <ellipse cx="380" cy="180" rx="135" ry="16" fill="#BEE3F8" stroke="#3182CE" stroke-width="1.8"/>',
            # Rubber Stoppers at bottom of mug (Left x=310, Right x=450, y=360)
            '  <rect x="295" y="350" width="30" height="25" rx="3" fill="#2D3748"/>',
            '  <rect x="435" y="350" width="30" height="25" rx="3" fill="#2D3748"/>',
            '  <text x="280" y="390" font-size="11" font-weight="600" fill="#4A5568">Rubber Stopper</text>',
            # Carbon / Graphite Rod Electrodes (Vertical bars passing through stoppers)
            # Left Electrode (Cathode - Negative): x=310
            '  <rect x="306" y="220" width="8" height="150" rx="2" fill="#1A202C" stroke="#2D3748"/>',
            # Right Electrode (Anode - Positive): x=450
            '  <rect x="446" y="220" width="8" height="150" rx="2" fill="#1A202C" stroke="#2D3748"/>',
            # Inverted Graduated Test Tubes
            # Left Test Tube (Cathode - H2 Gas Collection): x=295 to x=325
            '  <path d="M 295 340 L 295 110 A 15 15 0 0 1 325 110 L 325 340" fill="#FFFFFF" fill-opacity="0.85" stroke="#3182CE" stroke-width="2"/>',
            # Water level in left tube displaced down to y=190 (Double volume of gas collected!)
            '  <rect x="297" y="190" width="26" height="150" fill="#90CDF4" fill-opacity="0.6"/>',
            '  <text x="310" y="145" font-size="13" font-weight="bold" fill="#2B6CB0" text-anchor="middle">H₂ Gas</text>',
            '  <text x="310" y="165" font-size="11" font-weight="bold" fill="#2B6CB0" text-anchor="middle">(2 Vol)</text>',
            # Rising gas bubbles in left tube (H2)
            '  <circle cx="310" cy="230" r="3" fill="#3182CE"/>',
            '  <circle cx="308" cy="210" r="3.5" fill="#3182CE"/>',
            '  <circle cx="312" cy="195" r="4" fill="#3182CE"/>',
            # Right Test Tube (Anode - O2 Gas Collection): x=435 to x=465
            '  <path d="M 435 340 L 435 110 A 15 15 0 0 1 465 110 L 465 340" fill="#FFFFFF" fill-opacity="0.85" stroke="#3182CE" stroke-width="2"/>',
            # Water level in right tube displaced only to y=150 (Single volume of gas collected!)
            '  <rect x="437" y="150" width="26" height="190" fill="#90CDF4" fill-opacity="0.6"/>',
            '  <text x="450" y="130" font-size="13" font-weight="bold" fill="#C53030" text-anchor="middle">O₂ Gas</text>',
            '  <text x="450" y="145" font-size="11" font-weight="bold" fill="#C53030" text-anchor="middle">(1 Vol)</text>',
            # Rising gas bubbles in right tube (O2)
            '  <circle cx="450" cy="240" r="3" fill="#E53E3E"/>',
            '  <circle cx="448" cy="200" r="3.5" fill="#E53E3E"/>',
            '  <circle cx="452" cy="165" r="3.5" fill="#E53E3E"/>',
            # External DC Electrical Circuit (Connecting wires to 6V Battery & Key)
            # Cathode wire (Black / Negative): from (310, 375) down to battery
            '  <path d="M 310 375 L 310 440 L 350 440" fill="none" stroke="#2D3748" stroke-width="2.5"/>',
            # Anode wire (Red / Positive): from (450, 375) through switch to battery
            '  <path d="M 450 375 L 450 440 L 410 440" fill="none" stroke="#E53E3E" stroke-width="2.5"/>',
            # 6V Battery Symbol at (380, 440)
            '  <rect x="350" y="425" width="60" height="30" fill="#FFFFFF" stroke="#2D3748" stroke-width="2" rx="4"/>',
            '  <line x1="365" y1="432" x2="365" y2="448" stroke="#2D3748" stroke-width="2.5"/>',
            '  <line x1="375" y1="436" x2="375" y2="444" stroke="#2D3748" stroke-width="4"/>',
            '  <line x1="385" y1="432" x2="385" y2="448" stroke="#2D3748" stroke-width="2.5"/>',
            '  <line x1="395" y1="436" x2="395" y2="444" stroke="#2D3748" stroke-width="4"/>',
            '  <text x="358" y="422" font-size="12" font-weight="bold" fill="#2D3748">-</text>',
            '  <text x="400" y="422" font-size="12" font-weight="bold" fill="#E53E3E">+</text>',
            '  <text x="380" y="472" font-size="12" font-weight="bold" fill="#1A202C" text-anchor="middle">6V DC Battery</text>',
            # Plug Key Switch at (465, 440)
            '  <circle cx="485" cy="440" r="8" fill="#FFFFFF" stroke="#2D3748" stroke-width="2"/>',
            '  <circle cx="485" cy="440" r="3" fill="#2D3748"/>',
            '  <text x="485" y="465" font-size="11" font-weight="bold" fill="#4A5568" text-anchor="middle">Switch (Closed)</text>',
            # Labels and Leader Lines
            '  <text x="170" y="240" font-size="12" font-weight="bold" fill="#2B6CB0">Cathode (Negative Terminal)</text>',
            '  <line x1="260" y1="240" x2="305" y2="250" stroke="#718096" stroke-width="1.2" stroke-dasharray="2,2"/>',
            '  <text x="590" y="240" font-size="12" font-weight="bold" fill="#C53030">Anode (Positive Terminal)</text>',
            '  <line x1="585" y1="240" x2="455" y2="250" stroke="#718096" stroke-width="1.2" stroke-dasharray="2,2"/>',
            '  <text x="170" y="190" font-size="12" font-weight="bold" fill="#2D3748">Plastic Mug</text>',
            '  <line x1="230" y1="190" x2="250" y2="210" stroke="#718096" stroke-width="1.2" stroke-dasharray="2,2"/>',
            '  <text x="590" y="190" font-size="12" font-weight="bold" fill="#2B6CB0">Acidified Water (H₂SO₄)</text>',
            '  <line x1="585" y1="190" x2="500" y2="210" stroke="#718096" stroke-width="1.2" stroke-dasharray="2,2"/>',
            '  <text x="380" y="505" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">Gas Volume Ratio: Hydrogen collected at Cathode is exactly DOUBLE the Oxygen at Anode (2 : 1)</text>',
        ]

        if caption:
            parts.append(f'  <text x="380" y="518" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

    # =========================================================================
    # 4. Refraction through a Triangular Glass Prism & Dispersion
    # =========================================================================
    @classmethod
    def _render_glass_prism(cls, title: str, caption: Optional[str], data: Dict[str, Any]) -> str:
        parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 500" width="100%" height="500" style="background-color: #FFFFFF; font-family: system-ui, -apple-system, sans-serif;">',
            '  <rect width="760" height="500" fill="#FFFFFF"/>',
            f'  <text x="380" y="32" font-size="17" font-weight="bold" fill="#1A202C" text-anchor="middle">{title}</text>',
            '  <text x="380" y="50" font-size="12" fill="#718096" text-anchor="middle">Refraction of Light through a Triangular Glass Prism &amp; Angle of Deviation</text>',
            '  <defs>',
            '    <marker id="prismRayArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#E53E3E"/>',
            '    </marker>',
            '    <linearGradient id="prismGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
            '      <stop offset="0%" stop-color="#EBF8FF" stop-opacity="0.8"/>',
            '      <stop offset="100%" stop-color="#BEE3F8" stop-opacity="0.95"/>',
            '    </linearGradient>',
            '  </defs>',
            # Triangular Prism ABC (Apex A at 380, 90; Base B at 190, 410; Base C at 570, 410)
            '  <polygon points="380,90 190,410 570,410" fill="url(#prismGrad)" stroke="#3182CE" stroke-width="2.8"/>',
            # Prism Vertices
            '  <text x="380" y="78" font-size="14" font-weight="bold" fill="#2D3748" text-anchor="middle">A</text>',
            '  <text x="175" y="425" font-size="14" font-weight="bold" fill="#2D3748">B</text>',
            '  <text x="580" y="425" font-size="14" font-weight="bold" fill="#2D3748">C</text>',
            '  <text x="380" y="390" font-size="12" font-weight="600" fill="#2B6CB0" text-anchor="middle">Glass Prism (Refractive Index n)</text>',
            # Angle of Prism A arc
            '  <path d="M 360 125 A 30 30 0 0 1 400 125" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="380" y="142" font-size="12" font-weight="bold" fill="#B7791F" text-anchor="middle">∠A</text>',
            # Normal NN' at E perpendicular to AB:
            '  <line x1="200" y1="180" x2="380" y2="330" stroke="#718096" stroke-width="1.5" stroke-dasharray="4,3"/>',
            '  <text x="195" y="175" font-size="12" font-weight="600" fill="#4A5568">N</text>',
            '  <text x="385" y="345" font-size="12" font-weight="600" fill="#4A5568">N&#x27;</text>',
            # Incident Ray PE striking face AB at point E (285, 250)
            '  <line x1="100" y1="310" x2="200" y2="276" stroke="#E53E3E" stroke-width="2.5" marker-end="url(#prismRayArrow)"/>',
            '  <line x1="200" y1="276" x2="285" y2="250" stroke="#E53E3E" stroke-width="2.5"/>',
            '  <circle cx="285" cy="250" r="4" fill="#E53E3E"/>',
            '  <text x="275" y="240" font-size="13" font-weight="bold" fill="#C53030">E</text>',
            '  <text x="110" y="295" font-size="12" font-weight="bold" fill="#C53030">Incident Ray (PE)</text>',
            # Angle of incidence i between PE and normal NN'
            '  <path d="M 245 262 A 30 30 0 0 1 250 220" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="230" y="240" font-size="12" font-weight="bold" fill="#B7791F">i</text>',
            # Refracted ray EF inside prism: bends towards base BC from E(285, 250) to F(475, 250)
            '  <line x1="285" y1="250" x2="390" y2="250" stroke="#E53E3E" stroke-width="2.5" marker-end="url(#prismRayArrow)"/>',
            '  <line x1="390" y1="250" x2="475" y2="250" stroke="#E53E3E" stroke-width="2.5"/>',
            '  <circle cx="475" cy="250" r="4" fill="#E53E3E"/>',
            '  <text x="485" y="240" font-size="13" font-weight="bold" fill="#C53030">F</text>',
            '  <text x="380" y="270" font-size="12" font-weight="bold" fill="#C53030" text-anchor="middle">Refracted Ray (EF)</text>',
            # Angle of refraction r at E inside prism
            '  <path d="M 315 250 A 25 25 0 0 1 310 270" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="325" y="268" font-size="12" font-weight="bold" fill="#B7791F">r</text>',
            # Normal MM' at face AC perpendicular to AC passing through F(475, 250):
            '  <line x1="560" y1="180" x2="380" y2="330" stroke="#718096" stroke-width="1.5" stroke-dasharray="4,3"/>',
            '  <text x="565" y="175" font-size="12" font-weight="600" fill="#4A5568">M</text>',
            '  <text x="375" y="345" font-size="12" font-weight="600" fill="#4A5568">M&#x27;</text>',
            # Emergent ray FS bending away from normal towards base BC: from F(475, 250) to S(660, 310)
            '  <line x1="475" y1="250" x2="575" y2="282" stroke="#E53E3E" stroke-width="2.5" marker-end="url(#prismRayArrow)"/>',
            '  <line x1="575" y1="282" x2="660" y2="310" stroke="#E53E3E" stroke-width="2.5"/>',
            '  <text x="665" y="325" font-size="12" font-weight="bold" fill="#C53030">Emergent Ray (FS)</text>',
            # Angle of emergence e between FS and normal MM'
            '  <path d="M 515 262 A 30 30 0 0 1 510 220" fill="none" stroke="#D69E2E" stroke-width="2"/>',
            '  <text x="525" y="240" font-size="12" font-weight="bold" fill="#B7791F">e</text>',
            # Dotted straight forward path of incident ray PE
            '  <line x1="285" y1="250" x2="540" y2="165" stroke="#A0AEC0" stroke-width="1.8" stroke-dasharray="4,4"/>',
            # Dotted backward extension of emergent ray FS
            '  <line x1="475" y1="250" x2="350" y2="175" stroke="#A0AEC0" stroke-width="1.8" stroke-dasharray="4,4"/>',
            # Point of intersection G (approx 420, 205)
            '  <circle cx="420" cy="205" r="3.5" fill="#805AD5"/>',
            '  <text x="420" y="195" font-size="12" font-weight="bold" fill="#805AD5" text-anchor="middle">G</text>',
            # Angle of Deviation D arc
            '  <path d="M 445 195 A 30 30 0 0 1 455 218" fill="none" stroke="#805AD5" stroke-width="2.5"/>',
            '  <text x="470" y="205" font-size="13" font-weight="bold" fill="#805AD5">∠D</text>',
            # Angle of Deviation callout badge
            '  <rect x="530" y="125" width="180" height="32" rx="6" fill="#FAF5FF" stroke="#805AD5" stroke-width="1.5"/>',
            '  <text x="620" y="146" font-size="11" font-weight="bold" fill="#6B46C1" text-anchor="middle">Angle of Deviation (∠D)</text>',
            # Footer summary
            '  <text x="380" y="465" font-size="12" font-weight="bold" fill="#2B6CB0" text-anchor="middle">Prism Relation: ∠i + ∠e = ∠A + ∠D | White Light Dispersion: Red deviates least, Violet deviates most</text>',
        ]

        if caption:
            parts.append(f'  <text x="380" y="488" font-size="11" fill="#718096" text-anchor="middle" font-style="italic">{caption}</text>')

        parts.append('</svg>')
        return "\n".join(parts)

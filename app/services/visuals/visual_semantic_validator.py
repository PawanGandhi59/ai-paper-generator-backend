from dataclasses import dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Word-to-number mapping for high-confidence entity count extraction
WORD_TO_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


@dataclass
class SemanticValidationResult:
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class VisualSemanticValidator:
    """
    Deterministic, subject-agnostic semantic sanity validator that cross-checks
    question text and solution context against structured visual specifications.
    Detects high-confidence entity omissions, count mismatches, topology contradictions,
    and parameter inconsistencies without calling external LLMs or heuristic AI.
    """

    @classmethod
    def validate(
        cls,
        question_text: str,
        visual_spec: Any,
        visual_type: Optional[str] = None,
        solution_text: Optional[str] = None,
    ) -> SemanticValidationResult:
        result = SemanticValidationResult()

        if not visual_spec or not question_text:
            return result

        # Normalize visual specification to dict/object format
        spec_dict: Dict[str, Any] = {}
        vtype = visual_type

        if hasattr(visual_spec, "spec"):
            raw_spec = visual_spec.spec
            if hasattr(raw_spec, "model_dump"):
                spec_dict = raw_spec.model_dump(by_alias=True, exclude_none=True)
            elif isinstance(raw_spec, dict):
                spec_dict = raw_spec
            vtype = getattr(visual_spec, "type", visual_type)
        elif isinstance(visual_spec, dict):
            raw_spec = visual_spec.get("spec") or visual_spec.get("data") or visual_spec.get("spec_data") or visual_spec
            if hasattr(raw_spec, "model_dump"):
                spec_dict = raw_spec.model_dump(by_alias=True, exclude_none=True)
            elif isinstance(raw_spec, dict):
                spec_dict = raw_spec
            vtype = visual_spec.get("type", visual_type)

        q_lower = question_text.lower()
        sol_lower = (solution_text or "").lower()
        combined_text = f"{q_lower} {sol_lower}"

        # Dispatch based on visual type
        if vtype == "circuit":
            cls._validate_circuit(q_lower, combined_text, spec_dict, result)
        elif vtype == "geometry":
            cls._validate_geometry(q_lower, combined_text, spec_dict, result)
        elif vtype == "graph":
            cls._validate_graph(q_lower, combined_text, spec_dict, result)
        elif vtype == "chart":
            cls._validate_chart(q_lower, combined_text, spec_dict, result)
        elif vtype == "diagram":
            cls._validate_diagram(q_lower, combined_text, spec_dict, result)

        if result.errors:
            result.is_valid = False

        return result

    # ==========================================================================
    # 1. Circuit Semantic Validation
    # ==========================================================================
    @classmethod
    def _validate_circuit(
        cls,
        q_text: str,
        combined_text: str,
        spec: Dict[str, Any],
        res: SemanticValidationResult,
    ) -> None:
        components: List[Dict[str, Any]] = spec.get("components") or []
        junctions: List[Dict[str, Any]] = spec.get("junctions") or []

        comp_types = [c.get("type", "").lower() for c in components]
        comp_labels = " ".join(str(c.get("label", "")) for c in components).lower()

        # A. High-Confidence Named Topology Checks
        if "cubical network" in combined_text or "resistor cube" in combined_text or "cube of 12 resistors" in combined_text:
            resistor_count = sum(1 for t in comp_types if t == "resistor")
            if resistor_count < 12:
                res.errors.append(
                    f"Question specifies a 12-resistor cubical network, but visual contains only {resistor_count} resistors."
                )

        if "wheatstone bridge" in combined_text:
            resistor_count = sum(1 for t in comp_types if t == "resistor")
            if resistor_count < 4:
                res.errors.append(
                    f"Question specifies a Wheatstone bridge circuit, but visual contains only {resistor_count} resistors (minimum 4 required)."
                )

        # B. High-Confidence Component Quantities
        # Pattern: "(\d+|word) (resistors|capacitors|inductors|batteries|bulbs|lamps|cells)"
        count_patterns = [
            (r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:identical\s+)?(?:[\d\.\-]+\s*(?:[Ω°µμ%a-zA-Z\-/]+)?\s*)?(?:identical\s+)?resistors?\b", "resistor", "resistor"),
            (r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:identical\s+)?(?:[\d\.\-]+\s*(?:[Ω°µμ%a-zA-Z\-/]+)?\s*)?(?:identical\s+)?capacitors?\b", "capacitor", "capacitor"),
            (r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:identical\s+)?(?:[\d\.\-]+\s*(?:[Ω°µμ%a-zA-Z\-/]+)?\s*)?(?:identical\s+)?inductors?\b", "inductor", "inductor"),
            (r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:identical\s+)?(?:[\d\.\-]+\s*(?:[Ω°µμ%a-zA-Z\-/]+)?\s*)?(?:identical\s+)?(?:lamps?|bulbs?)\b", "lamp", "lamp"),
            (r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(?:identical\s+)?(?:[\d\.\-]+\s*(?:[Ω°µμ%a-zA-Z\-/]+)?\s*)?(?:identical\s+)?(?:batteries|cells?)\b", "battery", "battery"),
        ]

        for pat, target_type, type_name in count_patterns:
            matches = re.findall(pat, q_text)
            for m in matches:
                expected_count = int(m) if m.isdigit() else WORD_TO_NUM.get(m.lower())
                if expected_count and expected_count > 1:
                    actual_count = sum(1 for t in comp_types if t == target_type or (target_type == "battery" and t == "cell"))
                    if actual_count < expected_count:
                        res.errors.append(
                            f"Question explicitly states {expected_count} {type_name}s, but visual specification contains only {actual_count}."
                        )

        # C. Required Entity Presence
        # 1. Switch / Key presence
        if re.search(r"\b(switch|key)\b", q_text) and not any(t == "switch" for t in comp_types):
            # Check if switch is a primary circuit element in problem
            if re.search(r"\b(switch|key)\s+(?:is|was|connected|closed|opened|through)\b", q_text) or "through a key" in q_text or "switch is" in q_text:
                res.errors.append("Question explicitly describes a switch/key, but visual contains no switch component.")

        # 2. Switch State (open vs closed)
        for comp in components:
            if comp.get("type") == "switch":
                switch_state = comp.get("state", "open")
                if re.search(r"\b(?:switch|key)\s+(?:is\s+)?closed\b|\bclosed\s+(?:switch|key)\b", q_text) and switch_state == "open":
                    res.warnings.append("Question specifies a closed switch/key, but visual switch is set to 'open'.")
                elif re.search(r"\b(?:switch|key)\s+(?:is\s+)?open(?:ed)?\b|\bopen\s+(?:switch|key)\b", q_text) and switch_state == "closed":
                    res.warnings.append("Question specifies an open switch/key, but visual switch is set to 'closed'.")

        # 3. AC Source presence
        if re.search(r"\bac\s+(?:source|voltage|supply|generator)\b|\balternating\s+(?:current|voltage)\s+source\b", q_text):
            has_ac = any(t == "ac_source" for t in comp_types) or ("ac" in comp_labels and any(t == "generic" for t in comp_types))
            if not has_ac:
                res.errors.append("Question specifies an AC power source, but visual contains no AC source component.")

        # 4. Iron-core inductor presence
        if re.search(r"\biron\s+(?:rod|core)\b|\biron-core\s+inductor\b", q_text):
            has_iron_core = any(c.get("type") == "inductor" and c.get("iron_core") is True for c in components)
            if not has_iron_core:
                res.errors.append(
                    "Question explicitly specifies an iron-core inductor / iron rod insertion, but visual inductor lacks iron_core=true."
                )

        # 5. Lamp / Bulb presence
        if re.search(r"\b(light\s+bulb|bulb|lamp)\b", q_text):
            if not any(t == "lamp" for t in comp_types):
                res.errors.append("Question explicitly describes a bulb/lamp, but visual contains no lamp component.")

        # D. Numerical Parameter Sanity (Voltage & Resistance)
        # e.g., "500 V" in question vs visual
        voltage_matches = re.findall(r"\b(\d+(?:\.\d+)?)\s*V(?:\s+supply|\s+source|\s+battery|\b)", q_text, re.IGNORECASE)
        for volt_str in voltage_matches:
            if float(volt_str) >= 10.0:  # Only check significant source voltages
                if not any(volt_str in str(c.get("label", "")) for c in components if c.get("type") in ["battery", "cell", "ac_source"]):
                    res.warnings.append(
                        f"Question mentions source voltage {volt_str} V, but visual source label does not clearly match."
                    )

    # ==========================================================================
    # 2. Geometry Semantic Validation
    # ==========================================================================
    @classmethod
    def _validate_geometry(
        cls,
        q_text: str,
        combined_text: str,
        spec: Dict[str, Any],
        res: SemanticValidationResult,
    ) -> None:
        points: List[Dict[str, Any]] = spec.get("points") or []
        segments: List[Dict[str, Any]] = spec.get("segments") or []
        point_ids: Set[str] = {p.get("id") or p.get("label") for p in points if p.get("id") or p.get("label")}

        # Check explicit named entities (e.g., "triangle ABC with altitude BD")
        geom_name_match = re.search(r"\b(?:triangle|polygon|quadrilateral)\s+([A-Z]{3,4})\b", q_text, re.IGNORECASE)
        if geom_name_match:
            expected_vertices = list(geom_name_match.group(1).upper())
            for v in expected_vertices:
                if v not in point_ids:
                    res.errors.append(
                        f"Geometry figure '{geom_name_match.group(1)}' mentions vertex '{v}', but point '{v}' is missing from visual points."
                    )

        # Check altitude / perpendicular point (e.g., "altitude BD" -> point D must exist)
        altitude_match = re.search(r"\baltitude\s+([A-Z])([A-Z])\b", q_text, re.IGNORECASE)
        if altitude_match:
            p1, p2 = altitude_match.group(1).upper(), altitude_match.group(2).upper()
            if p1 not in point_ids or p2 not in point_ids:
                missing_pt = p1 if p1 not in point_ids else p2
                res.errors.append(
                    f"Question specifies altitude {p1}{p2}, but point '{missing_pt}' is missing from visual specification."
                )

    # ==========================================================================
    # 3. Graph Semantic Validation
    # ==========================================================================
    @classmethod
    def _validate_graph(
        cls,
        q_text: str,
        combined_text: str,
        spec: Dict[str, Any],
        res: SemanticValidationResult,
    ) -> None:
        functions: List[Dict[str, Any]] = spec.get("functions") or []

        if not functions and not spec.get("points") and not spec.get("segments"):
            res.errors.append("Graph visual specification contains no plotted functions, curves, or data points.")
            return

        # Check if question specifies sinusoidal function with amplitude/frequency
        # e.g., "10 sin(100πt)" or "10*sin"
        if re.search(r"\b(\d+)\s*(?:\*|x)?\s*sin\s*\(", q_text):
            amp_match = re.search(r"\b(\d+)\s*(?:\*|x)?\s*sin\s*\(", q_text)
            if amp_match:
                amp_val = amp_match.group(1)
                all_exprs = " ".join(f.get("expression", "") for f in functions)
                if amp_val not in all_exprs and f"{amp_val}*" not in all_exprs and f"{amp_val} *" not in all_exprs:
                    res.warnings.append(
                        f"Question specifies waveform with amplitude {amp_val}, but graph expression does not contain this amplitude."
                    )

    # ==========================================================================
    # 4. Chart Semantic Validation
    # ==========================================================================
    @classmethod
    def _validate_chart(
        cls,
        q_text: str,
        combined_text: str,
        spec: Dict[str, Any],
        res: SemanticValidationResult,
    ) -> None:
        categories: List[str] = spec.get("categories") or []
        series: List[Dict[str, Any]] = spec.get("series") or []

        cat_count_match = re.search(r"\b(?:data\s+for|across)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:categories|subjects|items|tests|terms)\b", q_text)
        if cat_count_match:
            raw_num = cat_count_match.group(1)
            exp_count = int(raw_num) if raw_num.isdigit() else WORD_TO_NUM.get(raw_num.lower())
            if exp_count and len(categories) < exp_count:
                res.errors.append(
                    f"Question specifies data for {exp_count} categories, but chart contains only {len(categories)} categories."
                )

    # ==========================================================================
    # 5. Diagram Semantic Validation
    # ==========================================================================
    @classmethod
    def _validate_diagram(
        cls,
        q_text: str,
        combined_text: str,
        spec: Dict[str, Any],
        res: SemanticValidationResult,
    ) -> None:
        nodes: List[Dict[str, Any]] = spec.get("nodes") or []

        stage_count_match = re.search(r"\b(\d+|two|three|four|five|six|seven|eight)\s*-\s*stage\s+(?:process|cycle|flow)\b", q_text)
        if stage_count_match:
            raw_num = stage_count_match.group(1)
            exp_stages = int(raw_num) if raw_num.isdigit() else WORD_TO_NUM.get(raw_num.lower())
            if exp_stages and len(nodes) < exp_stages:
                res.errors.append(
                    f"Question specifies a {exp_stages}-stage process, but diagram contains only {len(nodes)} nodes."
                )

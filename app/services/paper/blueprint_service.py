import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.schemas.paper import QuestionConfigItem, QuestionType
from app.services.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)


class SectionBlueprint(BaseModel):
    name: str
    question_type: QuestionType
    question_count: int = Field(..., ge=1, description="Number of distinct question numbers in this section")
    marks_per_question: int = Field(..., ge=1, description="Marks assigned to each question number")
    total_section_marks: int = Field(..., ge=1, description="Total marks = question_count * marks_per_question")
    has_internal_choice: bool = Field(default=False, description="Whether questions in this section have internal choices (e.g. Q4(a) OR Q4(b))")
    alternatives_per_question: int = Field(default=1, ge=1, description="Number of alternatives per question number (1 if no internal choice, 2 for (a) OR (b))")
    choice_rule: Optional[str] = Field(default=None, description="Choice rule description, e.g. 'answer_one_of_two'")


class PaperBlueprint(BaseModel):
    total_marks: int = Field(..., ge=1)
    sections: List[SectionBlueprint] = Field(..., min_length=1)
    sample_questions: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


REFERENCE_ANALYSIS_PROMPT = """
You are an expert academic examination parser. Analyze the following past examination paper text and extract its complete structural blueprint as written in the paper.

Return ONLY a JSON object with this exact structure:
{{
  "total_marks": <actual total examination marks of this reference paper as integer>,
  "sections": [
    {{
      "name": "<Section Name, e.g. Part A, Part B, Part C>",
      "question_type": "<One of: MCQ, SHORT_ANSWER, LONG_ANSWER, NUMERICAL>",
      "question_count": <number of distinct question numbers in this section as integer>,
      "marks_per_question": <marks assigned per single question number as integer>,
      "has_internal_choice": <true if questions have internal OR choices (e.g. Q4(a) OR Q4(b)), false otherwise>,
      "alternatives_per_question": <number of alternatives per question number, e.g. 2 for (a) OR (b), 1 if no choice>,
      "choice_rule": "<'answer_one_of_two' if has_internal_choice is true, null otherwise>"
    }}
  ],
  "sample_questions": [
    {{
      "section_name": "<Section Name>",
      "question_type": "<MCQ | SHORT_ANSWER | LONG_ANSWER | NUMERICAL>",
      "question_text": "<Question text>",
      "marks": <marks>,
      "choice_group": "<Question number like Q4 if internal choice exists, null otherwise>",
      "alternative_label": "<'a' or 'b' if internal choice exists, null otherwise>"
    }}
  ]
}}

CRITICAL BLUEPRINT RULES:
1. question_count is the count of distinct question NUMBERS in the section (e.g., Q1 to Q5 is 5 questions; Q6 to Q10 is 5 question numbers; Q11 to Q15 is 5 question numbers).
2. marks_per_question is the mark assigned to ONE question (or ONE alternative), NOT the sum of choice options! For example, if Q11(a) is 7 marks OR Q11(b) is 7 marks, marks_per_question is 7 (NEVER 14!).
3. total_section_marks MUST BE equal to question_count * marks_per_question (e.g., 5 questions * 7 marks = 35 marks). Alternatives (a OR b) do NOT multiply or inflate section marks.
4. Total paper marks = sum of total_section_marks across all sections (e.g. Part A: 5x1=5, Part B: 5x4=20, Part C: 5x7=35 -> Total = 60).
5. COMPLETE SECTION EXTRACTION: Read all pages carefully. Identify all sections from question numbering (e.g., Q1-Q5, Q6-Q10, Q11-Q15), even if explicit section header labels (such as Part C) are missing or faint in OCR text. In standard 60-mark examination papers with Part A (5x1=5) and Part B (5x4=20), Part C questions Q11 to Q15 are 7 marks each (5x7=35 marks; Total = 60).
6. QUESTION TYPES: Classify question_type based on section style: 1-4 mark questions are SHORT_ANSWER, 5+ mark questions are LONG_ANSWER. Part A (1m) and Part B (4m) are SHORT_ANSWER, while Part C (7m) is LONG_ANSWER.

Examination Paper Text:
---
{paper_text}
---
"""


class BlueprintService:
    def __init__(self, ai_service: Optional[GeminiService] = None):
        self.ai_service = ai_service or GeminiService()

    def validate_blueprint(self, blueprint: PaperBlueprint) -> None:
        """
        Validates structural invariants of a PaperBlueprint:
        1. total_section_marks sum across all sections equals blueprint.total_marks.
        2. For each section: question_count >= 1, marks_per_question >= 1, alternatives_per_question >= 1.
        3. For sections with internal choice (has_internal_choice is True): alternatives_per_question == 2.
        4. For all sections: total_section_marks == question_count * marks_per_question.
        """
        if not blueprint.sections:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid blueprint: blueprint must contain at least one section.",
            )

        computed_total = 0
        for sec in blueprint.sections:
            if sec.question_count < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid section '{sec.name}': question_count must be >= 1.",
                )
            if sec.marks_per_question < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid section '{sec.name}': marks_per_question must be >= 1.",
                )
            if sec.has_internal_choice and sec.alternatives_per_question != 2:
                sec.alternatives_per_question = 2
                sec.choice_rule = "answer_one_of_two"

            expected_sec_marks = sec.question_count * sec.marks_per_question
            if sec.total_section_marks != expected_sec_marks:
                sec.total_section_marks = expected_sec_marks

            computed_total += sec.total_section_marks

        if computed_total != blueprint.total_marks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid blueprint: sum of section total marks ({computed_total}) does not equal paper total marks ({blueprint.total_marks}).",
            )

    def build_custom_blueprint(
        self,
        question_configs: List[QuestionConfigItem],
        total_marks: int,
    ) -> PaperBlueprint:
        """
        Constructs a PaperBlueprint from user-provided question_configs (CUSTOM mode).
        Validates that sum(question_count * marks_per_question) == total_marks.
        """
        if not question_configs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CUSTOM mode paper generation requires non-empty question_configs.",
            )

        sections: List[SectionBlueprint] = []
        for idx, cfg in enumerate(question_configs):
            sec_name = cfg.section_name or f"Section {chr(65 + idx)}"
            sec_marks = cfg.question_count * cfg.marks_per_question

            alts = cfg.alternatives or cfg.alternatives_per_question
            has_choice = bool(cfg.has_internal_choice) or (alts > 1)
            alts_per_q = max(alts, 2) if has_choice else 1
            c_rule = cfg.choice_rule or ("answer_one_of_two" if has_choice else None)

            sections.append(
                SectionBlueprint(
                    name=sec_name,
                    question_type=cfg.question_type,
                    question_count=cfg.question_count,
                    marks_per_question=cfg.marks_per_question,
                    total_section_marks=sec_marks,
                    has_internal_choice=has_choice,
                    alternatives_per_question=alts_per_q,
                    choice_rule=c_rule,
                )
            )

        blueprint = PaperBlueprint(
            total_marks=total_marks,
            sections=sections,
            sample_questions=[],
        )
        self.validate_blueprint(blueprint)
        return blueprint

    def analyze_reference_paper(
        self,
        paper_pages_text: List[str],
        requested_total_marks: Optional[int] = None,
    ) -> PaperBlueprint:
        """
        Analyzes reference paper text content using Gemini to extract structural blueprint
        (sections, question counts, marks, internal choices, sample questions).
        If requested_total_marks differs from reference paper total, adapts blueprint while
        preserving mark denominations.
        """
        combined_text = "\n".join(paper_pages_text).strip()
        if not combined_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reference paper has no extracted page content for structural analysis.",
            )

        # Truncate combined text to prevent context overflow if paper is huge
        truncated_text = combined_text[:12000]
        prompt = REFERENCE_ANALYSIS_PROMPT.format(paper_text=truncated_text)

        try:
            raw_response = self.ai_service.generate_response(prompt=prompt)
            parsed_json = self._parse_json_safely(raw_response)

            raw_sections = parsed_json.get("sections", [])
            sections: List[SectionBlueprint] = []
            for idx, sec in enumerate(raw_sections):
                name = str(sec.get("name", f"Section {chr(65 + idx)}"))
                q_type_str = str(sec.get("question_type", "SHORT_ANSWER")).upper()
                if q_type_str not in [e.value for e in QuestionType]:
                    q_type_str = "SHORT_ANSWER"
                q_count = max(1, int(sec.get("question_count", 5)))
                marks_per_q = max(1, int(sec.get("marks_per_question", 2)))

                has_choice = bool(sec.get("has_internal_choice", sec.get("internal_choice", False)))
                alts_per_q = 2 if has_choice else max(1, int(sec.get("alternatives_per_question", 1)))
                c_rule = str(sec.get("choice_rule", "")) if has_choice else None
                if has_choice and not c_rule:
                    c_rule = "answer_one_of_two"

                sec_marks = q_count * marks_per_q  # NEVER multiply by alts_per_q!

                sections.append(
                    SectionBlueprint(
                        name=name,
                        question_type=QuestionType(q_type_str),
                        question_count=q_count,
                        marks_per_question=marks_per_q,
                        total_section_marks=sec_marks,
                        has_internal_choice=has_choice,
                        alternatives_per_question=alts_per_q,
                        choice_rule=c_rule,
                    )
                )

            if not sections:
                # Fallback section if parsing extracted no sections
                sections = [
                    SectionBlueprint(
                        name="Section A",
                        question_type=QuestionType.SHORT_ANSWER,
                        question_count=5,
                        marks_per_question=2,
                        total_section_marks=10,
                    )
                ]

            analysis_total = sum(s.total_section_marks for s in sections)
            ref_blueprint = PaperBlueprint(
                total_marks=analysis_total,
                sections=sections,
                sample_questions=parsed_json.get("sample_questions", []),
            )
            self.validate_blueprint(ref_blueprint)

            # CORE RULE: If requested_total_marks matches reference paper's analyzed total_marks, PRESERVE IT EXACTLY.
            if requested_total_marks is None or requested_total_marks == ref_blueprint.total_marks:
                return ref_blueprint

            # Adapt reference blueprint ONLY IF requested_total_marks differs from reference blueprint total_marks
            adapted_bp = self.adapt_reference_blueprint(ref_blueprint, requested_total_marks)
            self.validate_blueprint(adapted_bp)
            return adapted_bp

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Failed to analyze reference paper: {exc}")
            # If AI structural analysis fails, return a safe structured fallback
            fallback_sections = [
                SectionBlueprint(
                    name="Section A",
                    question_type=QuestionType.MCQ,
                    question_count=5,
                    marks_per_question=1,
                    total_section_marks=5,
                ),
                SectionBlueprint(
                    name="Section B",
                    question_type=QuestionType.SHORT_ANSWER,
                    question_count=5,
                    marks_per_question=2,
                    total_section_marks=10,
                ),
            ]
            fallback_bp = PaperBlueprint(total_marks=15, sections=fallback_sections)
            if requested_total_marks:
                adapted_fallback = self.adapt_reference_blueprint(fallback_bp, requested_total_marks)
                self.validate_blueprint(adapted_fallback)
                return adapted_fallback
            self.validate_blueprint(fallback_bp)
            return fallback_bp

    def build_blueprint_from_generated_paper(
        self,
        paper: Any,
        requested_total_marks: Optional[int] = None,
    ) -> PaperBlueprint:
        """
        Builds a PaperBlueprint directly from an existing GeneratedPaper instance.
        Deserializes stored blueprint_json or reconstructs blueprint from paper questions,
        extracting sample questions and adapting total marks if requested.
        """
        raw_blueprint = paper.blueprint_json
        sample_questions: List[Dict[str, Any]] = []

        # Extract sample questions from existing generated paper questions
        if hasattr(paper, "questions") and paper.questions:
            for q in paper.questions:
                sample_questions.append({
                    "section_name": getattr(q, "section_name", "Section A"),
                    "question_type": getattr(q, "question_type", "SHORT_ANSWER"),
                    "question_text": getattr(q, "question_text", ""),
                    "marks": getattr(q, "marks", 1),
                    "choice_group": getattr(q, "choice_group", None),
                    "alternative_label": getattr(q, "alternative_label", None),
                })

        if raw_blueprint and isinstance(raw_blueprint, dict):
            try:
                blueprint = PaperBlueprint.model_validate(raw_blueprint)
                if sample_questions:
                    blueprint.sample_questions = sample_questions
                self.validate_blueprint(blueprint)
            except Exception as exc:
                logger.warning(f"Failed to parse stored blueprint_json for paper {getattr(paper, 'id', 'unknown')}: {exc}")
                blueprint = None
        else:
            blueprint = None

        if not blueprint:
            # Reconstruct blueprint from questions if blueprint_json was missing/invalid
            section_map: Dict[str, Dict[str, Any]] = {}
            if hasattr(paper, "questions") and paper.questions:
                for q in paper.questions:
                    sec_name = getattr(q, "section_name", "Section A")
                    q_type = getattr(q, "question_type", "SHORT_ANSWER")
                    q_marks = getattr(q, "marks", 1)

                    if sec_name not in section_map:
                        section_map[sec_name] = {
                            "name": sec_name,
                            "question_type": q_type,
                            "question_count": 0,
                            "marks_per_question": q_marks,
                            "total_section_marks": 0,
                            "has_internal_choice": False,
                            "alternatives_per_question": 1,
                        }
                    sec_entry = section_map[sec_name]
                    if getattr(q, "choice_group", None):
                        sec_entry["has_internal_choice"] = True
                        sec_entry["alternatives_per_question"] = 2

                    if not sec_entry["has_internal_choice"] or getattr(q, "alternative_label", "a") in ("a", None):
                        sec_entry["question_count"] += 1
                        sec_entry["total_section_marks"] += q_marks

            sections: List[SectionBlueprint] = []
            for sec_data in section_map.values():
                sec_data["total_section_marks"] = sec_data["question_count"] * sec_data["marks_per_question"]
                try:
                    sections.append(SectionBlueprint(**sec_data))
                except Exception:
                    pass

            if not sections:
                sections = [
                    SectionBlueprint(
                        name="Section A",
                        question_type=QuestionType.SHORT_ANSWER,
                        question_count=5,
                        marks_per_question=2,
                        total_section_marks=10,
                    )
                ]

            total_m = getattr(paper, "total_marks", sum(s.total_section_marks for s in sections))
            blueprint = PaperBlueprint(
                total_marks=total_m,
                sections=sections,
                sample_questions=sample_questions,
            )
            self.validate_blueprint(blueprint)

        if requested_total_marks is None or requested_total_marks == blueprint.total_marks:
            return blueprint

        adapted_bp = self.adapt_reference_blueprint(blueprint, requested_total_marks)
        self.validate_blueprint(adapted_bp)
        return adapted_bp



    def adapt_reference_blueprint(
        self,
        ref_blueprint: PaperBlueprint,
        target_total_marks: int,
    ) -> PaperBlueprint:
        """
        Adapt reference paper blueprint to target_total_marks while prioritizing
        preservation of exact reference mark denominations (e.g. 1, 4, 7).

        Priority 1: Exact reference blueprint if target_total_marks == ref_blueprint.total_marks.
        Priority 2: Construct target_total_marks using reference mark denominations and section structure.
        Priority 3: Controlled fallback adaptation if exact reference denominations cannot reach target.
        Priority 4: Always ensure sum(question_count * marks_per_question) == target_total_marks.
        """
        if ref_blueprint.total_marks == target_total_marks:
            return ref_blueprint

        sections = ref_blueprint.sections
        ref_total = float(ref_blueprint.total_marks)
        m_values = [sec.marks_per_question for sec in sections]
        ref_ratios = [sec.total_section_marks / ref_total for sec in sections]

        # Calculate ideal question counts based on proportional section scaling
        ideal_counts = []
        for sec in sections:
            ratio = sec.total_section_marks / ref_total
            target_sec_marks = ratio * target_total_marks
            ideal_c = max(1, int(round(target_sec_marks / float(sec.marks_per_question))))
            ideal_counts.append(ideal_c)

        # PRIORITY 2: Search for a valid combination of question counts using EXACT reference mark denominations
        best_counts = self._find_best_counts_with_ref_marks(
            m_values=m_values,
            ref_ratios=ref_ratios,
            target_total_marks=target_total_marks,
            ideal_counts=ideal_counts,
        )

        if best_counts is not None:
            new_sections: List[SectionBlueprint] = []
            for i, sec in enumerate(sections):
                c_i = best_counts[i]
                sec_marks = c_i * sec.marks_per_question
                new_sections.append(
                    SectionBlueprint(
                        name=sec.name,
                        question_type=sec.question_type,
                        question_count=c_i,
                        marks_per_question=sec.marks_per_question,
                        total_section_marks=sec_marks,
                        has_internal_choice=sec.has_internal_choice,
                        alternatives_per_question=sec.alternatives_per_question,
                        choice_rule=sec.choice_rule,
                    )
                )
            adapted_bp = PaperBlueprint(
                total_marks=target_total_marks,
                sections=new_sections,
                sample_questions=ref_blueprint.sample_questions,
            )
            self.validate_blueprint(adapted_bp)
            return adapted_bp

        # PRIORITY 3: Fallback adaptation if target_total_marks cannot be constructed using reference denominations
        fallback_sections = self._adapt_blueprint_fallback(ref_blueprint, target_total_marks)
        fallback_bp = PaperBlueprint(
            total_marks=target_total_marks,
            sections=fallback_sections,
            sample_questions=ref_blueprint.sample_questions,
        )
        self.validate_blueprint(fallback_bp)
        return fallback_bp

    def _find_best_counts_with_ref_marks(
        self,
        m_values: List[int],
        ref_ratios: List[float],
        target_total_marks: int,
        ideal_counts: List[int],
    ) -> Optional[List[int]]:
        """
        Search for integer question counts c_i >= 1 using reference mark denominations m_i
        such that sum(c_i * m_i) == target_total_marks, minimizing deviation from ref_ratios.
        """
        n = len(m_values)
        if n == 0:
            return None

        candidates: List[Tuple[float, float, List[int]]] = []

        def search(index: int, current_sum: int, current_counts: List[int]):
            if index == n - 1:
                rem = target_total_marks - current_sum
                m_last = m_values[-1]
                if rem > 0 and rem % m_last == 0:
                    c_last = rem // m_last
                    if c_last >= 1:
                        full_counts = current_counts + [c_last]
                        ratio_error = sum(
                            abs((full_counts[i] * m_values[i] / float(target_total_marks)) - ref_ratios[i])
                            for i in range(n)
                        )
                        count_dist = sum((full_counts[i] - ideal_counts[i]) ** 2 for i in range(n))
                        candidates.append((ratio_error, count_dist, full_counts))
                return

            m_i = m_values[index]
            max_c = (target_total_marks - current_sum) // m_i
            if max_c < 1:
                return

            possible_c = list(range(1, max_c + 1))
            possible_c.sort(key=lambda c: abs(c - ideal_counts[index]))

            for c_i in possible_c:
                next_sum = current_sum + c_i * m_i
                if next_sum >= target_total_marks:
                    continue
                search(index + 1, next_sum, current_counts + [c_i])
                if len(candidates) > 500:
                    break

        search(0, 0, [])

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    def _adapt_blueprint_fallback(
        self,
        ref_blueprint: PaperBlueprint,
        target_total_marks: int,
    ) -> List[SectionBlueprint]:
        """
        Fallback adaptation when target_total_marks cannot be constructed using reference mark denominations.
        """
        scale = target_total_marks / float(ref_blueprint.total_marks)
        new_sections: List[SectionBlueprint] = []

        for sec in ref_blueprint.sections:
            target_sec_marks = max(sec.marks_per_question, int(round(sec.total_section_marks * scale)))
            new_count = max(1, target_sec_marks // sec.marks_per_question)
            new_sec_marks = new_count * sec.marks_per_question

            new_sections.append(
                SectionBlueprint(
                    name=sec.name,
                    question_type=sec.question_type,
                    question_count=new_count,
                    marks_per_question=sec.marks_per_question,
                    total_section_marks=new_sec_marks,
                    has_internal_choice=sec.has_internal_choice,
                    alternatives_per_question=sec.alternatives_per_question,
                    choice_rule=sec.choice_rule,
                )
            )

        current_sum = sum(s.total_section_marks for s in new_sections)

        attempts = 0
        while current_sum != target_total_marks and attempts < 100:
            attempts += 1
            diff = target_total_marks - current_sum

            if diff > 0:
                valid_inc = [s for s in new_sections if current_sum + s.marks_per_question <= target_total_marks]
                if valid_inc:
                    sec_to_inc = min(valid_inc, key=lambda s: s.marks_per_question)
                    sec_to_inc.question_count += 1
                    sec_to_inc.total_section_marks = sec_to_inc.question_count * sec_to_inc.marks_per_question
                else:
                    break
            else:
                deletable = [s for s in new_sections if s.question_count > 1]
                if not deletable:
                    break
                sec_to_dec = min(deletable, key=lambda s: s.marks_per_question)
                sec_to_dec.question_count -= 1
                sec_to_dec.total_section_marks = sec_to_dec.question_count * sec_to_dec.marks_per_question

            current_sum = sum(s.total_section_marks for s in new_sections)

        if current_sum != target_total_marks:
            diff = target_total_marks - current_sum
            last_sec = new_sections[-1]
            target_last_marks = last_sec.total_section_marks + diff

            best_c = last_sec.question_count
            best_m = max(1, target_last_marks // best_c)
            found = False
            for c in range(last_sec.question_count, 0, -1):
                if target_last_marks % c == 0:
                    best_c = c
                    best_m = target_last_marks // c
                    found = True
                    break
            if not found:
                for c in range(last_sec.question_count + 1, target_last_marks + 1):
                    if target_last_marks % c == 0:
                        best_c = c
                        best_m = target_last_marks // c
                        found = True
                        break
            if not found:
                best_c = target_last_marks
                best_m = 1

            last_sec.question_count = best_c
            last_sec.marks_per_question = best_m
            last_sec.total_section_marks = best_c * best_m

        return new_sections

    def _parse_json_safely(self, text: str) -> Dict[str, Any]:
        text_str = text.strip()
        if "```json" in text_str:
            match = re.search(r"```json\s*(.*?)\s*```", text_str, re.DOTALL)
            if match:
                text_str = match.group(1).strip()
        elif "```" in text_str:
            match = re.search(r"```\s*(.*?)\s*```", text_str, re.DOTALL)
            if match:
                text_str = match.group(1).strip()

        try:
            return json.loads(text_str)
        except Exception:
            return {}

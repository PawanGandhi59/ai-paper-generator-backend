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
    question_count: int = Field(..., ge=1)
    marks_per_question: int = Field(..., ge=1)
    total_section_marks: int = Field(..., ge=1)


class PaperBlueprint(BaseModel):
    total_marks: int = Field(..., ge=1)
    sections: List[SectionBlueprint] = Field(..., min_length=1)
    sample_questions: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


REFERENCE_ANALYSIS_PROMPT = """
You are an expert academic examination parser. Analyze the following past examination paper text and extract its structural blueprint.

Return ONLY a JSON object with this exact structure:
{
  "total_marks": <total examination marks as integer>,
  "sections": [
    {
      "name": "<Section Name, e.g. Section A>",
      "question_type": "<One of: MCQ, SHORT_ANSWER, LONG_ANSWER, NUMERICAL>",
      "question_count": <number of questions in this section as integer>,
      "marks_per_question": <marks assigned per question in this section as integer>
    }
  ],
  "sample_questions": [
    {
      "section_name": "<Section Name>",
      "question_type": "<MCQ | SHORT_ANSWER | LONG_ANSWER | NUMERICAL>",
      "question_text": "<Question text>",
      "marks": <marks>
    }
  ]
}

Examination Paper Text:
---
{paper_text}
---
"""


class BlueprintService:
    def __init__(self, ai_service: Optional[GeminiService] = None):
        self.ai_service = ai_service or GeminiService()

    def build_custom_blueprint(
        self,
        question_configs: List[QuestionConfigItem],
        total_marks: int,
    ) -> PaperBlueprint:
        """
        Build and validate custom mode blueprint from user-configured question items.
        Enforces sum(question_count * marks_per_question) == total_marks.
        """
        sections: List[SectionBlueprint] = []
        computed_total = 0

        for idx, cfg in enumerate(question_configs):
            sec_name = cfg.section_name or f"Section {chr(65 + idx)}"
            sec_marks = cfg.question_count * cfg.marks_per_question
            computed_total += sec_marks

            sections.append(
                SectionBlueprint(
                    name=sec_name,
                    question_type=cfg.question_type,
                    question_count=cfg.question_count,
                    marks_per_question=cfg.marks_per_question,
                    total_section_marks=sec_marks,
                )
            )

        if computed_total != total_marks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid blueprint: sum of configured question marks ({computed_total}) does not equal target total marks ({total_marks}).",
            )

        return PaperBlueprint(total_marks=total_marks, sections=sections)

    def analyze_reference_paper(
        self,
        paper_pages_text: List[str],
        requested_total_marks: Optional[int] = None,
    ) -> PaperBlueprint:
        """
        Analyze extracted reference paper pages text using Gemini structured prompt.
        Validates structure and adapts blueprint if requested_total_marks differs.
        """
        combined_text = "\n\n".join(paper_pages_text).strip()
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

            total_marks = int(parsed_json.get("total_marks", 50))
            raw_sections = parsed_json.get("sections", [])

            sections: List[SectionBlueprint] = []
            for idx, sec in enumerate(raw_sections):
                name = str(sec.get("name", f"Section {chr(65 + idx)}"))
                q_type_str = str(sec.get("question_type", "SHORT_ANSWER")).upper()
                if q_type_str not in [e.value for e in QuestionType]:
                    q_type_str = "SHORT_ANSWER"
                q_count = max(1, int(sec.get("question_count", 5)))
                marks_per_q = max(1, int(sec.get("marks_per_question", 2)))
                sec_marks = q_count * marks_per_q

                sections.append(
                    SectionBlueprint(
                        name=name,
                        question_type=QuestionType(q_type_str),
                        question_count=q_count,
                        marks_per_question=marks_per_q,
                        total_section_marks=sec_marks,
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
                total_marks = 10

            analysis_total = sum(s.total_section_marks for s in sections)
            ref_blueprint = PaperBlueprint(
                total_marks=analysis_total,
                sections=sections,
                sample_questions=parsed_json.get("sample_questions", []),
            )

            # Adapt reference blueprint if target total_marks differs
            if requested_total_marks and requested_total_marks != ref_blueprint.total_marks:
                return self.adapt_reference_blueprint(ref_blueprint, requested_total_marks)

            return ref_blueprint

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
                return self.adapt_reference_blueprint(fallback_bp, requested_total_marks)
            return fallback_bp

    def adapt_reference_blueprint(
        self,
        ref_blueprint: PaperBlueprint,
        target_total_marks: int,
    ) -> PaperBlueprint:
        """
        Deterministic backend algorithm to adapt reference paper blueprint to target_total_marks.
        Preserves section types, ordering, and marks per question as closely as mathematically possible.
        Enforces sum(question_count * marks_per_question) == target_total_marks.
        """
        if ref_blueprint.total_marks == target_total_marks:
            return ref_blueprint

        scale = target_total_marks / float(ref_blueprint.total_marks)
        new_sections: List[SectionBlueprint] = []

        # 1. Scale section question counts proportionally
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
                )
            )

        current_sum = sum(s.total_section_marks for s in new_sections)

        # 2. Adjust counts deterministically to match exact target_total_marks
        attempts = 0
        while current_sum != target_total_marks and attempts < 100:
            attempts += 1
            diff = target_total_marks - current_sum

            if diff > 0:
                # Need to add marks: find section where adding 1 question gets closest without overshooting
                sec_to_inc = min(new_sections, key=lambda s: s.marks_per_question)
                sec_to_inc.question_count += 1
                sec_to_inc.total_section_marks = sec_to_inc.question_count * sec_to_inc.marks_per_question
            else:
                # Need to subtract marks: find section with question_count > 1
                deletable = [s for s in new_sections if s.question_count > 1]
                if not deletable:
                    break
                sec_to_dec = min(deletable, key=lambda s: s.marks_per_question)
                sec_to_dec.question_count -= 1
                sec_to_dec.total_section_marks = sec_to_dec.question_count * sec_to_dec.marks_per_question

            current_sum = sum(s.total_section_marks for s in new_sections)

        if current_sum != target_total_marks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reasonably adapt reference paper structure to the requested total marks of {target_total_marks}.",
            )

        return PaperBlueprint(
            total_marks=target_total_marks,
            sections=new_sections,
            sample_questions=ref_blueprint.sample_questions,
        )

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

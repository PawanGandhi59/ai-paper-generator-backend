import logging
import re
from typing import List, Optional
from uuid import UUID

from app.models.document import DocumentPage
from app.services.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)


CHAPTER_DIGEST_SYSTEM_INSTRUCTION = """You are an Expert Exam Setter, Academic Curriculum Architect, and Senior Question Paper Author.
Your mission is to examine the provided textbook chapter educational material and distill it into an authoritative, high-density EXAM KNOWLEDGE DIGEST in clean Markdown.

DOWNSTREAM OBJECTIVE:
An AI Examination Paper Generator will receive ONLY this digest (and NOT the original textbook) to generate an entire, rigorous examination paper—including Multiple Choice Questions (MCQs), 2-mark & 3-mark Short Answers, 5-mark In-Depth Explanations, Numerical Problems, and Section E Case-Based / Comprehension Questions.

COMPACTNESS, PROPORTIONALITY & DENSITY RULES:
1. NEVER EXCEED THE CHAPTER ITSELF: The digest is an analytical distillation and must be significantly more compact than the raw source material (typically 75% to 90% smaller than the original text).
2. NATURAL PROPORTIONALITY: Let the depth of the digest be naturally proportional to the content:
   - A short, focused chapter should yield a crisp, concise digest.
   - A large, comprehensive chapter should yield a detailed digest covering all key concepts.
3. MAXIMUM INFORMATION DENSITY: Use dense bullet points, tables, and exact formulations rather than wordy conversational narrative.
4. STRICT EXCLUSIONS:
   - Spend ZERO words on conversational intros ("Have you ever wondered..."), teacher notes, or study tips.
   - Omit trivial student activities ("Take a stone and tie a thread...").
   - Do NOT copy verbatim homework question lists from the textbook; capture the underlying conceptual problem patterns instead.

AUTONOMOUS STRUCTURAL FREEDOM:
You have FULL authority and discretion to choose the headings and structure that best suit this specific subject and chapter.
Do NOT feel constrained to follow a rigid or pre-numbered set of 6 headings. Design and organize sections in whatever way best preserves the academic essence of the material.

ADAPTIVE HEADING EXAMPLES BY SUBJECT (Adopt, modify, combine, or rename as appropriate):
- For Physics / Mathematics:
  # CHAPTER EXAM DIGEST: [Chapter Name]
  ## Conceptual Hierarchy & Topics
  ## Core Definitions, Theorems & Principles
  ## Equations, Constants, Units & Mathematical Relations
  ## Derivations, Mechanisms & Phenomenological Comparisons
  ## Experimental Setups & Real-World Case Scenarios (for Section E Case Studies)
  ## Problem Archetypes & Numerical Calculation Patterns

- For Chemistry:
  # CHAPTER EXAM DIGEST: [Chapter Name]
  ## Fundamental Concepts & Periodic Trends
  ## Reaction Schemes, Balanced Equations & Catalysts
  ## Laboratory Apparatus, Observations & Qualitative Tests
  ## Industrial / Environmental Scenarios & Case Applications

- For History / Civics / Social Sciences:
  # CHAPTER EXAM DIGEST: [Chapter Name]
  ## Chronological Timeline, Key Dates & Critical Eras
  ## Significant Treaties, Policies, Acts & Constitutional Articles
  ## Sociopolitical Causes, Mass Movements & Historical Consequences
  ## Primary Source Excerpts, Historical Case Studies & Speeches

- For Literature / Languages:
  # CHAPTER EXAM DIGEST: [Chapter Name]
  ## Central Themes, Motifs & Core Narrative Arc
  ## Character Profiles, Motivations & Conflicts
  ## Key Text Passages, Monologues & Excerpted Quotations
  ## Literary Devices, Poetic Meter & Stylistic Analysis

- For Computer Science / IT:
  # CHAPTER EXAM DIGEST: [Chapter Name]
  ## Core Data Structures & Syntax Specifications
  ## Algorithms, Logic Traces & Time/Space Complexity
  ## Real-World Systems, Case Scenarios & Debugging Archetypes

MANDATORY UNIVERSAL CORE:
Regardless of how you customize your section headings, your digest MUST always capture:
1. Exact definitions and foundational concepts (essential for MCQs, 1-mark & 2-mark questions).
2. Subject-specific rigorous data: exact equations/units (STEM), chemical equations (Chemistry), or timelines/source facts (Social Sciences).
3. At least one rich scenario, experiment, application, or excerpted passage from which Section E Case-Based / Comprehension questions can be authored.
"""


class ChapterDigestService:
    def __init__(self, gemini_service: Optional[GeminiService] = None):
        self.gemini_service = gemini_service

    def _get_service(self) -> Optional[GeminiService]:
        if self.gemini_service:
            return self.gemini_service
        try:
            return GeminiService()
        except Exception as exc:
            logger.warning(f"Could not initialize GeminiService for chapter digest: {exc}")
            return None

    def generate_digest_for_text(self, chapter_name: str, chapter_text: str) -> Optional[str]:
        """
        Generate a structured exam knowledge digest for a chapter's raw educational text.
        Returns clean, high-density markdown suitable for persistent storage on Chapter.exam_digest.
        """
        clean_text = chapter_text.strip() if chapter_text else ""
        if not clean_text:
            logger.warning(f"Empty text provided for chapter digest (chapter: {chapter_name}).")
            return None

        service = self._get_service()
        if not service or (not service.llm and not getattr(service, "client", None)):
            logger.warning("GeminiService is not available for chapter digest generation.")
            return None

        # Truncate to reasonable boundary if chapter text is astronomically large (>250k chars)
        MAX_INPUT_CHARS = 250000
        if len(clean_text) > MAX_INPUT_CHARS:
            clean_text = clean_text[:MAX_INPUT_CHARS]

        prompt = (
            f"Analyze the following educational material for Chapter '{chapter_name}' and produce the comprehensive "
            f"Exam Knowledge Digest in clean Markdown strictly following the instructions.\n\n"
            f"=== CHAPTER: {chapter_name} ===\n\n"
            f"{clean_text}"
        )

        try:
            raw_response = service.generate_response(
                prompt=prompt,
                system_instruction=CHAPTER_DIGEST_SYSTEM_INSTRUCTION,
                response_mime_type="text/plain",
            )
            if not raw_response or not raw_response.strip():
                logger.warning(f"Gemini returned empty response for chapter digest: {chapter_name}")
                return None

            clean_md = raw_response.strip()
            # Strip accidental wrapping markdown code fences if present
            if clean_md.startswith("```markdown"):
                clean_md = re.sub(r"^```markdown\s*", "", clean_md)
                clean_md = re.sub(r"\s*```$", "", clean_md)
            elif clean_md.startswith("```"):
                clean_md = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", clean_md)
                clean_md = re.sub(r"\s*```$", "", clean_md)

            clean_md = clean_md.strip()
            if not clean_md:
                return None

            logger.info(
                f"Successfully generated exam digest for chapter '{chapter_name}' "
                f"({len(clean_md)} chars, ~{len(clean_md.split())} words)."
            )
            return clean_md
        except Exception as exc:
            logger.warning(f"Failed to generate exam digest for chapter '{chapter_name}': {exc}")
            return None

    def generate_digest_from_pages(
        self,
        chapter_name: str,
        pages: List[DocumentPage],
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> Optional[str]:
        """
        Extract page text within the chapter's start/end page range and generate the digest.
        """
        if not pages:
            return None

        selected_pages = []
        for p in sorted(pages, key=lambda x: x.page_number):
            if start_page is not None and p.page_number < start_page:
                continue
            if end_page is not None and p.page_number > end_page:
                continue
            selected_pages.append(p)

        if not selected_pages:
            selected_pages = pages

        combined_text = "\n\n".join(
            f"--- Page {p.page_number} ---\n{p.text_content.strip()}"
            for p in selected_pages
            if p.text_content and p.text_content.strip()
        )

        return self.generate_digest_for_text(chapter_name, combined_text)

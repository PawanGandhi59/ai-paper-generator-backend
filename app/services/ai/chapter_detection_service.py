import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.document import DocumentPage
from app.services.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)


class ChapterDetectionItem(BaseModel):
    chapter_number: int = Field(..., description="Integer chapter number (1, 2, 3...)")
    name: str = Field(..., description="Clean chapter title / name")
    start_page: int = Field(..., description="1-based starting page number where the chapter begins")


class ChapterDetectionResult(BaseModel):
    chapters: List[ChapterDetectionItem] = Field(default_factory=list, description="List of detected chapters")


CHAPTER_DETECTION_SYSTEM_INSTRUCTION = """You are an expert textbook parser.
You are given a page-by-page header summary of a textbook. Each page block shows the page number and up to 15 non-empty lines from that page.

Your task is to analyze all page headers and identify every page where a NEW GENUINE TEXTBOOK CHAPTER OR UNIT BEGINS.

For each genuine chapter identified, return:
1. chapter_number: Integer chapter number (1, 2, 3...).
2. name: Clean chapter title / name (excluding "Chapter 1:" prefix if present).
3. start_page: The exact 1-based page number where this chapter begins.

Rules:
- Identify actual textbook chapters, units, modules, or main divisions.
- Do NOT output table of contents, preface, index, bibliography, answer keys, or sub-sections as separate chapters.
- Only mark a page as a start_page if a new chapter genuinely begins on that exact page number.
- Output MUST strictly match the requested JSON schema.
"""


class ChapterDetectionService:
    def __init__(self, gemini_service: Optional[GeminiService] = None):
        self.gemini_service = gemini_service

    def _get_service(self) -> Optional[GeminiService]:
        if self.gemini_service:
            return self.gemini_service
        try:
            return GeminiService()
        except Exception as exc:
            logger.warning(f"Could not initialize GeminiService for chapter detection: {exc}")
            return None

    def _build_page_header_context(
        self, sorted_pages: List[DocumentPage], max_lines_per_page: int = 15
    ) -> str:
        """
        Build a compact, deterministic page-header context across pages.
        For every page: extracts up to 15 non-empty lines without truncation or character limits.
        """
        blocks = []
        for page in sorted_pages:
            text = page.text_content or ""
            lines = [l.strip() for l in text.splitlines() if l.strip()][:max_lines_per_page]
            page_text = "\n".join(lines) if lines else "(empty page)"
            blocks.append(f"=== PAGE {page.page_number} ===\n{page_text}")

        return "\n\n".join(blocks)

    def detect_chapters(self, pages: List[DocumentPage]) -> List[ChapterDetectionItem]:
        if not pages:
            logger.warning("Chapter detection called with empty pages list.")
            return []

        sorted_pages = sorted(pages, key=lambda p: p.page_number)
        total_pages = len(sorted_pages)

        service = self._get_service()
        detected_chapters = []

        # --- PRIMARY PATH: Gemini Page-Structure Detection ---
        if service and service.client:
            try:
                detected_chapters = self._gemini_page_structure_detection(service, sorted_pages, total_pages)
                if detected_chapters:
                    logger.info("chapter_detection_method=GEMINI")
                    return detected_chapters
            except Exception as exc:
                logger.warning(f"Gemini page-structure chapter detection failed: {exc}. Proceeding to regex fallback.")

        # --- FALLBACK PATH: Regex / TOC Detection ---
        logger.info("chapter_detection_method=REGEX_FALLBACK")
        return self._regex_fallback_detection(service, sorted_pages, total_pages)

    def _gemini_page_structure_detection(
        self, service: GeminiService, sorted_pages: List[DocumentPage], total_pages: int
    ) -> List[ChapterDetectionItem]:
        """
        Primary Gemini Chapter Detection pass using page-by-page header context.
        Uses deterministic page batching if total token count exceeds single request context limits.
        """
        BATCH_SIZE = 250
        raw_items: List[ChapterDetectionItem] = []

        if len(sorted_pages) <= BATCH_SIZE:
            # Single call for normal-sized books
            header_context = self._build_page_header_context(sorted_pages, max_lines_per_page=15)
            items = self._call_gemini_detection(service, header_context)
            raw_items.extend(items)
        else:
            # Deterministic page batching for large books
            for i in range(0, len(sorted_pages), BATCH_SIZE):
                batch_pages = sorted_pages[i : i + BATCH_SIZE]
                header_context = self._build_page_header_context(batch_pages, max_lines_per_page=15)
                items = self._call_gemini_detection(service, header_context)
                raw_items.extend(items)

        valid_chapters = self._validate_and_clean_chapters(raw_items, total_pages)
        return valid_chapters

    def _regex_fallback_detection(
        self, service: Optional[GeminiService], sorted_pages: List[DocumentPage], total_pages: int
    ) -> List[ChapterDetectionItem]:
        """
        Fallback path using Table of Contents / Heading Candidates regex extraction.
        """
        detected = []
        if service and service.client:
            try:
                toc_text = self._extract_toc_text(sorted_pages)
                if toc_text:
                    detected = self._call_gemini_detection(service, toc_text)

                if not detected:
                    candidate_text = self._extract_heading_candidates(sorted_pages)
                    if candidate_text:
                        detected = self._call_gemini_detection(service, candidate_text)
            except Exception as exc:
                logger.warning(f"Regex fallback detection with Gemini failed: {exc}")

        return self._validate_and_clean_chapters(detected, total_pages)

    def _extract_toc_text(self, pages: List[DocumentPage]) -> Optional[str]:
        toc_lines = []
        is_in_toc = False

        toc_regex = re.compile(
            r"\b(table of contents|contents|index of chapters|index|contents at a glance|unit listing)\b",
            re.IGNORECASE,
        )

        for page in pages:
            text = page.text_content or ""
            lines = text.splitlines()

            for line in lines:
                clean_line = line.strip()
                if not clean_line:
                    continue

                if toc_regex.search(clean_line):
                    is_in_toc = True

                if is_in_toc:
                    toc_lines.append(f"[Page {page.page_number}] {clean_line}")
                    if len(toc_lines) > 500:
                        break

            if len(toc_lines) > 500:
                break

        if toc_lines and len(toc_lines) >= 3:
            return "\n".join(toc_lines)
        return None

    def _extract_heading_candidates(self, sorted_pages: List[DocumentPage]) -> str:
        candidates = []

        chapter_patterns = [
            re.compile(r"^\s*(chapter|chap\.|unit|module|part|section|lesson)\s+(\d+|[ivxlcdm]+)\b", re.IGNORECASE),
            re.compile(r"^\s*(\d+|[IVXLCDM]+)[\.\:]?\s+([A-Z][A-Za-z0-9\s\-\:\,\'\’\!]{2,80})$"),
            re.compile(r"^\s*(chapter|unit|module|lesson)\b.*$", re.IGNORECASE),
        ]

        exercise_keywords = (
            "?", "what do", "why did", "where is", "how are", "which ", "according to",
            "answer the", "read the", "circle the", "fill in", "match the", "complete the",
            "write a", "draw yourself", "listen to", "can you", "find out"
        )

        for page in sorted_pages:
            lines = (page.text_content or "").splitlines()
            top_lines = lines[:15]
            for idx, line in enumerate(top_lines):
                clean_line = line.strip()
                if not clean_line or len(clean_line) < 3 or len(clean_line) > 100:
                    continue

                if any(kw in clean_line.lower() for kw in exercise_keywords):
                    continue

                for pat in chapter_patterns:
                    if pat.search(clean_line):
                        top_12_text = "\n".join([l.strip() for l in lines[:12] if l.strip()])[:400]
                        candidates.append(f"--- Page {page.page_number} ---\n{top_12_text}")
                        break

        if len(candidates) > 200:
            candidates = candidates[:200]

        return "\n".join(candidates)

    def _call_gemini_detection(self, service: GeminiService, input_text: str) -> List[ChapterDetectionItem]:
        from google.genai import types

        prompt = f"Analyze the following textbook document text / page headers and identify all chapters with their 1-based start pages:\n\n{input_text}"

        config = types.GenerateContentConfig(
            system_instruction=CHAPTER_DETECTION_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ChapterDetectionResult,
            temperature=0.1,
        )

        response = service.client.models.generate_content(
            model=service.model_name,
            contents=prompt,
            config=config,
        )

        if not response or not response.text:
            logger.warning("Gemini returned empty response for chapter detection.")
            return []

        parsed_data = json.loads(response.text)
        result = ChapterDetectionResult.model_validate(parsed_data)
        return result.chapters

    def _validate_and_clean_chapters(
        self, items: List[ChapterDetectionItem], total_pages: int
    ) -> List[ChapterDetectionItem]:
        valid = []
        seen_numbers = set()
        seen_start_pages = set()

        for item in items:
            if item.chapter_number <= 0:
                logger.warning(f"Discarding chapter with invalid chapter_number={item.chapter_number}.")
                continue

            if item.start_page < 1 or item.start_page > total_pages:
                logger.warning(f"Discarding chapter {item.chapter_number} ({item.name}) with invalid start_page={item.start_page} (total pages={total_pages}).")
                continue

            if item.chapter_number in seen_numbers:
                logger.warning(f"Discarding duplicate chapter_number={item.chapter_number}.")
                continue

            if item.start_page in seen_start_pages:
                logger.warning(f"Discarding duplicate start_page={item.start_page} for chapter_number={item.chapter_number}.")
                continue

            clean_name = item.name.strip()
            if not clean_name:
                continue

            valid.append(
                ChapterDetectionItem(
                    chapter_number=item.chapter_number,
                    name=clean_name,
                    start_page=item.start_page,
                )
            )
            seen_numbers.add(item.chapter_number)
            seen_start_pages.add(item.start_page)

        valid.sort(key=lambda c: c.start_page)
        return valid

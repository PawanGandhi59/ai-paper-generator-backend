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
Your task is to analyze document text or candidate chapter headings extracted from a textbook and return a structured JSON list of all actual chapters.
For each chapter identified, extract:
1. chapter_number: integer number of the chapter (1, 2, 3...).
2. name: clean title of the chapter (excluding "Chapter 1:" prefix if present).
3. start_page: 1-based page number where the chapter begins in the book.

Rules:
- Do NOT invent fake chapters.
- Only output genuine textbook chapters/units (do not include table of contents, preface, index, bibliography, or sub-sections as separate chapters).
- Ensure chapter start_page values accurately reflect the starting page numbers provided in the input context.
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

    def detect_chapters(self, pages: List[DocumentPage]) -> List[ChapterDetectionItem]:
        if not pages:
            logger.warning("Chapter detection called with empty pages list.")
            return []

        sorted_pages = sorted(pages, key=lambda p: p.page_number)
        total_pages = len(sorted_pages)

        service = self._get_service()
        if not service or not service.client:
            logger.warning("GeminiService client unavailable. Skipping AI chapter detection.")
            return []

        try:
            # Stage 1: Search all pages for Table of Contents
            toc_text = self._extract_toc_text(sorted_pages)
            detected = []

            if toc_text:
                logger.info("Table of Contents detected. Attempting Stage 1 extraction.")
                detected = self._call_gemini_detection(service, toc_text)

            # Stage 2: Fallback to scanning heading candidates across all pages if Stage 1 fails
            if not detected:
                logger.info("Stage 1 TOC detection returned no chapters. Proceeding to Stage 2 heading candidate scan.")
                candidate_text = self._extract_heading_candidates(sorted_pages)
                if candidate_text:
                    detected = self._call_gemini_detection(service, candidate_text)

            # Validate and clean up detected chapters
            valid_chapters = self._validate_and_clean_chapters(detected, total_pages)
            logger.info(f"Chapter detection completed. Found {len(valid_chapters)} valid chapters.")
            return valid_chapters

        except Exception as exc:
            logger.warning(f"AI Chapter Detection failed with error: {exc}. Falling back safely with zero detected chapters.")
            return []

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
                    # Keep accumulating up to 500 lines of TOC
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
            # Inspect first 15 lines of each page for potential chapter titles
            top_lines = lines[:15]
            for idx, line in enumerate(top_lines):
                clean_line = line.strip()
                if not clean_line or len(clean_line) < 3 or len(clean_line) > 100:
                    continue

                # Skip obvious exercise/question lines
                if any(kw in clean_line.lower() for kw in exercise_keywords):
                    continue

                for pat in chapter_patterns:
                    if pat.search(clean_line):
                        top_12_text = "\n".join([l.strip() for l in lines[:12] if l.strip()])[:400]
                        candidates.append(f"--- Page {page.page_number} ---\n{top_12_text}")
                        break

        # Truncate candidates if too large
        if len(candidates) > 200:
            candidates = candidates[:200]

        return "\n".join(candidates)

    def _call_gemini_detection(self, service: GeminiService, input_text: str) -> List[ChapterDetectionItem]:
        from google.genai import types

        prompt = f"Analyze the following textbook document text / candidates and identify all chapters with their 1-based start pages:\n\n{input_text}"

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

        # Parse JSON
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
            # Validate chapter number and page range
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

        # Sort strictly by start_page ascending
        valid.sort(key=lambda c: c.start_page)
        return valid

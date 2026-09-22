from unittest.mock import MagicMock, patch
import uuid

import pytest

from app.models.chapter import Chapter
from app.models.document import DocumentPage, DocumentChunk
from app.services.ai.chapter_digest_service import ChapterDigestService
from app.services.paper.paper_generator_service import PaperGeneratorService


def test_chapter_digest_service_generate_digest_for_text_direct_markdown():
    mock_gemini = MagicMock()
    mock_markdown = (
        "# CHAPTER EXAM DIGEST: Thermodynamics\n\n"
        "## 1. TOPICS & SUBTOPICS\n- First Law of Thermodynamics\n\n"
        "## 2. CORE DEFINITIONS, LAWS & THEOREMS\n- First Law: dQ = dU + dW\n\n"
        "## 3. FORMULAS, EQUATIONS, CONSTANTS & UNITS\n- dQ = dU + dW (Joules)\n\n"
        "## 5. CASE SCENARIOS, EXPERIMENTS & PASSAGES\n- Carnot Cycle efficiency\n"
    )
    mock_gemini.generate_response.return_value = mock_markdown

    service = ChapterDigestService(gemini_service=mock_gemini)
    result = service.generate_digest_for_text("Thermodynamics", "Full raw text of thermodynamics chapter...")

    assert result is not None
    assert "# CHAPTER EXAM DIGEST: Thermodynamics" in result
    assert "dQ = dU + dW" in result
    assert "Carnot Cycle" in result
    mock_gemini.generate_response.assert_called_once()
    # Ensure response_mime_type was text/plain
    assert mock_gemini.generate_response.call_args.kwargs.get("response_mime_type") == "text/plain"


def test_chapter_digest_service_strips_markdown_code_fences():
    mock_gemini = MagicMock()
    fenced_markdown = (
        "```markdown\n"
        "# CHAPTER EXAM DIGEST: Optics\n\n"
        "## 1. TOPICS\n- Reflection and Refraction\n"
        "```"
    )
    mock_gemini.generate_response.return_value = fenced_markdown

    service = ChapterDigestService(gemini_service=mock_gemini)
    result = service.generate_digest_for_text("Optics", "Raw optics text...")

    assert result is not None
    assert not result.startswith("```")
    assert not result.endswith("```")
    assert "# CHAPTER EXAM DIGEST: Optics" in result


def test_chapter_digest_service_generate_digest_from_pages():
    mock_gemini = MagicMock()
    mock_gemini.generate_response.return_value = "# CHAPTER EXAM DIGEST: Optics\n\n## 1. TOPICS\n- Reflection"

    service = ChapterDigestService(gemini_service=mock_gemini)
    pages = [
        DocumentPage(page_number=1, text_content="Intro page"),
        DocumentPage(page_number=2, text_content="Optics laws and mirrors"),
        DocumentPage(page_number=3, text_content="End of optics"),
        DocumentPage(page_number=4, text_content="Next chapter"),
    ]

    result = service.generate_digest_from_pages(
        chapter_name="Optics",
        pages=pages,
        start_page=2,
        end_page=3,
    )

    assert result is not None
    assert "# CHAPTER EXAM DIGEST: Optics" in result


def test_paper_generator_retrieves_exam_digest_when_present():
    """Verify that when selected chapters have exam_digest, _retrieve_chapter_context uses it directly."""
    mock_db = MagicMock()
    ch_id = uuid.uuid4()
    ch = MagicMock(spec=Chapter)
    ch.id = ch_id
    ch.chapter_number = 1
    ch.name = "Kinematics"
    ch.exam_digest = "# CHAPTER EXAM DIGEST: Kinematics\n\n## 1. TOPICS\n- Motion in 1D"
    ch.start_page = 1
    ch.end_page = 20
    ch.book_id = uuid.uuid4()

    mock_db.query.return_value.filter.return_value.all.return_value = [ch]

    svc = PaperGeneratorService(db=mock_db)
    context = svc._retrieve_chapter_context(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        book_id=ch.book_id,
        selected_chapter_ids=[ch_id],
        topic_focus=None,
    )

    assert "Source Exam Knowledge Digest" in context
    assert "CHAPTER EXAM DIGEST: Kinematics" in context
    assert str(ch_id) in svc._chapter_contexts_map
    # DocumentChunk query should NOT be executed when all chapters have precomputed digests
    mock_db.execute.assert_not_called()


def test_paper_generator_falls_back_to_chunks_when_digest_missing():
    """Verify that when selected chapters lack exam_digest, our normal system (DocumentChunks) acts as fallback."""
    mock_db = MagicMock()
    ch_id = uuid.uuid4()
    ch = MagicMock(spec=Chapter)
    ch.id = ch_id
    ch.chapter_number = 2
    ch.name = "Dynamics"
    ch.exam_digest = None  # Missing digest - should trigger normal chunk fallback
    ch.start_page = 21
    ch.end_page = 40
    ch.book_id = uuid.uuid4()

    mock_db.query.return_value.filter.return_value.all.return_value = [ch]

    chunk = MagicMock(spec=DocumentChunk)
    chunk.page_number = 25
    chunk.chapter_id = ch_id
    chunk.content = "Force equals mass times acceleration."

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [chunk]
    mock_db.execute.return_value.scalars.return_value = mock_scalars

    svc = PaperGeneratorService(db=mock_db)
    context = svc._retrieve_chapter_context(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        book_id=ch.book_id,
        selected_chapter_ids=[ch_id],
        topic_focus=None,
    )

    assert "Force equals mass times acceleration." in context
    assert "[Source Excerpt 1 (Page 25)" in context
    mock_db.execute.assert_called_once()

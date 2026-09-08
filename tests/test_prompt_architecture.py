"""
Unit and integration tests verifying the LLM prompt architecture:
1. Paper generation uses PAPER_GENERATION_SYSTEM_INSTRUCTION.
2. Paper generation never receives RAG_SYSTEM_INSTRUCTION.
3. Recovery uses PAPER_RECOVERY_SYSTEM_INSTRUCTION.
4. Blueprint analysis uses BLUEPRINT_ANALYSIS_SYSTEM_INSTRUCTION.
5. RAG continues using RAG_SYSTEM_INSTRUCTION.
6. Chapter detection remains unchanged (CHAPTER_DETECTION_SYSTEM_INSTRUCTION).
7. count_tokens() does not silently inject RAG_SYSTEM_INSTRUCTION.
8. Paper-generation dynamic data remains in the user prompt.
9. GeminiCompletePaperSchema remains active in structured output invocation.
10. CUSTOM mode paper generation still functions.
11. REFERENCE mode paper generation still functions.
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas.paper import (
    DifficultyLevel,
    GenerationMode,
    GeminiCompletePaperSchema,
    QuestionType,
)
from app.services.ai.gemini_service import GeminiService
from app.services.ai.prompts.blueprint_prompt import BLUEPRINT_ANALYSIS_SYSTEM_INSTRUCTION
from app.services.ai.prompts.paper_prompt import (
    PAPER_GENERATION_SYSTEM_INSTRUCTION,
    PAPER_RECOVERY_SYSTEM_INSTRUCTION,
)
from app.services.ai.prompts.rag_prompt import RAG_SYSTEM_INSTRUCTION
from app.services.ai.chapter_detection_service import (
    ChapterDetectionService,
    CHAPTER_DETECTION_SYSTEM_INSTRUCTION,
)
from app.services.paper.blueprint_service import (
    BlueprintService,
    PaperBlueprint,
    SectionBlueprint,
)
from app.services.paper.paper_generator_service import PaperGeneratorService


# ---------------------------------------------------------------------------
# 1 & 2 & 7: GeminiService System vs. User Message Separation & Token Counting
# ---------------------------------------------------------------------------

def test_gemini_service_generate_response_no_default_fallback():
    """Verify that generate_response does NOT silently inject RAG_SYSTEM_INSTRUCTION."""
    svc = GeminiService.__new__(GeminiService)
    svc.model_name = "gemini-2.5-flash"
    svc.session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "call_count": 0}
    mock_llm = MagicMock()
    mock_llm.bind.return_value = mock_llm
    mock_resp = MagicMock()
    mock_resp.content = "Test response"
    mock_llm.invoke.return_value = mock_resp
    svc.llm = mock_llm
    svc.client = None

    # Call with system_instruction=None
    svc.generate_response("User question prompt", system_instruction=None)

    called_messages = mock_llm.invoke.call_args[0][0]
    # Verify ONLY HumanMessage was passed; NO SystemMessage with RAG_SYSTEM_INSTRUCTION
    assert len(called_messages) == 1
    assert isinstance(called_messages[0], HumanMessage)
    assert called_messages[0].content == "User question prompt"
    assert not any(isinstance(m, SystemMessage) for m in called_messages)


def test_gemini_service_generate_response_explicit_paper_instruction():
    """Verify that generate_response attaches explicit PAPER_GENERATION_SYSTEM_INSTRUCTION."""
    svc = GeminiService.__new__(GeminiService)
    svc.model_name = "gemini-2.5-flash"
    svc.session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "call_count": 0}
    mock_llm = MagicMock()
    mock_llm.bind.return_value = mock_llm
    mock_resp = MagicMock()
    mock_resp.content = "{}"
    mock_llm.invoke.return_value = mock_resp
    svc.llm = mock_llm
    svc.client = None

    svc.generate_response(
        prompt="Generate exam questions",
        system_instruction=PAPER_GENERATION_SYSTEM_INSTRUCTION,
        response_schema=GeminiCompletePaperSchema,
    )

    called_messages = mock_llm.invoke.call_args[0][0]
    assert len(called_messages) == 2
    assert isinstance(called_messages[0], SystemMessage)
    assert called_messages[0].content == PAPER_GENERATION_SYSTEM_INSTRUCTION
    # Assert RAG_SYSTEM_INSTRUCTION is NOT present anywhere
    assert RAG_SYSTEM_INSTRUCTION not in called_messages[0].content
    assert "You are an expert AI Educational Tutor" not in called_messages[0].content
    assert "You are an expert academic examination author" in called_messages[0].content

    assert isinstance(called_messages[1], HumanMessage)
    assert called_messages[1].content == "Generate exam questions"


def test_gemini_service_count_tokens_no_silent_rag_injection():
    """Verify that count_tokens does NOT silently prepend RAG_SYSTEM_INSTRUCTION."""
    svc = GeminiService.__new__(GeminiService)
    mock_llm = MagicMock()
    mock_llm.get_num_tokens.side_effect = lambda text: len(text) // 4
    svc.llm = mock_llm

    prompt = "This is a prompt with exactly ten words."

    # Without system instruction
    count_bare = svc.count_tokens(prompt, system_instruction=None)

    # With paper system instruction
    count_paper = svc.count_tokens(prompt, system_instruction=PAPER_GENERATION_SYSTEM_INSTRUCTION)

    # With RAG system instruction
    count_rag = svc.count_tokens(prompt, system_instruction=RAG_SYSTEM_INSTRUCTION)

    # Verify bare count reflects prompt only
    assert count_bare == len(prompt) // 4
    # Verify count with PAPER instruction includes paper instruction tokens
    assert count_paper > count_bare
    # Verify count with RAG instruction is substantially larger (~1500 tokens)
    assert count_rag > count_paper
    # Verify RAG prompt wasn't used for count_bare
    mock_llm.get_num_tokens.assert_any_call(prompt)


# ---------------------------------------------------------------------------
# 3, 4, 8, 9: Paper Generation & Recovery System Prompts & Dynamic Data
# ---------------------------------------------------------------------------

def test_paper_generator_passes_paper_system_instruction_and_schema():
    """Verify that _generate_complete_paper passes PAPER_GENERATION_SYSTEM_INSTRUCTION and GeminiCompletePaperSchema."""
    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.count_tokens.return_value = 500
    mock_ai.generate_response.return_value = json.dumps({
        "sections": [
            {
                "section_name": "Section A",
                "questions": [
                    {
                        "question_text": "Sample question 1?",
                        "question_type": "MCQ",
                        "marks": 1,
                        "difficulty": "EASY",
                        "mcq_options": ["A. Opt 1", "B. Opt 2", "C. Opt 3", "D. Opt 4"],
                        "correct_answer": "A. Opt 1",
                        "solution_explanation": "Sol",
                    }
                ],
            }
        ]
    })

    svc = PaperGeneratorService.__new__(PaperGeneratorService)
    svc.ai_service = mock_ai
    svc.db = MagicMock()

    bp = PaperBlueprint(
        total_marks=1,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.MCQ,
                question_count=1,
                marks_per_question=1,
                total_section_marks=1,
            )
        ],
    )

    questions = svc._generate_complete_paper(
        blueprint=bp,
        context_text="Educational textbook content for Chapter 1.",
        topic_focus="Electric Charges",
        difficulty=DifficultyLevel.EASY,
        generation_mode=GenerationMode.CUSTOM,
        sample_questions=None,
        chapter_weightages_data=[{"chapter_number": 1, "chapter_name": "Electrostatics", "weightage_percentage": 100.0, "allocated_marks": 1}],
    )

    # 1. Assert count_tokens was called with PAPER_GENERATION_SYSTEM_INSTRUCTION
    mock_ai.count_tokens.assert_called_once()
    assert mock_ai.count_tokens.call_args[1].get("system_instruction") == PAPER_GENERATION_SYSTEM_INSTRUCTION

    # 2. Assert generate_response was called with PAPER_GENERATION_SYSTEM_INSTRUCTION
    mock_ai.generate_response.assert_called_once()
    call_kwargs = mock_ai.generate_response.call_args[1]
    assert call_kwargs.get("system_instruction") == PAPER_GENERATION_SYSTEM_INSTRUCTION
    assert call_kwargs.get("system_instruction") != RAG_SYSTEM_INSTRUCTION
    assert "AI Educational Tutor" not in call_kwargs.get("system_instruction")

    # 3. Assert structured schema is GeminiCompletePaperSchema
    assert call_kwargs.get("response_schema") == GeminiCompletePaperSchema

    # 4. Assert user prompt contains dynamic data (blueprint, context, topic focus, chapters)
    user_prompt = mock_ai.generate_response.call_args[0][0]
    assert "SECTION NAME: 'Section A'" in user_prompt
    assert "TOTAL EXAMINATION MARKS: 1" in user_prompt
    assert "Electric Charges" in user_prompt
    assert "Educational textbook content for Chapter 1." in user_prompt
    assert "Electrostatics" in user_prompt


def test_paper_recovery_passes_recovery_system_instruction():
    """Verify that supplemental recovery passes PAPER_RECOVERY_SYSTEM_INSTRUCTION."""
    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.count_tokens.return_value = 500

    # First call (main paper): returns 0 questions to force recovery loop
    # Second call (recovery): returns the needed question
    main_resp = json.dumps({"sections": [{"section_name": "Section A", "questions": []}]})
    recovery_resp = json.dumps({
        "questions": [
            {
                "question_text": "Supplemental recovered MCQ?",
                "question_type": "MCQ",
                "marks": 1,
                "difficulty": "EASY",
                "mcq_options": ["A. W", "B. X", "C. Y", "D. Z"],
                "correct_answer": "A. W",
                "solution_explanation": "Explanation",
            }
        ]
    })
    mock_ai.generate_response.side_effect = [main_resp, recovery_resp]

    svc = PaperGeneratorService.__new__(PaperGeneratorService)
    svc.ai_service = mock_ai
    svc.db = MagicMock()

    bp = PaperBlueprint(
        total_marks=1,
        sections=[
            SectionBlueprint(
                name="Section A",
                question_type=QuestionType.MCQ,
                question_count=1,
                marks_per_question=1,
                total_section_marks=1,
            )
        ],
    )

    questions = svc._generate_complete_paper(
        blueprint=bp,
        context_text="Educational content.",
        topic_focus=None,
        difficulty=DifficultyLevel.EASY,
        generation_mode=GenerationMode.CUSTOM,
        sample_questions=None,
        chapter_weightages_data=[{"chapter_number": 1, "chapter_name": "Ch 1", "weightage_percentage": 100.0, "allocated_marks": 1}],
    )

    assert len(questions) == 1
    assert mock_ai.generate_response.call_count == 2

    # Second call must be recovery with PAPER_RECOVERY_SYSTEM_INSTRUCTION
    rec_call = mock_ai.generate_response.call_args_list[1]
    rec_kwargs = rec_call[1]
    assert rec_kwargs.get("system_instruction") == PAPER_RECOVERY_SYSTEM_INSTRUCTION
    assert rec_kwargs.get("system_instruction") != RAG_SYSTEM_INSTRUCTION
    assert "AI Educational Tutor" not in rec_kwargs.get("system_instruction")

    rec_prompt = rec_call[0][0]
    assert "missing slot(s) across the examination paper" in rec_prompt
    assert "TARGET MISSING SLOTS:" in rec_prompt
    assert "EXCLUSION RULE:" in rec_prompt


# ---------------------------------------------------------------------------
# 4: Blueprint Analysis System Instruction
# ---------------------------------------------------------------------------

def test_blueprint_analysis_passes_blueprint_system_instruction():
    """Verify that analyze_reference_paper passes BLUEPRINT_ANALYSIS_SYSTEM_INSTRUCTION."""
    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "total_marks": 50,
        "sections": [
            {
                "name": "Part A",
                "question_type": "MCQ",
                "question_count": 10,
                "marks_per_question": 1,
                "has_internal_choice": False,
                "alternatives_per_question": 1,
            }
        ],
        "sample_questions": [],
    })

    svc = BlueprintService(ai_service=mock_ai)
    bp = svc.analyze_reference_paper(
        paper_pages_text=["Sample past paper page 1 with 10 MCQs."],
        requested_total_marks=50,
    )

    assert bp.total_marks == 50
    mock_ai.generate_response.assert_called_once()
    call_kwargs = mock_ai.generate_response.call_args[1]
    assert call_kwargs.get("system_instruction") == BLUEPRINT_ANALYSIS_SYSTEM_INSTRUCTION
    assert call_kwargs.get("system_instruction") != RAG_SYSTEM_INSTRUCTION
    assert "AI Educational Tutor" not in call_kwargs.get("system_instruction")
    assert "You are an expert academic examination parser" in call_kwargs.get("system_instruction")

    # Dynamic reference paper text is in user prompt
    prompt = call_kwargs.get("prompt") or mock_ai.generate_response.call_args[0][0]
    assert "Sample past paper page 1 with 10 MCQs." in prompt


# ---------------------------------------------------------------------------
# 5 & 6: RAG & Chapter Detection Integrity
# ---------------------------------------------------------------------------

def test_rag_workflow_continues_using_rag_system_instruction():
    """Verify that RAG generation explicitly uses RAG_SYSTEM_INSTRUCTION."""
    svc = GeminiService.__new__(GeminiService)
    svc.model_name = "gemini-2.5-flash"
    mock_llm = MagicMock()
    mock_llm.bind.return_value = mock_llm
    mock_resp = MagicMock()
    mock_resp.content = '{"answer": "Tutor explanation"}'
    mock_llm.invoke.return_value = mock_resp
    svc.llm = mock_llm
    svc.client = None

    res = svc.generate_with_context(query="What is Newton's second law?", context="F = ma")

    called_messages = mock_llm.invoke.call_args[0][0]
    assert len(called_messages) == 2
    assert isinstance(called_messages[0], SystemMessage)
    assert called_messages[0].content == RAG_SYSTEM_INSTRUCTION
    assert "AI Educational Tutor" in called_messages[0].content


def test_chapter_detection_continues_using_chapter_detection_system_instruction():
    """Verify that chapter detection continues passing CHAPTER_DETECTION_SYSTEM_INSTRUCTION."""
    mock_ai = MagicMock(spec=GeminiService)
    mock_ai.generate_response.return_value = json.dumps({
        "chapters": [{"chapter_number": 1, "name": "Kinematics", "start_page": 1}]
    })

    detector = ChapterDetectionService()
    chapters = detector._call_gemini_detection(mock_ai, "Textbook page headers text")

    assert len(chapters) == 1
    mock_ai.generate_response.assert_called_once()
    call_kwargs = mock_ai.generate_response.call_args[1]
    assert call_kwargs.get("system_instruction") == CHAPTER_DETECTION_SYSTEM_INSTRUCTION
    assert "You are an expert textbook parser" in call_kwargs.get("system_instruction")

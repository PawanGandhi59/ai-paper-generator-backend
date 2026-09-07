import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_end_to_end_paper_generation_and_retrieval_with_visuals():
    """
    Test full end-to-end HTTP pipeline:
    HTTP POST /api/v1/papers/generate
      -> PaperGeneratorService
      -> Gemini visual spec generation (mocked)
      -> SVGGeneratorService (deterministic SVG generation)
      -> GeneratedPaperQuestion persistence (PostgreSQL)
      -> HTTP 201 Response with visual fields and SVG
      -> HTTP GET /api/v1/papers/{paper_id} fresh retrieval from DB
      -> Verification that visual spec, SVG, and non-visual questions survive completely.
    """
    uid = uuid4().hex[:8]
    user_res = client.post(
        "/api/v1/auth/register",
        json={"name": f"Visual Author {uid}", "email": f"visual_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user_res['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Physics_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Physics Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Electricity & Magnetism", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapters": [{"chapter_id": ch1["id"]}],
        "generation_mode": "CUSTOM",
        "total_marks": 15,
        "difficulty": "MIXED",
        "topic_focus": "Circuits and coordinate geometry",
        "include_answers": True,
        "title": f"Midterm Exam {uid}",
        "question_configs": [
            {"question_type": "NUMERICAL", "question_count": 1, "marks_per_question": 5, "section_name": "Section A"},
            {"question_type": "SHORT_ANSWER", "question_count": 1, "marks_per_question": 5, "section_name": "Section B"},
            {"question_type": "LONG_ANSWER", "question_count": 1, "marks_per_question": 5, "section_name": "Section C", "alternatives_per_question": 2},
        ],
    }

    mock_gemini_response = {
        "sections": [
            {
                "section_name": "Section A",
                "questions": [
                    {
                        "question_text": "A 12 V battery is connected to a 6 ohm resistor. Find the current.",
                        "question_type": "NUMERICAL",
                        "marks": 5,
                        "difficulty": "MEDIUM",
                        "correct_answer": "2 A",
                        "solution_explanation": "I = V / R = 12 / 6 = 2 A.",
                        "is_numerical": True,
                        "visual": {
                            "required": True,
                            "type": "circuit",
                            "title": "Simple DC Circuit",
                            "caption": "12 V battery connected to a 6 ohm resistor",
                            "spec": {
                                "components": [
                                    {"id": "V1", "type": "battery", "label": "12 V"},
                                    {"id": "R1", "type": "resistor", "label": "6 ohm"},
                                ],
                                "connections": [
                                    {"from": "V1", "to": "R1", "show_current": True, "label": "I"},
                                    {"from": "R1", "to": "V1"},
                                ],
                            },
                        },
                    }
                ],
            },
            {
                "section_name": "Section B",
                "questions": [
                    {
                        "question_text": "State Ohm's Law and its mathematical formula.",
                        "question_type": "SHORT_ANSWER",
                        "marks": 5,
                        "difficulty": "EASY",
                        "correct_answer": "V = IR",
                        "solution_explanation": "Current is directly proportional to voltage.",
                        "visual": None,
                    }
                ],
            },
            {
                "section_name": "Section C",
                "questions": [
                    {
                        "question_text": "Option A: In triangle ABC, AB=5, AC=4 and angle A=60 deg. Find BC.",
                        "question_type": "LONG_ANSWER",
                        "marks": 5,
                        "difficulty": "HARD",
                        "correct_answer": "BC = sqrt(21)",
                        "solution_explanation": "Cosine rule.",
                        "choice_group": "Q3",
                        "alternative_label": "a",
                        "visual": {
                            "required": True,
                            "type": "geometry",
                            "title": "Triangle ABC",
                            "caption": "Triangle with side lengths and angle",
                            "spec": {
                                "points": [
                                    {"id": "A", "label": "A"},
                                    {"id": "B", "label": "B"},
                                    {"id": "C", "label": "C"},
                                ],
                                "segments": [
                                    {"from": "A", "to": "B", "label": "5"},
                                    {"from": "A", "to": "C", "label": "4"},
                                ],
                                "polygons": [{"points": ["A", "B", "C"]}],
                                "angles": [{"vertex": "A", "p1": "B", "p2": "C", "label": "60°"}],
                            },
                        },
                    },
                    {
                        "question_text": "Option B: Plot the parabola y = x^2 - 4 and find its roots.",
                        "question_type": "LONG_ANSWER",
                        "marks": 5,
                        "difficulty": "HARD",
                        "correct_answer": "x = 2, -2",
                        "solution_explanation": "Roots at y=0.",
                        "choice_group": "Q3",
                        "alternative_label": "b",
                        "visual": {
                            "required": True,
                            "type": "graph",
                            "title": "Parabola Graph",
                            "caption": "Plot of y = x^2 - 4",
                            "spec": {
                                "x_range": [-3, 3],
                                "y_range": [-5, 5],
                                "grid": True,
                                "functions": [{"expression": "x**2 - 4", "label": "y = x^2 - 4"}],
                            },
                        },
                    },
                ],
            },
        ]
    }

    with patch("app.services.ai.gemini_service.GeminiService.generate_response", return_value=json.dumps(mock_gemini_response)), \
         patch("app.services.ai.gemini_service.GeminiService.count_tokens", return_value=150):
        # 1. Trigger HTTP Paper Generation
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)
        assert res.status_code == 201, res.text
        paper_data = res.json()

        # 2. Verify Generation HTTP Response payload
        paper_id = paper_data["id"]
        questions = paper_data["questions"]
        assert len(questions) == 4

        # Q1: Circuit Visual (Section A)
        q1 = next(q for q in questions if q["section_name"] == "Section A")
        assert q1["visual_required"] is True
        assert q1["visual_type"] == "circuit"
        assert q1["visual_title"] == "Simple DC Circuit"
        assert q1["visual_caption"] == "12 V battery connected to a 6 ohm resistor"
        assert isinstance(q1["visual_spec"], dict)
        assert q1["visual_svg"] is not None
        assert "<svg" in q1["visual_svg"] and "</svg>" in q1["visual_svg"]
        assert "12 V" in q1["visual_svg"]
        assert "6 ohm" in q1["visual_svg"]

        # Q2: Non-visual Question (Section B)
        q2 = next(q for q in questions if q["section_name"] == "Section B")
        assert q2["visual_required"] is False
        assert q2["visual_type"] is None
        assert q2["visual_title"] is None
        assert q2["visual_caption"] is None
        assert q2["visual_spec"] is None
        assert q2["visual_svg"] is None

        # Q3(a): Geometry Visual Alternative
        q3a = next(q for q in questions if q["choice_group"] == "Q3" and q["alternative_label"] == "a")
        assert q3a["visual_required"] is True
        assert q3a["visual_type"] == "geometry"
        assert q3a["visual_title"] == "Triangle ABC"
        assert q3a["visual_svg"] is not None
        assert "<svg" in q3a["visual_svg"] and "</svg>" in q3a["visual_svg"]
        assert "<polygon" in q3a["visual_svg"]

        # Q3(b): Graph Visual Alternative
        q3b = next(q for q in questions if q["choice_group"] == "Q3" and q["alternative_label"] == "b")
        assert q3b["visual_required"] is True
        assert q3b["visual_type"] == "graph"
        assert q3b["visual_title"] == "Parabola Graph"
        assert q3b["visual_svg"] is not None
        assert "<svg" in q3b["visual_svg"] and "</svg>" in q3b["visual_svg"]

        # 3. Verify Fresh Database-Backed HTTP GET /api/v1/papers/{paper_id}
        get_res = client.get(f"/api/v1/papers/{paper_id}", headers=headers)
        assert get_res.status_code == 200, get_res.text
        retrieved_paper = get_res.json()

        retrieved_questions = retrieved_paper["questions"]
        assert len(retrieved_questions) == 4

        # Verify Q1 circuit survived DB round-trip
        rq1 = next(q for q in retrieved_questions if q["section_name"] == "Section A")
        assert rq1["visual_required"] is True
        assert rq1["visual_type"] == "circuit"
        assert rq1["visual_title"] == "Simple DC Circuit"
        assert rq1["visual_svg"] == q1["visual_svg"]
        assert "<svg" in rq1["visual_svg"] and "</svg>" in rq1["visual_svg"]

        # Verify Q2 non-visual survived DB round-trip
        rq2 = next(q for q in retrieved_questions if q["section_name"] == "Section B")
        assert rq2["visual_required"] is False
        assert rq2["visual_type"] is None
        assert rq2["visual_svg"] is None

        # Verify Q3(a) and Q3(b) independent internal choice visuals survived DB round-trip
        rq3a = next(q for q in retrieved_questions if q["choice_group"] == "Q3" and q["alternative_label"] == "a")
        rq3b = next(q for q in retrieved_questions if q["choice_group"] == "Q3" and q["alternative_label"] == "b")
        assert rq3a["visual_type"] == "geometry"
        assert rq3a["visual_svg"] == q3a["visual_svg"]
        assert rq3b["visual_type"] == "graph"
        assert rq3b["visual_svg"] == q3b["visual_svg"]


def test_end_to_end_required_visual_failure_handling():
    """
    Test that when a question has required: True but visual SVG generation fails,
    the question is still generated, visual_required remains True, visual_svg is None,
    and the API response / DB retrieval accurately reflect the failure state.
    """
    uid = uuid4().hex[:8]
    user_res = client.post(
        "/api/v1/auth/register",
        json={"name": f"Author {uid}", "email": f"author_{uid}@example.com", "password": "password123"},
    ).json()
    headers = {"Authorization": f"Bearer {user_res['access_token']}"}

    ws = client.post("/api/v1/workspaces", json={"name": f"WS_{uid}"}, headers=headers).json()
    subj = client.post(f"/api/v1/workspaces/{ws['id']}/subjects", json={"name": f"Math_{uid}"}, headers=headers).json()
    book = client.post(f"/api/v1/subjects/{subj['id']}/books", json={"name": f"Math Book_{uid}"}, headers=headers).json()
    ch1 = client.post(f"/api/v1/books/{book['id']}/chapters", json={"name": "Geometry", "chapter_number": 1}, headers=headers).json()

    gen_payload = {
        "book_id": book["id"],
        "selected_chapters": [{"chapter_id": ch1["id"]}],
        "generation_mode": "CUSTOM",
        "total_marks": 5,
        "difficulty": "EASY",
        "include_answers": True,
        "title": f"Failing Visual Exam {uid}",
        "question_configs": [
            {"question_type": "SHORT_ANSWER", "question_count": 1, "marks_per_question": 5, "section_name": "Section A"},
        ],
    }

    mock_gemini_response = {
        "sections": [
            {
                "section_name": "Section A",
                "questions": [
                    {
                        "question_text": "Question with unsupported visual type.",
                        "question_type": "SHORT_ANSWER",
                        "marks": 5,
                        "difficulty": "EASY",
                        "correct_answer": "42",
                        "solution_explanation": "Explanation",
                        "visual": {
                            "required": True,
                            "type": "unsupported_visual_type",
                            "spec": {},
                        },
                    }
                ],
            }
        ]
    }

    with patch("app.services.ai.gemini_service.GeminiService.generate_response", return_value=json.dumps(mock_gemini_response)), \
         patch("app.services.ai.gemini_service.GeminiService.count_tokens", return_value=100):
        # 1. Trigger HTTP Paper Generation
        res = client.post("/api/v1/papers/generate", json=gen_payload, headers=headers)
        assert res.status_code == 201, res.text
        paper_data = res.json()

        paper_id = paper_data["id"]
        q = paper_data["questions"][0]

        # Verify that visual_required is True, but visual_svg is None (not marked as successful)
        assert q["visual_required"] is True
        assert q["visual_svg"] is None

        # 2. Verify Fresh Database Retrieval
        get_res = client.get(f"/api/v1/papers/{paper_id}", headers=headers)
        assert get_res.status_code == 200, get_res.text
        retrieved_q = get_res.json()["questions"][0]

        assert retrieved_q["visual_required"] is True
        assert retrieved_q["visual_svg"] is None

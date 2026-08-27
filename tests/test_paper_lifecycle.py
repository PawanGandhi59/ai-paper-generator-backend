from datetime import datetime, timezone
import os
import shutil
import uuid
from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch


import pytest
from fastapi import HTTPException, UploadFile, status

from app.schemas.paper import PaperGenerateRequest, GenerationMode, DifficultyLevel, QuestionType
from app.services.paper.blueprint_service import PaperBlueprint, SectionBlueprint
from app.services.paper.paper_generator_service import PaperGeneratorService
from app.models.generated_paper import GeneratedPaper, GeneratedPaperQuestion
from app.models.document import Document, DocumentPage, DocumentChunk




def test_ai_generation_returns_structured_json_without_pdf():
    """
    1 & 2. Verify AI paper generation creates a paper record with NOT_SAVED status,
    returns structured JSON, and does NOT generate or require a PDF.
    """
    mock_db = MagicMock()
    pg_svc = PaperGeneratorService(db=mock_db)

    book_id = uuid4()
    ch_id = uuid4()
    subject_id = uuid4()
    workspace_id = uuid4()
    user_id = uuid4()

    mock_book = MagicMock()
    mock_book.id = book_id
    mock_book.subject_id = subject_id

    mock_subject = MagicMock()
    mock_subject.id = subject_id
    mock_subject.workspace_id = workspace_id

    mock_ch = MagicMock()
    mock_ch.id = ch_id

    pg_svc.workspace_service.get_book = MagicMock(return_value=mock_book)
    pg_svc.workspace_service.get_subject = MagicMock(return_value=mock_subject)
    pg_svc.workspace_service.list_chapters = MagicMock(return_value=[mock_ch])

    created_paper = GeneratedPaper(
        id=uuid4(),
        user_id=user_id,
        workspace_id=workspace_id,
        subject_id=subject_id,
        book_id=book_id,
        title="Custom Test Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=5,
        difficulty="MEDIUM",
        selected_chapter_ids=[str(ch_id)],
        include_answers=True,
        pdf_path=None,
        document_id=None,
        processing_status="NOT_SAVED",
        deleted_at=None,
        questions=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )

    pg_svc.paper_repo.create_paper = MagicMock(return_value=created_paper)
    pg_svc.paper_repo.get_paper = MagicMock(return_value=created_paper)
    pg_svc.paper_repo.update_status = MagicMock()

    with patch.object(pg_svc, "_retrieve_chapter_context", return_value="Context"), \
         patch.object(pg_svc, "_generate_complete_paper", return_value=[]), \
         patch.object(pg_svc, "_generate_section_questions", return_value=[]), \
         patch.object(pg_svc.paper_repo, "save_questions"):

        req = PaperGenerateRequest(
            book_id=book_id,
            selected_chapter_ids=[ch_id],
            generation_mode=GenerationMode.CUSTOM,
            total_marks=5,
            question_configs=[
                {
                    "question_type": "MCQ",
                    "question_count": 5,
                    "marks_per_question": 1,
                    "section_name": "Section A",
                }
            ],
        )

        res = pg_svc.generate_paper(current_user_id=user_id, request_data=req)

        assert res.status == "COMPLETED"
        assert res.has_saved_pdf is False
        assert res.pdf_url is None
        assert res.processing_status == "NOT_SAVED"
        assert res.reference_eligible is False


def test_save_pdf_validation_magic_bytes_and_second_save_conflict(tmp_path):
    """
    3, 4, 5 & 17. Verify PDF validation, file writing, magic bytes check,
    and second save conflict rejection (HTTP 409).
    """
    mock_db = MagicMock()
    pg_svc = PaperGeneratorService(db=mock_db)

    user_id = uuid4()
    paper_id = uuid4()
    subject_id = uuid4()
    workspace_id = uuid4()

    paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        workspace_id=workspace_id,
        subject_id=subject_id,
        book_id=uuid4(),
        pdf_path=None,
        document_id=None,
        processing_status="NOT_SAVED",
        deleted_at=None,
        title="Test Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=10,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        questions=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )

    pg_svc.paper_repo.get_paper = MagicMock(return_value=paper)
    pg_svc.workspace_service.get_subject = MagicMock()

    # 1. Invalid Extension Test (.txt)
    mock_file_txt = MagicMock()
    mock_file_txt.filename = "test.txt"
    with pytest.raises(HTTPException) as exc_info:
        pg_svc.save_pdf(paper_id=paper_id, current_user_id=user_id, file=mock_file_txt)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    # 2. Invalid Magic Bytes Test (fake PDF header)
    mock_file_bad_bytes = MagicMock()
    mock_file_bad_bytes.filename = "test.pdf"
    mock_file_bad_bytes.file.read.side_effect = [b"NOT_A_PDF_HEADER_BYTES", b""]
    with pytest.raises(HTTPException) as exc_info_magic:
        pg_svc.save_pdf(paper_id=paper_id, current_user_id=user_id, file=mock_file_bad_bytes)
    assert exc_info_magic.value.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Successful Valid PDF Save Test
    mock_file_valid = MagicMock()
    mock_file_valid.filename = "final_edited_paper.pdf"
    valid_pdf_content = b"%PDF-1.7 Valid test pdf content stream"
    mock_file_valid.file.read.side_effect = [valid_pdf_content, b""]

    doc_mock = MagicMock()
    doc_mock.id = uuid4()
    pg_svc.doc_repo.create_document = MagicMock(return_value=doc_mock)

    pdf_dest_path = str(tmp_path / "generated_papers" / str(paper_id) / "final.pdf")

    updated_paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        workspace_id=workspace_id,
        subject_id=subject_id,
        book_id=paper.book_id,
        pdf_path=pdf_dest_path,
        document_id=doc_mock.id,
        processing_status="PROCESSING",
        deleted_at=None,
        title="Test Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=10,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        questions=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )


    pg_svc.paper_repo.update_saved_pdf = MagicMock(return_value=updated_paper)
    pg_svc.paper_repo.get_paper = MagicMock(return_value=paper)

    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", str(tmp_path)), \
         patch("app.worker.process_document.delay"):
        res = pg_svc.save_pdf(paper_id=paper_id, current_user_id=user_id, file=mock_file_valid)
        assert res.has_saved_pdf is True
        assert res.processing_status == "PROCESSING"

    # 4. Second Save Conflict Test (HTTP 409)
    pg_svc.paper_repo.get_paper = MagicMock(return_value=updated_paper)
    with pytest.raises(HTTPException) as exc_info_conflict:
        pg_svc.save_pdf(paper_id=paper_id, current_user_id=user_id, file=mock_file_valid)
    assert exc_info_conflict.value.status_code == status.HTTP_409_CONFLICT


def test_reference_eligibility_only_when_ready(tmp_path):
    """
    8, 10, 11 & 13. Verify reference_eligible is true ONLY when pdf_path exists,
    processing_status is READY, and deleted_at is None.
    """
    mock_db = MagicMock()
    pg_svc = PaperGeneratorService(db=mock_db)

    # Create test PDF file on disk
    pdf_file = tmp_path / "final.pdf"
    pdf_file.write_bytes(b"%PDF-1.7 test content")

    paper_ready = GeneratedPaper(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        subject_id=uuid4(),
        book_id=uuid4(),
        pdf_path=str(pdf_file),

        document_id=uuid4(),
        processing_status="READY",
        deleted_at=None,
        title="Ready Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=10,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        questions=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )

    doc_mock = MagicMock()
    doc_mock.processing_status = "READY"
    pg_svc.doc_repo.get_document_by_id = MagicMock(return_value=doc_mock)

    res = pg_svc._build_paper_response(paper_ready)
    assert res.has_saved_pdf is True
    assert res.processing_status == "READY"
    assert res.reference_eligible is True

    # Processing state -> NOT eligible
    doc_mock.processing_status = "PROCESSING"
    res_proc = pg_svc._build_paper_response(paper_ready)
    assert res_proc.reference_eligible is False


def test_delete_paper_soft_deletes_db_and_hard_deletes_disk_and_document(tmp_path):
    """
    22, 23, 24, 25 & 26. Verify DELETE soft-deletes GeneratedPaper record in DB,
    and hard-deletes physical PDF file on disk and associated Document, DocumentPage, and DocumentChunk records.
    """
    mock_db = MagicMock()
    pg_svc = PaperGeneratorService(db=mock_db)

    paper_id = uuid4()
    doc_id = uuid4()
    user_id = uuid4()

    # Create dummy storage directories
    paper_dir = tmp_path / "generated_papers" / str(paper_id)
    paper_dir.mkdir(parents=True)
    pdf_file = paper_dir / "final.pdf"
    pdf_file.write_bytes(b"%PDF-1.7 dummy pdf")

    doc_dir = tmp_path / "documents" / str(doc_id)
    doc_dir.mkdir(parents=True)

    paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        subject_id=uuid4(),
        book_id=uuid4(),
        pdf_path=str(pdf_file),
        document_id=doc_id,
        processing_status="READY",
        deleted_at=None,
        title="ToDelete Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=10,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        questions=[],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )

    pg_svc.paper_repo.get_paper = MagicMock(return_value=paper)
    pg_svc.workspace_service.get_subject = MagicMock()
    pg_svc.paper_repo.soft_delete_paper = MagicMock()
    pg_svc.doc_repo.delete_document = MagicMock()

    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", str(tmp_path)):
        result = pg_svc.delete_paper(paper_id=paper_id, current_user_id=user_id)

        assert result["status"] == "deleted"
        pg_svc.paper_repo.soft_delete_paper.assert_called_once_with(paper_id)
        pg_svc.doc_repo.delete_document.assert_called_once_with(doc_id)
        assert not pdf_file.exists()
        assert not doc_dir.exists()


def test_saved_pdf_blueprint_override_original_json():
    """Test 1: Saved PDF blueprint overrides original AI questions/JSON when used as a reference paper."""
    db_mock = MagicMock()
    pg_svc = PaperGeneratorService(db_mock)

    user_id = uuid4()
    paper_id = uuid4()
    doc_id = uuid4()

    orig_q = GeneratedPaperQuestion(
        id=uuid4(),
        paper_id=paper_id,
        question_order=1,
        section_name="Sec A",
        question_type="MCQ",
        question_text="Original MCQ Question 1?",
        marks=1,
        difficulty="EASY",
        source_type="AI_GENERATED",
    )

    ws_id = uuid4()
    paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        workspace_id=ws_id,
        subject_id=uuid4(),
        book_id=uuid4(),
        pdf_path="/storage/generated_papers/dummy/final.pdf",
        document_id=doc_id,
        processing_status="READY",
        deleted_at=None,
        title="Saved Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=5,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        blueprint_json=None,  # Reset after save-pdf
        questions=[orig_q],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )

    pdf_page_text = "Section A: 3 Short Answer Questions of 5 marks each. Total: 15 marks."

    analyzed_blueprint = PaperBlueprint(
        total_marks=15,
        sections=[
            SectionBlueprint(
                name="Sec A",
                question_type=QuestionType.SHORT_ANSWER,
                question_count=3,
                marks_per_question=5,
                total_section_marks=15,
            )
        ],
        sample_questions=[],
    )

    new_paper_id = uuid4()
    now_dt = datetime.now(timezone.utc)
    new_paper = GeneratedPaper(
        id=new_paper_id,
        user_id=user_id,
        workspace_id=ws_id,
        subject_id=paper.subject_id,
        book_id=paper.book_id,
        reference_paper_id=paper_id,
        pdf_path=None,
        document_id=None,
        processing_status="NOT_SAVED",
        deleted_at=None,
        title="New Reference Paper",
        generation_mode="REFERENCE",
        status="COMPLETED",
        total_marks=15,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        error_message=None,
        blueprint_json=analyzed_blueprint.model_dump(),
        questions=[],
        created_at=now_dt,
        updated_at=now_dt,
    )



    pg_svc.paper_repo.get_paper = MagicMock(side_effect=lambda pid: paper if str(pid) == str(paper_id) else new_paper)
    pg_svc.ref_paper_repo.get_reference_paper = MagicMock(return_value=None)
    pg_svc.paper_repo.create_paper = MagicMock(return_value=new_paper)

    pg_svc.paper_repo.update_status = MagicMock(side_effect=lambda pid, status, error_message=None, blueprint_json=None: setattr(new_paper, 'blueprint_json', blueprint_json if blueprint_json is not None else new_paper.blueprint_json) or new_paper)
    pg_svc.paper_repo.save_questions = MagicMock()
    pg_svc.paper_repo.save_blueprint_json = MagicMock()
    pg_svc.workspace_service.get_subject = MagicMock()



    pg_svc.doc_repo.get_document_pages = MagicMock(return_value=[MagicMock(text_content=pdf_page_text)])


    pg_svc.blueprint_service.analyze_reference_paper = MagicMock(return_value=analyzed_blueprint)
    pg_svc._retrieve_chapter_context = MagicMock(return_value="Context")
    pg_svc._generate_complete_paper = MagicMock(return_value=[])
    pg_svc._generate_section_questions = MagicMock(return_value=[])

    ch_id = uuid4()
    book_mock = MagicMock(id=paper.book_id, subject_id=paper.subject_id)
    pg_svc.workspace_service.get_book = MagicMock(return_value=book_mock)
    pg_svc.workspace_service.get_subject = MagicMock(return_value=MagicMock(workspace_id=uuid4()))
    pg_svc.workspace_service.list_chapters = MagicMock(return_value=[MagicMock(id=ch_id)])

    req = PaperGenerateRequest(
        subject_id=paper.subject_id,
        book_id=paper.book_id,
        selected_chapter_ids=[ch_id],
        generation_mode=GenerationMode.REFERENCE,
        reference_paper_id=paper_id,
        title="New Reference Paper",
        total_marks=15,
        difficulty=DifficultyLevel.MEDIUM,
    )



    with patch("os.path.exists", return_value=True):
        pg_svc.generate_paper(current_user_id=user_id, request_data=req)

    # Assert blueprint analysis ran on PDF text, NOT original AI JSON
    pg_svc.blueprint_service.analyze_reference_paper.assert_called_once_with(
        paper_pages_text=[pdf_page_text],
        requested_total_marks=None,
    )
    pg_svc.paper_repo.save_blueprint_json.assert_called_once()
    # Original AI question remains preserved
    assert paper.questions[0].question_text == "Original MCQ Question 1?"


def test_saved_pdf_blueprint_caching():
    """Test 2: Blueprint caching reuses cached blueprint_json without re-calling Gemini analysis."""
    db_mock = MagicMock()
    pg_svc = PaperGeneratorService(db_mock)

    user_id = uuid4()
    paper_id = uuid4()
    doc_id = uuid4()
    now_dt = datetime.now(timezone.utc)


    cached_blueprint_dict = {
        "total_marks": 20,
        "sections": [
            {
                "name": "Sec A",
                "question_type": "MCQ",

                "question_count": 10,
                "marks_per_question": 2,
                "total_section_marks": 20,
                "has_internal_choice": False,
                "alternatives_per_question": 1,
            }
        ],
        "sample_questions": [],
    }

    ws_id = uuid4()
    paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        workspace_id=ws_id,
        subject_id=uuid4(),
        book_id=uuid4(),
        pdf_path="/storage/generated_papers/dummy/final.pdf",
        document_id=doc_id,
        processing_status="READY",
        deleted_at=None,
        title="Saved Paper Cached",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=20,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        blueprint_json=cached_blueprint_dict,  # Already cached!
        questions=[],
        created_at=now_dt,
        updated_at=now_dt,
    )

    new_paper_id = uuid4()
    new_paper = GeneratedPaper(
        id=new_paper_id,
        user_id=user_id,
        workspace_id=ws_id,
        subject_id=paper.subject_id,
        book_id=paper.book_id,
        reference_paper_id=paper_id,

        pdf_path=None,
        document_id=None,
        processing_status="NOT_SAVED",
        deleted_at=None,
        title="New Ref Paper",
        generation_mode="REFERENCE",
        status="COMPLETED",
        total_marks=20,
        difficulty="MEDIUM",
        selected_chapter_ids=[],
        include_answers=True,
        error_message=None,
        blueprint_json=cached_blueprint_dict,
        questions=[],
        created_at=now_dt,
        updated_at=now_dt,
    )



    pg_svc.paper_repo.get_paper = MagicMock(side_effect=lambda pid: paper if str(pid) == str(paper_id) else new_paper)
    pg_svc.ref_paper_repo.get_reference_paper = MagicMock(return_value=None)


    pg_svc.paper_repo.create_paper = MagicMock(return_value=new_paper)
    pg_svc.paper_repo.update_status = MagicMock(side_effect=lambda pid, status, error_message=None, blueprint_json=None: setattr(new_paper, 'blueprint_json', blueprint_json if blueprint_json is not None else new_paper.blueprint_json) or new_paper)

    pg_svc.paper_repo.save_questions = MagicMock()
    pg_svc.workspace_service.get_subject = MagicMock()



    pg_svc.blueprint_service.analyze_reference_paper = MagicMock()
    pg_svc._retrieve_chapter_context = MagicMock(return_value="Context")
    pg_svc._generate_complete_paper = MagicMock(return_value=[])
    pg_svc._generate_section_questions = MagicMock(return_value=[])

    ch_id = uuid4()
    book_mock = MagicMock(id=paper.book_id, subject_id=paper.subject_id)
    pg_svc.workspace_service.get_book = MagicMock(return_value=book_mock)
    pg_svc.workspace_service.get_subject = MagicMock(return_value=MagicMock(workspace_id=uuid4()))
    pg_svc.workspace_service.list_chapters = MagicMock(return_value=[MagicMock(id=ch_id)])

    req = PaperGenerateRequest(
        subject_id=paper.subject_id,
        book_id=paper.book_id,
        selected_chapter_ids=[ch_id],
        generation_mode=GenerationMode.REFERENCE,
        reference_paper_id=paper_id,
        title="New Ref Paper",
        total_marks=20,
        difficulty=DifficultyLevel.MEDIUM,
    )



    with patch("os.path.exists", return_value=True):
        pg_svc.generate_paper(current_user_id=user_id, request_data=req)

    # Gemini analyze_reference_paper should NOT be called because blueprint_json is cached!
    pg_svc.blueprint_service.analyze_reference_paper.assert_not_called()


def test_original_ai_json_preserved_after_save():
    """Test 4: Original AI questions remain unchanged after PDF save."""
    db_mock = MagicMock()
    pg_svc = PaperGeneratorService(db_mock)

    user_id = uuid4()
    paper_id = uuid4()

    orig_q = GeneratedPaperQuestion(
        id=uuid4(),
        paper_id=paper_id,
        question_order=1,
        section_name="Sec A",
        question_type="SHORT_ANSWER",
        question_text="Original AI Question Text",
        marks=5,
        difficulty="EASY",
        source_type="AI_GENERATED",
    )

    paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        subject_id=uuid4(),
        book_id=uuid4(),
        pdf_path=None,
        document_id=None,
        processing_status="NOT_SAVED",
        deleted_at=None,
        title="Original AI Paper",
        generation_mode="CUSTOM",
        status="COMPLETED",
        total_marks=10,
        difficulty="EASY",
        blueprint_json={"total_marks": 10},
        questions=[orig_q],
        created_at=MagicMock(),
        updated_at=MagicMock(),
    )

    pg_svc.paper_repo.get_paper = MagicMock(return_value=paper)
    pg_svc.workspace_service.get_subject = MagicMock()
    pg_svc.doc_repo.create_document = MagicMock(return_value=MagicMock(id=uuid4()))
    pg_svc.paper_repo.update_saved_pdf = MagicMock(side_effect=lambda paper_id, pdf_path, document_id, processing_status: setattr(paper, 'pdf_path', pdf_path) or setattr(paper, 'blueprint_json', None) or paper)
    pg_svc._build_paper_response = MagicMock()

    dummy_file = MagicMock()
    dummy_file.filename = "final.pdf"
    dummy_file.file.read = MagicMock(side_effect=[b"%PDF-1.7 data", b""])

    with patch("os.makedirs"), patch("builtins.open", MagicMock()), patch("os.path.exists", side_effect=[False, True]), patch("app.worker.process_document.delay"):
        pg_svc.save_pdf(paper_id=paper_id, current_user_id=user_id, file=dummy_file)

    # Original questions remain preserved and unchanged
    assert paper.questions[0].question_text == "Original AI Question Text"
    assert paper.blueprint_json is None



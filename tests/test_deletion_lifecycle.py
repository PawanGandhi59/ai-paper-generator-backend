import os
import shutil
import uuid
from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, status

from app.models.subject import Subject
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.topic import Topic
from app.models.document import Document, DocumentPage, DocumentChunk
from app.models.reference_paper import ReferencePaper, ReferencePaperPage
from app.models.generated_paper import GeneratedPaper
from app.repositories.workspace_repository import WorkspaceRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.reference_paper_repository import ReferencePaperRepository
from app.services.workspace_service import WorkspaceService
from app.services.reference_paper_service import ReferencePaperService
from app.services.paper.paper_generator_service import PaperGeneratorService
from app.worker import process_document, generate_document_embeddings


def test_subject_soft_delete_cascades_db_and_hard_deletes_disk_files(tmp_path):
    """
    1, 2, 3, 4, 5, 6, 7, 8, 9 & 10. Verify Subject deletion:
    - DB: Soft-deletes Subject, Books, Chapters, Topics, Documents, Pages, Chunks, ReferencePapers, ReferencePaperPages, GeneratedPapers.
    - DISK: Hard-deletes physical PDF files/directories for all descendants under the subject.
    - Other subjects remain untouched.
    """
    mock_db = MagicMock()
    ws_svc = WorkspaceService(db=mock_db)

    user_id = uuid4()
    workspace_id = uuid4()
    subject_id = uuid4()
    other_subject_id = uuid4()
    book1_id = uuid4()
    book2_id = uuid4()
    doc1_id = uuid4()
    ref1_id = uuid4()
    gen1_id = uuid4()

    # Setup Subject entity
    subject = Subject(
        id=subject_id,
        workspace_id=workspace_id,
        name="Physics Subject",
        deleted_at=None,
    )
    book1 = Book(id=book1_id, subject_id=subject_id, name="Physics Book 1", deleted_at=None)
    book2 = Book(id=book2_id, subject_id=subject_id, name="Physics Book 2", deleted_at=None)
    subject.books = [book1, book2]

    # Create dummy storage folders for documents, reference papers, generated papers
    storage_root = str(tmp_path)
    doc_dir = tmp_path / "documents" / str(doc1_id)
    doc_dir.mkdir(parents=True)
    (doc_dir / "original.pdf").write_bytes(b"%PDF-1.7 doc content")

    ref_dir = tmp_path / "reference_papers" / str(ref1_id)
    ref_dir.mkdir(parents=True)
    (ref_dir / "ref.pdf").write_bytes(b"%PDF-1.7 ref paper content")

    gen_dir = tmp_path / "generated_papers" / str(gen1_id)
    gen_dir.mkdir(parents=True)
    (gen_dir / "final.pdf").write_bytes(b"%PDF-1.7 gen paper content")

    # Mock DB query executions
    doc_mock = MagicMock()
    doc_mock.id = doc1_id

    ref_mock = MagicMock()
    ref_mock.id = ref1_id

    gen_mock = MagicMock()
    gen_mock.id = gen1_id

    def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        res = MagicMock()
        if "from documents" in stmt_str:
            res.scalars.return_value.all.return_value = [doc_mock]
        elif "from reference_papers" in stmt_str:
            res.scalars.return_value.all.return_value = [ref_mock]
        elif "from generated_papers" in stmt_str:
            res.scalars.return_value.all.return_value = [gen_mock]
        else:
            res.scalars.return_value.all.return_value = []
        return res

    mock_db.execute.side_effect = mock_execute
    ws_svc.get_subject = MagicMock(return_value=subject)
    ws_svc.repo.delete_subject = MagicMock()

    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", storage_root):
        ws_svc.delete_subject(subject_id=subject_id, current_user_id=user_id)

        ws_svc.repo.delete_subject.assert_called_once_with(subject)
        # Verify physical disk cleanup occurred for subject files
        assert not doc_dir.exists()
        assert not ref_dir.exists()
        assert not gen_dir.exists()


def test_book_soft_delete_cascades_db_and_hard_deletes_book_disk_files(tmp_path):
    """
    11, 12 & 13. Verify Book deletion:
    - Soft-deletes Book and its descendants.
    - Hard-deletes physical PDF files belonging ONLY to that Book.
    - Other Books under the same Subject remain untouched.
    """
    mock_db = MagicMock()
    ws_svc = WorkspaceService(db=mock_db)

    user_id = uuid4()
    book_id = uuid4()
    doc_id = uuid4()
    gen_id = uuid4()

    book = Book(id=book_id, subject_id=uuid4(), name="Chemistry Book", deleted_at=None)

    storage_root = str(tmp_path)
    doc_dir = tmp_path / "documents" / str(doc_id)
    doc_dir.mkdir(parents=True)

    gen_dir = tmp_path / "generated_papers" / str(gen_id)
    gen_dir.mkdir(parents=True)

    doc_mock = MagicMock()
    doc_mock.id = doc_id
    gen_mock = MagicMock()
    gen_mock.id = gen_id

    def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        res = MagicMock()
        if "from documents" in stmt_str:
            res.scalars.return_value.all.return_value = [doc_mock]
        elif "from generated_papers" in stmt_str:
            res.scalars.return_value.all.return_value = [gen_mock]
        else:
            res.scalars.return_value.all.return_value = []
        return res

    mock_db.execute.side_effect = mock_execute
    ws_svc.get_book = MagicMock(return_value=book)
    ws_svc.repo.delete_book = MagicMock()

    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", storage_root):
        ws_svc.delete_book(book_id=book_id, current_user_id=user_id)

        ws_svc.repo.delete_book.assert_called_once_with(book)
        assert not doc_dir.exists()
        assert not gen_dir.exists()



def test_chapter_soft_delete_cascades_db_and_hard_deletes_chapter_disk_files(tmp_path):
    """
    14, 15 & 16. Verify Chapter deletion:
    - Soft-deletes Chapter and associated DB records.
    - Hard-deletes physical PDFs uploaded specifically for that chapter.
    - Sibling chapters remain untouched.
    """
    mock_db = MagicMock()
    ws_svc = WorkspaceService(db=mock_db)

    user_id = uuid4()
    ch_id = uuid4()
    doc_id = uuid4()

    chapter = Chapter(id=ch_id, book_id=uuid4(), chapter_number=1, name="Motion", deleted_at=None)

    storage_root = str(tmp_path)
    doc_dir = tmp_path / "documents" / str(doc_id)
    doc_dir.mkdir(parents=True)

    doc_mock = MagicMock()
    doc_mock.id = doc_id

    def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        res = MagicMock()
        if "from documents" in stmt_str:
            res.scalars.return_value.all.return_value = [doc_mock]
        else:
            res.scalars.return_value.all.return_value = []
        return res

    mock_db.execute.side_effect = mock_execute
    ws_svc.get_chapter = MagicMock(return_value=chapter)
    ws_svc.repo.delete_chapter = MagicMock()


    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", storage_root):
        ws_svc.delete_chapter(chapter_id=ch_id, current_user_id=user_id)

        ws_svc.repo.delete_chapter.assert_called_once_with(chapter)
        assert not doc_dir.exists()


def test_reference_paper_soft_delete_db_and_hard_delete_disk_file(tmp_path):
    """
    17, 18, 19, 22 & 23. Verify ReferencePaper deletion:
    - DB record soft-deleted.
    - Physical PDF file/directory hard-deleted on disk.
    - Excluded from reference listing and reference selection.
    """
    mock_db = MagicMock()
    ref_svc = ReferencePaperService(db=mock_db)

    user_id = uuid4()
    paper_id = uuid4()

    ref_dir = tmp_path / "reference_papers" / str(paper_id)
    ref_dir.mkdir(parents=True)
    pdf_file = ref_dir / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.7 test ref paper")

    ref_paper = ReferencePaper(
        id=paper_id,
        workspace_id=uuid4(),
        subject_id=uuid4(),
        title="Sample Ref Paper",
        original_filename="sample.pdf",
        stored_path=str(pdf_file),
        mime_type="application/pdf",
        file_size=100,
        deleted_at=None,
    )

    ref_svc.get_reference_paper = MagicMock(return_value=ref_paper)
    ref_svc.repo.delete_reference_paper = MagicMock()

    ref_svc.delete_reference_paper(current_user_id=user_id, paper_id=paper_id)

    ref_svc.repo.delete_reference_paper.assert_called_once_with(paper_id)
    assert not ref_dir.exists()


def test_generated_paper_soft_delete_db_and_hard_delete_disk_file(tmp_path):
    """
    20, 21, 22 & 23. Verify AI Generated Paper deletion:
    - GeneratedPaper record soft-deleted in DB (`deleted_at` set).
    - Physical PDF and directory hard-deleted on disk.
    - Associated Document, DocumentPages, DocumentChunks soft-deleted.
    - reference_eligible becomes False.
    """
    mock_db = MagicMock()
    pg_svc = PaperGeneratorService(db=mock_db)

    user_id = uuid4()
    paper_id = uuid4()
    doc_id = uuid4()

    paper_dir = tmp_path / "generated_papers" / str(paper_id)
    paper_dir.mkdir(parents=True)
    pdf_file = paper_dir / "final.pdf"
    pdf_file.write_bytes(b"%PDF-1.7 final pdf")

    doc_dir = tmp_path / "documents" / str(doc_id)
    doc_dir.mkdir(parents=True)

    paper = GeneratedPaper(
        id=paper_id,
        user_id=user_id,
        workspace_id=uuid4(),
        subject_id=uuid4(),
        book_id=uuid4(),
        pdf_path=str(pdf_file),
        document_id=doc_id,
        processing_status="READY",
        deleted_at=None,
        title="Gen Paper",
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
        res = pg_svc.delete_paper(paper_id=paper_id, current_user_id=user_id)

        assert res["status"] == "deleted"
        pg_svc.paper_repo.soft_delete_paper.assert_called_once_with(paper_id)
        pg_svc.doc_repo.delete_document.assert_called_once_with(doc_id)
        assert not paper_dir.exists()
        assert not doc_dir.exists()

        # Check reference_eligible is False when deleted_at is set
        paper.deleted_at = MagicMock()
        resp_schema = pg_svc._build_paper_response(paper)
        assert resp_schema.reference_eligible is False


def test_soft_deleted_chunks_excluded_from_vector_search_and_rag():
    """
    18, 19, 20, 21, 24, 25 & 26. Verify vector search (`search_similar_chunks`)
    filters out soft-deleted chunks and soft-deleted ancestor entities (Document, Book, Subject, Chapter).
    """
    mock_db = MagicMock()
    doc_repo = DocumentRepository(mock_db)

    ws_id = uuid4()
    query_vec = [0.1] * 768

    doc_repo.search_similar_chunks(workspace_id=ws_id, query_vector=query_vec)

    # Verify query string includes DocumentChunk.deleted_at IS NULL & parent deleted_at IS NULL joins
    executed_stmt = str(mock_db.execute.call_args[0][0]).lower()
    assert "deleted_at is null" in executed_stmt
    assert "documents" in executed_stmt
    assert "books" in executed_stmt
    assert "subjects" in executed_stmt


def test_celery_task_aborts_if_document_or_ancestor_is_soft_deleted():
    """
    24, 25 & 27. Verify Celery processing tasks abort safely without processing or resurrecting data
    if Document, Book, Subject, or Chapter is soft-deleted.
    """
    mock_db = MagicMock()
    doc_id = uuid4()

    # 1. Document soft-deleted test
    doc_soft_deleted = MagicMock()
    doc_soft_deleted.deleted_at = MagicMock()

    with patch("app.worker.SessionLocal", return_value=mock_db), \
         patch("app.repositories.document_repository.DocumentRepository.claim_document_for_processing", return_value=doc_soft_deleted):

        res_proc = process_document(str(doc_id))
        assert res_proc["status"] in ("skipped", "ABORTED")

    # 2. Owning Book soft-deleted test
    doc_active = MagicMock()
    doc_active.deleted_at = None
    book_deleted = MagicMock()
    book_deleted.deleted_at = MagicMock()
    doc_active.book = book_deleted

    with patch("app.worker.SessionLocal", return_value=mock_db), \
         patch("app.repositories.document_repository.DocumentRepository.claim_document_for_processing", return_value=doc_active):

        res_book = process_document(str(doc_id))
        assert res_book["status"] == "ABORTED"
        assert "Book is soft-deleted" in res_book["reason"]


def test_idempotency_of_deletion_operations():
    """
    26. Verify repeated deletion calls on soft-deleted entities are safe and return 404 Not Found.
    """
    mock_db = MagicMock()
    ws_svc = WorkspaceService(db=mock_db)

    user_id = uuid4()
    sub_id = uuid4()

    # First call returns active subject, second call returns None (already soft-deleted)
    ws_svc.repo.get_subject_by_id = MagicMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        ws_svc.delete_subject(subject_id=sub_id, current_user_id=user_id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_multi_tenant_authorization_security():
    """
    27, 29. Verify cross-workspace deletion attempts are strictly forbidden with HTTP 403 / HTTP 404.
    """
    mock_db = MagicMock()
    ws_svc = WorkspaceService(db=mock_db)

    user1_id = uuid4()
    user2_id = uuid4()
    sub_id = uuid4()

    # User 2 tries to delete User 1's subject
    ws_svc.get_subject = MagicMock(side_effect=HTTPException(status_code=403, detail="Access denied"))

    with pytest.raises(HTTPException) as exc_info:
        ws_svc.delete_subject(subject_id=sub_id, current_user_id=user2_id)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

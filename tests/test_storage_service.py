import io
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from app.services.storage.storage_service import StorageService


@pytest.fixture
def local_storage(tmp_path):
    with patch("app.core.config.settings.LOCAL_STORAGE_PATH", str(tmp_path)):
        with patch("app.core.config.settings.AWS_S3_BUCKET", ""):
            with patch("app.core.config.settings.STORAGE_BACKEND", "local"):
                svc = StorageService()
                svc.local_root = str(tmp_path)
                yield svc


def test_normalize_key(local_storage):
    svc = local_storage
    assert svc.normalize_key("documents/123/original.pdf") == "documents/123/original.pdf"
    assert svc.normalize_key("/documents/123/original.pdf") == "documents/123/original.pdf"
    assert svc.normalize_key("storage/documents/123/original.pdf") == "documents/123/original.pdf"
    assert svc.normalize_key("/storage/documents/123/original.pdf") == "documents/123/original.pdf"
    assert svc.normalize_key(r"storage\documents\123\original.pdf") == "documents/123/original.pdf"


def test_local_upload_and_get_stream(local_storage, tmp_path):
    svc = local_storage
    test_content = b"%PDF-1.4 test content for storage"
    key = svc.upload_bytes(test_content, "generated_papers/test_paper/final.pdf", "application/pdf")
    assert key == "generated_papers/test_paper/final.pdf"
    assert svc.exists(key)

    stream, length, mime = svc.get_stream(key)
    read_data = stream.read()
    stream.close()
    assert read_data == test_content
    assert length == len(test_content)
    assert mime == "application/pdf"


def test_local_download_and_delete(local_storage, tmp_path):
    svc = local_storage
    test_content = b"sample downloaded content"
    key = svc.upload_bytes(test_content, "documents/test_doc/original.txt", "text/plain")

    dest_file = str(tmp_path / "downloaded.txt")
    svc.download_file(key, dest_file)
    with open(dest_file, "rb") as f:
        assert f.read() == test_content

    # Delete prefix
    svc.delete_prefix("documents/test_doc")
    assert not svc.exists(key)


def test_s3_mocked_operations():
    mock_s3 = MagicMock()
    with patch("app.core.config.settings.AWS_S3_BUCKET", "test-bucket"):
        with patch("app.core.config.settings.STORAGE_BACKEND", "s3"):
            with patch("boto3.client", return_value=mock_s3):
                svc = StorageService()
                svc._s3_client = mock_s3
                assert svc.is_s3_enabled

                # Test upload_bytes
                svc.upload_bytes(b"data", "documents/doc1/original.pdf", "application/pdf")
                mock_s3.put_object.assert_called_with(
                    Bucket="test-bucket",
                    Key="documents/doc1/original.pdf",
                    Body=b"data",
                    ContentType="application/pdf",
                )

                # Test get_stream
                mock_body = MagicMock()
                mock_body.read.return_value = b"data"
                mock_s3.get_object.return_value = {
                    "Body": mock_body,
                    "ContentLength": 4,
                    "ContentType": "application/pdf",
                }
                stream, length, mime = svc.get_stream("documents/doc1/original.pdf")
                assert length == 4
                assert mime == "application/pdf"
                mock_s3.get_object.assert_called_with(
                    Bucket="test-bucket",
                    Key="documents/doc1/original.pdf",
                )

                # Test delete_file
                svc.delete_file("documents/doc1/original.pdf")
                mock_s3.delete_object.assert_called_with(
                    Bucket="test-bucket",
                    Key="documents/doc1/original.pdf",
                )

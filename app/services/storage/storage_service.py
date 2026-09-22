import io
import logging
import mimetypes
import os
import shutil
from typing import BinaryIO, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Unified Storage Service supporting both Local Disk storage and AWS S3 storage.
    Automatically detects S3 when AWS_S3_BUCKET is configured.
    Supports both AWS IAM Roles (EC2) and explicit Access Keys.
    """

    def __init__(self):
        self.bucket_name = (settings.AWS_S3_BUCKET or "").strip()
        self.region = (settings.AWS_REGION or "ap-south-1").strip()
        self.backend = (settings.STORAGE_BACKEND or "local").lower()
        self.local_root = os.path.abspath(settings.LOCAL_STORAGE_PATH)
        os.makedirs(self.local_root, exist_ok=True)

        self._s3_client = None
        if self.is_s3_enabled:
            self._init_s3_client()

    @property
    def is_s3_enabled(self) -> bool:
        return bool(self.bucket_name) and (self.backend == "s3" or bool(self.bucket_name))

    def _init_s3_client(self):
        try:
            import boto3

            client_kwargs = {"region_name": self.region}
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

            self._s3_client = boto3.client("s3", **client_kwargs)
            logger.info(f"Initialized AWS S3 client for bucket '{self.bucket_name}' in region '{self.region}'.")
        except Exception as exc:
            logger.error(f"Failed to initialize AWS S3 client: {exc}. Falling back to local storage.")
            self._s3_client = None

    def normalize_key(self, remote_path: str) -> str:
        """
        Normalizes a storage key/path to forward slashes without leading slashes
        or redundant storage/ prefixes.
        Example: '/app/storage/documents/123/original.pdf' -> 'documents/123/original.pdf'
        """
        if not remote_path:
            return ""

        norm = remote_path.replace("\\", "/").strip()
        if norm.startswith(self.local_root.replace("\\", "/")):
            norm = norm[len(self.local_root.replace("\\", "/")):]

        while norm.startswith("/"):
            norm = norm[1:]

        if norm.startswith("storage/"):
            norm = norm[8:]

        return norm

    @staticmethod
    def resolve_content_type(path: str, fallback: Optional[str] = None) -> str:
        low = (path or "").lower()
        if low.endswith(".pdf"):
            return "application/pdf"
        if low.endswith(".svg"):
            return "image/svg+xml"
        if low.endswith(".png"):
            return "image/png"
        if low.endswith(".jpg") or low.endswith(".jpeg"):
            return "image/jpeg"
        if low.endswith(".pptx"):
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        if fallback and fallback != "application/octet-stream":
            return fallback
        guessed = mimetypes.guess_type(path)[0]
        return guessed or fallback or "application/octet-stream"

    def get_local_path(self, key: str) -> str:
        norm_key = self.normalize_key(key)
        return os.path.join(self.local_root, norm_key.replace("/", os.sep))

    def upload_file(self, local_path: str, remote_path: str, content_type: Optional[str] = None) -> str:
        norm_key = self.normalize_key(remote_path)
        content_type = self.resolve_content_type(norm_key, content_type or mimetypes.guess_type(local_path)[0])

        if self.is_s3_enabled and self._s3_client:
            extra_args = {"ContentType": content_type}
            self._s3_client.upload_file(local_path, self.bucket_name, norm_key, ExtraArgs=extra_args)
            logger.info(f"Uploaded file to S3: s3://{self.bucket_name}/{norm_key} as {content_type}")
            return norm_key
        else:
            dest_local = self.get_local_path(norm_key)
            os.makedirs(os.path.dirname(dest_local), exist_ok=True)
            if os.path.abspath(local_path) != os.path.abspath(dest_local):
                shutil.copy2(local_path, dest_local)
            logger.info(f"Saved file to local storage: {dest_local}")
            return norm_key

    def upload_bytes(self, data: bytes, remote_path: str, content_type: Optional[str] = None) -> str:
        norm_key = self.normalize_key(remote_path)
        content_type = self.resolve_content_type(norm_key, content_type)

        if self.is_s3_enabled and self._s3_client:
            self._s3_client.put_object(
                Bucket=self.bucket_name,
                Key=norm_key,
                Body=data,
                ContentType=content_type,
            )
            logger.info(f"Uploaded bytes to S3: s3://{self.bucket_name}/{norm_key} ({len(data)} bytes) as {content_type}")
            return norm_key
        else:
            dest_local = self.get_local_path(norm_key)
            os.makedirs(os.path.dirname(dest_local), exist_ok=True)
            with open(dest_local, "wb") as f:
                f.write(data)
            logger.info(f"Saved bytes to local storage: {dest_local} ({len(data)} bytes)")
            return norm_key

    def upload_fileobj(self, fileobj: BinaryIO, remote_path: str, content_type: Optional[str] = None) -> str:
        norm_key = self.normalize_key(remote_path)
        content_type = self.resolve_content_type(norm_key, content_type)

        if self.is_s3_enabled and self._s3_client:
            extra_args = {"ContentType": content_type}
            self._s3_client.upload_fileobj(fileobj, self.bucket_name, norm_key, ExtraArgs=extra_args)
            logger.info(f"Uploaded stream to S3: s3://{self.bucket_name}/{norm_key} as {content_type}")
            return norm_key
        else:
            dest_local = self.get_local_path(norm_key)
            os.makedirs(os.path.dirname(dest_local), exist_ok=True)
            with open(dest_local, "wb") as out_file:
                shutil.copyfileobj(fileobj, out_file)
            logger.info(f"Saved stream to local storage: {dest_local}")
            return norm_key

    def download_file(self, remote_path: str, local_destination: str) -> str:
        norm_key = self.normalize_key(remote_path)
        os.makedirs(os.path.dirname(os.path.abspath(local_destination)), exist_ok=True)

        if self.is_s3_enabled and self._s3_client:
            self._s3_client.download_file(self.bucket_name, norm_key, local_destination)
            logger.info(f"Downloaded s3://{self.bucket_name}/{norm_key} to {local_destination}")
            return local_destination
        else:
            local_src = self.get_local_path(norm_key)
            if not os.path.exists(local_src):
                raise FileNotFoundError(f"Local storage file not found: {local_src}")
            if os.path.abspath(local_src) != os.path.abspath(local_destination):
                shutil.copy2(local_src, local_destination)
            return local_destination

    def get_stream(self, remote_path: str) -> Tuple[BinaryIO, int, str]:
        """
        Retrieves a readable file stream, file size in bytes, and MIME content-type.
        Works transparently across both S3 and local storage.
        """
        norm_key = self.normalize_key(remote_path)

        if self.is_s3_enabled and self._s3_client:
            try:
                response = self._s3_client.get_object(Bucket=self.bucket_name, Key=norm_key)
                stream = response["Body"]
                content_length = response.get("ContentLength", 0)
                raw_type = response.get("ContentType")
                content_type = self.resolve_content_type(norm_key, raw_type)
                return stream, content_length, content_type
            except Exception as exc:
                logger.warning(f"S3 get_object failed for '{norm_key}': {exc}. Checking local fallback.")

        # Local fallback
        local_file = self.get_local_path(norm_key)
        if not os.path.exists(local_file) and os.path.exists(remote_path):
            local_file = remote_path

        if not os.path.exists(local_file):
            raise FileNotFoundError(f"File not found in storage: {norm_key}")

        size = os.path.getsize(local_file)
        mime = self.resolve_content_type(local_file)
        return open(local_file, "rb"), size, mime

    def get_range_stream(
        self, remote_path: str, byte_range: Optional[str] = None
    ) -> Tuple[BinaryIO, int, str, Optional[str], int]:
        """
        Retrieves a stream supporting HTTP byte ranges.
        Returns: (stream, content_length, content_type, content_range_str_or_None, status_code)
        """
        norm_key = self.normalize_key(remote_path)

        if self.is_s3_enabled and self._s3_client:
            try:
                kwargs = {"Bucket": self.bucket_name, "Key": norm_key}
                if byte_range and byte_range.strip().startswith("bytes="):
                    kwargs["Range"] = byte_range.strip()

                response = self._s3_client.get_object(**kwargs)
                stream = response["Body"]
                content_length = response.get("ContentLength", 0)
                raw_type = response.get("ContentType")
                content_type = self.resolve_content_type(norm_key, raw_type)
                content_range = response.get("ContentRange")
                status_code = 206 if content_range else 200
                return stream, content_length, content_type, content_range, status_code
            except Exception as exc:
                logger.warning(f"S3 get_range_stream failed for '{norm_key}': {exc}. Checking local fallback.")

        # Local fallback
        local_file = self.get_local_path(norm_key)
        if not os.path.exists(local_file) and os.path.exists(remote_path):
            local_file = remote_path

        if not os.path.exists(local_file):
            raise FileNotFoundError(f"File not found in storage: {norm_key}")

        total_size = os.path.getsize(local_file)
        mime = self.resolve_content_type(local_file)

        if byte_range and byte_range.strip().startswith("bytes="):
            try:
                range_str = byte_range.strip()[6:].strip()
                parts = range_str.split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else total_size - 1
                if start >= total_size:
                    start = total_size - 1
                if end >= total_size:
                    end = total_size - 1
                length = max(0, end - start + 1)
                f = open(local_file, "rb")
                f.seek(start)
                content_range = f"bytes {start}-{end}/{total_size}"
                return f, length, mime, content_range, 206
            except Exception:
                pass

        return open(local_file, "rb"), total_size, mime, None, 200

    def delete_file(self, remote_path: str) -> bool:
        norm_key = self.normalize_key(remote_path)
        deleted = False

        if self.is_s3_enabled and self._s3_client:
            try:
                self._s3_client.delete_object(Bucket=self.bucket_name, Key=norm_key)
                deleted = True
            except Exception as exc:
                logger.error(f"Error deleting S3 object '{norm_key}': {exc}")

        local_file = self.get_local_path(norm_key)
        if os.path.exists(local_file):
            try:
                os.remove(local_file)
                deleted = True
            except Exception as exc:
                logger.warning(f"Error deleting local file '{local_file}': {exc}")

        return deleted

    def delete_prefix(self, prefix: str) -> bool:
        norm_prefix = self.normalize_key(prefix)
        if not norm_prefix.endswith("/") and norm_prefix:
            norm_prefix += "/"

        if self.is_s3_enabled and self._s3_client:
            try:
                paginator = self._s3_client.get_paginator("list_objects_v2")
                pages = paginator.paginate(Bucket=self.bucket_name, Prefix=norm_prefix)
                for page in pages:
                    objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                    if objects:
                        self._s3_client.delete_objects(
                            Bucket=self.bucket_name,
                            Delete={"Objects": objects},
                        )
                logger.info(f"Deleted S3 objects with prefix: {norm_prefix}")
            except Exception as exc:
                logger.error(f"Error deleting S3 prefix '{norm_prefix}': {exc}")

        local_dir = self.get_local_path(norm_prefix)
        if os.path.exists(local_dir):
            try:
                shutil.rmtree(local_dir, ignore_errors=True)
            except Exception as exc:
                logger.warning(f"Error deleting local directory '{local_dir}': {exc}")

        return True

    def exists(self, remote_path: str) -> bool:
        norm_key = self.normalize_key(remote_path)
        if self.is_s3_enabled and self._s3_client:
            try:
                self._s3_client.head_object(Bucket=self.bucket_name, Key=norm_key)
                return True
            except Exception:
                pass

        local_path = self.get_local_path(norm_key)
        return os.path.exists(local_path) or (os.path.exists(remote_path) and os.path.isfile(remote_path))


storage_service = StorageService()

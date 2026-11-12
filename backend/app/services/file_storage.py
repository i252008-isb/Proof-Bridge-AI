"""Secure local storage for agreement and evidence uploads."""

import io
import logging
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.config import settings


logger = logging.getLogger("proofbridge.files")

UPLOAD_KIND_AGREEMENT = "agreements"
UPLOAD_KIND_EVIDENCE = "evidence"

ALLOWED_UPLOAD_DESCRIPTION = "PDF, DOCX, PNG, JPEG, and WEBP"

MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
}

_MAX_STEM_LENGTH = 240
_CHUNK_SIZE = 1024 * 1024
_EXTENSION_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")
_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')


@dataclass(frozen=True)
class DetectedFile:
    extension: str
    mime_type: str


def read_upload_bytes(upload: UploadFile) -> bytes:
    """Read an upload in bounded chunks and reject empty or oversized files."""
    limit = settings.MAX_UPLOAD_BYTES
    buffer = bytearray()

    upload.file.seek(0)

    while True:
        chunk = upload.file.read(_CHUNK_SIZE)

        if not chunk:
            break

        buffer.extend(chunk)

        if len(buffer) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Uploaded file exceeds the maximum size of {limit} "
                    "bytes (MAX_UPLOAD_BYTES)."
                )
            )

    if not buffer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes)."
        )

    return bytes(buffer)


def detect_upload_type(data: bytes) -> DetectedFile:
    """Identify a supported type from file content, never from client hints."""
    if data.startswith(b"%PDF"):
        return DetectedFile(".pdf", MIME_BY_EXTENSION[".pdf"])

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedFile(".png", MIME_BY_EXTENSION[".png"])

    if data.startswith(b"\xff\xd8\xff"):
        return DetectedFile(".jpg", MIME_BY_EXTENSION[".jpg"])

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return DetectedFile(".webp", MIME_BY_EXTENSION[".webp"])

    if data.startswith(b"PK\x03\x04") and _is_docx(data):
        return DetectedFile(".docx", MIME_BY_EXTENSION[".docx"])

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            "Unsupported file type. Allowed formats: "
            f"{ALLOWED_UPLOAD_DESCRIPTION}."
        )
    )


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def sanitize_filename(filename: str | None, extension: str) -> str:
    """Return a display-only filename with the detected extension."""
    candidate = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = Path(candidate).stem
    stem = _UNSAFE_FILENAME_CHARS.sub("_", stem).strip(" .")

    if not stem:
        stem = "upload"

    return f"{stem[:_MAX_STEM_LENGTH]}{extension}"


def store_upload(
    data: bytes,
    kind: str,
    project_id: int,
    extension: str
) -> str:
    """Write bytes under the upload root and return the relative path."""
    relative_path = Path(kind) / str(project_id) / f"{uuid4().hex}{extension}"
    absolute_path = settings.upload_dir / relative_path

    try:
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=absolute_path.parent,
            prefix=".upload-",
            suffix=".tmp"
        )

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary_name, absolute_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass

            raise
    except OSError as exc:
        logger.error("Failed to store upload for project %s.", project_id)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The uploaded file could not be stored."
        ) from exc

    return relative_path.as_posix()


def resolve_stored_path(relative_path: str | None) -> Path:
    """Resolve a stored path and guarantee it stays inside the upload root."""
    candidate = _contained_path(relative_path)

    if candidate is None or not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested file is not available."
        )

    return candidate


def delete_stored_file(relative_path: str | None) -> None:
    candidate = _contained_path(relative_path)

    if candidate is None or not candidate.is_file():
        return

    try:
        candidate.unlink()
    except OSError:
        logger.warning("Could not remove replaced upload file.")


def _contained_path(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None

    root = settings.upload_dir

    try:
        candidate = (root / relative_path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None

    if not candidate.is_relative_to(root):
        return None

    return candidate


def download_filename(
    filename: str | None,
    stored_path: str
) -> str:
    extension = Path(stored_path).suffix.lower()

    if not _EXTENSION_PATTERN.fullmatch(extension):
        extension = ""

    return sanitize_filename(filename, extension)


def media_type_for(stored_path: str, stored_mime_type: str | None) -> str:
    if stored_mime_type:
        return stored_mime_type

    return MIME_BY_EXTENSION.get(
        Path(stored_path).suffix.lower(),
        "application/octet-stream"
    )

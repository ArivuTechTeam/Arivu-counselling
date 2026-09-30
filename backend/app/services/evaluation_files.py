"""File rules shared by teacher evaluation papers and student answer scripts."""
from __future__ import annotations

from pathlib import Path


MAX_EVALUATION_FILE_BYTES = 30 * 1024 * 1024
ALLOWED_EVALUATION_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
}


def safe_filename(value: str | None) -> str:
    name = Path(value or "upload").name.strip()
    return (name or "upload")[:255]


def content_matches_type(content: bytes, content_type: str) -> bool:
    if content_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    return False


def validate_file_bytes(content: bytes, content_type: str) -> None:
    if content_type not in ALLOWED_EVALUATION_TYPES:
        raise ValueError("Only PDF, PNG and JPEG files are supported.")
    if not content:
        raise ValueError("Uploaded file is empty.")
    if len(content) > MAX_EVALUATION_FILE_BYTES:
        raise OverflowError("File is larger than 30 MiB.")
    if not content_matches_type(content, content_type):
        raise ValueError("File contents do not match the declared type.")

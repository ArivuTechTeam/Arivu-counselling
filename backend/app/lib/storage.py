"""
Storage abstraction.

Everything that touches file storage goes through THIS module. The rest of the
app calls upload_bytes/download_bytes and never imports the Supabase storage
client directly. That indirection is deliberate: your scoping's portability
principle says files should be swappable to S3 later — if we do that, we only
rewrite this one file, not every call site.

Uses the service_role client, so these run as trusted backend operations. The
'documents' bucket is PRIVATE — files are only reachable through here.
"""

from __future__ import annotations

from app.lib.supabase import get_service_client

BUCKET = "documents"
# Private bucket for extracted figure PNGs (document-figure support).
FIGURES_BUCKET = "question-figures"


def upload_bytes(
    path: str, content: bytes, content_type: str, *, bucket: str = BUCKET
) -> str:
    """Upload raw bytes to `path` inside the bucket. Returns the stored path."""
    client = get_service_client()
    client.storage.from_(bucket).upload(
        path,
        content,
        {"content-type": content_type},
    )
    return path


def replace_bytes(
    path: str, content: bytes, content_type: str, *, bucket: str = BUCKET
) -> str:
    """Replace an existing object without changing its stable storage path."""
    client = get_service_client()
    client.storage.from_(bucket).update(
        path,
        content,
        {"content-type": content_type},
    )
    return path


def download_bytes(path: str, *, bucket: str = BUCKET) -> bytes:
    """Download the file at `path` from the bucket as raw bytes."""
    client = get_service_client()
    return client.storage.from_(bucket).download(path)


def delete_bytes(paths: "str | list[str]", *, bucket: str = BUCKET) -> None:
    """Delete one or more stored objects. Accepts a single path or a list."""
    client = get_service_client()
    client.storage.from_(bucket).remove([paths] if isinstance(paths, str) else paths)


def signed_url(path: str, expires_in: int, *, bucket: str = BUCKET) -> str:
    """
    Return a time-limited signed URL for a PRIVATE object, valid for
    `expires_in` seconds. The storage3 client returns a full absolute URL under
    the project's Storage host, so the browser can open it directly — we never
    expose the raw storage path or any service-role credential to the client.
    """
    client = get_service_client()
    result = client.storage.from_(bucket).create_signed_url(path, expires_in)
    url = result.get("signedURL") or result.get("signed_url")
    if not isinstance(url, str) or not url:
        raise RuntimeError("Storage did not return a signed URL.")
    return url

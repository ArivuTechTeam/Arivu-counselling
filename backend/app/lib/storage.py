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


def upload_bytes(path: str, content: bytes, content_type: str) -> str:
    """Upload raw bytes to `path` inside the bucket. Returns the stored path."""
    client = get_service_client()
    client.storage.from_(BUCKET).upload(
        path,
        content,
        {"content-type": content_type},
    )
    return path


def download_bytes(path: str) -> bytes:
    """Download the file at `path` from the bucket as raw bytes."""
    client = get_service_client()
    return client.storage.from_(BUCKET).download(path)


def delete_bytes(path: str) -> None:
    """Delete a stored object when a later database operation cannot reference it."""
    client = get_service_client()
    client.storage.from_(BUCKET).remove([path])


def signed_url(path: str, expires_in: int) -> str:
    """
    Return a time-limited signed URL for a PRIVATE object, valid for
    `expires_in` seconds. The storage3 client returns a full absolute URL under
    the project's Storage host, so the browser can open it directly — we never
    expose the raw storage path or any service-role credential to the client.
    """
    client = get_service_client()
    result = client.storage.from_(BUCKET).create_signed_url(path, expires_in)
    url = result.get("signedURL") or result.get("signed_url")
    if not isinstance(url, str) or not url:
        raise RuntimeError("Storage did not return a signed URL.")
    return url

"""Shared personal-data erasure for self-service and administrator removals."""

from __future__ import annotations

from app.lib.storage import delete_bytes


def erase_account_data(service, *, user_id: str, tenant_id: str) -> None:
    """Remove owned file bytes, then delete/anonymize database personal data.

    The caller remains responsible for revoking sessions and deleting the
    Supabase Auth identity. Object paths are never logged or returned.
    """
    rows = (
        service.table("documents")
        .select("id, storage_path")
        .eq("tenant_id", tenant_id)
        .eq("uploaded_by", user_id)
        .execute()
        .data
        or []
    )
    storage_paths = dict.fromkeys(
        path
        for row in rows
        if isinstance(row, dict)
        and isinstance((path := row.get("storage_path")), str)
        and path
    )
    for storage_path in storage_paths:
        delete_bytes(storage_path)

    # Also erase figures rendered from those documents (question-figures bucket),
    # before anonymize_account_data removes the rows we'd need to find their paths.
    document_ids = [
        row["id"] for row in rows if isinstance(row, dict) and row.get("id")
    ]
    if document_ids:
        from app.services.document_figures import purge_figures_for_documents

        purge_figures_for_documents(
            service, tenant_id=tenant_id, document_ids=document_ids
        )

    service.rpc(
        "anonymize_account_data",
        {"p_user_id": user_id, "p_tenant_id": tenant_id},
    ).execute()

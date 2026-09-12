from pathlib import Path

from app.api.documents import MAX_BYTES, MAX_MB


ROOT = Path(__file__).resolve().parents[2]
LIMIT_BYTES = 30 * 1024 * 1024


def test_document_limits_match_backend_migration_and_canonical_schema() -> None:
    migration = (
        ROOT / "migrations" / "migration-34-document-upload-limit.sql"
    ).read_text(encoding="utf-8")
    schema = (ROOT / "migrations" / "schema.sql").read_text(encoding="utf-8")

    assert MAX_MB == 30
    assert MAX_BYTES == LIMIT_BYTES
    assert "31457280" in migration
    assert "31457280" in schema
    assert "on conflict (id) do update" in migration.lower()
    assert "set file_size_limit = excluded.file_size_limit" in migration.lower()

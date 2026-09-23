from types import SimpleNamespace
from unittest.mock import Mock

from app.services.deployment_check import inspect_deployment


def test_disabled_queue_is_not_claimed_ready_and_no_mutations(tmp_path):
    (tmp_path / "migration-43-faculty-background-jobs.sql").write_text("-- fixture")
    service = Mock()
    result = inspect_deployment(service, SimpleNamespace(faculty_jobs_enabled=False), tmp_path)
    assert result["schema_checks_passed"] is True
    assert result["production_ready"] is False
    assert result["final_generation_mode"] == "legacy_in_process"
    assert result["repository_migrations"] == ["migration-43-faculty-background-jobs.sql"]
    assert "faculty_jobs" not in [call.args[0] for call in service.table.call_args_list]
    service.rpc.assert_not_called()
    service.table.return_value.insert.assert_not_called()
    service.table.return_value.update.assert_not_called()


def test_missing_schema_fails_without_exposing_internal_error(tmp_path):
    service = Mock()
    service.table.return_value.select.return_value.limit.return_value.execute.side_effect = RuntimeError("secret source text and credentials")
    result = inspect_deployment(service, SimpleNamespace(faculty_jobs_enabled=True, figure_attach_enabled=True), tmp_path)
    assert result["schema_checks_passed"] is False
    assert "secret" not in str(result)
    assert {"faculty_jobs", "document_figures"}.issubset({c.args[0] for c in service.table.call_args_list})

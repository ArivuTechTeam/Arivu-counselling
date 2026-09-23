from unittest.mock import patch

from app.services.generation_jobs import create_final_generation_job, _run_final_generation
from tests.test_generation_jobs import _Fake, _Query


class Query(_Query):
    def contains(self, key, values):
        self.containment = (key, values)
        return self

    def in_(self, key, values):
        self.allowed = (key, values)
        return self

    def limit(self, *_args):
        return self

    def _match(self, row):
        if not super()._match(row):
            return False
        if hasattr(self, "containment"):
            key, values = self.containment
            if any((row.get(key) or {}).get(k) != v for k, v in values.items()):
                return False
        if hasattr(self, "allowed"):
            key, values = self.allowed
            if row.get(key) not in values:
                return False
        return True


class Service(_Fake):
    def table(self, name):
        return Query(self.db, name)


def test_same_settings_on_different_documents_get_distinct_jobs():
    service = Service()
    with patch("app.services.generation_jobs.get_service_client", return_value=service):
        def create(document):
            return create_final_generation_job(document_id=document, tenant_id="tenant", created_by="teacher",
                                               request={"subject_id": "subject", "chapter_name": "Chapter"}, launch=False)
        first, created = create("document-one")
        assert created
        assert create("document-one") == (first, False)
        second, created = create("document-two")
        assert created and second != first
        assert create("document-two") == (second, False)


def test_final_failure_does_not_publish_exception_payload():
    service = Service()
    service.db["quiz_generation_jobs"] = [{"id": "job", "tenant_id": "tenant", "created_by": "teacher",
                                           "params": {"request": {}}, "status": "queued"}]
    with patch("app.services.generation_jobs.get_service_client", return_value=service), \
         patch("app.services.generation_jobs.CurrentProfile", side_effect=RuntimeError("private source text")):
        _run_final_generation("job", "tenant")
    row = service.db["quiz_generation_jobs"][0]
    assert row["status"] == "failed"
    assert "private source text" not in row["error_message"]
    assert "task ID" in row["error_message"]

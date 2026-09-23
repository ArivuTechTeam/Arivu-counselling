from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import document_figures as mod
from app.services.figure_extraction import FigureCandidate


class _Query:
    def __init__(self, table: str, service: "_Service") -> None:
        self.table = table
        self.service = service
        self.op = "select"
        self.payload: dict | None = None
        self.single = False

    def select(self, *_a):
        self.op = "select"
        return self

    def insert(self, payload: dict):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload: dict):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, *_a):
        return self

    def in_(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        if self.op == "insert":
            self.service.inserts.append(self.payload)
            return SimpleNamespace(data=[self.payload])
        if self.op == "update":
            self.service.updates.append(self.payload)
            return SimpleNamespace(data=[self.payload])
        if self.op == "delete":
            self.service.deletes += 1
            return SimpleNamespace(data=[])
        if self.single:  # document lookup — a single row (or None)
            return SimpleNamespace(data=self.service.select_rows[0] if self.service.select_rows else None)
        return SimpleNamespace(data=self.service.select_rows)


class _Service:
    def __init__(self, select_rows: list[dict] | None = None) -> None:
        self.select_rows = select_rows or []
        self.inserts: list[dict] = []
        self.updates: list[dict] = []
        self.deletes = 0

    def table(self, name: str) -> _Query:
        return _Query(name, self)


def _candidate(label: str) -> FigureCandidate:
    return FigureCandidate(
        page=1, bbox={"x0": 0, "y0": 0, "x1": 1, "y1": 1}, label=label,
        caption=f"{label} caption", nearby_text=f"{label} caption",
        png_bytes=b"\x89PNG-fake", width=100, height=80,
    )


class StoreDocumentFiguresTests(unittest.TestCase):
    def test_uploads_and_inserts_each_figure(self) -> None:
        service = _Service()
        with patch.object(
            mod, "extract_document_figures",
            return_value=[_candidate("Figure 1"), _candidate("Figure 2")],
        ), patch.object(mod, "upload_bytes") as up, patch.object(mod, "delete_bytes"):
            n = mod.store_document_figures(
                service, tenant_id="t1", document_id="d1", pdf_bytes=b"pdf"
            )
        self.assertEqual(n, 2)
        self.assertEqual(len(service.inserts), 2)
        self.assertEqual(up.call_count, 2)
        self.assertEqual(service.deletes, 0)
        # Storage path is tenant/document scoped.
        self.assertTrue(service.inserts[0]["storage_path"].startswith("t1/d1/"))

    def test_reanalysis_reuses_figure_id_and_preserves_question_links(self) -> None:
        existing = {
            "id": "figure-stable",
            "page": 1,
            "label": "Figure 1",
            "storage_path": "t1/d1/figure-stable.png",
        }
        service = _Service(select_rows=[existing])
        with patch.object(
            mod, "extract_document_figures", return_value=[_candidate("Figure 1")]
        ), patch.object(mod, "replace_bytes") as replace, patch.object(
            mod, "upload_bytes"
        ) as upload, patch.object(mod, "delete_bytes") as delete:
            n = mod.store_document_figures(
                service, tenant_id="t1", document_id="d1", pdf_bytes=b"pdf"
            )

        self.assertEqual(n, 1)
        self.assertEqual(service.inserts, [])
        self.assertEqual(len(service.updates), 1)
        replace.assert_called_once_with(
            "t1/d1/figure-stable.png", b"\x89PNG-fake", "image/png",
            bucket=mod.FIGURES_BUCKET,
        )
        upload.assert_not_called()
        delete.assert_not_called()
        self.assertEqual(service.deletes, 0)

    def test_empty_reanalysis_does_not_delete_existing_linked_figures(self) -> None:
        service = _Service(select_rows=[{
            "id": "figure-stable", "page": 1, "label": "Figure 1",
            "storage_path": "t1/d1/figure-stable.png",
        }])
        with patch.object(mod, "extract_document_figures", return_value=[]), patch.object(
            mod, "delete_bytes"
        ) as delete:
            n = mod.store_document_figures(
                service, tenant_id="t1", document_id="d1", pdf_bytes=b"pdf"
            )
        self.assertEqual(n, 0)
        delete.assert_not_called()
        self.assertEqual(service.deletes, 0)

    def test_extraction_failure_returns_zero(self) -> None:
        service = _Service()
        with patch.object(mod, "extract_document_figures", side_effect=RuntimeError):
            n = mod.store_document_figures(
                service, tenant_id="t1", document_id="d1", pdf_bytes=b"pdf"
            )
        self.assertEqual(n, 0)
        self.assertEqual(service.inserts, [])


class ExtractAndStoreGateTests(unittest.TestCase):
    def test_no_op_when_flag_disabled(self) -> None:
        service = _Service()
        with patch.object(
            mod, "get_settings",
            return_value=SimpleNamespace(figure_attach_enabled=False, figure_max_per_document=50),
        ), patch.object(mod, "extract_document_figures") as extract:
            n = mod.extract_and_store_for_document(
                service, tenant_id="t1", document_id="d1"
            )
        self.assertEqual(n, 0)
        extract.assert_not_called()  # never even reads the document

    def test_no_op_for_non_pdf(self) -> None:
        # flag on, but the document is a DOCX → skip (figures come from PDFs).
        service = _Service(select_rows=[{"storage_path": "p", "file_type": "docx"}])
        with patch.object(
            mod, "get_settings",
            return_value=SimpleNamespace(figure_attach_enabled=True, figure_max_per_document=50),
        ), patch.object(mod, "download_bytes") as dl:
            n = mod.extract_and_store_for_document(service, tenant_id="t1", document_id="d1")
        self.assertEqual(n, 0)
        dl.assert_not_called()


class AttachFiguresToQuestionsTests(unittest.TestCase):
    _CATALOG = [{"id": "f34", "page": 3, "label": "Fig. 3.4"}]

    def _run(self, questions, *, flag=True, catalog=None):
        service = _Service(select_rows=catalog if catalog is not None else self._CATALOG)
        with patch.object(
            mod, "get_settings",
            return_value=SimpleNamespace(figure_attach_enabled=flag, figure_max_per_document=50),
        ):
            linked = mod.attach_figures_to_questions(
                service, tenant_id="t1", document_id="d1", questions=questions
            )
        return linked, service

    def test_links_matching_question(self) -> None:
        linked, service = self._run([
            {"id": "q1", "question_text": "In the given figure, find the angle.",
             "source_page_start": 3, "source_page_end": 3},
            {"id": "q2", "question_text": "Compute 2 + 2.",
             "source_page_start": 3, "source_page_end": 3},
        ])
        self.assertEqual(linked, 1)  # only the figure-dependent question
        self.assertEqual(len(service.updates), 1)
        self.assertEqual(service.updates[0], {"figure_id": "f34"})

    def test_no_op_when_flag_disabled(self) -> None:
        linked, service = self._run(
            [{"id": "q1", "question_text": "In the given figure, find x.",
              "source_page_start": 3, "source_page_end": 3}],
            flag=False,
        )
        self.assertEqual(linked, 0)
        self.assertEqual(service.updates, [])

    def test_no_op_when_catalog_empty(self) -> None:
        linked, service = self._run(
            [{"id": "q1", "question_text": "In the given figure, find x.",
              "source_page_start": 3, "source_page_end": 3}],
            catalog=[],
        )
        self.assertEqual(linked, 0)
        self.assertEqual(service.updates, [])


class PurgeFiguresForDocumentsTests(unittest.TestCase):
    def test_deletes_objects_and_rows_for_documents(self) -> None:
        service = _Service(select_rows=[
            {"storage_path": "t1/d1/a.png"}, {"storage_path": "t1/d1/b.png"},
        ])
        with patch.object(mod, "delete_bytes") as del_bytes:
            removed = mod.purge_figures_for_documents(
                service, tenant_id="t1", document_ids=["d1", "d1", None]
            )
        self.assertEqual(removed, 2)
        del_bytes.assert_called_once()
        args, kwargs = del_bytes.call_args
        self.assertEqual(args[0], ["t1/d1/a.png", "t1/d1/b.png"])
        self.assertEqual(kwargs.get("bucket"), mod.FIGURES_BUCKET)
        self.assertGreaterEqual(service.deletes, 1)  # rows also removed

    def test_no_documents_is_a_no_op(self) -> None:
        service = _Service(select_rows=[{"storage_path": "x"}])
        with patch.object(mod, "delete_bytes") as del_bytes:
            self.assertEqual(
                mod.purge_figures_for_documents(service, tenant_id="t1", document_ids=[]),
                0,
            )
        del_bytes.assert_not_called()

    def test_lookup_failure_is_best_effort(self) -> None:
        class _Boom(_Service):
            def table(self, name):  # selecting figure rows raises
                raise RuntimeError("db down")

        with patch.object(mod, "delete_bytes") as del_bytes:
            self.assertEqual(
                mod.purge_figures_for_documents(_Boom(), tenant_id="t1", document_ids=["d1"]),
                0,
            )
        del_bytes.assert_not_called()


if __name__ == "__main__":
    unittest.main()

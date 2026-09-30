from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from app.services.llm import structured
from app.services.llm.base import LLMError


def settings():
    return SimpleNamespace(
        gemini_api_key="test-key",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_model="gemini-test",
        gemini_vision_timeout_seconds=240.0,
        gemini_extraction_max_output_tokens=32000,
    )


def gemini_response():
    response = Mock()
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "{}"}]}}]
    }
    return response


def invoke(files):
    return structured.gemini_json_multimodal(
        "system", "user", files, model="gemini-test"
    )


def test_failing_pdf_size_routes_through_files_api():
    raw_size = 13_653_092
    encoded_size = 4 * ((raw_size + 2) // 3)
    assert encoded_size == 18_204_124
    assert structured._requires_gemini_files_api(encoded_size, 0) is True


def test_small_multimodal_file_remains_inline():
    post = Mock(return_value=gemini_response())
    with patch.object(structured, "get_settings", return_value=settings()), \
         patch.object(structured, "post_gemini", post), \
         patch.object(structured, "_upload_to_gemini_files_api") as upload:
        assert invoke([("application/pdf", b"%PDF-small")]) == {}

    upload.assert_not_called()
    part = post.call_args.kwargs["payload"]["contents"][0]["parts"][1]
    assert part["inline_data"]["mime_type"] == "application/pdf"
    assert "file_data" not in part


def test_large_multimodal_file_uses_active_file_uri():
    post = Mock(return_value=gemini_response())
    with patch.object(structured, "GEMINI_FILES_API_THRESHOLD_B64", 4), \
         patch.object(structured, "get_settings", return_value=settings()), \
         patch.object(structured, "post_gemini", post), \
         patch.object(
             structured, "_upload_to_gemini_files_api",
             return_value="https://files.example/files/answer",
         ) as upload:
        assert invoke([("application/pdf", b"%PDF-large")]) == {}

    upload.assert_called_once()
    part = post.call_args.kwargs["payload"]["contents"][0]["parts"][1]
    assert part == {"file_data": {
        "mime_type": "application/pdf",
        "file_uri": "https://files.example/files/answer",
    }}


def test_oversized_document_never_runs_without_evidence_when_upload_fails():
    post = Mock(return_value=gemini_response())
    with patch.object(structured, "GEMINI_FILES_API_THRESHOLD_B64", 4), \
         patch.object(structured, "GEMINI_INLINE_B64_LIMIT", 4), \
         patch.object(structured, "get_settings", return_value=settings()), \
         patch.object(structured, "post_gemini", post), \
         patch.object(
             structured, "_upload_to_gemini_files_api",
             side_effect=LLMError("upload unavailable"),
         ):
        with pytest.raises(LLMError, match="too large for the safe inline"):
            invoke([("application/pdf", b"%PDF-large")])

    post.assert_not_called()


def test_files_api_failure_falls_back_only_when_complete_inline_file_fits():
    post = Mock(return_value=gemini_response())
    with patch.object(structured, "GEMINI_FILES_API_THRESHOLD_B64", 4), \
         patch.object(structured, "GEMINI_INLINE_B64_LIMIT", 100), \
         patch.object(structured, "get_settings", return_value=settings()), \
         patch.object(structured, "post_gemini", post), \
         patch.object(
             structured, "_upload_to_gemini_files_api",
             side_effect=LLMError("upload unavailable"),
         ):
        assert invoke([("application/pdf", b"%PDF-large")]) == {}

    part = post.call_args.kwargs["payload"]["contents"][0]["parts"][1]
    assert "inline_data" in part


def test_files_api_uses_resumable_upload_and_requires_active_state():
    initialized = Mock()
    initialized.headers = {"X-Goog-Upload-URL": "https://upload.example/session"}
    uploaded = Mock()
    uploaded.json.return_value = {
        "file": {
            "uri": "https://generativelanguage.googleapis.com/v1beta/files/abc",
            "state": "ACTIVE",
        }
    }
    with patch.object(
        structured.httpx, "post", side_effect=[initialized, uploaded]
    ) as post:
        uri = structured._upload_to_gemini_files_api(
            raw=b"%PDF-data",
            mime_type="application/pdf",
            display_name="evaluation_document_0",
            api_key="test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )

    assert uri.endswith("/files/abc")
    assert post.call_args_list[0].kwargs["headers"]["X-Goog-Upload-Command"] == "start"
    assert post.call_args_list[1] == call(
        "https://upload.example/session",
        content=b"%PDF-data",
        headers={
            "Content-Length": "9",
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        timeout=300.0,
    )

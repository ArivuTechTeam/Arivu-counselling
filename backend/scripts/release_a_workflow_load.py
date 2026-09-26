"""Run the destructive Release A student workflow against confirmed staging.

This is intentionally separate from the read-only A1 baseline. It consumes one
attempt for each disposable student token, keeps response bodies in memory only,
and writes a metrics-only report. Never point it at production.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import stat
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

from scripts.capacity_baseline import CapacityConfigurationError, percentile, validate_target


WRITE_CONFIRMATION = "A7_WRITE_TEST"
PROFILE_USERS = {"expected": 200, "stress": 500}


@dataclass(frozen=True)
class Actor:
    token: str
    variant_id: str
    subject_id: str
    practice_mode: str = "smart"
    chapter_id: str | None = None


@dataclass(frozen=True)
class StepResult:
    step: str
    status: int | None
    latency_ms: float
    error_type: str | None = None


Transport = Callable[[str, str, str, dict[str, Any] | None, float], tuple[int, dict[str, Any]]]


class _RejectRedirects(HTTPRedirectHandler):
    """Do not risk forwarding a staging bearer token to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def load_actors(path: Path, required: int) -> list[Actor]:
    """Load disposable staging credentials without ever copying them to output."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if os.name != "nt" and mode & 0o077:
            raise CapacityConfigurationError("token file must not be readable by group or others")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except CapacityConfigurationError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise CapacityConfigurationError(f"cannot read token file: {type(exc).__name__}") from exc
    rows = payload.get("actors") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(rows, list):
        raise CapacityConfigurationError("token file must use version 1 with an actors list")
    actors: list[Actor] = []
    seen_tokens: set[str] = set()
    for row in rows:
        token = row.get("token") if isinstance(row, dict) else None
        variant_id = row.get("variant_id") if isinstance(row, dict) else None
        subject_id = row.get("subject_id") if isinstance(row, dict) else None
        practice_mode = row.get("practice_mode", "smart") if isinstance(row, dict) else None
        chapter_id = row.get("chapter_id") if isinstance(row, dict) else None
        if (
            not isinstance(token, str) or len(token) < 20
            or not isinstance(variant_id, str) or not variant_id
            or not isinstance(subject_id, str) or not subject_id
            or practice_mode not in {"smart", "chapter", "revision"}
            or (practice_mode == "chapter" and not isinstance(chapter_id, str))
        ):
            raise CapacityConfigurationError(
                "every actor needs token, variant_id, subject_id, and valid practice scope"
            )
        if token in seen_tokens:
            raise CapacityConfigurationError("each virtual user must have a unique token")
        seen_tokens.add(token)
        actors.append(Actor(
            token=token,
            variant_id=variant_id,
            subject_id=subject_id,
            practice_mode=practice_mode,
            chapter_id=chapter_id,
        ))
    if len(actors) < required:
        raise CapacityConfigurationError(f"profile requires {required} unique disposable student tokens")
    return actors[:required]


def validate_write_target(base_url: str, confirm_host: str | None, confirmation: str | None) -> str:
    if confirmation != WRITE_CONFIRMATION:
        raise CapacityConfigurationError(f"write run requires --confirm-write {WRITE_CONFIRMATION}")
    normalized = validate_target(base_url, True, confirm_host)
    if urlparse(normalized).hostname in {"localhost", "127.0.0.1", "::1"}:
        return normalized
    if not os.getenv("CAPACITY_PRODUCTION_HOST", "").strip():
        raise CapacityConfigurationError("CAPACITY_PRODUCTION_HOST must be set for remote write runs")
    return normalized


def http_json(method: str, url: str, token: str, body: dict[str, Any] | None, timeout: float) -> tuple[int, dict[str, Any]]:
    encoded = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=encoded,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Request-ID": f"capacity-a7-{uuid4().hex}",
        },
    )
    try:
        opener = build_opener(_RejectRedirects(), HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("response_too_large")
            return response.status, json.loads(raw or b"{}")
    except HTTPError as exc:
        exc.read(2 * 1024 * 1024 + 1)
        return exc.code, {}


def _call(
    transport: Transport,
    base_url: str,
    actor: Actor,
    step: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    timeout: float,
) -> tuple[StepResult, dict[str, Any]]:
    started = time.perf_counter()
    try:
        status, payload = transport(method, urljoin(base_url, path.lstrip("/")), actor.token, body, timeout)
        if not isinstance(payload, dict):
            raise ValueError("invalid_response_shape")
        error = None
    except (TimeoutError, URLError, OSError, ValueError) as exc:
        status, payload, error = None, {}, type(exc).__name__
    return StepResult(step, status, (time.perf_counter() - started) * 1000, error), payload


def run_actor(actor: Actor, base_url: str, timeout: float, transport: Transport = http_json) -> tuple[list[StepResult], bool]:
    results: list[StepResult] = []
    sample, _ = _call(transport, base_url, actor, "catalogue", "GET", "/api/v1/quizzes?page_size=10", None, timeout)
    results.append(sample)
    if sample.status != 200:
        return results, False

    sample, started = _call(
        transport, base_url, actor, "attempt_start", "POST", "/api/v1/attempts",
        {"variant_id": actor.variant_id}, timeout,
    )
    results.append(sample)
    attempt_id = started.get("attempt_id")
    questions = started.get("questions")
    if sample.status != 200 or not isinstance(attempt_id, str) or not isinstance(questions, list) or not questions:
        return results, False
    question_ids = [question.get("id") for question in questions if isinstance(question, dict) and question.get("id")]
    if len(question_ids) != len(questions):
        return results, False

    answers = {question_id: None for question_id in question_ids}
    sample, saved = _call(
        transport, base_url, actor, "autosave", "PATCH",
        f"/api/v1/attempts/{attempt_id}/autosave", {"answers": answers}, timeout,
    )
    results.append(sample)
    if sample.status != 200 or saved.get("saved") is not True:
        return results, False

    sample, submitted = _call(
        transport, base_url, actor, "submit", "POST", f"/api/v1/attempts/{attempt_id}/submit",
        {"answers": [], "finalize_reason": "left"}, timeout,
    )
    results.append(sample)
    submitted_results = submitted.get("results")
    if (
        sample.status != 200
        or submitted.get("status") != "graded"
        or not isinstance(submitted_results, list)
        or len(submitted_results) != len(question_ids)
    ):
        return results, False

    sample, receipt = _call(
        transport, base_url, actor, "graded_receipt", "GET", f"/api/v1/attempts/{attempt_id}", None, timeout,
    )
    results.append(sample)
    quiz_intact = (
        sample.status == 200
        and receipt.get("status") == "graded"
        and receipt.get("attempt_id") == attempt_id
        and isinstance(receipt.get("results"), list)
        and len(receipt["results"]) == len(question_ids)
    )
    if not quiz_intact:
        return results, False

    practice_body = {
        "mode": actor.practice_mode,
        "subject_id": actor.subject_id,
        "chapter_id": actor.chapter_id,
        "count": 10,
        "difficulty": None,
    }
    sample, preview = _call(
        transport, base_url, actor, "practice_preview", "POST",
        "/api/v1/practice/preview", practice_body, timeout,
    )
    results.append(sample)
    preview_count = preview.get("question_count")
    if (
        sample.status != 200
        or isinstance(preview_count, bool)
        or not isinstance(preview_count, int)
        or not 0 < preview_count <= 10
    ):
        return results, False

    sample, practice = _call(
        transport, base_url, actor, "practice_start", "POST",
        "/api/v1/practice/sessions", practice_body, timeout,
    )
    results.append(sample)
    session_id = practice.get("attempt_id")
    practice_questions = practice.get("questions")
    if sample.status != 200 or not isinstance(session_id, str) or not isinstance(practice_questions, list) or not practice_questions:
        return results, False
    practice_ids = [question.get("id") for question in practice_questions if isinstance(question, dict) and question.get("id")]
    if len(practice_ids) != len(practice_questions):
        return results, False

    sample, saved = _call(
        transport, base_url, actor, "practice_autosave", "PATCH",
        f"/api/v1/practice/sessions/{session_id}/autosave",
        {"answers": {question_id: None for question_id in practice_ids}}, timeout,
    )
    results.append(sample)
    if sample.status != 200 or saved.get("saved") is not True:
        return results, False

    sample, submitted = _call(
        transport, base_url, actor, "practice_submit", "POST",
        f"/api/v1/practice/sessions/{session_id}/submit",
        {"answers": [], "finalize_reason": "left"}, timeout,
    )
    results.append(sample)
    submitted_results = submitted.get("results")
    if (
        sample.status != 200
        or submitted.get("status") != "graded"
        or not isinstance(submitted_results, list)
        or len(submitted_results) != len(practice_ids)
    ):
        return results, False

    sample, receipt = _call(
        transport, base_url, actor, "practice_graded_receipt", "GET",
        f"/api/v1/practice/sessions/{session_id}", None, timeout,
    )
    results.append(sample)
    intact = (
        sample.status == 200
        and receipt.get("status") == "graded"
        and receipt.get("attempt_id") == session_id
        and isinstance(receipt.get("results"), list)
        and len(receipt["results"]) == len(practice_ids)
    )
    return results, intact


def _metrics(samples: list[StepResult]) -> dict[str, Any]:
    latencies = [sample.latency_ms for sample in samples]
    errors = sum(1 for sample in samples if sample.error_type or sample.status != 200)
    return {
        "requests": len(samples),
        "errors": errors,
        "error_rate_percent": round(errors / len(samples) * 100, 3) if samples else 0,
        "status_counts": dict(sorted(Counter(str(sample.status or "network_error") for sample in samples).items())),
        "latency_ms": {
            "p50": round(percentile(latencies, 50) or 0, 3),
            "p95": round(percentile(latencies, 95) or 0, 3),
            "p99": round(percentile(latencies, 99) or 0, 3),
            "max": round(max(latencies), 3) if latencies else None,
        },
    }


def run_workload(*, actors: list[Actor], base_url: str, timeout: float, transport: Transport = http_json) -> dict[str, Any]:
    started = time.perf_counter()
    samples: list[StepResult] = []
    intact = 0
    with ThreadPoolExecutor(max_workers=len(actors)) as executor:
        futures = [executor.submit(run_actor, actor, base_url, timeout, transport) for actor in actors]
        for future in as_completed(futures):
            actor_samples, actor_intact = future.result()
            samples.extend(actor_samples)
            intact += int(actor_intact)
    grouped: dict[str, list[StepResult]] = defaultdict(list)
    for sample in samples:
        grouped[sample.step].append(sample)
    elapsed = time.perf_counter() - started
    return {
        "schema_version": 1,
        "target_host": urlparse(base_url).hostname,
        "virtual_users": len(actors),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_requests_per_second": round(len(samples) / elapsed, 3) if elapsed else None,
        "completed_intact_workflows": intact,
        "workflow_integrity_met": intact == len(actors),
        "overall": _metrics(samples),
        "steps": {name: _metrics(rows) for name, rows in sorted(grouped.items())},
        "privacy": "No tokens, actor IDs, variant IDs, attempt IDs, response bodies, prompts, or answers are stored.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--profile", choices=sorted(PROFILE_USERS), required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--confirm-host", required=True)
    parser.add_argument("--confirm-write", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--output", type=Path, default=Path(".tmp/a7-workflow-report.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not 0 < args.timeout_seconds <= 120:
            raise CapacityConfigurationError("timeout-seconds must be greater than 0 and at most 120")
        base_url = validate_write_target(args.base_url, args.confirm_host, args.confirm_write)
        actors = load_actors(args.token_file, PROFILE_USERS[args.profile])
        report = run_workload(actors=actors, base_url=base_url, timeout=args.timeout_seconds)
        report["profile"] = args.profile
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except CapacityConfigurationError as exc:
        print(f"A7 workflow configuration error: {exc}")
        return 2
    print(json.dumps({"report": str(args.output), "workflow_integrity_met": report["workflow_integrity_met"], "overall": report["overall"]}, indent=2))
    return 0 if report["workflow_integrity_met"] and report["overall"]["error_rate_percent"] < 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

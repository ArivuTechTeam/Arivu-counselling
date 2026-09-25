"""Run a bounded, read-only API capacity baseline and write a safe JSON report.

This tool deliberately supports only GET and HEAD requests. Local targets work by
default; a remote target must be explicitly confirmed as staging. Authorization
tokens are read from environment variables named by the scenario and are never
included in the report.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import ssl
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


ALLOWED_METHODS = {"GET", "HEAD"}
ALLOWED_ROLES = {
    "public",
    "student",
    "teacher",
    "institution_admin",
    "super_admin",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SERVER_TIMING_PATTERN = re.compile(r"(?:^|,)\s*app;dur=([0-9]+(?:\.[0-9]+)?)")


class CapacityConfigurationError(ValueError):
    """Raised when a scenario or target violates a safety rule."""


@dataclass(frozen=True)
class RouteSpec:
    name: str
    method: str
    path: str
    role: str
    weight: int
    p95_target_ms: float


@dataclass(frozen=True)
class Sample:
    route: str
    status: int | None
    latency_ms: float
    app_latency_ms: float | None = None
    error_type: str | None = None


def percentile(values: list[float], percentile_value: float) -> float | None:
    """Return an interpolated percentile, or None for an empty sample."""
    if not values:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _positive_int(value: Any, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise CapacityConfigurationError(f"{field} must be an integer from 1 to {maximum}")
    return value


def load_scenario(path: Path) -> tuple[str, list[RouteSpec]]:
    """Load and strictly validate the safe subset of the scenario format."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapacityConfigurationError(f"Cannot read scenario: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise CapacityConfigurationError("scenario version must be 1")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CapacityConfigurationError("scenario name is required")
    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise CapacityConfigurationError("scenario routes must be a non-empty list")

    routes: list[RouteSpec] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_routes):
        if not isinstance(raw, dict):
            raise CapacityConfigurationError(f"routes[{index}] must be an object")
        route_name = raw.get("name")
        if not isinstance(route_name, str) or not route_name.strip() or route_name in names:
            raise CapacityConfigurationError(f"routes[{index}].name must be non-empty and unique")
        method = str(raw.get("method", "GET")).upper()
        if method not in ALLOWED_METHODS:
            raise CapacityConfigurationError(
                f"routes[{index}].method must be GET or HEAD; writes are forbidden"
            )
        route_path = raw.get("path")
        parsed_path = urlparse(route_path) if isinstance(route_path, str) else None
        if (
            not isinstance(route_path, str)
            or not route_path.startswith("/")
            or route_path.startswith("//")
            or parsed_path is None
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.fragment
        ):
            raise CapacityConfigurationError(f"routes[{index}].path must be a relative API path")
        role = raw.get("role", "public")
        if role not in ALLOWED_ROLES:
            raise CapacityConfigurationError(f"routes[{index}].role is unsupported")
        p95_target_ms = raw.get("p95_target_ms", 500)
        if isinstance(p95_target_ms, bool) or not isinstance(p95_target_ms, (int, float)) or p95_target_ms <= 0:
            raise CapacityConfigurationError(f"routes[{index}].p95_target_ms must be positive")
        routes.append(
            RouteSpec(
                name=route_name,
                method=method,
                path=route_path,
                role=role,
                weight=_positive_int(raw.get("weight", 1), f"routes[{index}].weight", 100),
                p95_target_ms=float(p95_target_ms),
            )
        )
        names.add(route_name)
    return name, routes


def validate_target(base_url: str, allow_remote_staging: bool, confirm_host: str | None) -> str:
    """Return a normalized base URL after local/staging safety checks."""
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CapacityConfigurationError("base URL must be an http(s) origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CapacityConfigurationError("base URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise CapacityConfigurationError("base URL must not contain a path")
    hostname = parsed.hostname.lower()
    if hostname not in LOCAL_HOSTS:
        if not allow_remote_staging:
            raise CapacityConfigurationError(
                "remote runs require --allow-remote-staging and --confirm-host"
            )
        if not confirm_host or confirm_host.lower() != hostname:
            raise CapacityConfigurationError("--confirm-host must exactly match the remote hostname")
        production_host = os.getenv("CAPACITY_PRODUCTION_HOST", "").strip().lower()
        if production_host and hostname == production_host:
            raise CapacityConfigurationError("the configured production host is never an allowed target")
    return base_url.rstrip("/") + "/"


def _token_for_role(role: str) -> str | None:
    if role == "public":
        return None
    return os.getenv(f"CAPACITY_{role.upper()}_TOKEN")


def _parse_server_timing(value: str | None) -> float | None:
    if not value:
        return None
    match = SERVER_TIMING_PATTERN.search(value)
    return float(match.group(1)) if match else None


def _drain_response(response: Any) -> None:
    """Consume a response in bounded chunks without retaining its payload."""
    while response.read(64 * 1024):
        pass


def execute_request(base_url: str, route: RouteSpec, timeout_seconds: float) -> Sample:
    """Execute one request without retaining its body, URL parameters, or token."""
    headers = {"Accept": "application/json", "X-Request-ID": f"capacity-{uuid4().hex}"}
    token = _token_for_role(route.role)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(urljoin(base_url, route.path.lstrip("/")), method=route.method, headers=headers)
    started = time.perf_counter()
    status: int | None = None
    app_latency_ms: float | None = None
    error_type: str | None = None
    try:
        with urlopen(request, timeout=timeout_seconds, context=ssl.create_default_context()) as response:
            status = response.status
            app_latency_ms = _parse_server_timing(response.headers.get("Server-Timing"))
            _drain_response(response)
    except HTTPError as exc:
        status = exc.code
        app_latency_ms = _parse_server_timing(exc.headers.get("Server-Timing"))
        _drain_response(exc)
    except (TimeoutError, URLError, OSError) as exc:
        error_type = type(exc).__name__
    return Sample(
        route=route.name,
        status=status,
        latency_ms=(time.perf_counter() - started) * 1000,
        app_latency_ms=app_latency_ms,
        error_type=error_type,
    )


def _metric_block(samples: list[Sample]) -> dict[str, Any]:
    latencies = [sample.latency_ms for sample in samples]
    app_latencies = [sample.app_latency_ms for sample in samples if sample.app_latency_ms is not None]
    errors = sum(1 for sample in samples if sample.error_type or not sample.status or sample.status >= 400)
    return {
        "requests": len(samples),
        "errors": errors,
        "error_rate_percent": round((errors / len(samples) * 100) if samples else 0, 3),
        "status_counts": dict(sorted(Counter(str(sample.status or "network_error") for sample in samples).items())),
        "network_error_types": dict(sorted(Counter(sample.error_type for sample in samples if sample.error_type).items())),
        "latency_ms": {
            "p50": _rounded_percentile(latencies, 50),
            "p95": _rounded_percentile(latencies, 95),
            "p99": _rounded_percentile(latencies, 99),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "application_latency_ms": {
            "samples": len(app_latencies),
            "p50": _rounded_percentile(app_latencies, 50),
            "p95": _rounded_percentile(app_latencies, 95),
            "p99": _rounded_percentile(app_latencies, 99),
        },
    }


def _rounded_percentile(values: list[float], value: float) -> float | None:
    result = percentile(values, value)
    return round(result, 3) if result is not None else None


def build_report(
    *,
    scenario_name: str,
    base_url: str,
    concurrency: int,
    elapsed_seconds: float,
    samples: list[Sample],
    routes: list[RouteSpec],
) -> dict[str, Any]:
    grouped: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.route].append(sample)
    target_host = urlparse(base_url).hostname
    per_route: dict[str, Any] = {}
    objectives_met = True
    for route in routes:
        if route.name not in grouped:
            continue
        metrics = _metric_block(grouped[route.name])
        p95 = metrics["latency_ms"]["p95"]
        metrics["p95_target_ms"] = route.p95_target_ms
        metrics["p95_target_met"] = p95 is not None and p95 <= route.p95_target_ms
        objectives_met = objectives_met and metrics["p95_target_met"] and metrics["error_rate_percent"] < 1
        per_route[route.name] = metrics
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario": scenario_name,
        "target_host": target_host,
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "throughput_requests_per_second": round(len(samples) / elapsed_seconds, 3) if elapsed_seconds else None,
        "objectives_met": objectives_met,
        "overall": _metric_block(samples),
        "routes": per_route,
        "privacy": "No response bodies, tokens, query values, prompts, or answers are stored.",
    }
    return report


def run_capacity_baseline(
    *,
    base_url: str,
    scenario_name: str,
    routes: list[RouteSpec],
    selected_roles: set[str],
    rounds: int,
    concurrency: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    selected = [route for route in routes if route.role in selected_roles]
    if not selected:
        raise CapacityConfigurationError("no scenario routes match the selected roles")
    missing_tokens = sorted({route.role for route in selected if route.role != "public" and not _token_for_role(route.role)})
    if missing_tokens:
        variables = ", ".join(f"CAPACITY_{role.upper()}_TOKEN" for role in missing_tokens)
        raise CapacityConfigurationError(f"missing token environment variables: {variables}")
    work = [route for route in selected for _ in range(route.weight * rounds)]
    if len(work) > 100_000:
        raise CapacityConfigurationError("scenario exceeds the 100,000-request safety limit")
    random.Random(20260925).shuffle(work)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(execute_request, base_url, route, timeout_seconds) for route in work]
        samples = [future.result() for future in as_completed(futures)]
    elapsed = time.perf_counter() - started
    return build_report(
        scenario_name=scenario_name,
        base_url=base_url,
        concurrency=concurrency,
        elapsed_seconds=elapsed,
        samples=samples,
        routes=selected,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenario", type=Path, default=Path(__file__).with_name("capacity_scenario.json"))
    parser.add_argument("--role", action="append", choices=sorted(ALLOWED_ROLES), dest="roles")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=15)
    parser.add_argument("--output", type=Path, default=Path(".tmp/capacity-baseline.json"))
    parser.add_argument("--allow-remote-staging", action="store_true")
    parser.add_argument("--confirm-host")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        scenario_name, routes = load_scenario(args.scenario)
        base_url = validate_target(args.base_url, args.allow_remote_staging, args.confirm_host)
        rounds = _positive_int(args.rounds, "rounds", 10_000)
        concurrency = _positive_int(args.concurrency, "concurrency", 500)
        if not 0 < args.timeout_seconds <= 120:
            raise CapacityConfigurationError("timeout-seconds must be greater than 0 and at most 120")
        roles = set(args.roles or ["public"])
        report = run_capacity_baseline(
            base_url=base_url,
            scenario_name=scenario_name,
            routes=routes,
            selected_roles=roles,
            rounds=rounds,
            concurrency=concurrency,
            timeout_seconds=args.timeout_seconds,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except CapacityConfigurationError as exc:
        print(f"capacity baseline configuration error: {exc}")
        return 2
    print(json.dumps({"report": str(args.output), "objectives_met": report["objectives_met"], "overall": report["overall"]}, indent=2))
    return 0 if report["objectives_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

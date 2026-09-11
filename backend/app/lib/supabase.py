"""
Supabase client wrapper.

We expose TWO ways to get a Supabase client, matching the two keys:

  1. get_service_client()  -> uses the service_role key. BYPASSES RLS.
     Only for trusted backend work (e.g. creating a tenant, incrementing
     usage counters). Never expose the data it can reach directly to a user.

  2. get_anon_client()     -> uses the anon key. RESPECTS RLS.
     Use only for stateless anon-key operations. Auth sign-in mutates client
     state and must use create_anon_auth_client() instead.

Keeping this in one wrapper means the rest of the app never touches raw
keys or client construction — it just asks for the client it needs, and the
name of the function makes the security intent obvious at the call site.
"""

from __future__ import annotations

import logging
import random
import time
from threading import Lock

import httpx
from supabase import Client, ClientOptions, create_client

from app.lib.config import get_settings


_service_client: Client | None = None
_anon_client: Client | None = None
_service_client_lock = Lock()
_anon_client_lock = Lock()
logger = logging.getLogger(__name__)


class SupabaseUnavailableError(RuntimeError):
    """The Supabase Data API remained unavailable after safe retries."""


class _ReadRetryTransport(httpx.BaseTransport):
    """Retry only idempotent requests after transient transport failures.

    postgrest-py already retries GET responses with status 503 or 520. This
    transport fills the gap that affected production: exceptions raised before
    an HTTP response exists (for example ``RemoteProtocolError``), plus the
    remaining transient gateway statuses. Writes are deliberately never
    retried because replaying a quiz start or submission could duplicate data.
    """

    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    _RETRYABLE_STATUSES = {408, 502, 503, 504, 520}

    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        max_retries: int = 2,
        base_delay_seconds: float = 0.1,
    ) -> None:
        self._inner = inner
        self._max_retries = max_retries
        self._base_delay_seconds = base_delay_seconds

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in self._SAFE_METHODS:
            return self._inner.handle_request(request)

        for attempt in range(self._max_retries + 1):
            try:
                response = self._inner.handle_request(request)
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise SupabaseUnavailableError(
                        "Supabase transport failed after retries."
                    ) from exc
                failure = type(exc).__name__
            else:
                if response.status_code not in self._RETRYABLE_STATUSES:
                    return response
                failure = f"HTTP {response.status_code}"
                response.close()
                if attempt >= self._max_retries:
                    raise SupabaseUnavailableError(
                        "Supabase returned a transient error after retries."
                    )

            logger.warning(
                "Retrying transient Supabase read (%s, attempt %d/%d, path=%s)",
                failure,
                attempt + 1,
                self._max_retries,
                request.url.path,
            )

            # Exponential backoff with small jitter prevents concurrent
            # dashboard requests from retrying in lockstep.
            delay = self._base_delay_seconds * (2**attempt)
            time.sleep(delay * random.uniform(0.8, 1.2))

        raise RuntimeError("Unreachable retry state")

    def close(self) -> None:
        self._inner.close()


def _create_shared_http_client() -> httpx.Client:
    """Build the thread-safe HTTP client shared by one Supabase client.

    HTTP/2 multiplexing produced the observed intermittent
    ConnectionTerminated failures during concurrent dashboard reads. HTTP/1.1
    still keeps connections alive, but uses ordinary pooled connections.
    """
    limits = httpx.Limits(
        max_connections=50,
        max_keepalive_connections=20,
        keepalive_expiry=30.0,
    )
    inner = httpx.HTTPTransport(http2=False, limits=limits)
    return httpx.Client(
        transport=_ReadRetryTransport(inner),
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
        follow_redirects=True,
    )


def _create_stateless_client(key: str) -> Client:
    settings = get_settings()
    options = ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
        httpx_client=_create_shared_http_client(),
    )
    return create_client(settings.supabase_url, key, options=options)


def get_service_client() -> Client:
    """
    Client authenticated with the service_role key. BYPASSES Row Level
    Security — it can read and write every tenant's data. Backend-only.
    """
    global _service_client
    if _service_client is None:
        with _service_client_lock:
            if _service_client is None:
                settings = get_settings()
                _service_client = _create_stateless_client(
                    settings.supabase_service_role_key
                )
    return _service_client


def get_anon_client() -> Client:
    """
    Process-wide client authenticated with the anon key. RESPECTS Row Level
    Security. Only safe for operations that do not change its auth session.
    """
    global _anon_client
    if _anon_client is None:
        with _anon_client_lock:
            if _anon_client is None:
                settings = get_settings()
                _anon_client = _create_stateless_client(settings.supabase_anon_key)
    return _anon_client


def create_anon_auth_client() -> Client:
    """Return an isolated anon client for an operation that changes auth state.

    Supabase auth sign-in updates the client's in-memory session and shared
    Authorization headers. Such operations must never use the process-wide anon
    singleton, or concurrent users could overwrite one another's session state.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)

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

from threading import Lock

from supabase import Client, create_client

from app.lib.config import get_settings


_service_client: Client | None = None
_anon_client: Client | None = None
_service_client_lock = Lock()
_anon_client_lock = Lock()


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
                _service_client = create_client(
                    settings.supabase_url, settings.supabase_service_role_key
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
                _anon_client = create_client(
                    settings.supabase_url, settings.supabase_anon_key
                )
    return _anon_client


def create_anon_auth_client() -> Client:
    """Return an isolated anon client for an operation that changes auth state.

    Supabase auth sign-in updates the client's in-memory session and shared
    Authorization headers. Such operations must never use the process-wide anon
    singleton, or concurrent users could overwrite one another's session state.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)

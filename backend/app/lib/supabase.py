"""
Supabase client wrapper.

We expose TWO ways to get a Supabase client, matching the two keys:

  1. get_service_client()  -> uses the service_role key. BYPASSES RLS.
     Only for trusted backend work (e.g. creating a tenant, incrementing
     usage counters). Never expose the data it can reach directly to a user.

  2. get_anon_client()     -> uses the anon key. RESPECTS RLS.
     Use when acting on behalf of a logged-in user.

Keeping this in one wrapper means the rest of the app never touches raw
keys or client construction — it just asks for the client it needs, and the
name of the function makes the security intent obvious at the call site.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.lib.config import get_settings


@lru_cache
def get_service_client() -> Client:
    """
    Client authenticated with the service_role key. BYPASSES Row Level
    Security — it can read and write every tenant's data. Backend-only.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


@lru_cache
def get_anon_client() -> Client:
    """
    Client authenticated with the anon key. RESPECTS Row Level Security.
    Use this for actions that should be scoped to the logged-in user.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)

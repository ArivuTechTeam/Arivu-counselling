"""Test-wide safety defaults.

The local developer .env may point at a real Supabase project.  Tests must
never write their mocked provider requests to that project.
"""

from __future__ import annotations

import os


os.environ["APP_ENV"] = "test"

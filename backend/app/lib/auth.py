"""
Authentication for the API.

Two layers, deliberately kept separate:

  get_current_user     -> AUTHENTICATION ("who are you?")
                          Verifies the Supabase JWT locally (HS256) using our
                          JWT secret. No network call. Returns the identity
                          carried in the token: user_id + email.

  get_current_profile  -> AUTHORIZATION CONTEXT ("what tenant / role?")
                          Loads the user's row from the `profiles` table, which
                          is the SOURCE OF TRUTH for tenant_id and role. We do
                          NOT trust tenant/role from the token itself for
                          permission decisions — the DB row is authoritative,
                          and it's the same data our RLS policies read.

Use get_current_user when you only need "is this a logged-in user".
Use get_current_profile when you need to know their tenant or role.
"""

from __future__ import annotations

from functools import lru_cache

import jwt  # the PyJWT library
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.lib.config import get_settings
from app.lib.supabase import get_service_client

# HTTPBearer reads the "Authorization: Bearer <token>" header for us and
# returns the raw token string. auto_error=True -> missing header => 401.
_bearer_scheme = HTTPBearer(auto_error=True)


@lru_cache
def _get_jwks_client() -> PyJWKClient:
    """
    A cached client for Supabase's public signing keys (JWKS).

    Modern Supabase signs user tokens with an ASYMMETRIC key (ES256): a private
    key we never see, and a matching PUBLIC key published at the project's JWKS
    URL. PyJWKClient downloads those public keys once and caches them, so we can
    verify tokens locally without a network call on every request.
    """
    settings = get_settings()
    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url)


def decode_supabase_jwt(token: str) -> dict:
    """
    Verify a Supabase access token and return its claims (payload).

    Handles both signing modes so the backend is portable:
      - ES256/RS256 (asymmetric, the modern default): verify with the project's
        public key fetched from JWKS.
      - HS256 (legacy shared secret): verify with SUPABASE_JWT_SECRET.

    Raises jwt.InvalidTokenError (or a subclass) if the token is bad.
    """
    settings = get_settings()
    # The header tells us which algorithm signed this token. It is NOT trusted
    # for security by itself — we still cryptographically verify below.
    alg = jwt.get_unverified_header(token).get("alg")

    if alg == "HS256":
        key = settings.supabase_jwt_secret
        algorithms = ["HS256"]
    else:
        # Asymmetric: look up the public key whose id (kid) matches the token.
        key = _get_jwks_client().get_signing_key_from_jwt(token).key
        algorithms = ["ES256", "RS256"]

    return jwt.decode(
        token,
        key,
        algorithms=algorithms,
        audience="authenticated",
    )


class CurrentUser(BaseModel):
    """The verified identity carried inside a Supabase JWT."""

    user_id: str  # the "sub" claim = auth.users.id (a UUID string)
    email: str | None = None


class CurrentProfile(BaseModel):
    """A user's authoritative tenant + role, loaded from the profiles table."""

    user_id: str
    tenant_id: str
    role: str  # 'super_admin' | 'institution_admin' | 'teacher' | 'student'
    full_name: str | None = None
    email: str | None = None
    must_change_password: bool = False


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> CurrentUser:
    """
    Verify the incoming JWT and return the caller's identity.

    Raises 401 if the token is missing, expired, tampered, or otherwise
    invalid. On success, we KNOW the user is who the token says they are.
    """
    token = credentials.credentials

    try:
        payload = decode_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        # Bad signature, wrong audience, malformed token, etc.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        # A valid signature but no subject means we can't identify anyone.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject (sub) claim.",
        )

    return CurrentUser(user_id=user_id, email=payload.get("email"))


def get_current_profile(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentProfile:
    """
    Load the caller's authoritative profile (tenant_id + role) from the DB.

    Depends on get_current_user, so the token is already verified by the time
    we get here. We use the service_role client purely to READ this one row by
    its primary key; the user_id came from a signature-verified token, so we
    are only ever looking up the caller's own profile.
    """
    client = get_service_client()
    result = (
        client.table("profiles")
        .select(
            "id,tenant_id,role,full_name,must_change_password,"
            "tenant:tenants!profiles_tenant_id_fkey(id,is_active)"
        )
        .eq("id", user.user_id)
        .maybe_single()  # returns None instead of erroring if no row
        .execute()
    )

    if result is None or not result.data:
        # Authenticated by Supabase, but no profile row exists. This means the
        # signup trigger didn't create one (e.g. signup metadata was missing
        # tenant_id/role). Treat as "account not fully provisioned".
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No profile found for this user. Account is not fully set up.",
        )

    row = result.data
    if str(row["role"]) != "super_admin":
        tenant = row.get("tenant")
        if not isinstance(tenant, dict) or not tenant.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This institution is inactive. Contact the platform administrator.",
            )
    must_change_password = bool(row.get("must_change_password", False))
    if (
        must_change_password
        and request.url.path
        not in {"/api/v1/auth/change-password", "/api/v1/auth/account"}
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must change your temporary password before continuing.",
        )
    return CurrentProfile(
        user_id=user.user_id,
        tenant_id=str(row["tenant_id"]),
        role=str(row["role"]),
        full_name=row.get("full_name"),
        email=user.email,
        must_change_password=must_change_password,
    )

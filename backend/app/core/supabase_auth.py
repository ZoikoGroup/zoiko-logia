from pydantic import BaseModel
import logging

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

settings = get_settings()

# NOTE: use logging, NOT print(). uvicorn --reload routes the worker's
# stdout to DEVNULL, silently eating print() output. uvicorn.error is the
# logger that demonstrably reaches the same stream as the access logs.
log = logging.getLogger("uvicorn.error")

# PyJWKClient caches fetched keys internally, so this module-level client
# (not one per request) is what makes verification a JWKS-cache-hit in the
# common case rather than a network round-trip per request.
_jwks_client: PyJWKClient | None = None
_config_warning_emitted: bool = False


def _get_jwks_client() -> PyJWKClient | None:
    global _jwks_client, _config_warning_emitted
    if not settings.SUPABASE_URL:
        # Every authenticated endpoint 401s while this holds — say it once,
        # loudly, so it reads as a config gap instead of a wall of 401s.
        if not _config_warning_emitted:
            _config_warning_emitted = True
            log.warning(
                "SUPABASE_URL is not set — token verification returns None "
                "(every authenticated request 401s). Set SUPABASE_URL in backend/.env, "
                "pointing at the SAME project as the frontend's NEXT_PUBLIC_SUPABASE_URL."
            )
        return None
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_client


class SupabaseClaims(BaseModel):
    sub: str
    email: str | None = None
    tenant_id: str = ""
    role: str = ""


def verify_token(token: str) -> SupabaseClaims | None:
    """Verify a Supabase-issued access token against the project's JWKS.
    Returns None on any failure (expired, wrong signature, wrong issuer,
    Supabase not configured) — same fail-closed shape callers already
    expect from the old decode_access_token."""
    client = _get_jwks_client()
    if client is None:
        return None
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            # Immune to small clock offsets between the dev machine and the
            # Supabase signer. Without this, a machine clock even a few
            # seconds behind the issuer makes a freshly-issued token read as
            # "not yet valid" (iat in the future) and every login 401s.
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        # A 401 here is otherwise a silent wall. Surface WHY verification
        # failed so a mis-signed/expired/wrong-project token reads as a
        # config or session problem instead of a mystery. Only the token's
        # header and the identity/time claims are logged — never the
        # signature, email, app_metadata, or any secret material.
        try:
            header = jwt.get_unverified_header(token)
            unverified = jwt.decode(token, options={"verify_signature": False})
            claims = {k: unverified.get(k) for k in ("iss", "aud", "exp", "iat", "nbf", "sub") if k in unverified}
        except Exception:
            header, claims = None, None
        log.warning(
            "Supabase token verification failed "
            f"({type(exc).__name__}: {exc}). "
            f"header={header or 'unparseable'} claims={claims or 'unparseable'}"
        )
        return None

    app_metadata = payload.get("app_metadata") or {}
    return SupabaseClaims(
        sub=payload["sub"],
        email=payload.get("email"),
        tenant_id=app_metadata.get("tenant_id", ""),
        role=app_metadata.get("role", ""),
    )

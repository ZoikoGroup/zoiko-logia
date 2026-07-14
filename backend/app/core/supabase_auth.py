from pydantic import BaseModel
import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

settings = get_settings()

# PyJWKClient caches fetched keys internally, so this module-level client
# (not one per request) is what makes verification a JWKS-cache-hit in the
# common case rather than a network round-trip per request.
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient | None:
    global _jwks_client
    if not settings.SUPABASE_URL:
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
        )
    except jwt.PyJWTError:
        return None

    app_metadata = payload.get("app_metadata") or {}
    return SupabaseClaims(
        sub=payload["sub"],
        email=payload.get("email"),
        tenant_id=app_metadata.get("tenant_id", ""),
        role=app_metadata.get("role", ""),
    )

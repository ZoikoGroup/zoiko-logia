import httpx

from app.core.config import get_settings

settings = get_settings()


def _headers() -> dict:
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }
    # Supabase's sb_secret_* API keys are opaque keys, not JWTs. Sending one
    # as a Bearer token makes the gateway reject the Admin API request.
    # Keep the Bearer header for older JWT-based service_role keys.
    if not settings.SUPABASE_SERVICE_ROLE_KEY.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}"
    return headers


def is_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


class SupabaseNotConfiguredError(RuntimeError):
    """Raised when a Supabase Admin API operation is attempted while
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY is unset or empty. Guards run
    BEFORE any request is assembled, so the alternative failure mode here —
    a malformed "Bearer " header leaking an httpx.LocalProtocolError as a raw
    500 — is structurally impossible."""


def _require_configured() -> None:
    if not is_configured():
        raise SupabaseNotConfiguredError(
            "Supabase admin API not configured — set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY (service-role key) in backend/.env "
            "or the environment before calling the Admin API."
        )


def create_user(email: str, password: str, email_confirm: bool = False) -> dict:
    """Create a Supabase auth user via the GoTrue Admin API. Service-role
    only — never callable from the frontend. email_confirm=True bypasses
    the verification email (used for backend-seeded/admin-created accounts,
    which aren't going through the public sign-up flow)."""
    _require_configured()
    resp = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users",
        headers=_headers(),
        json={"email": email, "password": password, "email_confirm": email_confirm},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_user_by_email(email: str) -> dict | None:
    _require_configured()
    resp = httpx.get(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users",
        headers=_headers(),
        params={"email": email},
        timeout=15,
    )
    resp.raise_for_status()
    users = resp.json().get("users", [])
    return users[0] if users else None


def revoke_all_sessions(user_id: str) -> bool:
    """Revoke every active session for a user via the GoTrue Admin API —
    used by POST /auth/sign-out-all-sessions. Service-role only. 204 means
    every access/refresh token the user holds became invalid server-side,
    so a lost/stolen session dies even if the client never signs out."""
    _require_configured()
    resp = httpx.delete(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}/sessions",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.status_code == 204


def update_app_metadata(user_id: str, tenant_id: str, role: str) -> dict:
    """Set tenant_id/role into app_metadata — writable only via the
    service-role key, so a client can never grant itself a role/tenant.
    Supabase embeds app_metadata into every access token it issues for
    this user afterwards, which is what lets get_current_user/get_db read
    tenant_id and role straight off the verified token, no DB round-trip."""
    _require_configured()
    resp = httpx.put(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=_headers(),
        json={"app_metadata": {"tenant_id": tenant_id, "role": role}},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
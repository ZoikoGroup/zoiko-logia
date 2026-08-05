import httpx

from app.core.config import get_settings

settings = get_settings()


def _headers() -> dict:
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


def create_user(
    email: str,
    password: str,
    email_confirm: bool = False,
    user_id: str | None = None,
) -> dict:
    """Create a Supabase auth user via the GoTrue Admin API. Service-role
    only — never callable from the frontend. email_confirm=True bypasses
    the verification email (used for backend-seeded/admin-created accounts,
    which aren't going through the public sign-up flow)."""
    payload = {"email": email, "password": password, "email_confirm": email_confirm}
    if user_id is not None:
        payload["id"] = user_id
    resp = httpx.post(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_user_by_email(email: str) -> dict | None:
    """Return the auth user whose email exactly matches ``email``.

    GoTrue's list-users endpoint does not reliably support an ``email`` query
    parameter.  When it is ignored, taking the first returned user makes every
    requested email appear to exist and prevents seeded accounts from being
    created.  Walk the paginated result and perform the exact match locally.
    """
    wanted = email.casefold()
    page = 1
    per_page = 1000
    while True:
        resp = httpx.get(
            f"{settings.SUPABASE_URL}/auth/v1/admin/users",
            headers=_headers(),
            params={"page": page, "per_page": per_page},
            timeout=15,
        )
        resp.raise_for_status()
        users = resp.json().get("users", [])
        for user in users:
            if str(user.get("email", "")).casefold() == wanted:
                return user
        if len(users) < per_page:
            return None
        page += 1


def update_user_password(user_id: str, password: str) -> dict:
    """Set a backend-managed user's password through the Admin API."""
    resp = httpx.put(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=_headers(),
        json={"password": password, "email_confirm": True},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def update_app_metadata(user_id: str, tenant_id: str, role: str) -> dict:
    """Set tenant_id/role into app_metadata — writable only via the
    service-role key, so a client can never grant itself a role/tenant.
    Supabase embeds app_metadata into every access token it issues for
    this user afterwards, which is what lets get_current_user/get_db read
    tenant_id and role straight off the verified token, no DB round-trip."""
    resp = httpx.put(
        f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=_headers(),
        json={"app_metadata": {"tenant_id": tenant_id, "role": role}},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

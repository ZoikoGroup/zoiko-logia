"""Make the platform Super Admin in SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD
(backend/.env) able to sign in, and hold the platform role.

    python scripts/ensure_super_admin.py --by operator@zoikogroup.com

Idempotent. It makes sure that:
- a confirmed Supabase auth user exists for the email, with that password;
- it is the SAME identity as the local profile row (users.id). When the auth
  user was deleted and re-created, sign-in otherwise fails with a 409 from
  /auth/provision ("account already exists under a different sign-in
  identity"). Here the local row wins: the stray auth user is replaced by one
  carrying the row's id, so the account keeps its tenant and data;
- the local row is active, a tenant Admin, and holds platform_role=super_admin.

Like grant_platform_role.py this is an operator action, never an API: the app
itself does not read these variables.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values
from sqlalchemy import func, select

from app.core import supabase_admin
from app.core.database import AsyncSessionLocal
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import Tenant, User

PLATFORM_TENANT_NAME = "ZoikoLogia Platform"


def _credentials() -> tuple[str, str]:
    file_values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    email = (os.environ.get("SUPER_ADMIN_EMAIL") or file_values.get("SUPER_ADMIN_EMAIL") or "").strip()
    password = os.environ.get("SUPER_ADMIN_PASSWORD") or file_values.get("SUPER_ADMIN_PASSWORD") or ""
    return email, password


def _ensure_auth_user(local_id: str | None, email: str, password: str) -> str:
    """Returns the auth user id the local row must carry."""
    auth = supabase_admin.get_user_by_email(email)
    if auth is not None and local_id is not None and auth["id"] != local_id:
        print(f"Supabase identity {auth['id']} does not match the local profile {local_id}; replacing it.")
        supabase_admin.delete_user(auth["id"])
        auth = None
    if auth is None:
        if local_id is not None:
            created = supabase_admin.create_user_with_id(local_id, email, password)
        else:
            created = supabase_admin.create_user(email, password, email_confirm=True)
        print(f"Created confirmed Supabase user {created['id']}.")
        return created["id"]
    supabase_admin.set_password(auth["id"], password)
    if not auth.get("email_confirmed_at"):
        supabase_admin.confirm_email(auth["id"])
    print(f"Supabase user {auth['id']}: password set, email confirmed.")
    return auth["id"]


async def main(by: str) -> int:
    email, password = _credentials()
    if not email or not password:
        print("Set SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD in backend/.env first.")
        return 1
    try:
        supabase_admin._require_configured()
    except supabase_admin.SupabaseNotConfiguredError as exc:
        print(exc)
        return 1

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()
        auth_id = _ensure_auth_user(user.id if user else None, email, password)

        if user is None:
            tenant = Tenant(name=PLATFORM_TENANT_NAME)
            db.add(tenant)
            await db.flush()
            user = User(id=auth_id, tenant_id=tenant.id, email=email, first_name="Super", last_name="Admin",
                        full_name="Super Admin", role="Admin", is_active=True)
            db.add(user)
            print(f"Created local profile in tenant '{PLATFORM_TENANT_NAME}'.")

        previous = user.platform_role
        user.platform_role = "super_admin"
        user.role = "Admin"
        user.is_active = True
        await db.flush()
        if previous != "super_admin":
            await record_event_async(
                db, tenant_id=user.tenant_id, event_name="platform.role_changed", emitting_service="platform",
                actor_id=None, subject_type="user_account", subject_id=user.id,
                payload={"from": previous, "to": "super_admin", "granted_by": by},
            )
        await db.commit()
        supabase_admin.update_app_metadata(user.id, user.tenant_id, user.role)
        print(f"{email}: ready to sign in (tenant role Admin, platform role super_admin).")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--by", required=True, help="Who authorised this (recorded in the audit ledger)")
    sys.exit(asyncio.run(main(parser.parse_args().by)))

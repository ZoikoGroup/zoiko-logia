"""Re-attach a local profile to a re-created Supabase identity.

When a Supabase auth user is deleted and the person registers again, Supabase
mints a new auth id while the local users row (and everything hanging off it:
tenant, conversations, documents…) still carries the old one. Sign-in then
409s from /auth/provision because the email is already taken.

The profile is moved to the new id only when BOTH hold:
- the old auth identity no longer exists in Supabase (nobody else can still
  sign in as it), and
- the new identity's email is confirmed (the person proved they own the
  address — the same proof a password reset relies on).
Anything else keeps the 409: re-linking a live identity, or on an unverified
address, would hand one person another's tenant.

The move runs in one transaction on the owner connection (the users table is
under RLS and the old row is invisible to the caller's session): copy the row
under the new id, repoint every foreign key, delete the old row.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase_admin
from app.core.database import AsyncSessionLocal
from app.domains.identity.models import User

log = logging.getLogger("uvicorn.error")

_PG_FOREIGN_KEYS = text("""
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.referential_constraints rc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = rc.constraint_name AND kcu.constraint_schema = rc.constraint_schema
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = rc.unique_constraint_name AND ccu.constraint_schema = rc.unique_constraint_schema
    WHERE ccu.table_schema = 'public' AND ccu.table_name = 'users' AND ccu.column_name = 'id'
""")


async def _foreign_keys(db: AsyncSession) -> list[tuple[str, str]]:
    if db.bind.dialect.name == "sqlite":
        tables = (await db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))).scalars().all()
        refs = []
        for table in tables:
            for row in (await db.execute(text(f'PRAGMA foreign_key_list("{table}")'))).mappings():
                if row["table"] == "users" and row["to"] in ("id", None):
                    refs.append((table, row["from"]))
        return refs
    return [(t, c) for t, c in (await db.execute(_PG_FOREIGN_KEYS)).all()]


async def move_profile(db: AsyncSession, old_id: str, new_id: str) -> None:
    """Re-key users.id from old_id to new_id, repointing every reference.
    The caller commits (or rolls back on error)."""
    columns = [c.name for c in User.__table__.columns if c.name not in ("id", "email")]
    col_list = ", ".join(f'"{c}"' for c in columns)
    email = await db.scalar(text("SELECT email FROM users WHERE id = :old"), {"old": old_id})
    # Free the unique email, then copy the row under the new id with it.
    await db.execute(text("UPDATE users SET email = :tmp WHERE id = :old"),
                     {"tmp": f"relinking+{old_id}@invalid", "old": old_id})
    await db.execute(
        text(f'INSERT INTO users (id, email, {col_list}) SELECT :new, :email, {col_list} FROM users WHERE id = :old'),
        {"new": new_id, "email": email, "old": old_id},
    )
    for table, column in await _foreign_keys(db):
        await db.execute(text(f'UPDATE "{table}" SET "{column}" = :new WHERE "{column}" = :old'),
                         {"new": new_id, "old": old_id})
    await db.execute(text("DELETE FROM users WHERE id = :old"), {"old": old_id})


async def relink_if_reregistered(new_id: str, email: str) -> bool:
    """Move the profile that owns `email` to `new_id` when the rules above
    allow it. Returns True when the profile now carries new_id."""
    if not supabase_admin.is_configured():
        return False
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(User).where(func.lower(User.email) == email.strip().lower())
        )).scalar_one_or_none()
        if existing is None or existing.id == new_id:
            return existing is not None
        old_id = existing.id
        try:
            if supabase_admin.get_user(old_id) is not None:
                return False  # the original identity still exists — not a re-registration
            new_user = supabase_admin.get_user(new_id)
        except Exception as exc:  # noqa: BLE001 — undecidable: keep the 409
            log.warning("Re-link check failed for %s (%s)", new_id, type(exc).__name__)
            return False
        if not new_user or not new_user.get("email_confirmed_at") \
                or (new_user.get("email") or "").lower() != email.strip().lower():
            return False
        db.expunge(existing)
        try:
            await move_profile(db, old_id, new_id)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.error("Re-link of profile %s -> %s failed (%s: %s)", old_id, new_id, type(exc).__name__, exc)
            return False
    log.warning("Re-linked profile %s to re-registered Supabase identity %s", old_id, new_id)
    return True

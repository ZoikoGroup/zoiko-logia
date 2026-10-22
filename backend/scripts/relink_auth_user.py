"""Operator-only identity repair; dry-run unless --apply is supplied.

An operator must authorize workspace recovery before running this command.
Matching an email never authorizes automatic linking in the public API.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_engine
from app.core.supabase_admin import _headers, _require_configured, update_app_metadata
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User  # Registers referenced tenant/user tables for audit inserts.


async def repair(email: str, old_id: str, new_id: str, operator: str, apply: bool) -> None:
    _require_configured()
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        # Check both identities. Never displace a still-existing auth user.
        response = await client.get(f"{settings.SUPABASE_URL}/auth/v1/admin/users/{new_id}", headers=_headers())
        response.raise_for_status()
        auth_user = response.json()
        if auth_user.get("id") != new_id or (auth_user.get("email") or "").lower() != email.lower() or not auth_user.get("email_confirmed_at"):
            raise RuntimeError("Target must be the verified auth identity for this email")
        response = await client.get(f"{settings.SUPABASE_URL}/auth/v1/admin/users/{old_id}", headers=_headers())
        if response.status_code != 404:
            raise RuntimeError("Old auth identity still exists or could not be checked; repair refused")

    async with async_engine.begin() as connection:
        await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        await connection.execute(text("SET LOCAL statement_timeout = '15s'"))
        profile = (await connection.execute(text(
            "SELECT id, email, tenant_id, role, is_active FROM public.users WHERE id=:old FOR UPDATE"
        ), {"old": old_id})).mappings().one()
        if profile["email"].lower() != email.lower() or not profile["is_active"]:
            raise RuntimeError("Source profile does not match the active account")
        if await connection.scalar(text("SELECT count(*) FROM public.users WHERE id=:new"), {"new": new_id}):
            raise RuntimeError("Target already has a backend profile")
        fks = (await connection.execute(text("""
            SELECT n.nspname AS schema_name, t.relname AS table_name,
                   a.attname AS column_name, f.conname, f.condeferrable,
                   f.condeferred, cardinality(f.conkey) AS key_count
            FROM pg_constraint f
            JOIN pg_class t ON t.oid=f.conrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            JOIN pg_attribute a ON a.attrelid=f.conrelid AND a.attnum=ANY(f.conkey)
            WHERE f.contype='f' AND f.confrelid='public.users'::regclass
            ORDER BY n.nspname,t.relname,f.conname
        """))).mappings().all()
        if any(f["key_count"] != 1 for f in fks):
            raise RuntimeError("Composite foreign keys require a separate repair plan")
        quote = connection.dialect.identifier_preparer.quote
        tables = [f'{quote(f["schema_name"])}.{quote(f["table_name"])}' for f in fks]
        counts_sql = " UNION ALL ".join(
            f"SELECT {i} AS idx, count(*) AS n FROM {table} WHERE {quote(f['column_name'])}=:old"
            for i, (f, table) in enumerate(zip(fks, tables))
        )
        counts = (await connection.execute(text(counts_sql), {"old": old_id})).all() if fks else []
        affected = [(fks[i], tables[i], n) for i, n in counts if n]
        # These ownership fields intentionally have no foreign key. Historical
        # audit actors and signed evidence are not ownership fields and stay
        # unchanged.
        soft_tables = ("notifications", "user_settings", "query_answer_records", "answer_feedback")
        soft_counts = (await connection.execute(text(" UNION ALL ".join(
            f"SELECT {i} AS idx, count(*) AS n FROM public.{quote(table)} WHERE user_id=:old"
            for i, table in enumerate(soft_tables)
        )), {"old": old_id})).all()
        print("Preserving workspace and role:", profile["tenant_id"], profile["role"])
        for f, table, n in affected:
            print(f"Reference: {table}.{f['column_name']} ({n} rows)")
        for i, n in soft_counts:
            if n:
                print(f"Ownership: {soft_tables[i]}.user_id ({n} rows)")
        if not apply:
            print("Dry run only; no changes made.")
            return

        # Defer only the affected constraints within this transaction, then
        # restore their original settings before committing. No triggers or
        # integrity checks are disabled, and any failure rolls everything back.
        for f, table, _ in affected:
            await connection.execute(text(f"ALTER TABLE {table} ALTER CONSTRAINT {quote(f['conname'])} DEFERRABLE INITIALLY DEFERRED"))
        await connection.execute(text("UPDATE public.users SET id=:new, updated_at=now() WHERE id=:old"), {"old": old_id, "new": new_id})
        for f, table, n in affected:
            result = await connection.execute(text(f"UPDATE {table} SET {quote(f['column_name'])}=:new WHERE {quote(f['column_name'])}=:old"), {"old": old_id, "new": new_id})
            if result.rowcount != n:
                raise RuntimeError("Reference count changed during repair")
        for i, n in soft_counts:
            if n:
                result = await connection.execute(text(f"UPDATE public.{quote(soft_tables[i])} SET user_id=:new WHERE user_id=:old"), {"old": old_id, "new": new_id})
                if result.rowcount != n:
                    raise RuntimeError("Ownership count changed during repair")
        await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        for f, table, _ in affected:
            original = ("DEFERRABLE INITIALLY DEFERRED" if f["condeferred"] else "DEFERRABLE INITIALLY IMMEDIATE") if f["condeferrable"] else "NOT DEFERRABLE"
            await connection.execute(text(f"ALTER TABLE {table} ALTER CONSTRAINT {quote(f['conname'])} {original}"))
        async with AsyncSession(bind=connection) as session:
            await record_event_async(
                session, tenant_id=profile["tenant_id"], event_name="auth.identity_relinked",
                emitting_service="identity", actor_id=None, subject_type="user_account", subject_id=new_id,
                payload={"previous_user_id": old_id, "current_user_id": new_id, "authorized_by": operator},
            )
    # Existing audit records retain their historical actor IDs and hashes.
    update_app_metadata(new_id, profile["tenant_id"], profile["role"])
    print("Identity repaired and auth workspace metadata synchronized.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--old-id", required=True)
    parser.add_argument("--new-id", required=True)
    parser.add_argument("--by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        await repair(args.email, args.old_id, args.new_id, args.by, args.apply)
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

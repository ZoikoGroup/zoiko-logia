"""Seed a LOCAL-DEV WF-01 governance tenant, for exercising the workflow end
to end on an isolated database. Never a real approval or a real identity:
every account is named "LOCAL-DEV simulated <role>", and the script refuses
any database that is not on localhost with "wf01_dev" in its name.

Creates the tenant, one local Admin person (the owner the service-account
rules require) and one service account per WF-01 role, plus a second tenant
with one service account for seeding fixture F7, each with a fresh 1-day API
key, through identity/governance.py (the same path an Admin uses). Re-running
reuses the tenants and accounts and issues new keys. Writes the
tenant id and the keys to the file given as the first argument (keep it out
of the repository) and prints only key prefixes.

    DATABASE_URL=postgresql+asyncpg://me@localhost:5432/zoikologia_wf01_dev \
        python scripts/seed_wf01_local.py /path/outside/repo/wf01-local.json
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROLES = ("Document Control", "Chief Architect", "Independent QA", "QA Automation", "CTO")
TENANT = "LOCAL-DEV WF-01 governance (simulated)"
TENANT_B = "LOCAL-DEV WF-01 tenant B (simulated, fixture F7)"


def _refuse_unless_local(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if parsed.hostname not in ("localhost", "127.0.0.1") or "wf01_dev" not in (parsed.path or ""):
        raise SystemExit(f"Refusing: {parsed.hostname}{parsed.path} is not a local wf01_dev database.")


async def main(out: Path) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.domains.identity import governance
    from app.domains.identity.models import ServiceAccount, Tenant, User

    async with AsyncSessionLocal() as db:
        keys = {}
        tenant_id = None
        for tenant_name, roles, prefix in ((TENANT, ROLES, "LOCAL-DEV simulated"), (TENANT_B, ("Learner",), "LOCAL-DEV tenant B")):
            tenant = (await db.execute(select(Tenant).where(Tenant.name == tenant_name))).scalar_one_or_none()
            if tenant is None:
                tenant = Tenant(name=tenant_name)
                db.add(tenant)
                await db.flush()
                db.add(User(tenant_id=tenant.id, email=f"wf01-local-admin-{tenant.id[:8]}@local.invalid", first_name="LOCAL-DEV",
                            last_name="Admin", full_name="LOCAL-DEV simulated Admin", role="Admin", is_active=True))
                await db.commit()
            tenant_id = tenant_id or tenant.id
            admin = (await db.execute(select(User).where(User.tenant_id == tenant.id, User.role == "Admin"))).scalars().first()
            existing = {a.name: a for a in (await db.execute(select(ServiceAccount).where(ServiceAccount.tenant_id == tenant.id))).scalars()}
            for role in roles:
                name = f"{prefix} {role}"
                account = existing.get(name) or await governance.create_service_account(
                    db, admin, name=name, description="Local workflow test actor; not an approver.", role=role,
                    owner_user_id=admin.id)
                _, raw = await governance.issue_service_account_key(db, admin, account.id, 1)
                keys["TENANT_B" if tenant_name == TENANT_B else role] = {"user_id": account.id, "api_key": raw}
                print(f"{name}: {account.id} key {raw[:12]}…")
        tenant = SimpleNamespace(id=tenant_id)
    out.write_text(json.dumps({"tenant_id": tenant.id, "keys": keys}, indent=1))
    os.chmod(out, 0o600)
    print(f"tenant {tenant.id}; keys written to {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    _refuse_unless_local(os.environ.get("APP_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
    asyncio.run(main(Path(sys.argv[1])))

"""Grant or revoke the platform Super Admin role. The only way to set
users.platform_role: there is deliberately no API for it, so a tenant Admin
can never promote themselves into the control plane.

    python scripts/grant_platform_role.py person@zoikogroup.com --by operator@zoikogroup.com
    python scripts/grant_platform_role.py person@zoikogroup.com --revoke --by operator@zoikogroup.com
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.platform.service import PLATFORM_ROLES


async def main(email: str, revoke: bool, by: str) -> int:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()
        if user is None:
            print(f"No ZoikoLogia account for {email}. The person must sign in once first.")
            return 1
        new_role = None if revoke else "super_admin"
        if new_role is not None and new_role not in PLATFORM_ROLES:
            return 1
        previous, user.platform_role = user.platform_role, new_role
        await record_event_async(
            db, tenant_id=user.tenant_id, event_name="platform.role_changed", emitting_service="platform",
            actor_id=None, subject_type="user_account", subject_id=user.id,
            payload={"from": previous, "to": new_role, "granted_by": by},
        )
        await db.commit()
        print(f"{email}: platform role {previous or 'none'} -> {new_role or 'none'}")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true")
    parser.add_argument("--by", required=True, help="Who authorised this change (recorded in the audit ledger)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.email, args.revoke, args.by)))

"""
WORM-equivalent archive tier for replay-required / legal-hold evidence (Section 6).

This is an application-layer immutability marker standing in for a real
WORM mechanism (cloud Object Lock in Compliance Mode, immutable blob storage
with a policy lock, etc.) until one is attested by Security Lead +
Legal/Compliance. Swapping in a real provider requires no change to callers,
only to this module — same pattern as MockProviderAdapter in model_gateway.
"""
from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent, _now


class ArchiveError(Exception):
    pass


async def archive_event(db: AsyncSession, event_id: str) -> AuditEvent:
    event = await db.get(AuditEvent, event_id)
    if event is None:
        raise ArchiveError("Event not found")

    material = f"{event.id}|{event.chain_hash}|{event.payload_hash}"
    event.archive_ref = hashlib.sha256(material.encode("utf-8")).hexdigest()
    event.archived = True
    event.archived_at = _now()
    await db.commit()
    await db.refresh(event)
    return event

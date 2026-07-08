"""
Governed corrections via compensating events — never mutate history (Section 5).

A compensating event references the original AuditEvent it corrects rather
than editing it. Maker-checker applies: the actor who issues a correction
cannot also be its approver.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent, CompensatingEvent


class CompensatingEventError(Exception):
    """Raised when a compensating event fails enforcement rules (Section 5)."""


async def issue_compensating_event(
    db: AsyncSession,
    *,
    corrects_event_id: str,
    correction_type: str,
    correction_reason: str,
    issued_by: str,
    approver_id: str,
    corrected_fields_summary: list[str] | None = None,
    is_material: bool = False,
    effective_for_replay: bool = True,
) -> CompensatingEvent:
    original = await db.get(AuditEvent, corrects_event_id)
    if original is None:
        raise CompensatingEventError("corrects_event_id does not refer to an existing event")

    if issued_by == approver_id:
        raise CompensatingEventError(
            "Maker-checker violation: the actor issuing the correction cannot approve it"
        )

    row = CompensatingEvent(
        corrects_event_id=corrects_event_id,
        correction_type=correction_type,
        is_material=is_material,
        correction_reason=correction_reason,
        corrected_fields_summary=corrected_fields_summary or [],
        issued_by=issued_by,
        approver_id=approver_id,
        effective_for_replay=effective_for_replay,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row

"""Stored Reporting Rules Resolutions (Document 03 §6.1 states, §11.1
approval integrity).

Each resolution keeps the facts it was made from, their hash, the rule-pack
digest, the result, reviewer judgments and an append-only history. Changing
any fact makes a new revision and the previous one INVALIDATED (§6.1 change
impact: no silent framework switch); a revision that replaces an approval
starts REVALIDATION_REQUIRED. Judgments, rejection and approval each need
someone other than the preparer; approval is re-checked on the server and
refused with any open blocker (AT-22), then freezes the revision with its
pinned rule pack (AT-19). Revoking an approval, or the approver losing
access, removes the release authority (AT-20). An unreviewed rule pack never
permits a statutory claim, approved or not.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User

from .models import FsResolution
from .standards import EntityFacts, YearFigures, resolve, rule_pack_digest
from .store import NotFound, Refused

_CLOSED = ("FROZEN", "INVALIDATED", "REJECTED")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── facts from a request body ───────────────────────────────────────────────

def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        raise Refused(f"'{value}' is not a full date (use YYYY-MM-DD); partial dates are not inferred.") from None


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        raise Refused(f"'{value}' is not a number.") from None


def _year(data: dict | None) -> YearFigures:
    data = data or {}
    employees = data.get("employees")
    try:
        staff = int(employees) if employees not in (None, "") else None
    except (TypeError, ValueError):
        raise Refused(f"'{employees}' is not a whole number of employees.") from None
    return YearFigures(turnover=_dec(data.get("turnover")), balance_sheet_total=_dec(data.get("balance_sheet_total")),
                       employees=staff)


def _names(value) -> tuple[str, ...]:
    return tuple(sorted({str(v).strip() for v in (value or ()) if str(v).strip()}))


def facts_from(data: dict) -> EntityFacts:
    return EntityFacts(
        entity_name=str(data.get("entity_name") or ""), incorporation_jurisdiction=str(data.get("incorporation_jurisdiction") or ""),
        legal_form=str(data.get("legal_form") or ""), scope=str(data.get("scope") or "individual"),
        report_type=str(data.get("report_type") or "annual"), period_start=_date(data.get("period_start")),
        period_end=_date(data.get("period_end")), flags=_names(data.get("flags")),
        current_year=_year(data.get("current_year")), prior_year=_year(data.get("prior_year")),
        prior_year_size=str(data.get("prior_year_size") or ""), framework_election=str(data.get("framework_election") or ""),
        election_signed_by=str(data.get("election_signed_by") or ""), early_adoption=_names(data.get("early_adoption")),
        requested_claim=str(data.get("requested_claim") or "illustrative"), group_perimeter=_names(data.get("group_perimeter")),
        parent_framework=str(data.get("parent_framework") or ""), prior_framework=str(data.get("prior_framework") or ""),
        first_time_adoption=bool(data.get("first_time_adoption")), policy_questions=_names(data.get("policy_questions")),
        requested_statements=_names(data.get("requested_statements")),
        evidence={str(k): str(v) for k, v in (data.get("evidence") or {}).items() if v})


def _hash(data: dict) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _view(row: FsResolution, approver_active: bool | None = None) -> dict:
    return {"id": row.id, "revision": row.revision, "state": row.state, "entity_key": row.entity_key, "facts": row.facts,
            "facts_hash": row.facts_hash, "rule_pack_digest": row.rule_pack_digest, "result": row.result,
            "judgments": row.judgments or {}, "history": row.history or [],
            "pack_is_current": row.rule_pack_digest == rule_pack_digest(),
            "approval_valid": row.state == "FROZEN" and approver_active is not False,
            "trial_balance_id": row.trial_balance_id, "prepared_by": row.prepared_by, "approved_by": row.approved_by,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _approver_active(db: AsyncSession, row: FsResolution) -> bool | None:
    if not row.approved_by:
        return None
    approver = await db.get(User, row.approved_by)
    return bool(approver and approver.is_active)


async def _record(db, row: FsResolution, user, action: str, detail: dict) -> None:
    """Append to the resolution's history and the tenant audit ledger."""
    row.history = [*(row.history or []), {"action": action, "actor_id": user.id, "at": _now().isoformat(),
                                          "state": row.state, "detail": detail}]
    await record_event_async(db, tenant_id=row.tenant_id, event_name=f"financial_statements.resolution_{action}",
                             emitting_service="financial_statements", actor_id=user.id,
                             subject_type="reporting_rules_resolution", subject_id=row.id, payload=detail)


def _recompute(row: FsResolution, *, approved: bool = False) -> dict:
    return resolve(facts_from(row.facts), approved=approved, judgments=row.judgments or {}).to_dict()


def _state_after(row: FsResolution, result_state: str) -> str:
    return "REVALIDATION_REQUIRED" if row.state == "REVALIDATION_REQUIRED" and result_state == "REVIEW_REQUIRED" \
        else result_state


# ── commands ────────────────────────────────────────────────────────────────

async def create(db: AsyncSession, user, data: dict, trial_balance_id: str | None = None) -> dict:
    facts = facts_from(data)
    clean = json.loads(json.dumps(data, sort_keys=True, default=str))
    entity_key = f"{facts.entity_name.strip().lower()}|{facts.period_start}|{facts.period_end}|{facts.scope}"
    latest = (await db.execute(select(FsResolution).where(
        FsResolution.tenant_id == user.tenant_id, FsResolution.entity_key == entity_key)
        .order_by(FsResolution.revision.desc()))).scalars().first()
    current = latest if latest is not None and latest.state not in ("INVALIDATED", "REJECTED") else None
    digest = _hash(clean)
    if current is not None and current.facts_hash == digest and current.rule_pack_digest == rule_pack_digest():
        return _view(current, await _approver_active(db, current))      # same facts and pack: same decision (AT-24)
    result = resolve(facts).to_dict()
    replaces_approval = current is not None and current.state in ("APPROVED", "FROZEN")
    row = FsResolution(tenant_id=user.tenant_id, entity_key=entity_key, revision=(latest.revision + 1) if latest else 1,
                       facts=clean, facts_hash=digest, rule_pack_digest=rule_pack_digest(), result=result,
                       judgments={}, history=[],
                       state="REVALIDATION_REQUIRED" if replaces_approval and result["state"] == "REVIEW_REQUIRED"
                       else result["state"], trial_balance_id=trial_balance_id, prepared_by=user.id)
    db.add(row)
    await db.flush()
    if current is not None:
        current.state = "INVALIDATED"
        await _record(db, current, user, "invalidated", {"by_revision": row.revision,
                                                         "was_approved": replaces_approval})
    await _record(db, row, user, "context_captured", {"revision": row.revision, "facts_hash": digest})
    await _record(db, row, user, "candidates_resolved", {
        "state": row.state, "blockers": result["blockers"], "selected": result["selected_framework"],
        "candidates": [c["framework"] for c in result["candidates"]]})
    await db.commit()
    return _view(row)


async def request_review(db: AsyncSession, user, resolution_id: str, note: str = "") -> dict:
    row = await _open(db, user, resolution_id)
    await _record(db, row, user, "review_requested", {"note": note.strip()})
    await db.commit()
    return _view(row)


async def record_judgment(db: AsyncSession, user, resolution_id: str, key: str, choice: str, reason: str) -> dict:
    """A qualified reviewer's decision on a policy judgment or source conflict (§10.2, §11)."""
    row = await _open(db, user, resolution_id)
    if user.id == row.prepared_by:
        raise Refused("The preparer cannot decide their own accounting judgment (Document 03 §11.1).")
    pending = {p["key"]: p for p in row.result.get("pending_judgments", [])}
    if key not in pending:
        raise Refused(f"'{key}' is not an open judgment on this resolution.")
    if pending[key]["decided"]:
        raise Refused("That judgment is already recorded; a change needs a new revision.")
    if not choice.strip() or not reason.strip():
        raise Refused("A judgment needs the choice made and the reason, with the alternatives considered.")
    row.judgments = {**(row.judgments or {}), key: {"choice": choice.strip(), "reason": reason.strip(),
                                                    "by": user.id, "at": _now().isoformat()}}
    row.result = _recompute(row)
    row.state = _state_after(row, row.result["state"])
    await _record(db, row, user, "judgment_recorded", {"key": key, "choice": choice.strip(), "reason": reason.strip(),
                                                       "blockers": row.result["blockers"]})
    await db.commit()
    return _view(row)


async def approve(db: AsyncSession, user, resolution_id: str) -> dict:
    row = await _get(db, user, resolution_id)
    if row.state == "INVALIDATED":
        raise Refused("This revision was replaced by a newer one; approve the current revision.")
    if row.state in ("APPROVED", "FROZEN"):
        raise Refused("This resolution is already approved.")
    if row.state == "REJECTED":
        raise Refused("This resolution was rejected; save a corrected revision.")
    if user.id == row.prepared_by:
        raise Refused("The preparer cannot approve their own framework decision (Document 03 §11.1).")
    check = _recompute(row, approved=True)          # re-checked on the server, today (AT-15, AT-22)
    if check["blockers"]:
        row.result = _recompute(row)
        row.state = _state_after(row, row.result["state"])
        await db.commit()
        raise Refused("Cannot approve while blockers are open: " + ", ".join(check["blockers"]) + ".")
    row.result = check
    row.state, row.approved_by, row.approved_at = "FROZEN", user.id, _now()
    await _record(db, row, user, "approved", {"permit_statutory_claim": check["permit_statutory_claim"],
                                              "rule_pack": check["rule_pack"]["status"],
                                              "rule_pack_digest": row.rule_pack_digest})
    await db.commit()
    return _view(row, True)


async def reject(db: AsyncSession, user, resolution_id: str, reason: str) -> dict:
    row = await _open(db, user, resolution_id)
    if user.id == row.prepared_by:
        raise Refused("The preparer cannot reject their own framework decision; save a new revision instead.")
    if not reason.strip():
        raise Refused("A rejection needs a reason and the corrective action.")
    row.state = "REJECTED"
    await _record(db, row, user, "rejected", {"reason": reason.strip()})
    await db.commit()
    return _view(row)


async def revoke(db: AsyncSession, user, resolution_id: str, reason: str) -> dict:
    """Withdraw an approval (AT-20): the old authorisation can no longer release anything."""
    row = await _get(db, user, resolution_id)
    if row.state != "FROZEN":
        raise Refused("Only an approved, frozen resolution can be revoked.")
    if user.id != row.approved_by and user.role != "Admin":
        raise Refused("Only the approver or an Admin can revoke this approval.")
    if not reason.strip():
        raise Refused("Revoking an approval needs a reason.")
    row.state = "INVALIDATED"
    await _record(db, row, user, "approval_revoked", {"reason": reason.strip(), "approved_by": row.approved_by})
    await db.commit()
    return _view(row, False)


async def release_check(db: AsyncSession, user, resolution_id: str) -> dict:
    """The hand-off gate (R8) for statement publishing: a statutory claim needs
    a frozen resolution, an approver who still has access and a permitted claim."""
    row = await _get(db, user, resolution_id)
    active = await _approver_active(db, row)
    reasons = []
    if row.state != "FROZEN":
        reasons.append(f"The resolution is {row.state.replace('_', ' ').lower()}, not approved and frozen.")
    if row.state == "FROZEN" and active is False:
        reasons.append("The approver no longer has access; the approval cannot authorise a release.")
    if not row.result.get("permit_statutory_claim"):
        reasons.append("The resolution does not permit a statutory claim (see its blockers and rule-pack status).")
    return {"resolution_id": row.id, "revision": row.revision, "statutory_release_allowed": not reasons,
            "illustrative_allowed": True, "reasons": reasons, "rule_pack_digest": row.rule_pack_digest,
            "framework_edition": row.result.get("framework_edition")}


async def _get(db: AsyncSession, user, resolution_id: str) -> FsResolution:
    row = (await db.execute(select(FsResolution).where(
        FsResolution.id == resolution_id, FsResolution.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Resolution not found.")
    return row


async def _open(db: AsyncSession, user, resolution_id: str) -> FsResolution:
    row = await _get(db, user, resolution_id)
    if row.state in _CLOSED:
        raise Refused(f"This resolution is {row.state.lower()}; save a new revision to change it.")
    return row


async def get(db: AsyncSession, user, resolution_id: str) -> dict:
    row = await _get(db, user, resolution_id)
    return _view(row, await _approver_active(db, row))


async def list_for(db: AsyncSession, user) -> list[dict]:
    rows = (await db.execute(select(FsResolution).where(FsResolution.tenant_id == user.tenant_id)
                             .order_by(FsResolution.created_at.desc()))).scalars().all()
    approvers = {r.approved_by for r in rows if r.approved_by}
    active = {u.id: u.is_active for u in (await db.execute(select(User).where(User.id.in_(approvers)))).scalars()} \
        if approvers else {}
    return [_view(r, active.get(r.approved_by) if r.approved_by else None) for r in rows]

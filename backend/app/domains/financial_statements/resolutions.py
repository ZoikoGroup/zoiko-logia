"""Stored Reporting Rules Resolutions (Document 03 §6.1 states, §11.1
approval integrity).

Each resolution keeps the facts it was made from, their hash, the rule-pack
digest and the result. Changing any fact makes a new revision and the
previous one INVALIDATED (§6.1 change impact: no silent framework switch).
Approval needs someone other than the preparer and no open blocker; it
freezes the revision. An unreviewed rule pack never permits a statutory
claim, approved or not.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async

from .models import FsResolution
from .standards import EntityFacts, YearFigures, resolve, rule_pack_digest
from .store import NotFound, Refused


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── facts from a request body ───────────────────────────────────────────────

def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        raise Refused(f"'{value}' is not a date (use YYYY-MM-DD).") from None


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
    return YearFigures(turnover=_dec(data.get("turnover")), balance_sheet_total=_dec(data.get("balance_sheet_total")),
                       employees=int(employees) if employees not in (None, "") else None)


def facts_from(data: dict) -> EntityFacts:
    return EntityFacts(
        entity_name=str(data.get("entity_name") or ""), incorporation_jurisdiction=str(data.get("incorporation_jurisdiction") or ""),
        legal_form=str(data.get("legal_form") or ""), scope=str(data.get("scope") or "individual"),
        report_type=str(data.get("report_type") or "annual"), period_start=_date(data.get("period_start")),
        period_end=_date(data.get("period_end")), flags=tuple(sorted(set(data.get("flags") or ()))),
        current_year=_year(data.get("current_year")), prior_year=_year(data.get("prior_year")),
        prior_year_size=str(data.get("prior_year_size") or ""), framework_election=str(data.get("framework_election") or ""),
        early_adoption=tuple(sorted(set(data.get("early_adoption") or ()))),
        requested_claim=str(data.get("requested_claim") or "illustrative"))


def _hash(data: dict) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _view(row: FsResolution) -> dict:
    return {"id": row.id, "revision": row.revision, "state": row.state, "entity_key": row.entity_key, "facts": row.facts,
            "facts_hash": row.facts_hash, "rule_pack_digest": row.rule_pack_digest, "result": row.result,
            "trial_balance_id": row.trial_balance_id, "prepared_by": row.prepared_by, "approved_by": row.approved_by,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _event(db, row: FsResolution, user, action: str, detail: dict) -> None:
    await record_event_async(db, tenant_id=row.tenant_id, event_name=f"financial_statements.resolution_{action}",
                             emitting_service="financial_statements", actor_id=user.id,
                             subject_type="reporting_rules_resolution", subject_id=row.id, payload=detail)


# ── commands ────────────────────────────────────────────────────────────────

async def create(db: AsyncSession, user, data: dict, trial_balance_id: str | None = None) -> dict:
    facts = facts_from(data)
    clean = json.loads(json.dumps(data, sort_keys=True, default=str))
    entity_key = f"{facts.entity_name.strip().lower()}|{facts.period_start}|{facts.period_end}|{facts.scope}"
    previous = (await db.execute(select(FsResolution).where(
        FsResolution.tenant_id == user.tenant_id, FsResolution.entity_key == entity_key,
        FsResolution.state != "INVALIDATED").order_by(FsResolution.revision.desc()))).scalars().first()
    digest = _hash(clean)
    if previous is not None and previous.facts_hash == digest and previous.rule_pack_digest == rule_pack_digest():
        return _view(previous)                     # same facts and pack: same decision (AT-24)
    result = resolve(facts).to_dict()
    row = FsResolution(tenant_id=user.tenant_id, entity_key=entity_key, revision=(previous.revision + 1) if previous else 1,
                       facts=clean, facts_hash=digest, rule_pack_digest=rule_pack_digest(), result=result,
                       state=result["state"], trial_balance_id=trial_balance_id, prepared_by=user.id)
    db.add(row)
    await db.flush()
    if previous is not None:
        previous.state = "INVALIDATED"
        await _event(db, previous, user, "invalidated", {"by_revision": row.revision})
    await _event(db, row, user, "created", {"revision": row.revision, "state": row.state,
                                             "blockers": result["blockers"], "selected": result["selected_framework"]})
    await db.commit()
    return _view(row)


async def approve(db: AsyncSession, user, resolution_id: str) -> dict:
    row = await _get(db, user, resolution_id)
    if row.state == "INVALIDATED":
        raise Refused("This revision was replaced by a newer one; approve the current revision.")
    if row.state in ("APPROVED", "FROZEN"):
        raise Refused("This resolution is already approved.")
    if user.id == row.prepared_by:
        raise Refused("The preparer cannot approve their own framework decision (Document 03 §11.1).")
    if row.result.get("blockers"):
        raise Refused("Cannot approve while blockers are open: " + ", ".join(row.result["blockers"]) + ".")
    row.result = resolve(facts_from(row.facts), approved=True).to_dict()
    row.state, row.approved_by, row.approved_at = "FROZEN", user.id, _now()
    await _event(db, row, user, "approved", {"permit_statutory_claim": row.result["permit_statutory_claim"],
                                              "rule_pack": row.result["rule_pack"]["status"]})
    await db.commit()
    return _view(row)


async def _get(db: AsyncSession, user, resolution_id: str) -> FsResolution:
    row = (await db.execute(select(FsResolution).where(
        FsResolution.id == resolution_id, FsResolution.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Resolution not found.")
    return row


async def get(db: AsyncSession, user, resolution_id: str) -> dict:
    return _view(await _get(db, user, resolution_id))


async def list_for(db: AsyncSession, user) -> list[dict]:
    rows = (await db.execute(select(FsResolution).where(FsResolution.tenant_id == user.tenant_id)
                             .order_by(FsResolution.created_at.desc()))).scalars().all()
    return [_view(r) for r in rows]

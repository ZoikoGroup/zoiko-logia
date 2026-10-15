"""Billing & Usage: metered usage, estimated charges, statements.

Usage is measured from the tenant's own hash-chained audit ledger, so every
billed quantity traces back to recorded events:

    meter                 source event                         unit
    kriton_interactions   query_received (count)               interaction
    model_input           model_run_completed (input_length)   million characters
    tool_calls            agent_tool_called (count)            tool call
    external_data_calls   external_reference_data_call (count) call
    document_uploads      attachment_uploaded (size_bytes)     GB

Charges = plan commitment + max(0, usage - included) x rate, per meter,
minus approved credits. A meter under open dispute is excluded from the
estimate until the dispute is resolved. Each month is priced with the plan
version in effect for it; a closed month is an immutable statement. Nothing
here is invented: with no approved plan the page shows usage only.
"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.audit_ledger.models import AuditEvent
from app.domains.billing.models import BillingAdjustment, BillingPlan, BillingStatement
from app.domains.identity.models import Engagement, User

METERS = [
    {"key": "kriton_interactions", "label": "Kriton interactions", "unit": "interaction", "event": "query_received"},
    {"key": "model_input", "label": "Model input processed", "unit": "million characters", "event": "model_run_completed"},
    {"key": "tool_calls", "label": "Agent tool calls", "unit": "tool call", "event": "agent_tool_called"},
    {"key": "external_data_calls", "label": "External data calls", "unit": "call", "event": "external_reference_data_call"},
    {"key": "document_uploads", "label": "Document uploads", "unit": "GB", "event": "kriton_workspace.attachment_uploaded"},
]
METER_KEYS = [m["key"] for m in METERS]
_BY_EVENT = {m["event"]: m["key"] for m in METERS}
_SUMMED = {"model_run_completed": ("input_length", 1e6), "kriton_workspace.attachment_uploaded": ("size_bytes", 1e9)}


class BillingError(ValueError):
    """A billing change the rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: datetime | None) -> str | None:
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()


def period_of(d: datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def bounds(period: str) -> tuple[datetime, datetime]:
    y, m = (int(x) for x in period.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


def previous_periods(period: str, count: int) -> list[str]:
    y, m = (int(x) for x in period.split("-"))
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def _valid_period(period: str) -> str:
    try:
        y, m = (int(x) for x in period.split("-"))
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            raise ValueError
    except ValueError as exc:
        raise BillingError("Period must look like 2026-10") from exc
    return f"{y:04d}-{m:02d}"


# ── Metering ───────────────────────────────────────────────────────────────

async def measure(db: AsyncSession, tenant_id: str, start: datetime, end: datetime) -> dict:
    """Quantities per meter, per day, and Kriton interactions per engagement."""
    events = [m["event"] for m in METERS]
    rows = (await db.execute(
        select(AuditEvent.event_name, func.date(AuditEvent.ingested_at), func.count())
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= start, AuditEvent.ingested_at < end,
               AuditEvent.event_name.in_([e for e in events if e not in _SUMMED]))
        .group_by(AuditEvent.event_name, func.date(AuditEvent.ingested_at)))).all()
    totals: dict[str, float] = {k: 0.0 for k in METER_KEYS}
    daily: dict[str, dict[str, float]] = defaultdict(lambda: {k: 0.0 for k in METER_KEYS})
    for name, day, count in rows:
        key = _BY_EVENT[name]
        totals[key] += count
        daily[str(day)][key] += count
    summed = (await db.execute(
        select(AuditEvent.event_name, AuditEvent.ingested_at, AuditEvent.payload)
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= start, AuditEvent.ingested_at < end,
               AuditEvent.event_name.in_(list(_SUMMED))))).all()
    for name, at, payload in summed:
        field, divisor = _SUMMED[name]
        value = (payload or {}).get(field) or 0
        qty = float(value) / divisor if isinstance(value, (int, float)) else 0.0
        key = _BY_EVENT[name]
        totals[key] += qty
        daily[str(at.date() if hasattr(at, "date") else at)[:10]][key] += qty
    contexts = (await db.execute(
        select(AuditEvent.payload).where(AuditEvent.tenant_id == tenant_id, AuditEvent.ingested_at >= start,
                                         AuditEvent.ingested_at < end, AuditEvent.event_name == "task_context_resolved"))).scalars().all()
    by_engagement = Counter(((p or {}).get("effective_context") or {}).get("engagement_id") or None for p in contexts)
    return {"totals": {k: round(v, 6) for k, v in totals.items()},
            "daily": {d: {k: round(v, 6) for k, v in q.items()} for d, q in sorted(daily.items())},
            "engagements": dict(by_engagement)}


# ── Plans ──────────────────────────────────────────────────────────────────

async def _plans(db: AsyncSession, tenant_id: str) -> list[BillingPlan]:
    return list((await db.execute(select(BillingPlan).where(BillingPlan.tenant_id == tenant_id)
                                  .order_by(BillingPlan.version))).scalars().all())


def plan_for(plans: list[BillingPlan], period: str) -> BillingPlan | None:
    """The approved version in effect for a month: the latest approved one
    whose effective month is not after it."""
    approved = [p for p in plans if p.status in {"active", "superseded"} and p.effective_from <= period]
    return approved[-1] if approved else None


def _plan_view(p: BillingPlan | None, names: dict[str, str]) -> dict | None:
    if p is None:
        return None
    return {"id": p.id, "version": p.version, "status": p.status, "name": p.name, "currency": p.currency,
            "commitmentCents": p.commitment_cents, "included": p.included, "rates": p.rates,
            "softBudgetCents": p.soft_budget_cents, "hardCapCents": p.hard_cap_cents, "effectiveFrom": p.effective_from,
            "note": p.note, "proposedBy": names.get(p.proposed_by, ""), "proposedById": p.proposed_by,
            "proposedAt": _iso(p.proposed_at), "decidedBy": names.get(p.decided_by or "", None), "decidedAt": _iso(p.decided_at)}


# ── Charges ────────────────────────────────────────────────────────────────

def price(plan: BillingPlan | None, usage: dict[str, float], adjustments: list[BillingAdjustment]) -> dict:
    disputes = {a.meter: a for a in adjustments if a.kind == "dispute" and a.status in {"open", "accepted"}}
    lines = []
    if plan is not None:
        lines.append({"key": "commitment", "label": f"{plan.name} commitment", "unit": "month", "quantity": 1,
                      "included": 0, "billable": 1, "rateCents": plan.commitment_cents, "amountCents": plan.commitment_cents,
                      "status": "contracted", "excluded": False})
    for m in METERS:
        qty = usage.get(m["key"], 0.0)
        included = float((plan.included or {}).get(m["key"], 0)) if plan else 0.0
        rate = float((plan.rates or {}).get(m["key"], 0)) if plan else 0.0
        billable = max(0.0, qty - included)
        amount = round(billable * rate)
        dispute = disputes.get(m["key"])
        lines.append({"key": m["key"], "label": m["label"], "unit": m["unit"], "quantity": round(qty, 6),
                      "included": included, "billable": round(billable, 6), "rateCents": rate, "amountCents": amount,
                      "status": ("disputed" if dispute and dispute.status == "open" else "waived" if dispute else
                                 "measured" if plan else "unpriced"),
                      "excluded": dispute is not None})
    credits = -sum(a.amount_cents for a in adjustments if a.kind == "credit" and a.status == "approved")
    if credits:
        lines.append({"key": "credit", "label": "Approved service credits", "unit": "credit", "quantity": 1, "included": 0,
                      "billable": 1, "rateCents": credits, "amountCents": credits, "status": "approved_credit", "excluded": False})
    subtotal = sum(l["amountCents"] for l in lines if not l["excluded"] and l["key"] != "credit")
    excluded = sum(l["amountCents"] for l in lines if l["excluded"])
    variable = sum(l["amountCents"] for l in lines if l["key"] in METER_KEYS and not l["excluded"])
    return {"lines": lines, "subtotalCents": subtotal, "creditsCents": credits, "totalCents": subtotal + credits,
            "variableCents": variable, "excludedCents": excluded, "priced": plan is not None}


async def _adjustments(db: AsyncSession, tenant_id: str, period: str | None = None) -> list[BillingAdjustment]:
    q = select(BillingAdjustment).where(BillingAdjustment.tenant_id == tenant_id)
    if period:
        q = q.where(BillingAdjustment.period == period)
    return list((await db.execute(q.order_by(BillingAdjustment.created_at.desc()))).scalars().all())


async def _statements(db: AsyncSession, tenant_id: str) -> list[BillingStatement]:
    return list((await db.execute(select(BillingStatement).where(BillingStatement.tenant_id == tenant_id)
                                  .order_by(BillingStatement.period.desc()))).scalars().all())


async def _names(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}


async def charges_for(db: AsyncSession, tenant_id: str, period: str, plans: list[BillingPlan] | None = None) -> dict:
    plans = plans if plans is not None else await _plans(db, tenant_id)
    start, end = bounds(period)
    usage = await measure(db, tenant_id, start, end)
    plan = plan_for(plans, period)
    return {"period": period, "planVersion": plan.version if plan else None, "currency": plan.currency if plan else "USD",
            "usage": usage, **price(plan, usage["totals"], await _adjustments(db, tenant_id, period))}


async def overview(db: AsyncSession, tenant_id: str, *, now: datetime | None = None) -> dict:
    now = now or _now()
    period = period_of(now)
    plans = await _plans(db, tenant_id)
    names = await _names(db, tenant_id)
    current = await charges_for(db, tenant_id, period, plans)
    statements = await _statements(db, tenant_id)
    closed = {s.period: s for s in statements}

    trend = []
    for p in previous_periods(period, 6):
        if p == period:
            trend.append({"period": p, "totalCents": current["totalCents"], "interactions": current["usage"]["totals"]["kriton_interactions"],
                          "estimate": True, "priced": current["priced"]})
            continue
        if p in closed:
            s = closed[p]
            interactions = next((l["quantity"] for l in s.lines if l["key"] == "kriton_interactions"), 0)
            trend.append({"period": p, "totalCents": s.total_cents, "interactions": interactions, "estimate": False, "priced": True})
        else:
            c = await charges_for(db, tenant_id, p, plans)
            trend.append({"period": p, "totalCents": c["totalCents"], "interactions": c["usage"]["totals"]["kriton_interactions"],
                          "estimate": True, "priced": c["priced"]})

    # Allocation: charges shared out by each engagement's share of Kriton interactions.
    engagements = {e.id: e.name for e in (await db.execute(select(Engagement).where(Engagement.tenant_id == tenant_id))).scalars()}
    counts = current["usage"]["engagements"]
    total_ctx = sum(counts.values())
    allocation = []
    for eid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        share = n / total_ctx if total_ctx else 0
        allocation.append({"engagementId": eid, "name": engagements.get(eid, "Unassigned (no engagement)") if eid else "Unassigned (no engagement)",
                           "interactions": n, "share": round(share, 4), "amountCents": round(current["totalCents"] * share)})

    active = plan_for(plans, period)
    start, end = bounds(period)
    elapsed = max((now - start).total_seconds(), 1) / (end - start).total_seconds()
    variable = current["variableCents"]
    projected = (active.commitment_cents if active else 0) + round(variable / elapsed) + current["creditsCents"]
    adjustments = await _adjustments(db, tenant_id)
    pending_plan = next((p for p in reversed(plans) if p.status == "proposed"), None)
    trail = (await db.execute(select(AuditEvent).where(
        AuditEvent.tenant_id == tenant_id, AuditEvent.event_name.like("billing_%"))
        .order_by(AuditEvent.ingested_at.desc()).limit(15))).scalars().all()
    open_disputes = [a for a in adjustments if a.kind == "dispute" and a.status == "open"]
    return {
        "period": period, "now": now.isoformat(),
        "meters": METERS,
        "current": current,
        "summary": {
            "estimatedCents": current["totalCents"], "commitmentCents": active.commitment_cents if active else 0,
            "variableCents": variable, "interactions": current["usage"]["totals"]["kriton_interactions"],
            "softBudgetCents": active.soft_budget_cents if active else 0, "hardCapCents": active.hard_cap_cents if active else 0,
            "budgetUsedPct": round(100 * current["totalCents"] / active.soft_budget_cents, 1) if active and active.soft_budget_cents else None,
            "projectedCents": projected if active else None, "openDisputes": len(open_disputes),
            "excludedCents": current["excludedCents"], "priced": current["priced"],
        },
        "trend": trend,
        "allocation": allocation,
        "plan": _plan_view(active, names),
        "pendingPlan": _plan_view(pending_plan, names),
        "planHistory": [_plan_view(p, names) for p in reversed(plans)],
        "adjustments": [{"id": a.id, "period": a.period, "kind": a.kind, "meter": a.meter, "amountCents": a.amount_cents,
                         "reason": a.reason, "status": a.status, "createdBy": names.get(a.created_by, ""), "createdById": a.created_by,
                         "createdAt": _iso(a.created_at), "decidedBy": names.get(a.decided_by or "", None),
                         "decisionNote": a.decision_note} for a in adjustments],
        "statements": [{"id": s.id, "ref": s.ref, "period": s.period, "currency": s.currency, "planVersion": s.plan_version,
                        "subtotalCents": s.subtotal_cents, "creditsCents": s.credits_cents, "totalCents": s.total_cents,
                        "status": s.status, "issuedBy": names.get(s.issued_by, ""), "issuedAt": _iso(s.issued_at),
                        "paidAt": _iso(s.paid_at), "paymentReference": s.payment_reference, "lines": s.lines} for s in statements],
        "closablePeriods": [p for p in previous_periods(period, 13)[:-1] if p not in closed and plan_for(plans, p)],
        "trail": [{"id": e.id, "event": e.event_name, "at": _iso(e.ingested_at), "actor": names.get(e.actor_id or "", "System"),
                   "detail": {k: v for k, v in (e.payload or {}).items() if k in {"version", "period", "ref", "meter", "amount_cents", "status"}}}
                  for e in trail],
    }


# ── Changes (every one audited) ────────────────────────────────────────────

async def _audit(db: AsyncSession, actor: User, event: str, subject_id: str, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="billing",
                             actor_id=actor.id, subject_type="billing", subject_id=subject_id, payload=payload)


def _cents(value, label: str) -> int:
    if not isinstance(value, (int, float)) or value < 0:
        raise BillingError(f"{label} must be zero or more")
    return int(round(value))


async def propose_plan(db: AsyncSession, actor: User, data: dict) -> BillingPlan:
    plans = await _plans(db, actor.tenant_id)
    if any(p.status == "proposed" for p in plans):
        raise BillingError("A plan change is already waiting for approval")
    if not str(data.get("name", "")).strip():
        raise BillingError("Name the plan")
    included = {k: float(v) for k, v in (data.get("included") or {}).items() if k in METER_KEYS and float(v) >= 0}
    rates = {k: float(v) for k, v in (data.get("rates") or {}).items() if k in METER_KEYS and float(v) >= 0}
    plan = BillingPlan(
        tenant_id=actor.tenant_id, version=(plans[-1].version + 1 if plans else 1), status="proposed",
        name=str(data["name"]).strip()[:120], currency=str(data.get("currency") or "USD").upper()[:3],
        commitment_cents=_cents(data.get("commitment_cents", 0), "Commitment"), included=included, rates=rates,
        soft_budget_cents=_cents(data.get("soft_budget_cents", 0), "Soft budget"),
        hard_cap_cents=_cents(data.get("hard_cap_cents", 0), "Hard cap"),
        effective_from=_valid_period(str(data.get("effective_from") or period_of(_now()))),
        note=str(data.get("note") or "").strip()[:1000], proposed_by=actor.id)
    db.add(plan)
    await db.flush()
    await _audit(db, actor, "billing_plan_proposed", plan.id, {"version": plan.version})
    return plan


async def decide_plan(db: AsyncSession, actor: User, plan_id: str, approve: bool, note: str) -> BillingPlan:
    plans = await _plans(db, actor.tenant_id)
    plan = next((p for p in plans if p.id == plan_id), None)
    if plan is None:
        raise LookupError("Plan version not found")
    if plan.status != "proposed":
        raise BillingError("This version has already been decided")
    if plan.proposed_by == actor.id:
        raise BillingError("A different Admin must approve a plan change")
    if approve:
        for p in plans:
            if p.status == "active":
                p.status = "superseded"
        plan.status = "active"
    else:
        if not note.strip():
            raise BillingError("Record why the change is rejected")
        plan.status = "rejected"
    plan.decided_by, plan.decided_at = actor.id, _now()
    await db.flush()
    await _audit(db, actor, f"billing_plan_{plan.status}", plan.id, {"version": plan.version, "note": note.strip()})
    return plan


async def add_adjustment(db: AsyncSession, actor: User, *, kind: str, period: str, reason: str,
                         amount_cents: int = 0, meter: str | None = None) -> BillingAdjustment:
    period = _valid_period(period)
    if not reason.strip():
        raise BillingError("A reason is required")
    if any(s.period == period for s in await _statements(db, actor.tenant_id)):
        raise BillingError("That month is closed; adjustments go on a later statement")
    if kind == "credit":
        adj = BillingAdjustment(tenant_id=actor.tenant_id, period=period, kind="credit",
                                amount_cents=_cents(amount_cents, "Credit"), reason=reason.strip(), status="pending",
                                created_by=actor.id, decision_note="")
        if adj.amount_cents <= 0:
            raise BillingError("A credit needs an amount")
    elif kind == "dispute":
        if meter not in METER_KEYS:
            raise BillingError("Choose the meter being disputed")
        if any(a.kind == "dispute" and a.meter == meter and a.status == "open" for a in await _adjustments(db, actor.tenant_id, period)):
            raise BillingError("That meter is already under dispute for this month")
        adj = BillingAdjustment(tenant_id=actor.tenant_id, period=period, kind="dispute", meter=meter, amount_cents=0,
                                reason=reason.strip(), status="open", created_by=actor.id, decision_note="")
    else:
        raise BillingError("Unknown adjustment")
    db.add(adj)
    await db.flush()
    await _audit(db, actor, f"billing_{kind}_raised", adj.id, {"period": period, "meter": meter, "amount_cents": adj.amount_cents})
    return adj


async def decide_adjustment(db: AsyncSession, actor: User, adj_id: str, decision: str, note: str) -> BillingAdjustment:
    adj = (await db.execute(select(BillingAdjustment).where(
        BillingAdjustment.id == adj_id, BillingAdjustment.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if adj is None:
        raise LookupError("Adjustment not found")
    allowed = {"credit": ({"pending"}, {"approved", "rejected"}), "dispute": ({"open"}, {"accepted", "rejected"})}[adj.kind]
    if adj.status not in allowed[0]:
        raise BillingError("Already decided")
    if decision not in allowed[1]:
        raise BillingError("Unknown decision")
    if adj.created_by == actor.id:
        raise BillingError("A different Admin must decide this")
    if decision == "rejected" and not note.strip():
        raise BillingError("Record why it is rejected")
    adj.status, adj.decided_by, adj.decided_at, adj.decision_note = decision, actor.id, _now(), note.strip()
    await db.flush()
    await _audit(db, actor, f"billing_{adj.kind}_{decision}", adj.id, {"period": adj.period, "meter": adj.meter})
    return adj


async def close_period(db: AsyncSession, actor: User, period: str, *, now: datetime | None = None) -> BillingStatement:
    period = _valid_period(period)
    now = now or _now()
    if period >= period_of(now):
        raise BillingError("Only a finished month can be closed")
    statements = await _statements(db, actor.tenant_id)
    if any(s.period == period for s in statements):
        raise BillingError("That month is already closed")
    if any(a.kind == "dispute" and a.status == "open" for a in await _adjustments(db, actor.tenant_id, period)):
        raise BillingError("Resolve the open metering dispute for that month first")
    c = await charges_for(db, actor.tenant_id, period)
    if not c["priced"]:
        raise BillingError("No approved plan was in effect for that month")
    year_count = sum(1 for s in statements if s.period.startswith(period[:4]))
    statement = BillingStatement(
        tenant_id=actor.tenant_id, ref=f"INV-{period[:4]}-{year_count + 1:03d}", period=period, currency=c["currency"],
        plan_version=c["planVersion"], lines=c["lines"], subtotal_cents=c["subtotalCents"], credits_cents=c["creditsCents"],
        total_cents=c["totalCents"], status="issued", issued_by=actor.id, payment_reference="")
    db.add(statement)
    await db.flush()
    await _audit(db, actor, "billing_statement_issued", statement.id, {"period": period, "ref": statement.ref})
    return statement


async def mark_paid(db: AsyncSession, actor: User, statement_id: str, reference: str) -> BillingStatement:
    s = (await db.execute(select(BillingStatement).where(
        BillingStatement.id == statement_id, BillingStatement.tenant_id == actor.tenant_id))).scalar_one_or_none()
    if s is None:
        raise LookupError("Statement not found")
    if s.status == "paid":
        raise BillingError("Already marked paid")
    if not reference.strip():
        raise BillingError("Record the payment reference")
    s.status, s.paid_at, s.payment_reference = "paid", _now(), reference.strip()[:120]
    await db.flush()
    await _audit(db, actor, "billing_statement_paid", s.id, {"ref": s.ref})
    return s


async def report_csv(db: AsyncSession, tenant_id: str, period: str) -> str:
    c = await charges_for(db, tenant_id, _valid_period(period))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["period", "line", "unit", "quantity", "included", "billable", "rate_cents", "amount_cents", "status", "excluded"])
    for l in c["lines"]:
        w.writerow([period, l["label"], l["unit"], l["quantity"], l["included"], l["billable"], l["rateCents"],
                    l["amountCents"], l["status"], l["excluded"]])
    w.writerow([period, "TOTAL", "", "", "", "", "", c["totalCents"], "estimate" if period == period_of(_now()) else "", ""])
    return buf.getvalue()

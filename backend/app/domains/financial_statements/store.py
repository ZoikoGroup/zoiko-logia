"""Stored trial-balance intake: upload, decisions, journals, supporting
records, approval, history and lineage (Document 04 §11 operations).

Every read and write is scoped to the caller's tenant. Every decision is
recorded twice: in fs_events for the screen's history and in the platform
audit ledger. Any change after approval supersedes the approved snapshot
(SD-010); a corrected upload is a new version that supersedes the old one
(SD-042). The original bytes are never modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async

from . import journals as journals_mod, mapping, supporting, workflow
from .findings import Finding
from .models import FsEvent, FsJournal, FsMappingDecision, FsSnapshot, FsSupportingRecord, FsTrialBalance
from .service import run_intake


class NotFound(LookupError):
    pass


class Refused(ValueError):
    """A request the rules refuse; the message says why."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(text: str | None) -> Decimal:
    try:
        return Decimal(text or "0")
    except InvalidOperation:
        return Decimal("0")


# ── rebuilding engine objects from rows ──────────────────────────────────

def _proposal(row: FsMappingDecision) -> mapping.MappingProposal:
    return mapping.MappingProposal(
        account_key=row.account_key, account_name=row.account_name, balance=_decimal(row.balance), status=row.status,
        line_id=row.line_id, candidates=tuple(row.candidates or ()), evidence_required=row.evidence_required,
        basis=row.basis, allocations=tuple(mapping.Allocation(a["line_id"], _decimal(a["amount"]))
                                           for a in row.allocations or ()),
        reviewer=row.reviewer_id, source=row.source)


def _journal(row: FsJournal) -> journals_mod.JournalProposal:
    return journals_mod.JournalProposal(
        journal_id=row.id, kind=row.kind, reason=row.reason,
        lines=tuple(journals_mod.JournalLine(l["line_id"], _decimal(l["debit"]), _decimal(l["credit"]))
                    for l in row.lines or ()),
        evidence_refs=tuple(row.evidence_refs or ()), created_by=row.created_by, review_status=row.review_status,
        posting_status=row.posting_status, reviewer=row.reviewer_id, correction_type=row.correction_type)


def _finding(data: dict) -> Finding:
    return Finding(code=data["code"], severity=data["severity"], message=data["message"], rule=data["rule"],
                   refs=tuple(data.get("refs") or ()))


# ── loading ──────────────────────────────────────────────────────────────

async def _tb(db: AsyncSession, user, tb_id: str) -> FsTrialBalance:
    row = (await db.execute(select(FsTrialBalance).where(
        FsTrialBalance.id == tb_id, FsTrialBalance.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Trial balance not found.")
    return row


async def _children(db: AsyncSession, tb: FsTrialBalance):
    def q(model):
        return select(model).where(model.trial_balance_id == tb.id, model.tenant_id == tb.tenant_id)
    maps = list((await db.execute(q(FsMappingDecision).order_by(FsMappingDecision.account_name))).scalars())
    jnls = list((await db.execute(q(FsJournal).order_by(FsJournal.created_at))).scalars())
    sups = list((await db.execute(q(FsSupportingRecord).order_by(FsSupportingRecord.created_at))).scalars())
    snaps = list((await db.execute(q(FsSnapshot).order_by(FsSnapshot.approved_at))).scalars())
    events = list((await db.execute(q(FsEvent).order_by(FsEvent.at))).scalars())
    return maps, jnls, sups, snaps, events


def _all_findings(tb: FsTrialBalance, sups: list[FsSupportingRecord]) -> list[Finding]:
    return [*(_finding(f) for f in tb.findings or ()), *(_finding(s.finding) for s in sups if s.finding)]


def _state(tb, maps, jnls, sups, snaps) -> str:
    if tb.superseded_by:
        return workflow.SUPERSEDED
    if tb.media_type == "rejected":
        return workflow.REJECTED_SOURCE
    if any(s.status == "APPROVED" for s in snaps):
        return workflow.APPROVED_SNAPSHOT
    return workflow.state_of(_all_findings(tb, sups), [_proposal(m) for m in maps], [_journal(j) for j in jnls])


async def _event(db: AsyncSession, tb: FsTrialBalance, user, action: str, detail: dict) -> None:
    db.add(FsEvent(tenant_id=tb.tenant_id, trial_balance_id=tb.id, actor_id=user.id, action=action, detail=detail))
    await record_event_async(db, tenant_id=tb.tenant_id, event_name=f"financial_statements.{action}",
                             emitting_service="financial_statements", actor_id=user.id,
                             subject_type="trial_balance", subject_id=tb.id, payload=detail)


async def _supersede_snapshots(db: AsyncSession, tb: FsTrialBalance, user, reason: str) -> None:
    snaps = (await db.execute(select(FsSnapshot).where(
        FsSnapshot.trial_balance_id == tb.id, FsSnapshot.status == "APPROVED"))).scalars().all()
    for snap in snaps:
        snap.status, snap.superseded_at = "SUPERSEDED", _now()
        await _event(db, tb, user, "snapshot_superseded", {"snapshot_id": snap.id, "reason": reason})


def _require_open(tb: FsTrialBalance) -> None:
    if tb.superseded_by:
        raise Refused("This version has been superseded by a newer upload; work on the current version.")
    if tb.media_type == "rejected":
        raise Refused("This upload was rejected; upload a corrected file.")


# ── views ────────────────────────────────────────────────────────────────

def _summary(tb: FsTrialBalance, state: str) -> dict:
    return {"id": tb.id, "filename": tb.filename, "sha256": tb.sha256, "version": tb.version, "kind": tb.kind,
            "state": state, "uploaded_by": tb.uploaded_by, "created_at": tb.created_at.isoformat() if tb.created_at else None,
            "supersedes_id": tb.supersedes_id, "superseded_by": tb.superseded_by,
            "balanced": (tb.integrity or {}).get("balanced"),
            "hard_stops": sum(1 for f in tb.findings or () if f.get("severity") == "HARD_STOP")}


async def detail(db: AsyncSession, user, tb_id: str) -> dict:
    tb = await _tb(db, user, tb_id)
    maps, jnls, sups, snaps, events = await _children(db, tb)
    state = _state(tb, maps, jnls, sups, snaps)
    proposals = [_proposal(m) for m in maps]
    counts = {s: sum(1 for p in proposals if p.status == s)
              for s in (mapping.SUGGESTED, mapping.NEEDS_EVIDENCE, mapping.UNMAPPED, mapping.APPROVED, "REJECTED")}
    return {
        **_summary(tb, state),
        "units": tb.units, "sign_convention": tb.sign_convention, "period_end": tb.period_end or None,
        "sheets": tb.sheets, "integrity": tb.integrity,
        "findings": [f.to_dict() for f in _all_findings(tb, sups)],
        "lines": tb.lines,
        "mappings": [{"id": m.id, **_proposal(m).to_dict(), "evidence_ref": m.evidence_ref,
                      "decided_at": m.decided_at.isoformat() if m.decided_at else None} for m in maps],
        "mapping_counts": counts,
        "journals": [{**_journal(j).to_dict(), "created_at": j.created_at.isoformat() if j.created_at else None,
                      "reviewed_at": j.reviewed_at.isoformat() if j.reviewed_at else None} for j in jnls],
        "supporting": [{"id": s.id, "kind": s.kind, "filename": s.filename, "sha256": s.sha256, "total": s.total,
                        "basis": s.basis, "finding": s.finding} for s in sups],
        "snapshots": [{"id": s.id, "content_hash": s.content_hash, "status": s.status, "preparer_id": s.preparer_id,
                       "approver_id": s.approver_id, "approved_at": s.approved_at.isoformat() if s.approved_at else None,
                       "line_totals": s.line_totals} for s in snaps],
        "history": [{"action": e.action, "actor_id": e.actor_id, "at": e.at.isoformat() if e.at else None,
                     "detail": e.detail} for e in events],
        "status_note": "Mappings are proposals until a reviewer other than the uploader approves them; "
                       "nothing is posted to any ledger.",
    }


async def list_trial_balances(db: AsyncSession, user) -> list[dict]:
    rows = (await db.execute(select(FsTrialBalance).where(FsTrialBalance.tenant_id == user.tenant_id)
                             .order_by(FsTrialBalance.created_at.desc()))).scalars().all()
    out = []
    for tb in rows:
        maps, jnls, sups, snaps, _ = await _children(db, tb)
        out.append(_summary(tb, _state(tb, maps, jnls, sups, snaps)))
    return out


# ── commands ─────────────────────────────────────────────────────────────

async def create(db: AsyncSession, user, filename: str, content: bytes, supersedes_id: str | None = None) -> dict:
    previous = await _tb(db, user, supersedes_id) if supersedes_id else None
    if previous is not None and previous.superseded_by:
        raise Refused("That version is already superseded; correct the current version.")
    result = run_intake(filename, content, uploaded_by=user.id)
    rejected = result.state == workflow.REJECTED_SOURCE
    tb = FsTrialBalance(
        tenant_id=user.tenant_id, uploaded_by=user.id, filename=filename, sha256=result.manifest.sha256,
        size_bytes=result.manifest.size_bytes, media_type=result.manifest.media_type, original=content,
        kind=result.tb.kind, units=result.tb.units, sign_convention=result.tb.sign_convention,
        period_end=result.tb.period_end.isoformat() if result.tb.period_end else "",
        sheets={"sheets": list(result.manifest.sheets), "hidden_sheets": list(result.manifest.hidden_sheets)},
        integrity=result.report.to_dict() if not rejected else {},
        findings=[f.to_dict() for f in result.findings], lines=[l.to_dict() for l in result.tb.lines],
        version=(previous.version + 1) if previous else 1, supersedes_id=previous.id if previous else None,
    )
    db.add(tb)
    await db.flush()
    for p in result.mappings:
        db.add(FsMappingDecision(tenant_id=tb.tenant_id, trial_balance_id=tb.id, account_key=p.account_key,
                                 account_name=p.account_name, balance=str(p.balance), status=p.status,
                                 line_id=p.line_id, candidates=list(p.candidates), evidence_required=p.evidence_required,
                                 basis=p.basis, allocations=[], source=p.source))
    await _event(db, tb, user, "uploaded", {"filename": filename, "sha256": tb.sha256, "version": tb.version,
                                            "state": result.state, "findings": len(result.findings)})
    if previous is not None:
        previous.superseded_by = tb.id
        await _supersede_snapshots(db, previous, user, f"superseded by version {tb.version}")
        await _event(db, previous, user, "superseded", {"by": tb.id, "version": tb.version})
    await db.commit()
    return await detail(db, user, tb.id)


async def decide_mapping(db: AsyncSession, user, tb_id: str, mapping_id: str, *, action: str,
                         line_id: str | None = None, allocations: list[tuple[str, str]] | None = None,
                         evidence_ref: str = "", reason: str = "") -> dict:
    tb = await _tb(db, user, tb_id)
    _require_open(tb)
    row = (await db.execute(select(FsMappingDecision).where(
        FsMappingDecision.id == mapping_id, FsMappingDecision.trial_balance_id == tb.id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Mapping not found.")
    if action == "approve":
        if user.id == tb.uploaded_by:
            raise Refused("The person who uploaded the trial balance cannot approve its mappings.")
        proposal = _proposal(row)
        if row.status == "REJECTED":
            # A rejected needs-evidence account still needs its evidence.
            from dataclasses import replace
            proposal = replace(proposal, status=mapping.NEEDS_EVIDENCE if row.evidence_required else mapping.SUGGESTED)
        try:
            decided = mapping.approve(proposal, reviewer=user.id, line_id=line_id, evidence_ref=evidence_ref,
                                      allocations=[(l, _decimal(a)) for l, a in allocations] if allocations else None)
        except mapping.MappingError as error:
            raise Refused(str(error)) from None
        row.status, row.line_id, row.basis = decided.status, decided.line_id, decided.basis
        row.allocations = [{"line_id": a.line_id, "amount": str(a.amount)} for a in decided.allocations]
    elif action == "reject":
        row.status, row.basis = "REJECTED", f"Rejected by reviewer: {reason or 'no reason given'}"
    else:
        raise Refused("The action is approve or reject.")
    row.evidence_ref, row.reviewer_id, row.decided_at = evidence_ref, user.id, _now()
    await _supersede_snapshots(db, tb, user, f"mapping changed: {row.account_name}")
    await _event(db, tb, user, f"mapping_{action}d" if action == "approve" else "mapping_rejected",
                 {"account": row.account_name, "line_id": row.line_id, "allocations": row.allocations,
                  "evidence_ref": evidence_ref, "reason": reason})
    await db.commit()
    return await detail(db, user, tb.id)


async def add_journal(db: AsyncSession, user, tb_id: str, *, kind: str, reason: str, lines: list[tuple[str, str, str]],
                      evidence_refs: list[str] | None = None, correction_type: str | None = None) -> dict:
    tb = await _tb(db, user, tb_id)
    _require_open(tb)
    try:
        proposal = journals_mod.propose_journal(
            kind=kind, reason=reason, created_by=user.id, evidence_refs=evidence_refs, correction_type=correction_type,
            lines=[(l, _decimal(dr), _decimal(cr)) for l, dr, cr in lines])
    except journals_mod.JournalError as error:
        raise Refused(str(error)) from None
    maps, *_ = await _children(db, tb)
    effect = journals_mod.simulate([_proposal(m) for m in maps], proposal)
    if (await db.get(FsJournal, proposal.journal_id)) is not None:
        raise Refused("The same journal has already been proposed.")
    db.add(FsJournal(id=proposal.journal_id, tenant_id=tb.tenant_id, trial_balance_id=tb.id, kind=proposal.kind,
                     correction_type=proposal.correction_type, reason=proposal.reason,
                     lines=[{"line_id": l.line_id, "debit": str(l.debit), "credit": str(l.credit)} for l in proposal.lines],
                     evidence_refs=list(proposal.evidence_refs), created_by=user.id))
    await _supersede_snapshots(db, tb, user, "journal proposed")
    await _event(db, tb, user, "journal_proposed", {"journal_id": proposal.journal_id, "kind": kind,
                                                    "correction_type": proposal.correction_type, "effect": effect})
    await db.commit()
    return {**(await detail(db, user, tb.id)), "effect": effect}


async def review_journal(db: AsyncSession, user, tb_id: str, journal_id: str, *, approve: bool) -> dict:
    tb = await _tb(db, user, tb_id)
    _require_open(tb)
    row = (await db.execute(select(FsJournal).where(FsJournal.id == journal_id,
                                                     FsJournal.trial_balance_id == tb.id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Journal not found.")
    try:
        reviewed = journals_mod.review_journal(_journal(row), reviewer=user.id, approve=approve)
    except journals_mod.JournalError as error:
        raise Refused(str(error)) from None
    row.review_status, row.reviewer_id, row.reviewed_at = reviewed.review_status, user.id, _now()
    await _supersede_snapshots(db, tb, user, f"journal {journal_id} reviewed")
    await _event(db, tb, user, "journal_reviewed", {"journal_id": journal_id, "decision": reviewed.review_status,
                                                    "posting_status": row.posting_status})
    await db.commit()
    return await detail(db, user, tb.id)


async def add_supporting(db: AsyncSession, user, tb_id: str, *, kind: str, filename: str, content: bytes) -> dict:
    tb = await _tb(db, user, tb_id)
    _require_open(tb)
    if kind not in supporting.KINDS:
        raise Refused(f"The supporting record is one of: {', '.join(supporting.KINDS)}.")
    total, findings = supporting.total_of(kind, filename, content)
    maps, *_ = await _children(db, tb)
    # The current classification of each account, approved or suggested.
    lines: dict[str, Decimal] = {}
    for m in maps:
        if m.line_id:
            lines[m.line_id] = lines.get(m.line_id, Decimal("0")) + _decimal(m.balance)
    result = findings[0] if findings else supporting.reconcile(kind, total, lines)
    db.add(FsSupportingRecord(tenant_id=tb.tenant_id, trial_balance_id=tb.id, kind=kind, filename=filename,
                              sha256=total.sha256, total=str(total.total) if total.total is not None else None,
                              basis=total.basis, finding=result.to_dict(), uploaded_by=user.id))
    await _supersede_snapshots(db, tb, user, f"supporting record added: {filename}")
    await _event(db, tb, user, "supporting_added", {"kind": kind, "filename": filename, "result": result.code})
    await db.commit()
    return await detail(db, user, tb.id)


async def approve(db: AsyncSession, user, tb_id: str) -> dict:
    tb = await _tb(db, user, tb_id)
    _require_open(tb)
    maps, jnls, sups, snaps, _ = await _children(db, tb)
    if any(s.status == "APPROVED" for s in snaps):
        raise Refused("This trial balance is already approved.")
    try:
        snapshot = workflow.approve_snapshot(
            source_sha256=tb.sha256, tb=list(tb.lines), findings=_all_findings(tb, sups),
            mappings=[_proposal(m) for m in maps], journals=[_journal(j) for j in jnls],
            preparer=tb.uploaded_by, approver=user.id)
    except workflow.ApprovalError as error:
        raise Refused(str(error)) from None
    db.add(FsSnapshot(id=f"{snapshot.snapshot_id}-{tb.id[:8]}", tenant_id=tb.tenant_id, trial_balance_id=tb.id,
                      content_hash=snapshot.content_hash, line_totals=snapshot.line_totals,
                      preparer_id=tb.uploaded_by, approver_id=user.id))
    await _event(db, tb, user, "snapshot_approved", {"content_hash": snapshot.content_hash})
    await db.commit()
    return await detail(db, user, tb.id)


async def lineage(db: AsyncSession, user, tb_id: str, account_key: str) -> dict:
    """SD-020 / AT-31: an account from its source rows to its statement line."""
    tb = await _tb(db, user, tb_id)
    maps, jnls, _, snaps, _ = await _children(db, tb)
    row = next((m for m in maps if m.account_key == account_key), None)
    if row is None:
        raise NotFound("Account not found.")
    lines_used = {row.line_id, *(a["line_id"] for a in row.allocations or ())} - {None}
    return {
        "account_key": account_key, "account_name": row.account_name, "balance": row.balance,
        "source_rows": [l for l in tb.lines if l.get("key") == account_key],
        "source_file": {"filename": tb.filename, "sha256": tb.sha256, "version": tb.version},
        "mapping": {"status": row.status, "line_id": row.line_id, "allocations": row.allocations, "basis": row.basis,
                    "reviewer_id": row.reviewer_id, "evidence_ref": row.evidence_ref},
        "journals": [_journal(j).to_dict() for j in jnls if lines_used & {l["line_id"] for l in j.lines}],
        "snapshot": next(({"id": s.id, "status": s.status, "content_hash": s.content_hash} for s in reversed(snaps)), None),
    }


async def original(db: AsyncSession, user, tb_id: str) -> tuple[str, str, bytes]:
    tb = await _tb(db, user, tb_id)
    return tb.filename, tb.media_type, tb.original

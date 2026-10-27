"""Stored report packages (Document 05 §16 services, §16.1 states, §17.1
four-stage sign-off).

A package is built from an APPROVED Document 04 snapshot and a Document 03
resolution; each input set has a fingerprint. Notes, exemption decisions and
reviewer dispositions are inputs too. A change before any sign-off updates
the version; a change after a sign-off makes a new version and the old one
is kept, superseded (AT-18, AT-25). A package whose upstream snapshot,
resolution or rule set has moved on reads as INVALIDATED and cannot be
signed or exported (AS-008, AT-30).

Sign-off order: preparer (the builder) → technical reviewer and disclosure
owner (not the preparer) → authorised issuer (not the preparer or the
technical reviewer). Issuing or filing belongs to Documents 06 and 07.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async

from . import assembly, resolutions, supporting
from .assembly import RULESET, PackageInputs, Snapshot
from .models import FsJournal, FsReportPackage, FsResolution, FsSnapshot, FsSupportingRecord
from .store import NotFound, Refused, _tb

ROLES = ("preparer", "technical_reviewer", "disclosure_owner", "issuer")
DECISIONS = ("include", "not_applicable", "exempt")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── loading the upstream decisions ──────────────────────────────────────────

async def _snapshot(db: AsyncSession, user, tb_id: str) -> Snapshot:
    tb = await _tb(db, user, tb_id)
    approved = (await db.execute(select(FsSnapshot).where(
        FsSnapshot.trial_balance_id == tb.id, FsSnapshot.tenant_id == tb.tenant_id, FsSnapshot.status == "APPROVED")
        .order_by(FsSnapshot.approved_at.desc()))).scalars().first()
    if approved is None or tb.superseded_by:
        return Snapshot(trial_balance_id=tb.id, content_hash=f"unapproved:{tb.sha256}", approved=False, line_totals={},
                        period_end=tb.period_end, units=tb.units, findings=tuple(tb.findings or ()))
    journals = (await db.execute(select(FsJournal).where(
        FsJournal.trial_balance_id == tb.id, FsJournal.review_status == "APPROVED"))).scalars().all()
    records = (await db.execute(select(FsSupportingRecord).where(FsSupportingRecord.trial_balance_id == tb.id)
                                .order_by(FsSupportingRecord.created_at))).scalars().all()
    support = {}
    for r in records:                                   # the latest record of each kind
        line_id = supporting.KINDS.get(r.kind, (None,))[0]
        if line_id:
            support[line_id] = {"kind": r.kind, "total": r.total,
                                "agreed": (r.finding or {}).get("code") == "SUPPORTING_AGREED"}
    return Snapshot(trial_balance_id=tb.id, content_hash=approved.content_hash, approved=True,
                    line_totals=dict(approved.line_totals or {}),
                    journals=tuple({"journal_id": j.id, "correction_type": j.correction_type, "lines": j.lines}
                                   for j in journals),
                    period_end=tb.period_end, units=tb.units, supporting=support, findings=tuple(tb.findings or ()))


async def _resolution(db: AsyncSession, user, resolution_id: str | None) -> dict | None:
    return await resolutions.get(db, user, resolution_id) if resolution_id else None


async def _inputs(db: AsyncSession, user, row_or_args: dict) -> PackageInputs:
    a = row_or_args
    return PackageInputs(
        snapshot=await _snapshot(db, user, a["trial_balance_id"]),
        resolution=await _resolution(db, user, a.get("resolution_id")),
        prior=await _snapshot(db, user, a["prior_trial_balance_id"]) if a.get("prior_trial_balance_id") else None,
        schedules=dict(a.get("schedules") or {}), disclosures=dict(a.get("disclosures") or {}),
        dispositions=dict(a.get("dispositions") or {}))


def _args(row: FsReportPackage) -> dict:
    return {"trial_balance_id": row.trial_balance_id, "prior_trial_balance_id": row.prior_trial_balance_id,
            "resolution_id": row.resolution_id, **(row.inputs or {})}


# ── views ───────────────────────────────────────────────────────────────────

async def _stale(db: AsyncSession, user, row: FsReportPackage) -> list[str]:
    """Why this package no longer reflects its approved inputs (AS-008)."""
    reasons = []
    source = (row.result or {}).get("source", {})
    current = await _snapshot(db, user, row.trial_balance_id)
    if current.content_hash != source.get("snapshot_hash"):
        reasons.append("The trial-balance snapshot changed or is no longer approved.")
    if row.prior_trial_balance_id:
        prior = await _snapshot(db, user, row.prior_trial_balance_id)
        if prior.content_hash != source.get("prior_snapshot_hash"):
            reasons.append("The prior-period snapshot changed or is no longer approved.")
    profile = (row.result or {}).get("profile", {})
    if row.resolution_id:
        res = await db.get(FsResolution, row.resolution_id)
        if res is None or res.state != profile.get("resolution_state") or res.revision != profile.get("resolution_revision"):
            reasons.append("The Document 03 resolution changed state or revision.")
    if (profile.get("ruleset") or {}).get("version") != RULESET["version"]:
        reasons.append("The assembly and disclosure rule set was updated; affected notes and approvals must be "
                       "re-validated.")
    return reasons


async def _view(db: AsyncSession, user, row: FsReportPackage) -> dict:
    stale = [] if row.superseded_by else await _stale(db, user, row)
    state = "SUPERSEDED" if row.superseded_by else "INVALIDATED" if stale else row.state
    return {"id": row.id, "version": row.version, "state": state, "stored_state": row.state, "stale_reasons": stale,
            "trial_balance_id": row.trial_balance_id, "prior_trial_balance_id": row.prior_trial_balance_id,
            "resolution_id": row.resolution_id, "inputs": row.inputs, "fingerprint": row.fingerprint,
            "result": row.result, "signoffs": row.signoffs or {}, "history": row.history or [],
            "created_by": row.created_by, "superseded_by": row.superseded_by,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _record(db, row: FsReportPackage, user, action: str, detail: dict) -> None:
    row.history = [*(row.history or []), {"action": action, "actor_id": user.id, "at": _now().isoformat(),
                                          "version": row.version, "detail": detail}]
    await record_event_async(db, tenant_id=row.tenant_id, event_name=f"financial_statements.package_{action}",
                             emitting_service="financial_statements", actor_id=user.id,
                             subject_type="report_package", subject_id=row.id, payload=detail)


async def _get(db: AsyncSession, user, package_id: str) -> FsReportPackage:
    row = await db.get(FsReportPackage, package_id)
    if row is not None and row.tenant_id != user.tenant_id:
        # AT-29: another tenant's package is denied and the attempt is logged.
        await record_event_async(db, tenant_id=user.tenant_id, event_name="financial_statements.package_access_denied",
                                 emitting_service="financial_statements", actor_id=user.id,
                                 subject_type="report_package", subject_id=package_id, payload={"reason": "cross_tenant"})
        await db.commit()
        row = None
    if row is None:
        raise NotFound("Report package not found.")
    return row


async def _current(db: AsyncSession, user, package_id: str) -> FsReportPackage:
    row = await _get(db, user, package_id)
    if row.superseded_by:
        raise Refused("This version was superseded; work on the current version.")
    return row


# ── commands ────────────────────────────────────────────────────────────────

async def build(db: AsyncSession, user, *, trial_balance_id: str, resolution_id: str | None = None,
                prior_trial_balance_id: str | None = None, schedules: dict | None = None) -> dict:
    await _tb(db, user, trial_balance_id)
    if prior_trial_balance_id:
        if prior_trial_balance_id == trial_balance_id:
            raise Refused("The prior period cannot be the same trial balance (AT-22).")
        await _tb(db, user, prior_trial_balance_id)
    if resolution_id:
        await resolutions.get(db, user, resolution_id)
    current = (await db.execute(select(FsReportPackage).where(
        FsReportPackage.tenant_id == user.tenant_id, FsReportPackage.trial_balance_id == trial_balance_id,
        FsReportPackage.superseded_by.is_(None)).order_by(FsReportPackage.version.desc()))).scalars().first()
    carried = dict(current.inputs or {}) if current else {}
    args = {"trial_balance_id": trial_balance_id, "prior_trial_balance_id": prior_trial_balance_id,
            "resolution_id": resolution_id, "schedules": {k: str(v) for k, v in (schedules or {}).items() if v not in (None, "")},
            "disclosures": carried.get("disclosures", {}), "dispositions": carried.get("dispositions", {})}
    inputs = await _inputs(db, user, args)
    if current is not None and (current.result or {}).get("source", {}).get("snapshot_hash") != inputs.snapshot.content_hash:
        # New source figures: earlier note approvals and dispositions no longer apply (AT-30).
        args["disclosures"] = {k: {**v, "approved_by": None} for k, v in args["disclosures"].items()}
        args["dispositions"] = {}
        inputs = await _inputs(db, user, args)
    result = assembly.assemble(inputs)
    if current is not None and current.fingerprint == result["fingerprint"] and not await _stale(db, user, current):
        return await _view(db, user, current)           # same inputs, same package (§5 idempotent)
    stored = {k: args[k] for k in ("schedules", "disclosures", "dispositions")}
    if current is not None and not current.signoffs:
        current.prior_trial_balance_id, current.resolution_id = prior_trial_balance_id, resolution_id
        current.inputs, current.result, current.fingerprint, current.state = stored, result, result["fingerprint"], result["state"]
        await _record(db, current, user, "rebuilt", {"state": result["state"], "counts": result["counts"]})
        await db.commit()
        return await _view(db, user, current)
    row = FsReportPackage(tenant_id=user.tenant_id, trial_balance_id=trial_balance_id,
                          prior_trial_balance_id=prior_trial_balance_id, resolution_id=resolution_id,
                          version=(current.version + 1) if current else 1, inputs=stored, fingerprint=result["fingerprint"],
                          result=result, state=result["state"], signoffs={}, history=[], created_by=user.id)
    db.add(row)
    await db.flush()
    if current is not None:
        current.superseded_by = row.id
        await _record(db, current, user, "superseded", {"by_version": row.version, "signoffs_invalidated": list(current.signoffs)})
    await _record(db, row, user, "assembled", {"state": result["state"], "counts": result["counts"],
                                               "fingerprint": result["fingerprint"]})
    await db.commit()
    return await _view(db, user, row)


async def _change(db: AsyncSession, user, row: FsReportPackage, inputs: dict, action: str, detail: dict) -> dict:
    """Apply an input change: in place before sign-off, as a new version after (AT-18)."""
    args = {**_args(row), **inputs}
    result = assembly.assemble(await _inputs(db, user, args))
    stored = {k: args.get(k, {}) for k in ("schedules", "disclosures", "dispositions")}
    if not row.signoffs:
        row.inputs, row.result, row.fingerprint, row.state = stored, result, result["fingerprint"], result["state"]
        await _record(db, row, user, action, detail)
        await db.commit()
        return await _view(db, user, row)
    new = FsReportPackage(tenant_id=row.tenant_id, trial_balance_id=row.trial_balance_id,
                          prior_trial_balance_id=row.prior_trial_balance_id, resolution_id=row.resolution_id,
                          version=row.version + 1, inputs=stored, fingerprint=result["fingerprint"], result=result,
                          state=result["state"], signoffs={}, history=[], created_by=row.created_by)
    db.add(new)
    await db.flush()
    row.superseded_by = new.id
    await _record(db, row, user, "superseded", {"by_version": new.version, "signoffs_invalidated": list(row.signoffs)})
    await _record(db, new, user, action, detail)
    await db.commit()
    return await _view(db, user, new)


async def submit_disclosure(db: AsyncSession, user, package_id: str, *, requirement_id: str, decision: str,
                            text: str = "", evidence_ref: str = "", rationale: str = "") -> dict:
    row = await _current(db, user, package_id)
    if requirement_id not in {r.rid for r in assembly.REQUIREMENTS}:
        raise Refused(f"'{requirement_id}' is not a disclosure requirement.")
    if decision not in DECISIONS:
        raise Refused("The decision is include, not_applicable or exempt.")
    disclosures = dict((row.inputs or {}).get("disclosures") or {})
    # Stored verbatim as data; it is checked, never followed (AT-28).
    disclosures[requirement_id] = {"decision": decision, "text": text, "evidence_ref": evidence_ref.strip(),
                                   "rationale": rationale, "submitted_by": user.id, "approved_by": None,
                                   "at": _now().isoformat()}
    return await _change(db, user, row, {"disclosures": disclosures}, "disclosure_submitted",
                         {"requirement_id": requirement_id, "decision": decision, "evidence_ref": evidence_ref})


async def approve_disclosure(db: AsyncSession, user, package_id: str, requirement_id: str) -> dict:
    row = await _current(db, user, package_id)
    disclosures = dict((row.inputs or {}).get("disclosures") or {})
    sub = disclosures.get(requirement_id)
    if not sub:
        raise Refused("Nothing has been submitted for this note.")
    if sub.get("submitted_by") == user.id:
        raise Refused("The author of a note cannot approve it; a disclosure owner does (AS-043).")
    if sub.get("approved_by"):
        raise Refused("This note is already approved.")
    disclosures[requirement_id] = {**sub, "approved_by": user.id}
    return await _change(db, user, row, {"disclosures": disclosures}, "disclosure_approved", {"requirement_id": requirement_id})


async def dispose(db: AsyncSession, user, package_id: str, *, code: str, reason: str) -> dict:
    """A reviewer's disposition of a P2 review item (§17); P0 and P1 cannot be waived."""
    row = await _current(db, user, package_id)
    finding = next((f for f in (row.result or {}).get("findings", []) if f["code"] == code), None)
    if finding is None:
        raise Refused("No such finding on this package.")
    if finding["severity"] != "P2":
        raise Refused(f"A {finding['severity']} finding cannot be waived; it must be resolved at source.")
    if user.id == row.created_by:
        raise Refused("The preparer cannot dispose of their own review items.")
    if not reason.strip():
        raise Refused("A disposition needs a reason.")
    dispositions = {**((row.inputs or {}).get("dispositions") or {}),
                    code: {"by": user.id, "reason": reason.strip(), "at": _now().isoformat()}}
    return await _change(db, user, row, {"dispositions": dispositions}, "finding_disposed", {"code": code, "reason": reason})


async def sign(db: AsyncSession, user, package_id: str, role: str) -> dict:
    row = await _current(db, user, package_id)
    if role not in ROLES:
        raise Refused(f"The sign-off role is one of: {', '.join(ROLES)}.")
    stale = await _stale(db, user, row)
    if stale:
        raise Refused("The package is out of date: " + " ".join(stale) + " Rebuild it.")
    if not row.result.get("ready_for_signoff"):
        raise Refused("Not ready for sign-off: open P0/P1 findings, open notes or undisposed review items remain.")
    signed = dict(row.signoffs or {})
    if role in signed:
        raise Refused(f"The {role.replace('_', ' ')} has already signed this version.")
    if role == "preparer" and user.id != row.created_by:
        raise Refused("The preparer sign-off belongs to the person who built the package.")
    if role != "preparer":
        if "preparer" not in signed:
            raise Refused("The preparer signs first.")
        if user.id == row.created_by:
            raise Refused("The preparer cannot also review or issue the package (§17.1).")
    if role == "issuer":
        if not {"technical_reviewer", "disclosure_owner"} <= set(signed):
            raise Refused("The technical reviewer and the disclosure owner sign before the issuer.")
        if signed["technical_reviewer"]["by"] == user.id:
            raise Refused("The technical reviewer cannot also be the authorised issuer.")
    signed[role] = {"by": user.id, "at": _now().isoformat()}
    row.signoffs = signed
    if role == "issuer":
        row.state = "APPROVED"
    elif {"technical_reviewer", "disclosure_owner"} <= set(signed):
        row.state = "REVIEWED"
    await _record(db, row, user, "signed", {"role": role, "state": row.state})
    await db.commit()
    return await _view(db, user, row)


async def release_check(db: AsyncSession, user, package_id: str) -> dict:
    row = await _get(db, user, package_id)
    view = await _view(db, user, row)
    reasons = list(view["stale_reasons"])
    if view["state"] != "APPROVED":
        reasons.append(f"The package is {view['state'].replace('_', ' ').lower()}, not approved by all four sign-offs.")
    reasons += row.result.get("release_reasons", [])
    if row.resolution_id:
        upstream = await resolutions.release_check(db, user, row.resolution_id)
        reasons += upstream["reasons"]
    else:
        reasons.append("No Document 03 resolution is attached.")
    return {"package_id": row.id, "version": row.version, "statutory_release_allowed": not reasons,
            "draft_allowed": True, "reasons": list(dict.fromkeys(reasons)), "fingerprint": row.fingerprint}


async def export(db: AsyncSession, user, package_id: str, fmt: str) -> tuple[str, str, str]:
    row = await _get(db, user, package_id)
    if await _stale(db, user, row):
        raise Refused("The package is out of date; rebuild it before exporting.")
    from .workspace import misleading_reasons
    misleading = misleading_reasons(row.result or {})
    if misleading:
        raise Refused("Even a watermarked draft would be materially misleading: " + " ".join(misleading))
    check = await release_check(db, user, package_id)
    try:
        media, body = assembly.export(row.result, fmt, package_id=row.id, version=row.version,
                                      statutory=check["statutory_release_allowed"])
    except ValueError as error:
        raise Refused(str(error)) from None
    await _record(db, row, user, "exported", {"format": fmt, "watermarked": not check["statutory_release_allowed"]})
    await db.commit()
    return media, body, f"report-package-v{row.version}.{fmt}"


async def get(db: AsyncSession, user, package_id: str) -> dict:
    return await _view(db, user, await _get(db, user, package_id))


async def list_for(db: AsyncSession, user) -> list[dict]:
    rows = (await db.execute(select(FsReportPackage).where(FsReportPackage.tenant_id == user.tenant_id)
                             .order_by(FsReportPackage.created_at.desc()))).scalars().all()
    return [{"id": r.id, "version": r.version, "state": "SUPERSEDED" if r.superseded_by else r.state,
             "trial_balance_id": r.trial_balance_id, "resolution_id": r.resolution_id,
             "entity": (r.result or {}).get("profile", {}).get("entity", ""),
             "counts": (r.result or {}).get("counts", {}),
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

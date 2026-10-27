"""Stored assurance: runs, the finding register, decisions, evidence,
materiality, attestations and the release certificate (Document 07 §8, §10,
§11).

Every state transition is checked on the server (QA-025). Decisions are
appended to a hash-chained ledger (QA-010, QA-043) and never erased; a
finding that stops arising is closed by the re-run with an event (QA-036).
Any change to evidence, materiality or misstatements re-runs the controls
and makes a new run, so earlier attestations stop applying (QA-022,
QA-026, QA-028). Overrides of quality gates and unsupported claims are
refused and logged (T26, T28, T32).
"""
from __future__ import annotations

import hashlib
import mimetypes
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User

from . import assurance, packages, resolutions, store
from .intake import MAX_BYTES
from .models import FsAssuranceCase, FsAssuranceRun, FsEvidenceItem, FsReportPackage
from .store import NotFound, Refused

DECISIONS = ("accept_treatment", "request_evidence", "document_na", "escalate", "waive", "withdraw")
DOMAINS = tuple(d[0] for d in assurance.RISK_DOMAINS)
ATTESTATION_ORDER = ("preparer", "independent_reviewer", "officer")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _event(db, tenant_id: str, user, action: str, subject_id: str, detail: dict) -> None:
    await record_event_async(db, tenant_id=tenant_id, event_name=f"financial_statements.assurance_{action}",
                             emitting_service="financial_statements", actor_id=user.id,
                             subject_type="assurance_run", subject_id=subject_id, payload=detail)


async def _active(db, user_id: str | None) -> bool:
    person = await db.get(User, user_id) if user_id else None
    return bool(person and person.is_active)


def _ledger_append(case: FsAssuranceCase, entry: dict) -> dict:
    """Append-only, each entry carrying the previous entry's hash (QA-010)."""
    previous = case.ledger[-1]["hash"] if case.ledger else "genesis"
    body = {**entry, "at": _now().isoformat(), "previous_event_hash": previous}
    body["hash"] = assurance.digest(body)
    case.ledger = [*case.ledger, body]
    return body


# ── loading ─────────────────────────────────────────────────────────────────

async def _package_row(db, user, package_id: str) -> FsReportPackage:
    await packages.get(db, user, package_id)               # tenant check and cross-tenant logging
    return await db.get(FsReportPackage, package_id)


async def _case(db, user, package_row: FsReportPackage) -> FsAssuranceCase:
    case = (await db.execute(select(FsAssuranceCase).where(
        FsAssuranceCase.tenant_id == user.tenant_id,
        FsAssuranceCase.trial_balance_id == package_row.trial_balance_id))).scalars().first()
    if case is None:
        case = FsAssuranceCase(tenant_id=user.tenant_id, trial_balance_id=package_row.trial_balance_id, materiality={},
                               register={}, ledger=[], misstatements=[])
        db.add(case)
        await db.flush()
    return case


async def _evidence(db, case: FsAssuranceCase) -> list[dict]:
    rows = (await db.execute(select(FsEvidenceItem).where(FsEvidenceItem.case_id == case.id)
                             .order_by(FsEvidenceItem.created_at))).scalars().all()
    return [{"id": e.id, "filename": e.filename, "sha256": e.sha256, "size_bytes": e.size_bytes, "description": e.description,
             "domains": e.domains or [], "instruction_flag": bool(e.instruction_flag), "uploaded_by": e.uploaded_by,
             "created_at": e.created_at.isoformat() if e.created_at else None,
             "withdrawn_at": e.withdrawn_at.isoformat() if e.withdrawn_at else None, "withdrawn_reason": e.withdrawn_reason}
            for e in rows]


async def _get_run(db, user, run_id: str) -> FsAssuranceRun:
    row = await db.get(FsAssuranceRun, run_id)
    if row is not None and row.tenant_id != user.tenant_id:
        await record_event_async(db, tenant_id=user.tenant_id, event_name="financial_statements.assurance_access_denied",
                                 emitting_service="financial_statements", actor_id=user.id, subject_type="assurance_run",
                                 subject_id=run_id, payload={"reason": "cross_tenant"})       # T24
        await db.commit()
        row = None
    if row is None:
        raise NotFound("Assurance run not found.")
    return row


async def _inputs(db, user, package_row: FsReportPackage, case: FsAssuranceCase):
    package = await packages.get(db, user, package_row.id)
    tb = await store.detail(db, user, package_row.trial_balance_id)
    resolution = await resolutions.get(db, user, package_row.resolution_id) if package_row.resolution_id else None
    evidence = await _evidence(db, case)
    input_hash = assurance.digest({
        "package": [package["id"], package["version"], package["fingerprint"], package["stale_reasons"]],
        "resolution": [(resolution or {}).get(k) for k in ("id", "revision", "state", "rule_pack_digest")],
        "evidence": [[e["id"], e["sha256"], e["withdrawn_at"], e["domains"]] for e in evidence],
        "materiality": case.materiality, "misstatements": case.misstatements, "ruleset": assurance.RULESET})
    return package, tb, resolution, evidence, input_hash


# ── views ───────────────────────────────────────────────────────────────────

async def _view(db, user, row: FsAssuranceRun) -> dict:
    case = await db.get(FsAssuranceCase, row.case_id)
    package = await packages.get(db, user, row.package_id)
    resolution = await resolutions.get(db, user, package["resolution_id"]) if package["resolution_id"] else None
    findings, merged = assurance.merge_register(row.result.get("findings", []), case.register or {})
    open_ = assurance.open_items(findings, date.today().isoformat())
    result_pkg = package["result"]
    state = assurance.status(ingested=not result_pkg.get("halted"), scope_resolved=(resolution or {}).get("state") == "FROZEN",
                             open_=open_, attestations=row.attestations or {}, released=bool(row.certificate),
                             superseded=bool(row.superseded_by))
    claim_rows = assurance.claims(result=result_pkg, resolution=resolution, findings=findings, open_=open_,
                                  attestations=row.attestations or {})
    return {"id": row.id, "package_id": row.package_id, "package_version": row.package_version, "status": state,
            "input_hash": row.input_hash, "snapshot_hash": result_pkg.get("source", {}).get("snapshot_hash"),
            "standards_profile_hash": (resolution or {}).get("rule_pack_digest"), "ruleset": assurance.RULESET,
            "header": {"tenant_id": row.tenant_id, "entity": result_pkg["profile"].get("entity"),
                       "period_start": result_pkg["profile"].get("period_start"), "period_end": result_pkg["profile"].get("period_end"),
                       "framework": result_pkg["profile"].get("framework"), "edition": result_pkg["profile"].get("edition"),
                       "scope": result_pkg["profile"].get("scope"),
                       "statements": [s["statement_id"] for s in result_pkg.get("statements", [])]},
            "result": row.result, "findings": findings, "closed_findings": merged["closed"], "open": open_,
            "attestations": row.attestations or {}, "certificate": row.certificate, "claims": claim_rows,
            "control_statement": assurance.control_statement(package=package, resolution=resolution, state=state,
                                                             open_=open_, claim_rows=claim_rows,
                                                             evidence_scope=row.result.get("evidence_scope", "")),
            "materiality": case.materiality, "misstatements": case.misstatements, "ledger": case.ledger,
            "evidence": await _evidence(db, case), "preparer": package["created_by"],
            "superseded_by": row.superseded_by, "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None}


# ── run ─────────────────────────────────────────────────────────────────────

async def run(db: AsyncSession, user, package_id: str) -> dict:
    row = await _package_row(db, user, package_id)
    if row.superseded_by:
        raise Refused("This package version was superseded; run assurance on the current version.")
    case = await _case(db, user, row)
    package, tb, resolution, evidence, input_hash = await _inputs(db, user, row, case)
    latest = (await db.execute(select(FsAssuranceRun).where(
        FsAssuranceRun.case_id == case.id, FsAssuranceRun.superseded_by.is_(None))
        .order_by(FsAssuranceRun.created_at.desc()))).scalars().first()
    if latest is not None and latest.input_hash == input_hash and latest.package_id == package_id:
        return await _view(db, user, latest)                # idempotent
    result = assurance.evaluate(package=package, tb=tb, resolution=resolution, evidence=evidence,
                                materiality=case.materiality, misstatements=case.misstatements)
    _, merged = assurance.merge_register(result["findings"], case.register or {})
    for closed in merged["closed"]:
        if (case.register or {}).get(closed["key"], {}).get("state") != "CLOSED_BY_RERUN":
            _ledger_append(case, {"type": "closed_by_rerun", "finding_key": closed["key"], "actor_id": user.id,
                                  "rationale": "The finding no longer arises from the current inputs."})
    case.register = merged["register"]
    new = FsAssuranceRun(tenant_id=user.tenant_id, case_id=case.id, package_id=package_id, package_version=package["version"],
                         input_hash=input_hash, result=result, attestations={}, created_by=user.id)
    db.add(new)
    await db.flush()
    if latest is not None:
        latest.superseded_by = new.id
        await _event(db, user.tenant_id, user, "superseded", latest.id, {"by": new.id,
                                                                         "attestations_invalidated": list(latest.attestations or {})})
    await _event(db, user.tenant_id, user, "run", new.id, {"package_id": package_id, "input_hash": input_hash,
                                                           "findings": len(result["findings"])})
    await db.commit()
    return await _view(db, user, new)


async def _current_run(db, user, run_id: str) -> FsAssuranceRun:
    row = await _get_run(db, user, run_id)
    if row.superseded_by:
        raise Refused("This run was superseded by a newer one after an input changed; use the current run.")
    if row.certificate:
        raise Refused("This run is released; its base cannot change. A change needs a new package version.")
    return row


# ── decisions (QA-007, QA-017, QA-018, QA-037, QA-038) ──────────────────────

async def decide(db: AsyncSession, user, run_id: str, *, finding_key: str, decision: str, rationale: str = "",
                 citation: str = "", alternatives: list[str] | None = None, evidence_id: str | None = None,
                 expires: str = "", owner: str = "", due: str = "") -> dict:
    row = await _current_run(db, user, run_id)
    if decision not in DECISIONS:
        raise Refused(f"The decision is one of: {', '.join(DECISIONS)}.")
    if row.attestations:
        raise Refused("Attestations exist on this run; a change of judgement needs a re-run and fresh attestations (QA-028).")
    finding = next((f for f in row.result.get("findings", []) if f["key"] == finding_key), None)
    if finding is None:
        raise Refused("No such finding on this run.")
    if not await _active(db, user.id):
        raise Refused("Your authorisation is not active (T23).")
    package = await packages.get(db, user, row.package_id)
    tb = await store.detail(db, user, package["trial_balance_id"])
    preparers = {package["created_by"], tb["uploaded_by"]}
    severity = finding["severity"]
    judging = decision in ("accept_treatment", "document_na", "waive", "withdraw")
    if judging and user.id in preparers:
        raise Refused("The preparer cannot decide their own finding (maker-checker, QA-007).")
    if judging and severity in assurance.UNWAIVABLE:
        raise Refused(f"A {severity} finding is resolved at source and re-run, never accepted, waived or withdrawn here.")
    if decision in ("accept_treatment", "waive") and severity == "MATERIAL" and user.role not in assurance.TECHNICAL_ROLES:
        raise Refused("A material finding needs a technical accounting lead (" + ", ".join(assurance.TECHNICAL_ROLES) + ").")
    alternatives = [a.strip() for a in alternatives or [] if a.strip()]
    if decision == "accept_treatment" and (not rationale.strip() or not citation.strip() or not alternatives):
        raise Refused("Accepting a treatment needs the rationale, the authoritative citation and the alternatives rejected (QA-017).")
    if decision == "document_na":
        items = {e["id"]: e for e in await _evidence(db, await db.get(FsAssuranceCase, row.case_id))}
        if not rationale.strip() or evidence_id not in items or items[evidence_id]["withdrawn_at"]:
            raise Refused("'Not applicable' needs a rationale and active evidence (QA-037).")
    if decision == "waive":
        try:
            expiry = date.fromisoformat(expires)
        except ValueError:
            raise Refused("A waiver needs an expiry date (YYYY-MM-DD) (QA-018).") from None
        if expiry <= date.today() or not rationale.strip():
            raise Refused("A waiver needs a justification and a future expiry date (QA-018).")
    if decision == "withdraw" and not rationale.strip():
        raise Refused("Withdrawing a finding needs a reason; it stays in the register (QA-036).")
    if decision == "request_evidence" and (not owner.strip() or not due.strip()):
        raise Refused("An evidence request needs an owner and a due date (QA-038).")
    case = await db.get(FsAssuranceCase, row.case_id)
    entry = _ledger_append(case, {"type": "decision", "finding_key": finding_key, "decision": decision,
                                  "severity": severity, "rationale": rationale.strip(), "citation": citation.strip(),
                                  "alternatives": alternatives, "evidence_id": evidence_id, "expires": expires,
                                  "owner": owner.strip(), "due": due.strip(), "actor_id": user.id, "role": user.role})
    state = {"accept_treatment": "ACCEPTED", "document_na": "RESOLVED", "waive": "WAIVED", "withdraw": "WITHDRAWN",
             "escalate": "ESCALATED", "request_evidence": "OPEN"}[decision]
    current = (case.register or {}).get(finding_key, {})
    case.register = {**(case.register or {}), finding_key: {
        "state": state, "decisions": [*current.get("decisions", []), entry["hash"]],
        "waiver": {"by": user.id, "justification": rationale.strip(), "expires": expires} if decision == "waive" else current.get("waiver")}}
    await _event(db, row.tenant_id, user, "decision", row.id, {"finding_key": finding_key, "decision": decision})
    await db.commit()
    return await _view(db, user, row)


# ── inputs that re-run the controls ─────────────────────────────────────────

async def set_materiality(db: AsyncSession, user, package_id: str, *, overall: str, performance: str, trivial: str,
                          basis: str, qualitative: str = "") -> dict:
    row = await _package_row(db, user, package_id)
    if user.id == row.created_by or user.role not in assurance.TECHNICAL_ROLES:
        raise Refused("Materiality is approved by a technical accounting lead who did not prepare the package.")
    try:
        o, p, t = Decimal(overall), Decimal(performance), Decimal(trivial)
    except (InvalidOperation, TypeError):
        raise Refused("Materiality thresholds must be numbers.") from None
    if not (Decimal("0") < t < p <= o) or not basis.strip():
        raise Refused("Thresholds need 0 < trivial < performance ≤ overall, with the basis stated.")
    case = await _case(db, user, row)
    case.materiality = {"overall": str(o), "performance": str(p), "trivial": str(t), "basis": basis.strip(),
                        "qualitative": qualitative.strip(), "approved_by": user.id, "at": _now().isoformat()}
    _ledger_append(case, {"type": "materiality", "actor_id": user.id, **case.materiality})
    await db.commit()
    return await run(db, user, package_id)


async def record_misstatement(db: AsyncSession, user, package_id: str, *, amount: str, statement: str, description: str) -> dict:
    row = await _package_row(db, user, package_id)
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError):
        raise Refused("The misstatement amount must be a number (signed).") from None
    if user.id == row.created_by or not description.strip():
        raise Refused("A reviewer other than the preparer records a misstatement, with a description.")
    case = await _case(db, user, row)
    item = {"amount": str(value), "statement": statement, "description": description.strip(), "by": user.id,
            "at": _now().isoformat()}
    case.misstatements = [*case.misstatements, item]
    _ledger_append(case, {"type": "misstatement", "actor_id": user.id, **item})
    await db.commit()
    return await run(db, user, package_id)


async def add_evidence(db: AsyncSession, user, package_id: str, *, filename: str, content: bytes, description: str,
                       domains: list[str]) -> dict:
    row = await _package_row(db, user, package_id)
    if len(content) > MAX_BYTES:
        raise Refused("The file is larger than 20 MB.")
    unknown = [d for d in domains if d not in DOMAINS]
    if unknown or not domains:
        raise Refused(f"Link the evidence to one or more of: {', '.join(DOMAINS)}.")
    case = await _case(db, user, row)
    text = content[:200_000].decode("utf-8", errors="ignore")
    item = FsEvidenceItem(tenant_id=user.tenant_id, case_id=case.id, filename=filename,
                          sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                          media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream", content=content,
                          description=description.strip(), domains=sorted(set(domains)),
                          instruction_flag=int(assurance.instruction_like(text) or assurance.instruction_like(description)),
                          uploaded_by=user.id)
    db.add(item)
    await db.flush()
    _ledger_append(case, {"type": "evidence_added", "actor_id": user.id, "evidence_id": item.id, "sha256": item.sha256,
                          "domains": item.domains})
    await db.commit()
    return await run(db, user, package_id)


async def withdraw_evidence(db: AsyncSession, user, evidence_id: str, reason: str) -> dict:
    item = await db.get(FsEvidenceItem, evidence_id)
    if item is None or item.tenant_id != user.tenant_id:
        raise NotFound("Evidence not found.")
    if item.withdrawn_at:
        raise Refused("This evidence is already withdrawn.")
    if not reason.strip():
        raise Refused("Withdrawing evidence needs a reason.")
    item.withdrawn_at, item.withdrawn_by, item.withdrawn_reason = _now(), user.id, reason.strip()
    case = await db.get(FsAssuranceCase, item.case_id)
    _ledger_append(case, {"type": "evidence_withdrawn", "actor_id": user.id, "evidence_id": item.id, "reason": reason.strip()})
    await db.commit()
    latest = (await db.execute(select(FsAssuranceRun).where(FsAssuranceRun.case_id == case.id,
                                                            FsAssuranceRun.superseded_by.is_(None))
                               .order_by(FsAssuranceRun.created_at.desc()))).scalars().first()
    if latest is None:
        raise NotFound("No assurance run for this evidence.")
    return await run(db, user, latest.package_id)


# ── attestations and release (§3, §8, §9) ───────────────────────────────────

async def attest(db: AsyncSession, user, run_id: str, *, role: str, scope: str, approval_evidence_id: str | None = None) -> dict:
    row = await _current_run(db, user, run_id)
    view = await _view(db, user, row)
    if role not in ATTESTATION_ORDER:
        raise Refused(f"The attestation role is one of: {', '.join(ATTESTATION_ORDER)}.")
    signed = dict(row.attestations or {})
    if role in signed:
        raise Refused("That attestation is already recorded on this run.")
    if view["status"] not in ("QUALITY_PASSED", "REVIEW_APPROVED"):
        raise Refused(f"Attestations need QUALITY_PASSED; the run is {view['status']}.")
    position = ATTESTATION_ORDER.index(role)
    if any(r not in signed for r in ATTESTATION_ORDER[:position]):
        raise Refused("Attestations follow the ladder: preparer, then independent reviewer, then authorised officer.")
    forbidden = assurance.forbidden_claims(scope)
    if forbidden or not scope.strip():
        raise Refused("State the scope reviewed in plain terms; it may not claim " + (", ".join(forbidden) or "anything unstated")
                      + " (QA-012, QA-033).")
    if not await _active(db, user.id):
        raise Refused("Your authorisation is not active (T23).")
    preparer = view["preparer"]
    if role == "preparer" and user.id != preparer:
        raise Refused("The preparer attestation belongs to the person who prepared the package.")
    if role != "preparer" and user.id == preparer:
        raise Refused("The preparer cannot review or authorise their own package (QA-007).")
    if role == "independent_reviewer":
        decided = {e["actor_id"] for e in view["ledger"] if e.get("type") == "decision"
                   and e.get("decision") in ("accept_treatment", "waive")}
        if user.id in decided:
            raise Refused("You accepted or waived findings on this case; the independent review must be someone else (self-review).")
    if role == "officer":
        if user.role not in assurance.OFFICER_ROLES:
            raise Refused("A company director or authorised officer (" + ", ".join(assurance.OFFICER_ROLES) + ") authorises.")
        if signed["independent_reviewer"]["by"] == user.id:
            raise Refused("The independent reviewer cannot also be the authorising officer.")
        evidence = {e["id"]: e for e in view["evidence"]}
        if approval_evidence_id not in evidence or evidence[approval_evidence_id]["withdrawn_at"]:
            raise Refused("Attach the approval record (e.g. board minute) as evidence and reference it (QA-011).")
    signed[role] = {"by": user.id, "role_code": user.role, "scope": scope.strip(), "at": _now().isoformat(),
                    "auth_aal": getattr(user, "auth_aal", "aal1"), "input_hash": row.input_hash,
                    "snapshot_hash": view["snapshot_hash"], "approval_evidence_id": approval_evidence_id}
    row.attestations = signed
    await _event(db, row.tenant_id, user, "attested", row.id, {"role": role, "auth_aal": signed[role]["auth_aal"]})
    await db.commit()
    return await _view(db, user, row)


async def release(db: AsyncSession, user, run_id: str) -> dict:
    row = await _get_run(db, user, run_id)
    if row.certificate:
        return await _view(db, user, row)                  # idempotent (§11 POST release)
    row = await _current_run(db, user, run_id)
    view = await _view(db, user, row)
    if view["status"] != "AUTHORIZED":
        raise Refused(f"Release needs an AUTHORIZED run; this one is {view['status']}.")
    if user.id == view["preparer"]:
        raise Refused("The preparer cannot release the package.")
    package_row = await db.get(FsReportPackage, row.package_id)
    _, _, _, _, now_hash = await _inputs(db, user, package_row, await db.get(FsAssuranceCase, row.case_id))
    if now_hash != row.input_hash:
        raise Refused("An input changed after the attestations; re-run and attest again (QA-026).")
    for role, a in (row.attestations or {}).items():
        if not await _active(db, a["by"]):
            raise Refused(f"The {role.replace('_', ' ')}'s authorisation was revoked; the attestation no longer stands (T23).")
    package = await packages.get(db, user, row.package_id)
    resolution = await resolutions.get(db, user, package["resolution_id"]) if package["resolution_id"] else None
    statements = [[s["statement_id"], [[l["line_id"], l.get("amount"), l.get("prior")] for l in s.get("lines", [])]]
                  for s in package["result"].get("statements", [])]
    certificate = {
        "release_id": "rel-" + row.input_hash[7:23], "kind": "INTERNAL_QUALITY_RELEASE",
        "wording": "Internal quality status and the controls achieved below. This is not an audit opinion, an assurance "
                   "engagement, regulator acceptance or a statutory compliance certification.",
        "report_version_id": f"{row.package_id}@v{row.package_version}", "snapshot_hash": view["snapshot_hash"],
        "checklist_hash": assurance.digest(view["result"]["gates"]), "locked_facts_hash": assurance.digest(statements),
        "residual_findings": [{"key": f["key"], "severity": f["severity"], "state": f["state"]} for f in view["findings"]
                              if f["state"] != "OPEN" or f["severity"] == "ADVISORY"],
        "approvals": [{"role": r, "by": a["by"], "at": a["at"], "auth_aal": a["auth_aal"]} for r, a in row.attestations.items()],
        "permitted_claims": [c["text"] for c in view["claims"] if c["allowed"]],
        "prohibited_claims": [c["claim"] for c in view["claims"] if not c["allowed"]],
        "limitations": view["result"]["negative"], "is_external_audit": False,
        "publication_route": "Pending the publication engine (Document 06); nothing is filed.",
        "issued_by": user.id, "issued_at": _now().isoformat(),
        "expires_at": ((resolution or {}).get("result") or {}).get("rule_pack", {}).get("valid_until"),
    }
    row.certificate = certificate
    await _event(db, row.tenant_id, user, "released", row.id, {"release_id": certificate["release_id"]})
    await db.commit()
    return await _view(db, user, row)


async def request_claim(db: AsyncSession, user, run_id: str, claim: str) -> dict:
    """A label is allowed only when its prerequisites are evidenced; a refusal is logged (T26, T28)."""
    row = await _get_run(db, user, run_id)
    view = await _view(db, user, row)
    match = next((c for c in view["claims"] if c["claim"] == claim), None)
    if match is None or not match["allowed"]:
        reasons = match["missing"] if match else ["the claim is not in the approved vocabulary"]
        await _event(db, row.tenant_id, user, "claim_refused", row.id, {"claim": claim, "reasons": reasons})
        await db.commit()
        raise Refused(f"'{claim}' is not allowed: " + "; ".join(reasons) + ".")
    return match


async def override(db: AsyncSession, user, run_id: str, gate_id: str, reason: str) -> None:
    """Quality gates have no override (T32); the attempt is logged."""
    row = await _get_run(db, user, run_id)
    await _event(db, row.tenant_id, user, "override_refused", row.id, {"gate_id": gate_id, "reason": reason[:500]})
    await db.commit()
    raise Refused("Quality gates cannot be overridden; resolve the finding at source and re-run.")


async def get(db: AsyncSession, user, run_id: str) -> dict:
    return await _view(db, user, await _get_run(db, user, run_id))


async def latest_for(db: AsyncSession, user, package_id: str) -> dict | None:
    row = await _package_row(db, user, package_id)
    case = (await db.execute(select(FsAssuranceCase).where(
        FsAssuranceCase.tenant_id == user.tenant_id, FsAssuranceCase.trial_balance_id == row.trial_balance_id))).scalars().first()
    if case is None:
        return None
    latest = (await db.execute(select(FsAssuranceRun).where(FsAssuranceRun.case_id == case.id)
                               .order_by(FsAssuranceRun.created_at.desc()))).scalars().first()
    return await _view(db, user, latest) if latest else None


async def summary(db: AsyncSession, user, run_id: str) -> str:
    return assurance.summary_text(await get(db, user, run_id))

"""Release Gates: release candidates and their ten mandatory gates.

Fail closed (QA Test Plan & Release Gate spec): a candidate reaches
production only when every gate passes, and a failed gate holds it. Gates
the platform can measure are measured at the moment they are read — the AI
evaluation and source-licensing gates from the Governance Dashboard's live
assessment, tenant isolation from the database's own policies, operational
readiness from the health samples — and the rest carry recorded evidence.
Independent authorization is a second person's approval; never the author's.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.admin_governance.models import ReleaseCandidate
from app.domains.audit_ledger.event_envelope import record_event_async
from app.domains.identity.models import User
from app.domains.operations import service as operations
from app.domains.operations.models import ServiceHealthSample

GATES = [
    ("change_scope", "Change scope & ownership", "Change record, named owner, release scope and impact", "derived"),
    ("build_integrity", "Build integrity & SBOM", "Signed artifacts, dependency inventory and provenance", "manual"),
    ("functional_tests", "Functional & numerical tests", "Accounting workflows, calculations and API regression", "manual"),
    ("security_isolation", "Security & tenant isolation", "Row-level security policies verified on every tenant table", "derived"),
    ("licensing_privacy", "Source licensing & privacy", "Source usage rights and licence status (live assessment)", "derived"),
    ("accounting_jurisdiction", "Accounting & jurisdiction checks", "Framework applicability, effective dates and ontology", "manual"),
    ("ai_evaluation", "Kriton AI evaluation gates", "Latest evaluation run and zero-tolerance metrics (live assessment)", "derived"),
    ("operational_readiness", "Canary & operational readiness", "No core service down in the latest health samples", "derived"),
    ("rollback_evidence", "Rollback / recovery evidence", "Rollback artifacts, migrations, backups and rehearsal", "manual"),
    ("independent_authorization", "Independent change authorization", "Approval by someone other than the author", "derived"),
]
MANUAL = [k for k, _, _, kind in GATES if kind == "manual"]
COMPONENTS = ("AI Orchestration", "Knowledge", "Accounting", "Integrations", "Governance", "Platform", "Frontend")


class ReleaseError(ValueError):
    """A transition the release rules refuse."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=timezone.utc))


def _iso(v: datetime | None) -> str | None:
    v = _aware(v)
    return v.isoformat() if v else None


def _entry(action: str, actor: User, note: str = "") -> dict:
    return {"at": _now().isoformat(), "action": action, "actorId": actor.id,
            "actor": actor.full_name or actor.email, "note": note}


async def live_evidence(db: AsyncSession, viewer: User) -> dict:
    """Measured once per view and shared by every candidate on the page."""
    from app.domains.governance_dashboard.assessment import assess
    from app.main import _verify_security_policies

    readiness = (await assess(db, viewer)).release
    by_gate = {g["gate"]: g for g in readiness}

    def from_readiness(name: str) -> dict:
        g = by_gate.get(name)
        if g is None or g["state"] == "not_assessed":
            return {"status": "open", "note": g["reason"] if g else "Not assessed by the platform yet"}
        return {"status": "pass" if g["state"] == "passed" else "fail", "note": g["reason"]}

    if get_settings().is_sqlite:
        isolation = {"status": "open", "note": "Not assessable on a SQLite database"}
    else:
        try:
            await _verify_security_policies()
            isolation = {"status": "pass", "note": "Every tenant table has its row-level security policy"}
        except Exception as exc:  # noqa: BLE001 — a missing policy or a fault both fail closed
            isolation = {"status": "fail", "note": str(exc)[:200]}

    latest = (select(ServiceHealthSample.service_key, func.max(ServiceHealthSample.checked_at).label("at"))
              .where(ServiceHealthSample.checked_at >= _now() - timedelta(minutes=15))
              .group_by(ServiceHealthSample.service_key).subquery())
    samples = (await db.execute(select(ServiceHealthSample).join(
        latest, (ServiceHealthSample.service_key == latest.c.service_key)
        & (ServiceHealthSample.checked_at == latest.c.at)))).scalars().all()
    core_down = [operations.SERVICE_NAMES.get(s.service_key, s.service_key) for s in samples
                 if s.state == "down" and s.service_key in operations.CORE_SERVICES]
    other_down = [operations.SERVICE_NAMES.get(s.service_key, s.service_key) for s in samples
                  if s.state == "down" and s.service_key not in operations.CORE_SERVICES]
    if not samples:
        ops = {"status": "open", "note": "No health samples in the last 15 minutes"}
    elif core_down:
        ops = {"status": "fail", "note": "Down: " + ", ".join(core_down)}
    else:
        ops = {"status": "pass", "note": "Core services healthy" + (f"; also down: {', '.join(other_down)}" if other_down else "")}

    return {"security_isolation": isolation, "licensing_privacy": from_readiness("Source licensing"),
            "ai_evaluation": from_readiness("Evaluation"), "operational_readiness": ops, "readiness": readiness}


def gate_states(r: ReleaseCandidate, live: dict, names: dict[str, str]) -> list[dict]:
    out = []
    for i, (key, label, description, kind) in enumerate(GATES, start=1):
        if kind == "manual":
            g = r.gates.get(key) or {"status": "open", "note": ""}
            value = {"status": g["status"], "note": g.get("note", ""), "byName": names.get(g.get("by") or ""), "at": g.get("at")}
        elif key == "change_scope":
            missing = [n for n, ok in (("owner", r.owner_user_id), ("change record", r.change_ref.strip()),
                                       ("scope description", r.description.strip())) if not ok]
            value = {"status": "open" if missing else "pass",
                     "note": "Missing " + ", ".join(missing) if missing else f"{r.change_ref} · owner recorded"}
        elif key == "independent_authorization":
            value = ({"status": "pass", "note": f"Approved by {names.get(r.approved_by, 'another person')}"}
                     if r.approved_by and r.approved_by != r.created_by else
                     {"status": "open", "note": "Awaiting approval by someone other than the author"})
        else:
            value = dict(live[key])
        out.append({"key": key, "number": i, "label": label, "description": description,
                    "derived": kind == "derived", **value})
    return out


def derived_status(r: ReleaseCandidate, gates: list[dict]) -> str:
    if r.status in {"deployed", "rolled_back"}:
        return r.status
    if any(g["status"] == "fail" for g in gates):
        return "on_hold"
    before_approval = [g for g in gates if g["key"] != "independent_authorization"]
    if all(g["status"] == "pass" for g in before_approval):
        return "approved" if r.approved_by else "approval_queue"
    return "validating"


def _rollout(r: ReleaseCandidate, gates: list[dict]) -> list[dict]:
    g = {x["key"]: x["status"] for x in gates}
    deployed = _aware(r.deployed_at)
    watching = deployed and _now() - deployed < timedelta(hours=24) and r.status == "deployed"
    return [
        {"step": "Staging acceptance", "detail": "Build integrity and functional tests",
         "status": "pass" if g["build_integrity"] == g["functional_tests"] == "pass" else "open"},
        {"step": "Canary validation", "detail": "Operational readiness from live health samples",
         "status": g["operational_readiness"]},
        {"step": "Production promotion", "detail": "Every mandatory gate passed and independently approved",
         "status": "pass" if r.status in {"deployed", "rolled_back"} else
                   ("fail" if any(x["status"] == "fail" for x in gates) else "open")},
        {"step": "Post-release watch", "detail": "24 hours after promotion; rollback stays available",
         "status": "rolled_back" if r.status == "rolled_back" else "watching" if watching
                   else "pass" if deployed else "open"},
    ]


def view(r: ReleaseCandidate, live: dict, names: dict[str, str]) -> dict:
    gates = gate_states(r, live, names)
    status = derived_status(r, gates)
    return {
        "id": r.id, "ref": r.ref, "name": r.name, "version": r.version, "component": r.component,
        "changeRef": r.change_ref, "description": r.description, "risk": r.risk,
        "ownerId": r.owner_user_id, "owner": names.get(r.owner_user_id or ""), "status": status,
        "stage": "Production" if status in {"deployed", "rolled_back"} else "Staging → Production",
        "gates": gates, "passed": sum(x["status"] == "pass" for x in gates),
        "failed": sum(x["status"] == "fail" for x in gates), "pending": sum(x["status"] == "open" for x in gates),
        "rollout": _rollout(r, gates), "createdBy": names.get(r.created_by, ""), "createdById": r.created_by,
        "createdAt": _iso(r.created_at), "approvedBy": names.get(r.approved_by or "", None),
        "approvedAt": _iso(r.approved_at), "deployedAt": _iso(r.deployed_at), "rolledBackAt": _iso(r.rolled_back_at),
        "history": r.history,
    }


async def _names(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars()}


async def register(db: AsyncSession, viewer: User) -> dict:
    live = await live_evidence(db, viewer)
    names = await _names(db, viewer.tenant_id)
    rows = (await db.execute(select(ReleaseCandidate).where(ReleaseCandidate.tenant_id == viewer.tenant_id)
                             .order_by(ReleaseCandidate.created_at.desc()))).scalars().all()
    views = [view(r, live, names) for r in rows]
    count = lambda *s: sum(v["status"] in s for v in views)  # noqa: E731
    return {
        "releases": views,
        "summary": {"records": len(views), "onHold": count("on_hold"), "validating": count("validating"),
                    "awaitingApproval": count("approval_queue"), "approved": count("approved"),
                    "deployed": count("deployed"), "rolledBack": count("rolled_back")},
        "readiness": live["readiness"],
        "components": COMPONENTS,
        "generatedAt": _now().isoformat(),
    }


async def _get(db: AsyncSession, tenant_id: str, release_id: str) -> ReleaseCandidate:
    r = (await db.execute(select(ReleaseCandidate).where(
        ReleaseCandidate.id == release_id, ReleaseCandidate.tenant_id == tenant_id))).scalar_one_or_none()
    if r is None:
        raise LookupError("Release not found")
    return r


async def _audit(db: AsyncSession, actor: User, event: str, r: ReleaseCandidate, payload: dict) -> None:
    await record_event_async(db, tenant_id=actor.tenant_id, event_name=event, emitting_service="admin_governance",
                             actor_id=actor.id, subject_type="release_candidate", subject_id=r.id,
                             payload={"ref": r.ref, **payload})


async def create(db: AsyncSession, actor: User, data: dict) -> ReleaseCandidate:
    if data.get("risk") not in {"critical", "high", "medium", "low"}:
        raise ReleaseError("Unknown risk class")
    if data.get("owner_user_id") and (await db.execute(select(User.id).where(
            User.id == data["owner_user_id"], User.tenant_id == actor.tenant_id, User.is_active.is_(True)))).first() is None:
        raise ReleaseError("Owner must be an active user in this workspace")
    count = (await db.execute(select(func.count()).select_from(ReleaseCandidate)
                              .where(ReleaseCandidate.tenant_id == actor.tenant_id))).scalar_one()
    r = ReleaseCandidate(tenant_id=actor.tenant_id, ref=f"REL-{count + 1:03d}", status="validating",
                         gates={k: {"status": "open", "note": "", "by": None, "at": None} for k in MANUAL},
                         created_by=actor.id, history=[_entry("created", actor)], **data)
    db.add(r)
    await db.flush()
    await _audit(db, actor, "release_candidate_created", r, {"name": r.name, "version": r.version})
    return r


async def set_gate(db: AsyncSession, actor: User, release_id: str, key: str, status: str, note: str) -> ReleaseCandidate:
    r = await _get(db, actor.tenant_id, release_id)
    if r.status in {"deployed", "rolled_back"}:
        raise ReleaseError("This release is closed; create a new candidate for further changes")
    if key not in MANUAL:
        raise ReleaseError("This gate is measured by the platform and cannot be set by hand")
    if status not in {"pass", "open", "fail"}:
        raise ReleaseError("Unknown gate status")
    if status in {"pass", "fail"} and not note.strip():
        raise ReleaseError("Record the evidence or the reason")
    r.gates = {**r.gates, key: {"status": status, "note": note.strip(), "by": actor.id, "at": _now().isoformat()}}
    # Changed evidence invalidates an approval given on the old evidence.
    if r.approved_by:
        r.approved_by, r.approved_at = None, None
        r.history = [*r.history, _entry("approval_withdrawn", actor, "Gate evidence changed after approval")]
    r.history = [*r.history, _entry(f"gate:{key}", actor, f"{status}: {note.strip()}")]
    await db.flush()
    await _audit(db, actor, "release_gate_recorded", r, {"gate": key, "status": status})
    return r


async def transition(db: AsyncSession, actor: User, viewer_live: dict, release_id: str, action: str, note: str) -> ReleaseCandidate:
    r = await _get(db, actor.tenant_id, release_id)
    names = await _names(db, actor.tenant_id)
    gates = gate_states(r, viewer_live, names)
    status = derived_status(r, gates)
    if action == "approve":
        if status != "approval_queue":
            open_or_failed = [g["label"] for g in gates if g["status"] != "pass" and g["key"] != "independent_authorization"]
            raise ReleaseError("Every mandatory gate must pass before approval: " + ", ".join(open_or_failed)
                               if open_or_failed else "This release is not awaiting approval")
        if r.created_by == actor.id:
            raise ReleaseError("Approval must come from someone other than the person who created the release")
        r.approved_by, r.approved_at = actor.id, _now()
    elif action == "deploy":
        if status != "approved":
            raise ReleaseError("Production promotion is blocked until every gate passes and the release is approved")
        r.status, r.deployed_at = "deployed", _now()
    elif action == "rollback":
        if r.status != "deployed":
            raise ReleaseError("Only a deployed release can be rolled back")
        if not note.strip():
            raise ReleaseError("Record why the release is being rolled back")
        r.status, r.rolled_back_at = "rolled_back", _now()
    else:
        raise ReleaseError("Unknown action")
    r.history = [*r.history, _entry(action, actor, note.strip())]
    await db.flush()
    await _audit(db, actor, f"release_{action}", r, {"note": note.strip()})
    return r

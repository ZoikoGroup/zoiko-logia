"""Stored publication: render jobs, issue, filing attempts and external
edits (Document 06 §13 state machine, §14 security, §16 APIs).

A render is idempotent on (package version, audience, channel, scale,
publication state, model hash, renderer version) (PUB-042). Each artifact
carries its model, byte hash and validation report (parity, sensitive
content, accessibility). Issue needs a Document 07 release of the same
package version, a different authorised person and passing parity on HTML,
Word and PDF; statutory audiences also need a permitted statutory claim.
Filing is never transmitted: every adapter is uncertified, and an attempt
is refused and logged (PUB-T038). A re-uploaded Word file is quarantined
with its diff and never replaces an issued artifact (PUB-003, PUB-T018).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.event_envelope import record_event_async

from . import assurance, assurance_store, packages, publication as pub, resolutions
from .models import FsPublicationArtifact, FsPublicationIssue
from .store import NotFound, Refused
from .workspace import misleading_reasons

ISSUERS = tuple(sorted(set(assurance.TECHNICAL_ROLES) | set(assurance.OFFICER_ROLES)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _event(db, user, action: str, subject_id: str, detail: dict, subject_type: str = "publication") -> None:
    await record_event_async(db, tenant_id=user.tenant_id, event_name=f"financial_statements.publication_{action}",
                             emitting_service="financial_statements", actor_id=user.id, subject_type=subject_type,
                             subject_id=subject_id, payload=detail)


async def _context(db: AsyncSession, user, package_id: str) -> dict:
    package = await packages.get(db, user, package_id)
    resolution = await resolutions.get(db, user, package["resolution_id"]) if package["resolution_id"] else None
    run = await assurance_store.latest_for(db, user, package_id)
    current_run = run if run and run["package_id"] == package_id and not run["superseded_by"] else None
    issue = (await db.execute(select(FsPublicationIssue).where(
        FsPublicationIssue.tenant_id == user.tenant_id, FsPublicationIssue.package_id == package_id,
        FsPublicationIssue.superseded_by.is_(None)).order_by(FsPublicationIssue.issued_at.desc()))).scalars().first()
    state = pub.publication_state(current_run["status"] if current_run else None, issued=bool(issue))
    if package["state"] in ("SUPERSEDED", "INVALIDATED"):
        state = "SUPERSEDED"
    return {"package": package, "resolution": resolution, "run": current_run, "issue": issue, "state": state}


def _internal_ids(ctx: dict) -> list[str]:
    package, run = ctx["package"], ctx["run"] or {}
    ids = {package["created_by"], package["trial_balance_id"], package.get("resolution_id"), package["id"]}
    ids |= {s.get("by") for s in (package.get("signoffs") or {}).values()}
    ids |= {a.get("by") for a in (run.get("attestations") or {}).values()}
    ids |= {e.get("uploaded_by") for e in run.get("evidence", [])}
    return [i for i in ids if i]


def _artifact_view(a: FsPublicationArtifact) -> dict:
    return {"id": a.id, "kind": a.kind, "audience": a.audience, "channel": a.channel, "scale": a.scale, "state": a.state,
            "package_version": a.package_version, "model_hash": a.model_hash, "filename": a.filename, "media_type": a.media_type,
            "sha256": a.sha256, "size_bytes": len(a.content or b""), "validation": a.validation,
            "source_artifact_id": a.source_artifact_id, "created_by": a.created_by,
            "created_at": a.created_at.isoformat() if a.created_at else None}


def _issue_view(i: FsPublicationIssue | None) -> dict | None:
    if i is None:
        return None
    return {"id": i.id, "audience": i.audience, "state": i.state, "release_id": i.release_id, "artifacts": i.artifacts,
            "filing": i.filing, "issued_by": i.issued_by, "auth_aal": i.auth_aal,
            "issued_at": i.issued_at.isoformat() if i.issued_at else None, "package_version": i.package_version}


# ── preview and render ──────────────────────────────────────────────────────

async def preview(db: AsyncSession, user, package_id: str, audience: str, scale: str = "units") -> dict:
    ctx = await _context(db, user, package_id)
    try:
        model = pub.build_model(package=ctx["package"], resolution=ctx["resolution"], audience=audience, scale=scale,
                                state=ctx["state"])
    except ValueError as error:
        raise Refused(str(error)) from None
    return {"model": model, "state": ctx["state"], "issue_blockers": await _issue_blockers(db, user, ctx, audience)}


async def render(db: AsyncSession, user, package_id: str, *, audience: str, channel: str, scale: str = "units") -> dict:
    ctx = await _context(db, user, package_id)
    if ctx["state"] == "SUPERSEDED":
        raise Refused("The package changed or was superseded; rebuild it before rendering (409, PUB-T014).")
    if channel not in pub.RENDERERS:
        raise Refused(f"The channel is one of: {', '.join(pub.RENDERERS)}.")
    misleading = misleading_reasons(ctx["package"]["result"])
    if misleading:
        raise Refused("Rendering declined; even a draft would be materially misleading: " + " ".join(misleading))
    try:
        model = pub.build_model(package=ctx["package"], resolution=ctx["resolution"], audience=audience, scale=scale,
                                state=ctx["state"])
    except ValueError as error:
        raise Refused(str(error)) from None
    if model["blockers"] and not model["draft"]:
        raise Refused("Cannot render the issue copy: " + " ".join(model["blockers"]))
    key = pub.digest([package_id, ctx["package"]["version"], audience, channel, scale, ctx["state"], model["model_hash"],
                      pub.RENDERER_VERSION])
    existing = (await db.execute(select(FsPublicationArtifact).where(
        FsPublicationArtifact.tenant_id == user.tenant_id, FsPublicationArtifact.idempotency_key == key))).scalars().first()
    if existing is not None:
        return _artifact_view(existing)                     # PUB-T035: same logical result
    content = pub.RENDERERS[channel](model)
    validation = {"parity": pub.parity(model, channel, content),
                  "sensitive": pub.sensitive(model, channel, content, internal_ids=_internal_ids(ctx)),
                  "accessibility": pub.accessibility(channel, content), "renderer_version": pub.RENDERER_VERSION,
                  "blockers": model["blockers"], "rounding": model["rounding"]}
    m = model["masthead"]
    name = "-".join(filter(None, [(m["entity"] or "entity").lower().replace(" ", "-")[:40], audience, f"v{ctx['package']['version']}"]))
    row = FsPublicationArtifact(tenant_id=user.tenant_id, package_id=package_id, package_version=ctx["package"]["version"],
                                kind="RENDER", audience=audience, channel=channel, scale=scale, state=ctx["state"],
                                idempotency_key=key, model=model, model_hash=model["model_hash"], filename=f"{name}.{channel}",
                                media_type=pub.CHANNELS[channel], sha256=hashlib.sha256(content).hexdigest(), content=content,
                                validation=validation, created_by=user.id)
    db.add(row)
    await db.flush()
    await _event(db, user, "rendered", row.id, {"package_id": package_id, "audience": audience, "channel": channel,
                                                "sha256": row.sha256, "parity": validation["parity"]["ok"]})
    await db.commit()
    return _artifact_view(row)


# ── issue (§13) ─────────────────────────────────────────────────────────────

async def _issue_blockers(db, user, ctx: dict, audience: str) -> list[str]:
    reasons = []
    if ctx["state"] != "AUTHORISED_FOR_ISSUE":
        reasons.append(f"The package is {ctx['state'].replace('_', ' ').lower()}; issue needs the Document 07 internal release "
                       "of this package version.")
    if pub.AUDIENCES.get(audience, {}).get("statutory"):
        claim = next((c for c in (ctx["run"] or {}).get("claims", []) if c["claim"] == "STATUTORY_COMPLIANT"), None)
        if not claim or not claim["allowed"]:
            reasons.append("A statutory audience needs a permitted statutory claim: "
                           + "; ".join((claim or {}).get("missing", ["no assurance run"])) + ".")
    return reasons


async def issue(db: AsyncSession, user, package_id: str, audience: str, scale: str = "units") -> dict:
    ctx = await _context(db, user, package_id)
    reasons = await _issue_blockers(db, user, ctx, audience)
    if user.role not in ISSUERS or user.id == ctx["package"]["created_by"]:
        reasons.append("Issue is by an authorised officer or technical accounting lead who did not prepare the package (PUB-020).")
    try:
        model = pub.build_model(package=ctx["package"], resolution=ctx["resolution"], audience=audience, scale=scale,
                                state=ctx["state"])
    except ValueError as error:
        raise Refused(str(error)) from None
    artifacts = (await db.execute(select(FsPublicationArtifact).where(
        FsPublicationArtifact.tenant_id == user.tenant_id, FsPublicationArtifact.package_id == package_id,
        FsPublicationArtifact.kind == "RENDER", FsPublicationArtifact.model_hash == model["model_hash"])
        .order_by(FsPublicationArtifact.created_at.desc()))).scalars().all()
    chosen: dict[str, FsPublicationArtifact] = {}
    for a in artifacts:                                     # the current approved model only (PUB-T014)
        chosen.setdefault(a.channel, a)
    for channel in ("html", "docx", "pdf"):
        a = chosen.get(channel)
        if a is None:
            reasons.append(f"Render the {channel.upper()} copy for this audience and state first.")
        elif not a.validation["parity"]["ok"]:
            reasons.append(f"{channel.upper()} fails parity: " + "; ".join(a.validation["parity"]["issues"][:3]) + " (PUB-040, PUB-046).")
        elif a.validation["sensitive"]["blocking"]:
            reasons.append(f"{channel.upper()} contains internal identifiers: {', '.join(a.validation['sensitive']['hits'])} (PUB-023).")
    if len({a.model["approved_facts_hash"] for a in chosen.values()}) > 1:
        reasons.append("The channels were rendered from different approved facts (PUB-033).")
    if reasons:
        await _event(db, user, "issue_refused", package_id, {"audience": audience, "reasons": reasons[:8]})
        await db.commit()
        raise Refused("Issue refused: " + " ".join(dict.fromkeys(reasons)))
    row = FsPublicationIssue(tenant_id=user.tenant_id, package_id=package_id, package_version=ctx["package"]["version"],
                             audience=audience, state="ISSUED", release_id=ctx["run"]["certificate"]["release_id"],
                             artifacts=[{"id": a.id, "channel": a.channel, "sha256": a.sha256, "model_hash": a.model_hash}
                                        for a in chosen.values()],
                             filing=[], issued_by=user.id, auth_aal=getattr(user, "auth_aal", "aal1"))
    db.add(row)
    await db.flush()
    await _event(db, user, "issued", row.id, {"package_id": package_id, "audience": audience, "release_id": row.release_id,
                                              "artifacts": row.artifacts})
    await db.commit()
    return _issue_view(row)


async def submit_filing(db: AsyncSession, user, issue_id: str, *, destination: str, live: bool, confirmed: bool) -> None:
    """Never transmits: no adapter is certified. Unauthorised attempts are security events (PUB-T038)."""
    row = await db.get(FsPublicationIssue, issue_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise NotFound("Issued publication not found.")
    if user.role not in ISSUERS:
        await _event(db, user, "filing_unauthorised", issue_id, {"destination": destination, "role": user.role})
        await db.commit()
        raise Refused("You are not authorised to file accounts; the attempt was recorded.")
    adapter = pub.ADAPTERS.get(destination)
    reasons = ["Explicit human confirmation is required."] if not confirmed else []
    reasons += [f"Unknown destination {destination}."] if adapter is None else [
        f"The {adapter['title']} adapter is {adapter['status'].replace('_', ' ').lower()}; nothing is transmitted."]
    reasons += pub.tagging({}, destination)["reasons"] if adapter else []
    attempt = {"destination": destination, "live": live, "by": user.id, "at": _now().isoformat(), "status": "NOT_SENT",
               "reasons": reasons}
    row.filing = [*row.filing, attempt]                     # attempts are kept; never a receipt (PUB-T022, PUB-T028)
    await _event(db, user, "filing_refused", issue_id, {"destination": destination, "reasons": reasons[:5]})
    await db.commit()
    raise Refused("Filing not sent: " + " ".join(reasons))


# ── external edits, downloads and overview ──────────────────────────────────

async def _artifact(db, user, artifact_id: str) -> FsPublicationArtifact:
    row = await db.get(FsPublicationArtifact, artifact_id)
    if row is not None and row.tenant_id != user.tenant_id:
        await _event(db, user, "access_denied", artifact_id, {"reason": "cross_tenant"})      # PUB-T031
        await db.commit()
        row = None
    if row is None:
        raise NotFound("Artifact not found.")
    return row


async def reimport_docx(db: AsyncSession, user, artifact_id: str, content: bytes) -> dict:
    original = await _artifact(db, user, artifact_id)
    if original.channel != "docx" or original.kind != "RENDER":
        raise Refused("Only a rendered Word file can be compared with a re-uploaded edit.")
    try:
        new, old = pub.extract("docx", content), pub.extract("docx", original.content)
    except Exception:  # noqa: BLE001 - any unreadable upload is refused, not stored
        raise Refused("The upload is not a readable Word document.") from None
    diff = [f"Row {i + 1}: {a} → {b}" for i, (a, b) in enumerate(zip(old["rows"], new["rows"])) if a != b]
    if len(old["rows"]) != len(new["rows"]):
        diff.append(f"Row count changed from {len(old['rows'])} to {len(new['rows'])}.")
    old_lines, new_lines = set(pub._norm(x) for x in old["text"].splitlines()), set(pub._norm(x) for x in new["text"].splitlines())
    diff += [f"Removed: {x}" for x in sorted(old_lines - new_lines) if x][:20]
    diff += [f"Added: {x}" for x in sorted(new_lines - old_lines) if x][:20]
    row = FsPublicationArtifact(tenant_id=user.tenant_id, package_id=original.package_id, package_version=original.package_version,
                                kind="EXTERNAL_EDIT", audience=original.audience, channel="docx", scale=original.scale,
                                state="QUARANTINED", idempotency_key=pub.digest(["external", hashlib.sha256(content).hexdigest()]),
                                model={}, model_hash="", filename=f"external-edit-of-{original.filename}",
                                media_type=pub.CHANNELS["docx"], sha256=hashlib.sha256(content).hexdigest(), content=content,
                                validation={"diff": diff, "changed": bool(diff),
                                            "note": "An externally edited file is not the approved snapshot; review the diff "
                                                    "and re-approve through the package before any statutory reuse."},
                                source_artifact_id=original.id, created_by=user.id)
    db.add(row)
    await db.flush()
    await _event(db, user, "external_edit_quarantined", row.id, {"source": original.id, "changes": len(diff)})
    await db.commit()
    return _artifact_view(row)


async def download(db: AsyncSession, user, artifact_id: str) -> tuple[str, str, bytes]:
    row = await _artifact(db, user, artifact_id)
    await _event(db, user, "downloaded", row.id, {"channel": row.channel, "state": row.state})
    await db.commit()
    return row.filename, row.media_type, row.content


async def overview(db: AsyncSession, user, package_id: str) -> dict:
    ctx = await _context(db, user, package_id)
    rows = (await db.execute(select(FsPublicationArtifact).where(
        FsPublicationArtifact.tenant_id == user.tenant_id, FsPublicationArtifact.package_id == package_id)
        .order_by(FsPublicationArtifact.created_at.desc()))).scalars().all()
    issues = (await db.execute(select(FsPublicationIssue).where(
        FsPublicationIssue.tenant_id == user.tenant_id, FsPublicationIssue.package_id == package_id)
        .order_by(FsPublicationIssue.issued_at.desc()))).scalars().all()
    return {"package_id": package_id, "package_version": ctx["package"]["version"], "state": ctx["state"],
            "entity": ctx["package"]["result"]["profile"].get("entity"),
            "framework": ctx["package"]["result"]["profile"].get("edition") or ctx["package"]["result"]["profile"].get("framework"),
            "assurance_status": (ctx["run"] or {}).get("status"),
            "release_id": ((ctx["run"] or {}).get("certificate") or {}).get("release_id"),
            "audiences": [{"key": k, **v, "issue_blockers": await _issue_blockers(db, user, ctx, k)} for k, v in pub.AUDIENCES.items()],
            "audience_matrix": pub.AUDIENCE_MATRIX, "adapters": pub.ADAPTERS, "taxonomies": pub.TAXONOMIES,
            "artifacts": [_artifact_view(a) for a in rows], "issues": [_issue_view(i) for i in issues],
            "misleading": misleading_reasons(ctx["package"]["result"])}

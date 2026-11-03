"""WF-01 A1: document authority — the register in the database, the alias
resolver, and Document Control proposals ratified by a different person.

  import_register   loads registry/authority_register.json (built from the
                    controlled documents); idempotent; resolves nothing.
  resolve           a reference to exactly one record, or a refusal:
                    COLLISION_UNRESOLVED (more than one referent),
                    UNKNOWN_REFERENCE; a record whose evidence is not in the
                    repository resolves with state EVIDENCE_UNAVAILABLE_IN_REPO,
                    never as approved or as non-existent.
  propose / ratify  a resolution needs a PROPOSAL (authority.propose) and a
                    RATIFICATION by someone else (authority.ratify), checked
                    against the revisions the proposer saw (compare-and-swap).
                    A referent whose text is not in the repository cannot be
                    given a canonical identifier.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin_governance.governance_access import canonical_sha256, governance_error
from app.domains.admin_governance.governance_models import AuthorityAlias, AuthorityChangeRequest, AuthorityDocument

REGISTER = Path(__file__).resolve().parents[3] / "registry" / "authority_register.json"
_ID = re.compile(r"^ZL-[A-Z0-9]+(?:-[A-Z0-9]+){1,5}$")


def _family(identifier: str | None) -> str:
    return (identifier or "").split("-")[1] if identifier and identifier.count("-") >= 1 else ""


async def _replay(db: AsyncSession, key: str) -> AuthorityChangeRequest | None:
    return (await db.execute(select(AuthorityChangeRequest).where(AuthorityChangeRequest.idempotency_key == key))).scalar_one_or_none()


async def import_register(db: AsyncSession, register: dict | None = None) -> dict:
    """Insert the register's records that are not yet present. A record that
    is present is left as it is: the register never overwrites a ratified one."""
    register = register or json.loads(REGISTER.read_text())
    version = register.get("version", "")
    present = set((await db.execute(select(AuthorityDocument.record_key))).scalars())
    added = 0
    collisions = {c["legacy_id"]: c for c in register.get("collisions", [])}
    for doc in register.get("documents", []):
        if doc["path"] in present:
            continue
        db.add(AuthorityDocument(record_key=doc["path"], canonical_id=doc.get("canonical_id"),
                                 family=_family(doc.get("canonical_id") or next((i["id"] for i in doc["declared_ids"]), "")),
                                 title=doc.get("title", ""), content_sha256=doc.get("sha256"), state=doc["state"],
                                 declared_ids=[i["id"] for i in doc.get("declared_ids", [])], register_version=version))
        for item in doc.get("declared_ids", []):
            db.add(AuthorityAlias(alias=item["id"], family=_family(item["id"]), record_key=doc["path"],
                                  state="COLLISION_UNRESOLVED" if item["id"] in collisions else "DECLARED",
                                  described_as=doc.get("title", "")))
        added += 1
    for ref in register.get("unavailable_references", []):
        key = f"ref:{ref['id']}"
        if key in present:
            continue
        db.add(AuthorityDocument(record_key=key, canonical_id=None, family=_family(ref["id"]), title="",
                                 content_sha256=None, state="EVIDENCE_UNAVAILABLE_IN_REPO", declared_ids=[ref["id"]],
                                 source="cited_only", register_version=version))
        db.add(AuthorityAlias(alias=ref["id"], family=_family(ref["id"]), record_key=key, state="DECLARED",
                              described_as="cited by controlled documents; not in the repository"))
        added += 1
    existing_alias = {(a.alias, a.described_as) for a in (await db.execute(select(AuthorityAlias))).scalars()}
    for legacy, collision in collisions.items():
        for candidate in collision.get("candidates", []):
            if (legacy, candidate["described_as"]) not in existing_alias:
                db.add(AuthorityAlias(alias=legacy, family=_family(legacy), record_key=None,
                                      described_as=candidate["described_as"], state="COLLISION_UNRESOLVED"))
    await db.commit()
    return {"added": added, "register_version": version}


def _public(doc: AuthorityDocument) -> dict:
    return {"record_key": doc.record_key, "canonical_id": doc.canonical_id, "state": doc.state, "title": doc.title,
            "family": doc.family, "content_sha256": doc.content_sha256, "declared_ids": doc.declared_ids,
            "revision": doc.revision}


async def list_documents(db: AsyncSession) -> list[dict]:
    return [_public(d) for d in (await db.execute(select(AuthorityDocument).order_by(AuthorityDocument.record_key))).scalars()]


async def resolve(db: AsyncSession, reference: str, family: str | None = None) -> dict:
    reference = (reference or "").strip()
    aliases = list((await db.execute(select(AuthorityAlias).where(AuthorityAlias.alias == reference))).scalars())
    if family:
        aliases = [a for a in aliases if a.family == family]
    if any(a.state == "COLLISION_UNRESOLVED" for a in aliases) or len({a.record_key for a in aliases}) > 1:
        raise governance_error("COLLISION_UNRESOLVED",
                               f"{reference} identifies more than one document; select one explicitly once it is ratified.")
    if aliases:
        doc = (await db.execute(select(AuthorityDocument).where(AuthorityDocument.record_key == aliases[0].record_key))).scalar_one()
        return _public(doc)
    doc = (await db.execute(select(AuthorityDocument).where(AuthorityDocument.canonical_id == reference))).scalar_one_or_none()
    if doc is None:
        raise governance_error("UNKNOWN_REFERENCE", f"{reference} is not in the authority register.", 404)
    return _public(doc)


async def propose(db: AsyncSession, actor, *, legacy_id: str, mapping: dict[str, str], reason: str, key: str) -> dict:
    replay = await _replay(db, key)
    if replay is not None:
        return _request_public(replay)
    if not mapping or not reason.strip():
        raise governance_error("PROPOSAL_INCOMPLETE", "A proposal needs a mapping and a reason.", 422)
    docs = {d.record_key: d for d in (await db.execute(select(AuthorityDocument).where(
        AuthorityDocument.record_key.in_(list(mapping))))).scalars()}
    missing = sorted(set(mapping) - set(docs))
    if missing:
        raise governance_error("EVIDENCE_UNAVAILABLE",
                               f"No controlled document in the repository for {missing}: a referent whose text is not "
                               "held cannot be given a canonical identifier.", 409)
    taken = set((await db.execute(select(AuthorityDocument.canonical_id).where(AuthorityDocument.canonical_id.is_not(None)))).scalars())
    for record_key, new_id in mapping.items():
        if not _ID.match(new_id or ""):
            raise governance_error("INVALID_IDENTIFIER", f"{new_id!r} is not a controlled-document identifier.", 422)
        if new_id in taken and docs[record_key].canonical_id != new_id:
            raise governance_error("DUPLICATE_CANONICAL_ID", f"{new_id} is already the canonical identifier of another document.")
        if docs[record_key].state == "EVIDENCE_UNAVAILABLE_IN_REPO":
            raise governance_error("EVIDENCE_UNAVAILABLE", f"{record_key} is cited but not held in the repository.")
    if len(set(mapping.values())) != len(mapping):
        raise governance_error("DUPLICATE_CANONICAL_ID", "A proposal cannot give two documents the same identifier.")
    content = {"kind": "PROPOSAL", "legacy_id": legacy_id, "mapping": mapping, "reason": reason,
               "expected_revisions": {k: d.revision for k, d in docs.items()}}
    row = AuthorityChangeRequest(kind="PROPOSAL", legacy_id=legacy_id, mapping=mapping, reason=reason,
                                 actor_id=actor.id, actor_role=actor.role, expected_revisions=content["expected_revisions"],
                                 content_sha256=canonical_sha256(content), idempotency_key=key)
    db.add(row)
    await db.commit()
    return _request_public(row)


async def ratify(db: AsyncSession, actor, *, proposal_id: str, decision: str, reason: str, key: str) -> dict:
    replay = await _replay(db, key)
    if replay is not None:
        return _request_public(replay)
    proposal = (await db.execute(select(AuthorityChangeRequest).where(
        AuthorityChangeRequest.id == proposal_id, AuthorityChangeRequest.kind == "PROPOSAL"))).scalar_one_or_none()
    if proposal is None:
        raise governance_error("UNKNOWN_PROPOSAL", "No such proposal.", 404)
    if proposal.actor_id == actor.id:
        raise governance_error("INDEPENDENCE_REQUIRED", "The proposer cannot ratify their own proposal.", 403)
    decided = (await db.execute(select(AuthorityChangeRequest).where(
        AuthorityChangeRequest.proposal_id == proposal_id))).scalars().first()
    if decided is not None:
        raise governance_error("ALREADY_DECIDED", f"This proposal was already {decided.kind.lower()}.")
    if decision not in ("RATIFY", "REJECT"):
        raise governance_error("INVALID_DECISION", "decision is RATIFY or REJECT.", 422)
    docs = {d.record_key: d for d in (await db.execute(select(AuthorityDocument).where(
        AuthorityDocument.record_key.in_(list(proposal.mapping))))).scalars()}
    stale = sorted(k for k, rev in proposal.expected_revisions.items() if docs.get(k) is None or docs[k].revision != rev)
    if stale:
        raise governance_error("STALE_REVISION", f"{stale} changed since the proposal; propose again.")
    kind = "RATIFICATION" if decision == "RATIFY" else "REJECTION"
    content = {"kind": kind, "proposal_id": proposal_id, "proposal_sha256": proposal.content_sha256, "reason": reason}
    row = AuthorityChangeRequest(kind=kind, proposal_id=proposal_id, legacy_id=proposal.legacy_id, mapping=proposal.mapping,
                                 reason=reason, actor_id=actor.id, actor_role=actor.role,
                                 expected_revisions=proposal.expected_revisions, content_sha256=canonical_sha256(content),
                                 idempotency_key=key)
    db.add(row)
    if kind == "RATIFICATION":
        now = datetime.now(timezone.utc)
        for record_key, new_id in proposal.mapping.items():
            doc = docs[record_key]
            doc.canonical_id, doc.state, doc.revision, doc.updated_at = new_id, "CANONICAL_RATIFIED", doc.revision + 1, now
            db.add(AuthorityAlias(alias=new_id, family=_family(new_id), record_key=record_key, state="DECLARED",
                                  described_as=doc.title))
        for alias in (await db.execute(select(AuthorityAlias).where(AuthorityAlias.alias == proposal.legacy_id))).scalars():
            if alias.record_key in proposal.mapping or alias.record_key is None:
                alias.state = "SUPERSEDED_BY_RATIFICATION"
    await db.commit()
    return _request_public(row)


def _request_public(row: AuthorityChangeRequest) -> dict:
    return {"id": row.id, "kind": row.kind, "proposal_id": row.proposal_id, "legacy_id": row.legacy_id,
            "mapping": row.mapping, "actor_id": row.actor_id, "content_sha256": row.content_sha256}


async def summary(db: AsyncSession) -> dict:
    docs = list((await db.execute(select(AuthorityDocument))).scalars())
    aliases = list((await db.execute(select(AuthorityAlias))).scalars())
    states: dict[str, int] = {}
    for doc in docs:
        states[doc.state] = states.get(doc.state, 0) + 1
    return {"documents": len(docs), "states": states,
            "unresolved_collisions": sorted({a.alias for a in aliases if a.state == "COLLISION_UNRESOLVED"})}

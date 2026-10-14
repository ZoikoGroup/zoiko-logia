"""Evidence packs: one ZIP that shows what an answer rested on.

Built on demand for a saved answer or a draft (a draft uses the saved answer
it was created from), from records Kriton already keeps for that question:

  answer.md        the question and the answer as saved (or the draft text)
  sources.md/.json the web sources and excerpts the answer was given
                   (QueryAnswerRecord.external_evidence)
  review.json      review cases on the question and their decisions
  feedback.json    users' ratings of the answer
  audit.json       the question's audit-ledger events with their chain hashes
  manifest.json    what is in the pack, who built it and when, and the
                   SHA-256 of every file, so a recipient can check that
                   nothing was altered after export

Everything is scoped to the requesting user's own saved answer or draft in
their tenant. Nothing is stored: the pack is rebuilt from the records each
time it is downloaded.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import User
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.orchestration.models import AnswerFeedback, QueryAnswerRecord, ReviewCase

PACK_KINDS = ("saved-answer", "draft")
AUDIT_LIMIT = 200
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _json(data) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def pack_filename(title: str) -> str:
    stem = _UNSAFE.sub("", title).strip()[:70] or "evidence"
    return f"Evidence pack - {stem}.zip"


async def _subject(db: AsyncSession, user: User, kind: str, item_id: str) -> tuple[str, str, SavedAnswer | None, Draft | None]:
    """(title, main text, saved answer or None, draft or None) for the user's own item."""
    if kind not in PACK_KINDS:
        raise HTTPException(status_code=404, detail="Unknown evidence pack type")
    if kind == "draft":
        draft = (await db.execute(select(Draft).where(
            Draft.id == item_id, Draft.user_id == user.id, Draft.tenant_id == user.tenant_id))).scalar_one_or_none()
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        answer = None
        if draft.saved_answer_id:
            answer = (await db.execute(select(SavedAnswer).where(
                SavedAnswer.id == draft.saved_answer_id, SavedAnswer.user_id == user.id,
                SavedAnswer.tenant_id == user.tenant_id))).scalar_one_or_none()
        return draft.title, f"# {draft.title}\n\nStatus: {draft.status}\n\n{draft.content}\n", answer, draft
    answer = (await db.execute(select(SavedAnswer).where(
        SavedAnswer.id == item_id, SavedAnswer.user_id == user.id, SavedAnswer.tenant_id == user.tenant_id))).scalar_one_or_none()
    if answer is None:
        raise HTTPException(status_code=404, detail="Saved answer not found")
    text = f"# Question\n\n{answer.query_text}\n\n# Answer\n\nRisk level: {answer.risk_level}\n\n{answer.answer_text}\n"
    return answer.query_text[:80], text, answer, None


async def build_evidence_pack(db: AsyncSession, user: User, kind: str, item_id: str,
                              now: datetime | None = None) -> tuple[bytes, str, dict]:
    """(zip bytes, filename, manifest)."""
    now = now or datetime.now(timezone.utc)
    title, main_text, answer, draft = await _subject(db, user, kind, item_id)
    query_id = answer.query_id if answer else None
    tenant = user.tenant_id

    sources, reviews, feedback, audit = [], [], [], []
    if query_id:
        record = (await db.execute(select(QueryAnswerRecord).where(
            QueryAnswerRecord.query_id == query_id, QueryAnswerRecord.tenant_id == tenant))).scalar_one_or_none()
        for item in (record.external_evidence if record else None) or []:
            item = item or {}
            sources.append({"title": item.get("title"), "url": item.get("url"),
                            "excerpt": item.get("content"), "effective_from": item.get("effective_from"),
                            "effective_to": item.get("effective_to")})
        for case in (await db.execute(select(ReviewCase).where(
                ReviewCase.query_id == query_id, ReviewCase.tenant_id == tenant).order_by(ReviewCase.created_at))).scalars():
            reviews.append({"id": case.id, "source": case.source, "status": case.status, "risk_level": case.risk_level,
                            "reason": case.reason, "decision": case.reviewer_decision, "reviewer_id": case.reviewer_id,
                            "note": case.review_note, "opened_at": _iso(case.created_at), "resolved_at": _iso(case.resolved_at)})
        for fb in (await db.execute(select(AnswerFeedback).where(
                AnswerFeedback.query_id == query_id, AnswerFeedback.tenant_id == tenant).order_by(AnswerFeedback.created_at))).scalars():
            feedback.append({"rating": fb.rating, "reasons": fb.reasons, "comment": fb.comment, "at": _iso(fb.created_at)})
        for event in (await db.execute(select(
                AuditEvent.id, AuditEvent.event_name, AuditEvent.event_time, AuditEvent.payload_hash,
                AuditEvent.previous_chain_hash, AuditEvent.chain_hash).where(
                AuditEvent.subject_id == query_id, AuditEvent.tenant_id == tenant)
                .order_by(AuditEvent.ingested_at).limit(AUDIT_LIMIT))).all():
            audit.append({"id": event.id, "event": event.event_name, "at": _iso(event.event_time),
                          "payload_hash": event.payload_hash, "previous_chain_hash": event.previous_chain_hash,
                          "chain_hash": event.chain_hash})

    def quoted(text: str) -> str:
        return "".join(f"   > {line}\n" for line in text[:600].splitlines() if line.strip())

    sources_md = "# Sources\n\n" + ("\n".join(
        f"{n}. {s['title'] or s['url']}\n   {s['url'] or ''}\n" + (quoted(s["excerpt"]) if s.get("excerpt") else "")
        for n, s in enumerate(sources, 1)) if sources else "No web sources are on record for this answer.\n")

    files = {
        "answer.md" if kind == "saved-answer" else "draft.md": main_text.encode("utf-8"),
        "sources.md": sources_md.encode("utf-8"),
        "sources.json": _json(sources),
        "review.json": _json(reviews),
        "feedback.json": _json(feedback),
        "audit.json": _json(audit),
    }
    if draft is not None and answer is not None:
        files["original-answer.md"] = (
            f"# Question\n\n{answer.query_text}\n\n# Answer\n\n{answer.answer_text}\n").encode("utf-8")
    manifest = {
        "pack": "ZoikoLogia evidence pack",
        "kind": kind,
        "item_id": item_id,
        "title": title,
        "query_id": query_id,
        "generated_at": now.isoformat(),
        "generated_by": {"user_id": user.id, "tenant_id": tenant},
        "counts": {"sources": len(sources), "review_cases": len(reviews), "feedback": len(feedback), "audit_events": len(audit)},
        "notes": [] if query_id else ["This draft was not created from a saved answer, so no sources, reviews or audit events are linked."],
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in files.items()},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", _json(manifest))
    return buffer.getvalue(), pack_filename(title), manifest

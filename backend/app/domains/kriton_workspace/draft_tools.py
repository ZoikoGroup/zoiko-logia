"""Draft deletion, sources and export (Drafts & Reports).

Every function is scoped to the draft's owner (user_id) and tenant, the same
boundary list_drafts/update_draft use: another user's draft is "not found".

Sources: a draft created from a saved answer keeps that answer's web
sources, read from the answer record Kriton stored when it answered
(QueryAnswerRecord.external_evidence). Uploaded-document sources are not
stored there, so they are not listed. A draft started blank has none.

Export renders the draft's text with the workspace's existing document
generator (artifacts._render), so Word, PDF and Markdown files are built and
validated the same way as generated artifacts, with the sources appended.
"""
from __future__ import annotations

import asyncio
import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.kriton_workspace.artifacts import _render
from app.domains.kriton_workspace.models import Draft, SavedAnswer
from app.orchestration.models import QueryAnswerRecord

EXPORT_FORMATS = ("docx", "pdf", "md")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
# Kriton's inline citation markers ("[REF-7]"). Their numbers index the
# answer's citation list, not the de-duplicated Sources list an export
# carries, so they would point at the wrong entry or at none.
_REF_MARKER = re.compile(r"\s?\[REF-\d+\]")
# Characters the PDF fonts cannot draw (rendered as a filled box).
_EXPORT_CHARS = str.maketrans({"‐": "-", "‑": "-", " ": " ", " ": " "})


def clean_for_export(text: str) -> str:
    return _REF_MARKER.sub("", text).translate(_EXPORT_CHARS)


async def _owned_draft(db: AsyncSession, tenant_id: str, user_id: str, draft_id: str) -> Draft:
    row = (await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user_id, Draft.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return row


async def delete_draft(db: AsyncSession, tenant_id: str, user_id: str, draft_id: str) -> Draft:
    row = await _owned_draft(db, tenant_id, user_id, draft_id)
    await db.delete(row)
    await db.commit()
    return row


async def draft_sources(db: AsyncSession, tenant_id: str, user_id: str, draft_id: str) -> list[dict]:
    """The web sources of the answer a draft was created from, one per URL."""
    draft = await _owned_draft(db, tenant_id, user_id, draft_id)
    if not draft.saved_answer_id:
        return []
    answer = (await db.execute(
        select(SavedAnswer).where(SavedAnswer.id == draft.saved_answer_id, SavedAnswer.user_id == user_id,
                                  SavedAnswer.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if answer is None:
        return []
    record = (await db.execute(
        select(QueryAnswerRecord).where(QueryAnswerRecord.query_id == answer.query_id,
                                        QueryAnswerRecord.tenant_id == tenant_id)
    )).scalar_one_or_none()
    sources: list[dict] = []
    seen: set[str] = set()
    for item in (record.external_evidence if record else None) or []:
        url = (item or {}).get("url") or ""
        if not url.startswith("https://") or url in seen:
            continue
        seen.add(url)
        sources.append({"title": (item.get("title") or url)[:200], "url": url})
    return sources


def _with_sources(content: str, sources: list[dict]) -> str:
    if not sources:
        return content
    lines = [f"- {s['title']}: {s['url']}" for s in sources]
    return f"{content.rstrip()}\n\n## Sources\n\n" + "\n".join(lines) + "\n"


def export_filename(title: str, extension: str) -> str:
    stem = _UNSAFE_FILENAME.sub("", title).strip()[:80] or "draft"
    return f"{stem}.{extension}"


async def export_draft(db: AsyncSession, tenant_id: str, user_id: str, draft_id: str,
                       format_name: str) -> tuple[bytes, str, str, str]:
    """(file bytes, filename, mime type, title) for the draft in format_name."""
    if format_name not in EXPORT_FORMATS:
        raise HTTPException(status_code=422,
                            detail=f"Format must be one of: {', '.join(EXPORT_FORMATS)}")
    draft = await _owned_draft(db, tenant_id, user_id, draft_id)
    if not (draft.content or "").strip():
        raise HTTPException(status_code=422, detail="The draft is empty")
    narrative = _with_sources(clean_for_export(draft.content), await draft_sources(db, tenant_id, user_id, draft_id))
    title = clean_for_export(draft.title)
    content, extension, mime_type = await asyncio.to_thread(_render, format_name, title, narrative, {}, "")
    return content, export_filename(draft.title, extension), mime_type, draft.title

"""Workpapers: client job files with a maker-checker sign-off.

Who may do what (all within the user's tenant):
  see          the owner, the assigned reviewer, active members of the
               linked engagement, and Admins
  edit, add or remove items, submit for review
               the owner, while the workpaper is open (not in review,
               not signed off)
  sign off, return with a note
               the assigned reviewer only, never the owner (maker-checker),
               and only while it is in review
A signed-off workpaper is locked. Every change is audited by the router.

Items are the owner's own saved answers, drafts and documents; their titles
are resolved when the workpaper is read, so a deleted item shows as removed.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.models import Engagement, EngagementMembership, User
from app.domains.kriton_workspace.evidence_pack import build_evidence_pack, pack_filename
from app.domains.kriton_workspace.models import Document, Draft, SavedAnswer
from app.domains.kriton_workspace.workpaper_models import ITEM_KINDS, Workpaper, WorkpaperItem

_ITEM_MODELS = {"saved_answer": SavedAnswer, "draft": Draft, "document": Document}
_PACK_KIND = {"saved_answer": "saved-answer", "draft": "draft"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _item_title(kind: str, row) -> str:
    if kind == "saved_answer":
        return row.query_text
    if kind == "draft":
        return row.title
    return row.filename


async def _member_engagements(db: AsyncSession, user: User) -> set[str]:
    rows = await db.execute(select(EngagementMembership.engagement_id).where(
        EngagementMembership.tenant_id == user.tenant_id, EngagementMembership.user_id == user.id,
        EngagementMembership.status == "active", EngagementMembership.revoked_at.is_(None)))
    return set(rows.scalars())


def _can_see(wp: Workpaper, user: User, engagements: set[str]) -> bool:
    return (user.role == "Admin" or wp.owner_id == user.id or wp.reviewer_id == user.id
            or (wp.engagement_id is not None and wp.engagement_id in engagements))


async def _get(db: AsyncSession, user: User, workpaper_id: str) -> Workpaper:
    wp = (await db.execute(select(Workpaper).where(
        Workpaper.id == workpaper_id, Workpaper.tenant_id == user.tenant_id))).scalar_one_or_none()
    if wp is None or not _can_see(wp, user, await _member_engagements(db, user)):
        raise HTTPException(status_code=404, detail="Workpaper not found")
    return wp


def _require_owner_editable(wp: Workpaper, user: User) -> None:
    if wp.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the workpaper's owner can change it")
    if wp.status == "signed_off":
        raise HTTPException(status_code=409, detail="A signed-off workpaper is locked")
    if wp.status == "in_review":
        # The reviewer must sign off what they reviewed, so it cannot change underneath them.
        raise HTTPException(status_code=409, detail="The workpaper is in review; it can change once the reviewer returns it")


async def _check_reviewer(db: AsyncSession, user: User, reviewer_id: str | None) -> None:
    if not reviewer_id:
        return
    if reviewer_id == user.id:
        raise HTTPException(status_code=422, detail="You cannot review your own workpaper")
    reviewer = (await db.execute(select(User).where(
        User.id == reviewer_id, User.tenant_id == user.tenant_id, User.is_active.is_(True)))).scalar_one_or_none()
    if reviewer is None:
        raise HTTPException(status_code=422, detail="Reviewer not found in this workspace")


async def _check_engagement(db: AsyncSession, user: User, engagement_id: str | None) -> None:
    if not engagement_id:
        return
    found = (await db.execute(select(Engagement.id).where(
        Engagement.id == engagement_id, Engagement.tenant_id == user.tenant_id))).scalar_one_or_none()
    if found is None or (user.role != "Admin" and engagement_id not in await _member_engagements(db, user)):
        raise HTTPException(status_code=422, detail="Client job not found or you are not a member of it")


async def summary(db: AsyncSession, wp: Workpaper, user: User, with_items: bool = False) -> dict:
    names = {u.id: u.full_name or u.email for u in (await db.execute(select(User).where(
        User.id.in_([i for i in (wp.owner_id, wp.reviewer_id, wp.signed_off_by) if i])))).scalars()}
    engagement = None
    if wp.engagement_id:
        engagement = (await db.execute(select(Engagement.name).where(Engagement.id == wp.engagement_id))).scalar_one_or_none()
    rows = (await db.execute(select(WorkpaperItem).where(WorkpaperItem.workpaper_id == wp.id)
                             .order_by(WorkpaperItem.added_at))).scalars().all()
    out = {
        "id": wp.id, "title": wp.title, "period": wp.period, "status": wp.status,
        "engagementId": wp.engagement_id, "engagementName": engagement,
        "ownerId": wp.owner_id, "ownerName": names.get(wp.owner_id),
        "reviewerId": wp.reviewer_id, "reviewerName": names.get(wp.reviewer_id) if wp.reviewer_id else None,
        "signedOffBy": names.get(wp.signed_off_by) if wp.signed_off_by else None, "signedOffAt": _iso(wp.signed_off_at),
        "itemCount": len(rows), "createdAt": _iso(wp.created_at), "updatedAt": _iso(wp.updated_at),
        "canEdit": wp.owner_id == user.id and wp.status == "open",
        "canReview": wp.reviewer_id == user.id and wp.owner_id != user.id and wp.status == "in_review",
    }
    if with_items:
        out["notes"], out["reviewNote"] = wp.notes, wp.review_note
        items = []
        for row in rows:
            model = _ITEM_MODELS[row.kind]
            target = (await db.execute(select(model).where(model.id == row.item_id, model.tenant_id == wp.tenant_id))).scalar_one_or_none()
            items.append({"id": row.id, "kind": row.kind, "itemId": row.item_id, "note": row.note,
                          "title": _item_title(row.kind, target) if target else "(removed)", "missing": target is None,
                          "addedAt": _iso(row.added_at)})
        out["items"] = items
    return out


async def list_workpapers(db: AsyncSession, user: User) -> list[dict]:
    engagements = await _member_engagements(db, user)
    query = select(Workpaper).where(Workpaper.tenant_id == user.tenant_id)
    if user.role != "Admin":
        query = query.where(or_(Workpaper.owner_id == user.id, Workpaper.reviewer_id == user.id,
                                Workpaper.engagement_id.in_(engagements or {""})))
    rows = (await db.execute(query.order_by(Workpaper.updated_at.desc()))).scalars().all()
    return [await summary(db, wp, user) for wp in rows]


async def create_workpaper(db: AsyncSession, user: User, title: str, period: str,
                           engagement_id: str | None, reviewer_id: str | None) -> Workpaper:
    if not title.strip():
        raise HTTPException(status_code=422, detail="A title is required")
    await _check_engagement(db, user, engagement_id)
    await _check_reviewer(db, user, reviewer_id)
    wp = Workpaper(tenant_id=user.tenant_id, title=title.strip()[:200], period=period.strip()[:60],
                   engagement_id=engagement_id or None, reviewer_id=reviewer_id or None, owner_id=user.id)
    db.add(wp)
    await db.commit()
    return wp


async def update_workpaper(db: AsyncSession, user: User, workpaper_id: str, changes: dict) -> Workpaper:
    wp = await _get(db, user, workpaper_id)
    _require_owner_editable(wp, user)
    if "reviewer_id" in changes:
        await _check_reviewer(db, user, changes["reviewer_id"])
        wp.reviewer_id = changes["reviewer_id"] or None
    if "engagement_id" in changes:
        await _check_engagement(db, user, changes["engagement_id"])
        wp.engagement_id = changes["engagement_id"] or None
    for field, limit in (("title", 200), ("period", 60), ("notes", 20000)):
        if field in changes and changes[field] is not None:
            setattr(wp, field, str(changes[field])[:limit])
    if not wp.title.strip():
        raise HTTPException(status_code=422, detail="A title is required")
    await db.commit()
    return wp


async def submit(db: AsyncSession, user: User, workpaper_id: str) -> Workpaper:
    wp = await _get(db, user, workpaper_id)
    _require_owner_editable(wp, user)
    if not wp.reviewer_id:
        raise HTTPException(status_code=422, detail="Choose a reviewer before submitting")
    wp.status = "in_review"
    await db.commit()
    return wp


async def review(db: AsyncSession, user: User, workpaper_id: str, decision: str, note: str) -> Workpaper:
    wp = await _get(db, user, workpaper_id)
    if wp.reviewer_id != user.id or wp.owner_id == user.id:
        raise HTTPException(status_code=403, detail="Only the assigned reviewer can review this workpaper")
    if wp.status != "in_review":
        raise HTTPException(status_code=409, detail="The workpaper is not in review")
    if decision == "sign_off":
        wp.status, wp.signed_off_by, wp.signed_off_at = "signed_off", user.id, _now()
    elif decision == "return":
        if not note.strip():
            raise HTTPException(status_code=422, detail="Say what needs changing when returning a workpaper")
        wp.status = "open"
    else:
        raise HTTPException(status_code=422, detail="Decision must be sign_off or return")
    wp.review_note = note.strip()[:4000]
    await db.commit()
    return wp


async def add_item(db: AsyncSession, user: User, workpaper_id: str, kind: str, item_id: str, note: str) -> WorkpaperItem:
    wp = await _get(db, user, workpaper_id)
    _require_owner_editable(wp, user)
    if kind not in ITEM_KINDS:
        raise HTTPException(status_code=422, detail=f"Kind must be one of: {', '.join(ITEM_KINDS)}")
    model = _ITEM_MODELS[kind]
    owned = (await db.execute(select(model.id).where(
        model.id == item_id, model.user_id == user.id, model.tenant_id == user.tenant_id))).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=404, detail="Item not found among your own answers, drafts and documents")
    duplicate = (await db.execute(select(WorkpaperItem.id).where(
        WorkpaperItem.workpaper_id == wp.id, WorkpaperItem.kind == kind, WorkpaperItem.item_id == item_id))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="That item is already in this workpaper")
    row = WorkpaperItem(tenant_id=user.tenant_id, workpaper_id=wp.id, kind=kind, item_id=item_id,
                        note=note.strip()[:2000], added_by=user.id)
    db.add(row)
    wp.updated_at = _now()
    await db.commit()
    return row


async def remove_item(db: AsyncSession, user: User, workpaper_id: str, row_id: str) -> WorkpaperItem:
    wp = await _get(db, user, workpaper_id)
    _require_owner_editable(wp, user)
    row = (await db.execute(select(WorkpaperItem).where(
        WorkpaperItem.id == row_id, WorkpaperItem.workpaper_id == wp.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found in this workpaper")
    await db.delete(row)
    wp.updated_at = _now()
    await db.commit()
    return row


async def reviewers(db: AsyncSession, user: User) -> list[dict]:
    rows = (await db.execute(select(User).where(
        User.tenant_id == user.tenant_id, User.is_active.is_(True), User.id != user.id).order_by(User.full_name))).scalars()
    return [{"id": u.id, "name": u.full_name or u.email, "role": u.role} for u in rows]


async def workpaper_pack(db: AsyncSession, user: User, workpaper_id: str) -> tuple[bytes, str, dict]:
    """A ZIP with the workpaper's record and an evidence pack per answer or
    draft. Items belong to the owner, so their packs are built as the owner."""
    wp = await _get(db, user, workpaper_id)
    detail = await summary(db, wp, user, with_items=True)
    owner = SimpleNamespace(id=wp.owner_id, tenant_id=wp.tenant_id)
    buffer = io.BytesIO()
    included = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for n, item in enumerate(detail["items"], 1):
            if item["kind"] in _PACK_KIND and not item["missing"]:
                content, _, manifest = await build_evidence_pack(db, owner, _PACK_KIND[item["kind"]], item["itemId"])
                name = f"{n:02d} {pack_filename(item['title'])}"
                archive.writestr(name, content)
                included.append({"item": item["itemId"], "kind": item["kind"], "file": name, "counts": manifest["counts"]})
        record = {k: v for k, v in detail.items() if k not in {"canEdit", "canReview"}}
        manifest = {"pack": "ZoikoLogia workpaper pack", "workpaper": record, "evidencePacks": included,
                    "generated_at": _now().isoformat(), "generated_by": user.id,
                    "notes": ["Documents are listed but not included; download them from Kriton Workspace."]}
        archive.writestr("workpaper.json", json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    return buffer.getvalue(), pack_filename(f"Workpaper {wp.title}"), manifest

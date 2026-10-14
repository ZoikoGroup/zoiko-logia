"""Workpapers: visibility, owner-only editing, maker-checker sign-off, lock
after sign-off, own-items-only, audit, and the workpaper evidence pack
(app/domains/kriton_workspace/workpapers.py + router)."""
import io
import json
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Engagement, EngagementMembership, Tenant, User
from app.domains.kriton_workspace import router as ws, workpapers as wps
from app.domains.kriton_workspace.models import Document, Draft, SavedAnswer
from app.orchestration.models import QueryAnswerRecord

OWNER = User(id="owner", tenant_id="t1", email="o@x.com", full_name="Olivia Owner", role="Controller")
REVIEWER = User(id="rev", tenant_id="t1", email="r@x.com", full_name="Ravi Reviewer", role="Audit Partner")
MEMBER = User(id="mem", tenant_id="t1", email="m@x.com", full_name="Mia Member", role="Finance Manager")
STRANGER = User(id="str", tenant_id="t1", email="s@x.com", full_name="Sam Stranger", role="Finance Manager")
OUTSIDER = User(id="out", tenant_id="t2", email="x@y.com", full_name="Other Tenant", role="Admin")


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([
            Tenant(id="t1", name="T"), Tenant(id="t2", name="Other"),
            *(User(id=u.id, tenant_id=u.tenant_id, email=u.email, full_name=u.full_name, role=u.role)
              for u in (OWNER, REVIEWER, MEMBER, STRANGER, OUTSIDER)),
            Engagement(id="eng", tenant_id="t1", name="Zoiko Sema Ltd · Revenue"),
            EngagementMembership(id="m1", tenant_id="t1", engagement_id="eng", user_id="owner"),
            EngagementMembership(id="m2", tenant_id="t1", engagement_id="eng", user_id="mem"),
            SavedAnswer(id="sa1", tenant_id="t1", user_id="owner", query_id="q1", query_text="IFRS 15 five steps?",
                        answer_text="Identify the contract…", risk_level="LOW"),
            QueryAnswerRecord(query_id="q1", tenant_id="t1", user_id="owner", question="q", answer_text="a",
                              external_evidence=[{"title": "IFRS 15", "url": "https://www.ifrs.org/ifrs-15"}]),
            Draft(id="d1", tenant_id="t1", user_id="owner", title="Revenue memo", content="Memo", status="Final"),
            Document(id="doc1", tenant_id="t1", user_id="owner", filename="contract.pdf", storage_path="x", content_hash="h"),
            SavedAnswer(id="sa-rev", tenant_id="t1", user_id="rev", query_id="q9", query_text="Not the owner's",
                        answer_text="x", risk_level="LOW"),
        ])
        await session.commit()
        yield session
    await engine.dispose()


async def _new(db, **kw):
    return await ws.post_workpaper(ws.WorkpaperCreateRequest(title="Revenue recognition FY26", period="FY2026",
                                                             engagement_id="eng", reviewer_id="rev", **kw),
                                   db=db, current_user=OWNER)


async def _events(db) -> list[str]:
    return [e for (e,) in (await db.execute(select(AuditEvent.event_name).order_by(AuditEvent.ingested_at))).all()]


async def test_full_flow_create_attach_submit_sign_off_and_lock(db):
    wp = await _new(db)
    assert wp["status"] == "open" and wp["engagementName"] == "Zoiko Sema Ltd · Revenue" and wp["reviewerName"] == "Ravi Reviewer"
    for kind, item in (("saved_answer", "sa1"), ("draft", "d1"), ("document", "doc1")):
        wp = await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind=kind, item_id=item), db=db, current_user=OWNER)
    assert [i["title"] for i in wp["items"]] == ["IFRS 15 five steps?", "Revenue memo", "contract.pdf"]

    wp = await ws.submit_workpaper(wp["id"], db=db, current_user=OWNER)
    assert wp["status"] == "in_review" and wp["canEdit"] is False
    with pytest.raises(HTTPException) as err:            # cannot change under the reviewer
        await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind="draft", item_id="d1"), db=db, current_user=OWNER)
    assert err.value.status_code == 409
    reviewed = await ws.review_workpaper(wp["id"], ws.WorkpaperReviewRequest(decision="sign_off", note="Agreed"), db=db, current_user=REVIEWER)
    assert reviewed["status"] == "signed_off" and reviewed["signedOffBy"] == "Ravi Reviewer"

    with pytest.raises(HTTPException) as err:            # locked after sign-off
        await ws.patch_workpaper(wp["id"], ws.WorkpaperUpdateRequest(notes="late edit"), db=db, current_user=OWNER)
    assert err.value.status_code == 409
    assert await _events(db) == ["workpaper.created", "workpaper.item_added", "workpaper.item_added",
                                 "workpaper.item_added", "workpaper.submitted", "workpaper.signed_off"]


async def test_the_owner_can_never_sign_off_their_own_workpaper(db):
    with pytest.raises(HTTPException) as err:
        await ws.post_workpaper(ws.WorkpaperCreateRequest(title="Self review", reviewer_id="owner"), db=db, current_user=OWNER)
    assert err.value.status_code == 422
    wp = await _new(db)
    await ws.submit_workpaper(wp["id"], db=db, current_user=OWNER)
    for user in (OWNER, MEMBER):
        with pytest.raises(HTTPException) as err:
            await ws.review_workpaper(wp["id"], ws.WorkpaperReviewRequest(decision="sign_off"), db=db, current_user=user)
        assert err.value.status_code == 403


async def test_returning_needs_a_note_and_reopens_the_workpaper(db):
    wp = await _new(db)
    await ws.submit_workpaper(wp["id"], db=db, current_user=OWNER)
    with pytest.raises(HTTPException) as err:
        await ws.review_workpaper(wp["id"], ws.WorkpaperReviewRequest(decision="return"), db=db, current_user=REVIEWER)
    assert err.value.status_code == 422
    back = await ws.review_workpaper(wp["id"], ws.WorkpaperReviewRequest(decision="return", note="Add the contract"),
                                     db=db, current_user=REVIEWER)
    assert back["status"] == "open" and back["reviewNote"] == "Add the contract" and back["canEdit"] is False  # reviewer's view
    assert (await ws.get_workpaper(wp["id"], db=db, current_user=OWNER))["canEdit"] is True                     # owner can fix it


async def test_submitting_needs_a_reviewer(db):
    wp = await ws.post_workpaper(ws.WorkpaperCreateRequest(title="No reviewer"), db=db, current_user=OWNER)
    with pytest.raises(HTTPException) as err:
        await ws.submit_workpaper(wp["id"], db=db, current_user=OWNER)
    assert err.value.status_code == 422


async def test_visibility_owner_reviewer_engagement_member_but_not_others(db):
    wp = await _new(db)
    for user in (OWNER, REVIEWER, MEMBER):
        assert [w["id"] for w in await wps.list_workpapers(db, user)] == [wp["id"]]
        assert (await ws.get_workpaper(wp["id"], db=db, current_user=user))["id"] == wp["id"]
    for user in (STRANGER, OUTSIDER):
        assert await wps.list_workpapers(db, user) == []
        with pytest.raises(HTTPException) as err:
            await ws.get_workpaper(wp["id"], db=db, current_user=user)
        assert err.value.status_code == 404


async def test_only_the_owner_edits_and_only_their_own_items_can_be_attached(db):
    wp = await _new(db)
    with pytest.raises(HTTPException) as err:
        await ws.patch_workpaper(wp["id"], ws.WorkpaperUpdateRequest(notes="x"), db=db, current_user=MEMBER)
    assert err.value.status_code == 403
    with pytest.raises(HTTPException) as err:
        await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind="saved_answer", item_id="sa-rev"), db=db, current_user=OWNER)
    assert err.value.status_code == 404
    await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind="draft", item_id="d1"), db=db, current_user=OWNER)
    with pytest.raises(HTTPException) as err:
        await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind="draft", item_id="d1"), db=db, current_user=OWNER)
    assert err.value.status_code == 409


async def test_engagement_must_be_one_the_owner_belongs_to(db):
    with pytest.raises(HTTPException) as err:
        await ws.post_workpaper(ws.WorkpaperCreateRequest(title="x", engagement_id="eng"), db=db, current_user=STRANGER)
    assert err.value.status_code == 422


async def test_removed_item_and_deleted_source_show_honestly(db):
    wp = await _new(db)
    wp = await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind="draft", item_id="d1"), db=db, current_user=OWNER)
    await db.delete(await db.get(Draft, "d1"))
    await db.commit()
    detail = await ws.get_workpaper(wp["id"], db=db, current_user=OWNER)
    assert detail["items"][0]["title"] == "(removed)" and detail["items"][0]["missing"]
    after = await ws.remove_workpaper_item(wp["id"], detail["items"][0]["id"], db=db, current_user=OWNER)
    assert after["items"] == []


async def test_reviewer_can_download_the_pack_built_from_the_owners_items(db):
    wp = await _new(db)
    for kind, item in (("saved_answer", "sa1"), ("document", "doc1")):
        await ws.add_workpaper_item(wp["id"], ws.WorkpaperItemRequest(kind=kind, item_id=item), db=db, current_user=OWNER)
    response = await ws.download_workpaper_pack(wp["id"], db=db, current_user=REVIEWER)
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("workpaper.json"))
        inner = zipfile.ZipFile(io.BytesIO(archive.read(names[0])))
        assert "sources.json" in inner.namelist()
    assert len(manifest["evidencePacks"]) == 1 and manifest["evidencePacks"][0]["counts"]["sources"] == 1
    assert manifest["workpaper"]["title"] == "Revenue recognition FY26"
    assert "workpaper.pack_exported" in await _events(db)


async def test_reviewer_list_is_the_tenant_without_yourself(db):
    names = [r["name"] for r in await ws.get_workpaper_reviewers(db=db, current_user=OWNER)]
    assert names == ["Mia Member", "Ravi Reviewer", "Sam Stranger"]

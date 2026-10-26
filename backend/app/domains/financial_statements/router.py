"""Trial-balance intake API (Document 04 §11.1 operations).

POST /intake checks a file without storing it. The /trial-balances routes
store the upload and record every decision; all are tenant scoped, and
approving a mapping, reviewing a journal and approving the snapshot are each
refused to the person who prepared the work. Nothing is ever posted.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user

from . import store
from .intake import MAX_BYTES
from .service import run_intake

router = APIRouter(prefix="/financial-statements", tags=["Financial Statements"])


async def _read(file: UploadFile) -> bytes:
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 20 MB.")
    return content


async def _run(call):
    try:
        return await call
    except store.NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except store.Refused as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


class Allocation(BaseModel):
    line_id: str
    amount: str


class MappingDecision(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    line_id: str | None = None
    allocations: list[Allocation] = []
    evidence_ref: str = ""
    reason: str = ""


class JournalLineIn(BaseModel):
    line_id: str
    debit: str = "0"
    credit: str = "0"


class JournalIn(BaseModel):
    kind: str
    reason: str
    lines: list[JournalLineIn]
    evidence_refs: list[str] = []
    correction_type: str | None = None


class JournalReview(BaseModel):
    approve: bool


class ResolutionIn(BaseModel):
    """Entity facts for a Reporting Rules Resolution (Document 03)."""
    facts: dict
    trial_balance_id: str | None = None


@router.post("/resolve")
async def resolve_framework(body: ResolutionIn, user: User = Depends(get_current_user)) -> dict:
    """Stateless: which frameworks are permitted and which rules apply, nothing stored."""
    from .resolutions import facts_from
    from .standards import resolve
    try:
        return resolve(facts_from(body.facts)).to_dict()
    except store.Refused as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.post("/resolutions")
async def create_resolution(body: ResolutionIn, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.create(db, user, body.facts, body.trial_balance_id))


@router.get("/resolutions")
async def list_resolutions(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    from . import resolutions
    return await resolutions.list_for(db, user)


@router.get("/resolutions/{resolution_id}")
async def get_resolution(resolution_id: str, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.get(db, user, resolution_id))


class ReviewNote(BaseModel):
    note: str = ""


class JudgmentIn(BaseModel):
    key: str
    choice: str
    reason: str


class ReasonIn(BaseModel):
    reason: str


@router.post("/resolutions/{resolution_id}/approve")
async def approve_resolution(resolution_id: str, db: AsyncSession = Depends(get_db),
                             user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.approve(db, user, resolution_id))


@router.post("/resolutions/{resolution_id}/request-review")
async def request_resolution_review(resolution_id: str, body: ReviewNote, db: AsyncSession = Depends(get_db),
                                    user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.request_review(db, user, resolution_id, body.note))


@router.post("/resolutions/{resolution_id}/judgments")
async def record_resolution_judgment(resolution_id: str, body: JudgmentIn, db: AsyncSession = Depends(get_db),
                                     user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.record_judgment(db, user, resolution_id, body.key, body.choice, body.reason))


@router.post("/resolutions/{resolution_id}/reject")
async def reject_resolution(resolution_id: str, body: ReasonIn, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.reject(db, user, resolution_id, body.reason))


@router.post("/resolutions/{resolution_id}/revoke")
async def revoke_resolution(resolution_id: str, body: ReasonIn, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.revoke(db, user, resolution_id, body.reason))


@router.get("/resolutions/{resolution_id}/release-check")
async def resolution_release_check(resolution_id: str, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(get_current_user)) -> dict:
    from . import resolutions
    return await _run(resolutions.release_check(db, user, resolution_id))


@router.get("/catalogue")
async def catalogue(user: User = Depends(get_current_user)) -> dict:
    """Statement lines, correction types and supporting-record kinds for the screen's choices."""
    from .journals import CORRECTION_TYPES
    from .mapping import LINES
    from .supporting import KINDS
    return {"lines": [{"line_id": k, "label": label, "section": section} for k, (label, section) in LINES.items()],
            "correction_types": [{"code": k, "treatment": v} for k, v in CORRECTION_TYPES.items()],
            "supporting_kinds": [{"code": k, "line_id": line, "label": label} for k, (line, label) in KINDS.items()]}


@router.post("/intake")
async def intake_trial_balance(file: UploadFile = File(...), user: User = Depends(get_current_user)) -> dict:
    return run_intake(file.filename or "upload", await _read(file), uploaded_by=str(user.id)).to_dict()


@router.post("/trial-balances")
async def upload_trial_balance(file: UploadFile = File(...), supersedes_id: str | None = Form(None),
                               db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    content = await _read(file)
    return await _run(store.create(db, user, file.filename or "upload", content, supersedes_id or None))


@router.get("/trial-balances")
async def list_trial_balances(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    return await store.list_trial_balances(db, user)


@router.get("/trial-balances/{tb_id}")
async def get_trial_balance(tb_id: str, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict:
    return await _run(store.detail(db, user, tb_id))


@router.get("/trial-balances/{tb_id}/original")
async def download_original(tb_id: str, db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)) -> Response:
    filename, media_type, content = await _run(store.original(db, user, tb_id))
    return Response(content=content, media_type="application/octet-stream" if media_type == "rejected" else media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/trial-balances/{tb_id}/mappings/{mapping_id}/decision")
async def decide_mapping(tb_id: str, mapping_id: str, body: MappingDecision, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    return await _run(store.decide_mapping(
        db, user, tb_id, mapping_id, action=body.action, line_id=body.line_id,
        allocations=[(a.line_id, a.amount) for a in body.allocations] or None,
        evidence_ref=body.evidence_ref, reason=body.reason))


@router.post("/trial-balances/{tb_id}/journals")
async def propose_journal(tb_id: str, body: JournalIn, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)) -> dict:
    return await _run(store.add_journal(
        db, user, tb_id, kind=body.kind, reason=body.reason, evidence_refs=body.evidence_refs,
        correction_type=body.correction_type, lines=[(l.line_id, l.debit, l.credit) for l in body.lines]))


@router.post("/trial-balances/{tb_id}/journals/{journal_id}/review")
async def review_journal(tb_id: str, journal_id: str, body: JournalReview, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict:
    return await _run(store.review_journal(db, user, tb_id, journal_id, approve=body.approve))


@router.post("/trial-balances/{tb_id}/supporting")
async def add_supporting(tb_id: str, kind: str = Form(...), file: UploadFile = File(...),
                         db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    content = await _read(file)
    return await _run(store.add_supporting(db, user, tb_id, kind=kind, filename=file.filename or "upload",
                                           content=content))


@router.post("/trial-balances/{tb_id}/approve")
async def approve_snapshot(tb_id: str, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict:
    return await _run(store.approve(db, user, tb_id))


@router.get("/trial-balances/{tb_id}/lineage/{account_key}")
async def account_lineage(tb_id: str, account_key: str, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)) -> dict:
    return await _run(store.lineage(db, user, tb_id, account_key))

"""Trial-balance intake API (Document 04). Stateless: the uploaded file is
checked and returned with its findings and mapping proposals; nothing is
stored or posted."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user

from .intake import MAX_BYTES
from .service import run_intake

router = APIRouter(prefix="/financial-statements", tags=["Financial Statements"])


@router.post("/intake")
async def intake_trial_balance(file: UploadFile = File(...), user: User = Depends(get_current_user)) -> dict:
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 20 MB.")
    return run_intake(file.filename or "upload", content, uploaded_by=str(user.id)).to_dict()

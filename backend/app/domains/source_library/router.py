from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin, get_current_user
from app.domains.source_library.schemas import (
    ExpiringSourceOut,
    JurisdictionSummaryOut,
    SourceCreateRequest,
    SourcePublic,
)
from app.domains.source_library.service import (
    approve_source_version,
    create_source,
    get_jurisdiction_summary,
    get_soonest_expiring,
    get_source_file,
    list_sources,
    save_uploaded_file,
)

router = APIRouter(prefix="/sources", tags=["source_library"])


@router.get("", response_model=list[SourcePublic])
async def get_sources(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[SourcePublic]:
    sources = await list_sources(db, category, tenant_id=admin.tenant_id)
    return [SourcePublic.model_validate(s) for s in sources]


@router.get("/expiring", response_model=ExpiringSourceOut | None)
async def get_expiring_source(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ExpiringSourceOut | None:
    expiring = await get_soonest_expiring(db)
    return ExpiringSourceOut.model_validate(expiring) if expiring else None


@router.get("/jurisdiction-summary", response_model=list[JurisdictionSummaryOut])
async def get_jurisdiction_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[JurisdictionSummaryOut]:
    summaries = await get_jurisdiction_summary(db)
    return [JurisdictionSummaryOut.model_validate(s) for s in summaries]


@router.post("", response_model=SourcePublic)
async def post_source(
    category: str = Form(...),
    title: str = Form(...),
    source_class: str = Form(...),
    jurisdiction_scope: str = Form("Global"),
    framework_scope: str = Form(""),
    note: str = Form(""),
    effective_from: date | None = Form(None),
    effective_to: date | None = Form(None),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourcePublic:
    file_path = await save_uploaded_file(file, admin.tenant_id) if file is not None else None
    payload = SourceCreateRequest(
        category=category,
        title=title,
        source_class=source_class,
        jurisdiction_scope=jurisdiction_scope,
        framework_scope=framework_scope,
        note=note or (f"Uploaded: {file.filename}" if file is not None else ""),
        file_path=file_path,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    source = await create_source(db, admin.id, payload, tenant_id=admin.tenant_id)
    return SourcePublic.model_validate(source)


@router.get("/{source_id}/file")
async def get_source_file_endpoint(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    # Any authenticated tenant user (not require_admin) — this backs the
    # citation links shown in ordinary Ask Kriton chat answers, not just the
    # admin Source Library page, so it can't be admin-gated the way the rest
    # of this router is.
    file_path = await get_source_file(db, source_id, tenant_id=current_user.tenant_id)
    return FileResponse(file_path)


@router.post("/{source_id}/versions/{version_id}/approve", response_model=SourcePublic)
async def post_approve(
    source_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourcePublic:
    source = await approve_source_version(db, admin.id, source_id, version_id, tenant_id=admin.tenant_id)
    return SourcePublic.model_validate(source)

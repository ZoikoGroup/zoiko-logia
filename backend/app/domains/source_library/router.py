import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.domains.source_library.schemas import (
    ExpiringSourceOut,
    JurisdictionSummaryOut,
    SourceCreateRequest,
    SourcePassagePublic,
    SourcePublic,
    SourceRelationshipRequest,
    SourceRevocationRequest,
    SourceRightGrantRequest,
    SourceRightPublic,
    SourceUsagePublic,
    SourceVersionPublic,
)
from app.domains.source_library.service import (
    add_relationship,
    approve_source_version,
    create_source,
    expire_source_versions,
    find_impacted_usages,
    get_jurisdiction_summary,
    get_soonest_expiring,
    grant_source_right,
    list_passages,
    list_sources,
    revoke_source_version,
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
    publisher: str = Form(""),
    owner: str = Form(""),
    source_class: str = Form(...),
    jurisdiction_scope: str = Form("Global"),
    framework_scope: str = Form(""),
    note: str = Form(""),
    effective_from: date | None = Form(None),
    effective_to: date | None = Form(None),
    source_url: str | None = Form(None),
    published_at: datetime | None = Form(None),
    original_language: str = Form("en"),
    translation_of_version_id: str | None = Form(None),
    rights_json: str = Form("{}"),
    terms_reference: str = Form(""),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourcePublic:
    try:
        rights = json.loads(rights_json)
        if not isinstance(rights, dict) or any(not isinstance(value, bool) for value in rights.values()):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="rights_json must be an object of operation:boolean pairs") from exc
    if file is not None:
        missing = [op for op in ("ingestion", "indexing", "retention") if rights.get(op) is not True]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"File registration requires explicit allow rights for: {', '.join(missing)}",
            )
    file_path = await save_uploaded_file(file, admin.tenant_id) if file is not None else None
    payload = SourceCreateRequest(
        category=category,
        title=title,
        publisher=publisher,
        owner=owner,
        source_class=source_class,
        jurisdiction_scope=jurisdiction_scope,
        framework_scope=framework_scope,
        note=note or (f"Uploaded: {file.filename}" if file is not None else ""),
        file_path=file_path,
        effective_from=effective_from,
        effective_to=effective_to,
        source_url=source_url,
        published_at=published_at,
        original_language=original_language,
        translation_of_version_id=translation_of_version_id,
        rights=rights,
        terms_reference=terms_reference,
    )
    source = await create_source(db, admin.id, payload, tenant_id=admin.tenant_id)
    return SourcePublic.model_validate(source)


@router.post("/{source_id}/versions/{version_id}/approve", response_model=SourcePublic)
async def post_approve(
    source_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourcePublic:
    source = await approve_source_version(db, admin.id, source_id, version_id, tenant_id=admin.tenant_id)
    return SourcePublic.model_validate(source)


@router.post("/versions/{version_id}/rights", response_model=SourceRightPublic)
async def post_source_right(
    version_id: str,
    payload: SourceRightGrantRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourceRightPublic:
    right = await grant_source_right(
        db, version_id=version_id, tenant_id=admin.tenant_id,
        actor_id=admin.id, grant=payload,
    )
    return SourceRightPublic.model_validate(right)


@router.get("/versions/{version_id}/passages", response_model=list[SourcePassagePublic])
async def get_source_passages(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[SourcePassagePublic]:
    passages = await list_passages(db, version_id=version_id, tenant_id=admin.tenant_id)
    return [SourcePassagePublic.model_validate(passage) for passage in passages]


@router.post("/versions/{version_id}/relationships", status_code=201)
async def post_source_relationship(
    version_id: str,
    payload: SourceRelationshipRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    relationship = await add_relationship(
        db,
        from_version_id=version_id,
        to_version_id=payload.to_version_id,
        relationship_type=payload.relationship_type,
        tenant_id=admin.tenant_id,
        actor_id=admin.id,
    )
    return {"id": relationship.id, "relationship_type": relationship.relationship_type}


@router.post("/versions/{version_id}/revoke", response_model=SourceVersionPublic)
async def post_revoke_source_version(
    version_id: str,
    payload: SourceRevocationRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourceVersionPublic:
    version = await revoke_source_version(
        db, version_id=version_id, tenant_id=admin.tenant_id, reason=payload.reason,
    )
    return SourceVersionPublic.model_validate(version)


@router.get("/versions/{version_id}/impacts", response_model=list[SourceUsagePublic])
async def get_source_impacts(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[SourceUsagePublic]:
    usages = await find_impacted_usages(db, version_id=version_id, tenant_id=admin.tenant_id)
    return [SourceUsagePublic.model_validate(usage) for usage in usages]


@router.post("/lifecycle/expire")
async def post_expire_sources(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    return {"expired_count": await expire_source_versions(db)}

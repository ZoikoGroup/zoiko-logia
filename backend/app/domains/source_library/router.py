from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.domains.source_library.schemas import SourceCreateRequest, SourcePublic
from app.domains.source_library.service import approve_source_version, create_source, list_sources

router = APIRouter(prefix="/sources", tags=["source_library"])


@router.get("", response_model=list[SourcePublic])
async def get_sources(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[SourcePublic]:
    sources = await list_sources(db, category)
    return [SourcePublic.model_validate(s) for s in sources]


@router.post("", response_model=SourcePublic)
async def post_source(
    payload: SourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SourcePublic:
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

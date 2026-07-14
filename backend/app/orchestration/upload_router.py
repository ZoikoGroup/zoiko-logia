"""
POST /kriton/upload — Document ingestion endpoint.
Accepts a file upload, runs the full ingestion pipeline:
  save → parse (Docling primary / LlamaParse cloud fallback) → metadata → chunk → embed (see rag/embeddings.py) → store
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.source_library.upload_service import save_uploaded_file
from app.domains.source_library.parser_service import get_parser
from app.domains.source_library.metadata_service import extract_metadata_from_file
from app.domains.source_library.ingestion_service import ingest_document_content

router = APIRouter(prefix="/kriton", tags=["orchestration"])


class UploadResponse(BaseModel):
    status: str
    title: str
    chunks_stored: str
    tenant_id: str
    jurisdiction: str
    file_path: str


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    """
    Upload a document (PDF/DOCX/XLSX/PPTX) and trigger the full background ingestion pipeline:
    1. Save file to uploads/ directory
    2. Parse with Docling (local); LlamaParse cloud API as a fallback for
       documents Docling can't handle
    3. Auto-extract metadata (jurisdiction, version, tenant, etc.)
    4. Chunk into 512-token nodes, generate embeddings (see rag/embeddings.py)
    5. Store vectors in pgvector (Supabase) / local SimpleVectorStore
    """
    # 1. Save & validate
    file_path = save_uploaded_file(file)

    # 2. Parse — Docling primary, cloud fallback on failure
    parser = get_parser(prefer_cloud=False)
    try:
        markdown_content = await parser.parse_file(file_path)
    except Exception as e:
        try:
            fallback_parser = get_parser(prefer_cloud=True)
            markdown_content = await fallback_parser.parse_file(file_path)
        except Exception as fallback_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Document parsing failed on both Docling and cloud fallback. Docling error: {str(e)}. Cloud error: {str(fallback_err)}"
            )

    # 3. Metadata extraction
    meta = extract_metadata_from_file(file_path)
    # Inherit the authenticated user's tenant_id for proper isolation
    meta["tenant_id"] = current_user.tenant_id

    # 4. Ingest (chunk + embed + store)
    try:
        ingest_result = await ingest_document_content(file_path, markdown_content, meta, db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion pipeline failed: {str(e)}"
        )

    return UploadResponse(
        status="INGESTED",
        title=meta["title"],
        chunks_stored=ingest_result,
        tenant_id=meta["tenant_id"],
        jurisdiction=meta["jurisdiction_scope"],
        file_path=file_path,
    )

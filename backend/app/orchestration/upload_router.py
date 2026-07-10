"""
POST /kriton/upload — Document ingestion endpoint.
Accepts a file upload, runs the full ingestion pipeline:
  save → parse (LlamaParse / Docling fallback) → metadata → chunk → embed (bge-m3) → store
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
    2. Parse with LlamaParse API (Docling fallback if no API key)
    3. Auto-extract metadata (jurisdiction, version, tenant, etc.)
    4. Chunk into 512-token nodes, generate BAAI/bge-m3 embeddings
    5. Store vectors in pgvector / local SimpleVectorStore
    """
    # 1. Save & validate
    file_path = save_uploaded_file(file)

    # 2. Parse
    parser = get_parser(use_fallback=False)
    try:
        markdown_content = await parser.parse_file(file_path)
    except Exception as e:
        # Fallback to local parsing (pypdf/docx/etc) if LlamaParse fails or has an invalid mock key
        try:
            fallback_parser = get_parser(use_fallback=True)
            markdown_content = await fallback_parser.parse_file(file_path)
        except Exception as fallback_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Document parsing failed on both cloud and local fallback. Cloud Error: {str(e)}. Local Error: {str(fallback_err)}"
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

"""
Object storage for the original uploaded files, via Supabase Storage's REST
API over plain httpx.

No new SDK: the API is three HTTP calls, httpx is already a dependency, and
SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are already configured for Auth. The
service-role key bypasses Storage RLS, which is correct here because tenant
scoping is enforced in the path (see _object_path) and by the RLS policies on
user_documents / document_chunks — the bucket is never exposed to a browser.

Storage is OPTIONAL. Retrieval reads chunks out of Postgres, never the original
file, so a failed or unconfigured upload must not fail the ingest: the document
is still fully answerable, it just cannot be downloaded again later. That is a
real, bounded loss and it is recorded on the row (storage_path stays empty)
rather than hidden.
"""
from __future__ import annotations

import os

import httpx

# Created on first use if missing. Kept private — downloads go through the API
# with the caller's own token, never a public bucket URL.
BUCKET = "kriton-documents"

_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _base_url() -> str:
    return (os.getenv("SUPABASE_URL") or "").rstrip("/")


def _service_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""


def is_configured() -> bool:
    return bool(_base_url() and _service_key())


def _headers() -> dict[str, str]:
    key = _service_key()
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _object_path(tenant_id: str, document_id: str, extension: str) -> str:
    """Tenant id first so a bucket listing can never mix tenants, and the
    document id (a uuid) as the name so a hostile filename cannot traverse out
    of its prefix. The original filename lives on the DB row, not in the path."""
    return f"{tenant_id}/{document_id}{extension}"


async def _ensure_bucket(client: httpx.AsyncClient) -> None:
    """Create the private bucket if it does not exist. A 400/409 here means it
    already exists, which is success."""
    response = await client.post(
        f"{_base_url()}/storage/v1/bucket",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"id": BUCKET, "name": BUCKET, "public": False},
    )
    if response.status_code not in (200, 201, 400, 409):
        response.raise_for_status()


async def upload(tenant_id: str, document_id: str, extension: str, data: bytes) -> str:
    """Store the original file and return its object path, or "" if storage is
    unavailable. Never raises: see the module docstring on why a storage
    failure must not fail the ingest."""
    if not is_configured():
        return ""
    path = _object_path(tenant_id, document_id, extension)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await _ensure_bucket(client)
            response = await client.post(
                f"{_base_url()}/storage/v1/object/{BUCKET}/{path}",
                headers={
                    **_headers(),
                    "Content-Type": _CONTENT_TYPES.get(extension, "application/octet-stream"),
                    # Same document id can only be ingested once, but an
                    # interrupted retry should overwrite rather than 409.
                    "x-upsert": "true",
                },
                content=data,
            )
            response.raise_for_status()
        return path
    except Exception as exc:
        print(f"WARNING: document {document_id} stored in DB but not in object storage: {exc}")
        return ""


async def download(path: str) -> bytes | None:
    """Fetch a stored original. None when storage is unconfigured, the path is
    empty, or the object is gone."""
    if not path or not is_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_base_url()}/storage/v1/object/{BUCKET}/{path}", headers=_headers()
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
    except Exception as exc:
        print(f"WARNING: could not download stored document {path}: {exc}")
        return None


async def delete(path: str) -> bool:
    """Remove a stored original. Returns whether the object is now gone."""
    if not path or not is_configured():
        return True
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.delete(
                f"{_base_url()}/storage/v1/object/{BUCKET}/{path}", headers=_headers()
            )
            return response.status_code in (200, 204, 404)
    except Exception as exc:
        print(f"WARNING: could not delete stored document {path}: {exc}")
        return False

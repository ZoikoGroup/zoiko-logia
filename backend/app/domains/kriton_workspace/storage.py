from __future__ import annotations

from urllib.parse import quote
import httpx

from app.core.config import get_settings


def uses_supabase() -> bool:
    return get_settings().OBJECT_STORAGE_PROVIDER.lower() == "supabase"


def _headers(content_type: str | None = None) -> dict[str, str]:
    settings = get_settings()
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _url(bucket: str, object_path: str) -> str:
    settings = get_settings()
    return f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/{quote(bucket)}/{quote(object_path, safe='/')}"


async def upload_object(bucket: str, object_path: str, content: bytes, mime_type: str) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            _url(bucket, object_path), content=content,
            headers={**_headers(mime_type), "x-upsert": "false"},
        )
        response.raise_for_status()


async def download_object(bucket: str, object_path: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(_url(bucket, object_path), headers=_headers())
        response.raise_for_status()
        return response.content


async def delete_object(bucket: str, object_path: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.delete(_url(bucket, object_path), headers=_headers())
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()

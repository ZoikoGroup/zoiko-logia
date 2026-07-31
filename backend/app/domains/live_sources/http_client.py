import httpx

from app.core.config import get_settings

_shared_client: httpx.AsyncClient | None = None


def get_shared_http_client() -> httpx.AsyncClient:
    """Returns a module-level shared httpx.AsyncClient singleton with connection pooling
    and TCP keep-alive configured for all live source connectors.
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        settings = get_settings()
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.LIVE_SOURCE_HTTP_TIMEOUT_SECONDS, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            follow_redirects=True,
        )
    return _shared_client


async def close_shared_http_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None

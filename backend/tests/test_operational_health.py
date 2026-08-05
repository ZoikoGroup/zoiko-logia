import pytest

from app.core.config import get_settings
from app.core.database import _pool_options
from app.main import app


def _endpoint(path: str):
    return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)


@pytest.mark.asyncio
async def test_liveness_endpoint_is_dependency_free():
    assert await _endpoint("/health")() == {
        "status": "ok",
        "service": "zoikologia-backend",
    }


@pytest.mark.asyncio
async def test_readiness_endpoint_checks_database():
    assert await _endpoint("/ready")() == {"status": "ready", "database": "ok"}


def test_hosted_database_pool_is_bounded():
    settings = get_settings()
    options = _pool_options("postgresql+asyncpg://example/db")
    assert options == {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
    }
    assert _pool_options("sqlite+aiosqlite:///./test.db") == {}

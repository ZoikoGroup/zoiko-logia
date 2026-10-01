"""A slow Supabase connection surfaced in the browser as a CORS error."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core import database


@pytest.mark.asyncio
async def test_request_connection_is_retried_once(monkeypatch):
    connection = object()
    connect = AsyncMock(side_effect=[TimeoutError(), connection])
    monkeypatch.setattr(database, "request_engine", SimpleNamespace(connect=connect))
    monkeypatch.setattr(database.asyncio, "sleep", AsyncMock())

    assert await database._open_request_connection() is connection
    assert connect.await_count == 2


@pytest.mark.asyncio
async def test_a_second_failure_still_raises(monkeypatch):
    monkeypatch.setattr(database, "request_engine", SimpleNamespace(connect=AsyncMock(side_effect=TimeoutError())))
    monkeypatch.setattr(database.asyncio, "sleep", AsyncMock())
    with pytest.raises(TimeoutError):
        await database._open_request_connection()


def test_timeout_is_a_503_with_cors_headers():
    from app.main import app

    @app.get("/__test_timeout")
    async def _boom():
        raise TimeoutError()

    origin = "http://localhost:3000"
    # Not entered as a context manager: the app's startup (database DDL) is
    # not needed to check error handling.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test_timeout", headers={"Origin": origin})
    assert response.status_code == 503
    assert response.headers.get("access-control-allow-origin") == origin
    assert "try again" in response.json()["detail"]

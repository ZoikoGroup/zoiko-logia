import json

import pytest
from fastapi.testclient import TestClient

import app.main as main


def _endpoint(app, path: str):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path
    )


@pytest.mark.asyncio
async def test_liveness_does_not_depend_on_database():
    response = await _endpoint(
        main.create_app(),
        "/health/live",
    )()
    assert response == {"status": "live"}


@pytest.mark.asyncio
async def test_readiness_fails_closed_without_database(
    monkeypatch,
):
    class UnavailableEngine:
        def connect(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        main,
        "async_engine",
        UnavailableEngine(),
    )
    response = await _endpoint(
        main.create_app(),
        "/health/ready",
    )()
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "not_ready",
        "database": "unavailable",
    }


def test_http_responses_include_security_headers():
    client = TestClient(main.create_app())
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["strict-transport-security"] == "max-age=31536000"

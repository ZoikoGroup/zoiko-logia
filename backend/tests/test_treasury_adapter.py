"""
Treasury Fiscal Data adapter + /internal/reference/exchange-rates smoke test.

Part 1 makes a real network call to the public Treasury Fiscal Data API.
Part 2 exercises the actual FastAPI endpoint (audit event included), which
needs a live DB connection exactly like the rest of this project's tests
(see test_massarius_tenant_scope.py) — get_current_user is overridden with
a fake user so the test doesn't need a real Supabase JWT.

Run locally (from backend/, with the venv active and backend/.env sourced
so DATABASE_URL is set):
    python3 tests/test_treasury_adapter.py
"""
import asyncio
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.reference_data.adapters.treasury_adapter import get_exchange_rates
from app.main import app

_FAKE_USER = User(
    id="test-script-user",
    tenant_id="GLOBAL_CONTROL",
    email="test-script@zoikologia.local",
    full_name="Test Script",
    role="Admin",
    is_active=True,
)

requires_network = pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="set RUN_NETWORK_TESTS=1 to run live Treasury integration tests",
)


@requires_network
async def test_get_exchange_rates_returns_data():
    data = await get_exchange_rates(since="2020-01-01")
    assert isinstance(data, list)
    assert len(data) > 0
    assert "exchange_rate" in data[0]
    assert "record_date" in data[0]
    print("test_get_exchange_rates_returns_data: PASSED")


@requires_network
def test_exchange_rates_endpoint():
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        with TestClient(app) as client:
            response = client.get("/internal/reference/exchange-rates", params={"since": "2020-01-01"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_name"] == "US Treasury Fiscal Data"
    assert body["licence_status"] == "public_no_auth"
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0
    print("test_exchange_rates_endpoint: PASSED")


if __name__ == "__main__":
    asyncio.run(test_get_exchange_rates_returns_data())
    test_exchange_rates_endpoint()

import pytest

from app.domains.reference_data.service import _retry_external


@pytest.mark.asyncio
async def test_reference_boundary_retries_transient_failure():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("request failed: temporary connection reset")
        return {"ok": True}

    assert await _retry_external(operation) == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_reference_boundary_does_not_retry_auth_failure():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        raise RuntimeError("API authentication failed")

    with pytest.raises(RuntimeError, match="authentication"):
        await _retry_external(operation)
    assert calls == 1

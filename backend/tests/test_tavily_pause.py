"""A used-up Tavily plan (HTTP 432) is reported with its reason and paused,
instead of a bare "HTTPStatusError" and a wasted call on every search."""
import httpx

from app.orchestration import websearch


def _reply(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", websearch._TAVILY_URL))


async def test_a_quota_failure_pauses_tavily_and_says_why(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setitem(websearch._tavily_paused, "until", 0.0)
    calls = []

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers, json):
            calls.append(json)
            return _reply(432, {"detail": {"error": "This request exceeds your plan's set usage limit."}})

    monkeypatch.setattr(websearch.httpx, "AsyncClient", _Client)
    assert await websearch._tavily_results("vat threshold", []) is None      # falls back
    status = websearch.tavily_status()
    assert status["paused"] and "HTTP 432" in status["reason"] and "usage limit" in status["reason"]
    assert await websearch._tavily_results("another search", []) is None
    assert len(calls) == 1                                                     # not retried while paused


async def test_a_one_off_server_error_does_not_pause(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setitem(websearch._tavily_paused, "until", 0.0)
    websearch._pause_tavily(_reply(500, {"detail": "oops"}))
    assert not websearch.tavily_status()["paused"]

"""Task Contract, Stage C-2a (shadow): which fetches retrieval would make for
each part the contract says needs an official figure or rule. Not collected
by the normal test run; run it explicitly:

    RETRIEVAL_FETCH_REPORT=report.json RETRIEVAL_QUESTIONS=questions.json \
        python -m pytest -q tests/retrieval_fetch_report.py

The real retrieval code runs with every outbound HTTP request recorded and
then refused (and sockets blocked), so nothing leaves the machine: the report
shows what each path would try to fetch, not what it would get back.
- prefetch: web_search_each and fetch_live_data on the whole question (the
  standard path, which fetches before composition);
- agent: web_search_each on the part's own wording (the agent path, where the
  model searches with its own query; the part's wording stands in for it).
Each fetch is classed as official (a government, regulator, central bank or
standard setter), search (the search engine) or other. No model is called.
"""
import asyncio
import json
import os
import socket
from pathlib import Path

import httpx
import pytest

from app.orchestration.task_contract import build_task_contract

EVALS = Path(__file__).resolve().parents[1] / "evals"
_OFFICIAL_HOSTS = ("gov.uk", "gov.sg", "gov.in", "nic.in", "gov.ae", "gov.my", "bankofengland.co.uk", "frankfurter",
                   "ecb.europa.eu", "irs.gov", "ato.gov.au", "oecd.org", "ifrs.org", "rba.gov.au", "cso.ie", "treasury.gov",
                   "sec.gov", "bankofcanada.ca", "gstcouncil.gov.in", "fasb.org", "iaasb.org", "abs.gov.au", "fred.stlouisfed.org",
                   "db.nomics.world")
_SEARCH_HOSTS = ("searx", "tavily", "localhost", "127.0.0.1", "duckduckgo", "bing", "google")


def _kind(host: str) -> str:
    if any(marker in host for marker in _SEARCH_HOSTS):
        return "search"
    if any(host == marker or host.endswith("." + marker) or marker in host for marker in _OFFICIAL_HOSTS):
        return "official"
    return "other"


class _Recorder:
    def __init__(self):
        self.urls: list[str] = []

    async def send(self, client, request, *args, **kwargs):
        self.urls.append(str(request.url))
        raise httpx.ConnectError("offline report: request refused", request=request)

    def take(self) -> list[dict]:
        seen = []
        for url in self.urls:
            host = httpx.URL(url).host
            entry = {"host": host, "path": httpx.URL(url).path[:80], "kind": _kind(host)}
            if entry not in seen:
                seen.append(entry)
        self.urls.clear()
        return seen


def _questions() -> list[str]:
    questions = [case["query"] for case in json.load(open(EVALS / "retrieval_requirement_expectations.json"))["cases"]]
    extra = os.environ.get("RETRIEVAL_QUESTIONS")
    if extra:
        questions += json.load(open(extra))
    return list(dict.fromkeys(q.strip() for q in questions if q.strip()))


@pytest.fixture
def offline(monkeypatch):
    recorder = _Recorder()

    async def send(self, request, *args, **kwargs):
        return await recorder.send(self, request, *args, **kwargs)

    def refuse(*args, **kwargs):
        raise OSError("offline report: socket refused")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("EVIDENCE_PLANNING", "off")
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "0")
    return recorder


async def _run(coroutine, recorder) -> list[dict]:
    try:
        await asyncio.wait_for(coroutine, timeout=30)
    except Exception:  # noqa: BLE001 — refused requests are the point
        pass
    return recorder.take()


async def test_retrieval_fetch_report(offline):
    from app.orchestration.live_data import fetch_live_data
    from app.orchestration.websearch import web_search_each
    rows = []
    for question in _questions():
        official = [r for r in build_task_contract(question).retrieval if r.needs_official]
        if not official:
            continue
        prefetch = await _run(web_search_each(question, limit=5), offline)
        prefetch += [f for f in await _run(fetch_live_data(question), offline) if f not in prefetch]
        for requirement in official:
            agent = await _run(web_search_each(requirement.part, limit=5), offline)
            rows.append({"question": question[:200], "part": requirement.part[:160], "fact": requirement.fact_type,
                         "jurisdictions": requirement.jurisdictions, "publisher": requirement.publisher,
                         "connector": requirement.connector,
                         "official_pages": [title for title, _ in requirement.official_pages],
                         "prefetch": prefetch, "agent": agent,
                         "prefetch_official": sorted({f["host"] for f in prefetch if f["kind"] == "official"}),
                         "agent_official": sorted({f["host"] for f in agent if f["kind"] == "official"})})
    out = os.environ.get("RETRIEVAL_FETCH_REPORT")
    if out:
        Path(out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))

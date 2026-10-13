"""Web-search result cache — orchestration/websearch.py.

The cache exists to keep the upstream engines from blocking the instance, not
to save milliseconds, so these tests assert on CALL COUNT rather than timing.

The cache lives in Redis. These tests stand a fake in for it rather than
requiring a running server, but the fake stores the same serialised strings
the module writes, so the JSON round trip is still exercised — a fake holding
WebSource objects directly would hide exactly the bugs this layer introduced.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.orchestration import websearch
from app.orchestration.websearch import WebSource


class _FakeRedis:
    """Minimal async stand-in: the get/psetex pair the cache actually uses."""

    def __init__(self):
        self.store: dict[str, tuple[float, str]] = {}
        self.writes: list[tuple[str, int, str]] = []

    async def get(self, key):
        entry = self.store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self.store[key]
            return None
        return value

    async def psetex(self, key, ttl_ms, value):
        self.writes.append((key, ttl_ms, value))
        self.store[key] = (time.monotonic() + ttl_ms / 1000.0, value)


class _BrokenRedis:
    """Every call raises — stands in for a stopped or unreachable server."""

    async def get(self, key):
        raise ConnectionError("redis is down")

    async def psetex(self, key, ttl_ms, value):
        raise ConnectionError("redis is down")


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(websearch, "_client", lambda: fake)
    return fake


def _fake_searxng(monkeypatch, results, counter):
    """Replace the HTTP call with a counted stub returning `results`."""

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": results}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url="", *a, **kw):
            # Count trips to the search engine only — reading the top official
            # pages (websearch._with_page_extracts) is a separate request.
            if str(url).endswith("/search"):
                counter.append(1)
            return _Resp()

    monkeypatch.setattr(websearch.httpx, "AsyncClient", _Client)


_IRS_HIT = [
    {"title": "Federal income tax rates", "url": "https://www.irs.gov/filing/rates", "content": "Brackets."}
]


def test_second_identical_query_does_not_reach_the_engines(monkeypatch):
    """The whole point: a repeated question makes ONE upstream request.

    Development asked the same handful of questions dozens of times, which is
    what got the instance suspended by Google and CAPTCHA'd by DuckDuckGo.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        first = await websearch.web_search("How is federal income tax calculated in the US?")
        second = await websearch.web_search("How is federal income tax calculated in the US?")
        return first, second

    first, second = asyncio.run(run())

    assert len(calls) == 1, "second identical query went back out to the engines"
    assert [s.url for s in first] == [s.url for s in second]


def test_empty_results_are_never_cached(monkeypatch, fake_redis):
    """A blocked engine and a genuine no-match both look like results: [].

    Caching that would pin "no sources" in place for the whole TTL and keep
    serving it after the block lifted — so an empty result must always retry.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, [], calls)
    monkeypatch.setattr(websearch, "_EMPTY_RETRY_DELAY_SECONDS", 0)

    async def run():
        await websearch.web_search("a question nothing matches")
        first = len(calls)
        await websearch.web_search("a question nothing matches")
        return first

    first = asyncio.run(run())

    # The second search goes upstream again, exactly as the first did
    # (including its retries), rather than reading a cached empty.
    assert first >= 2 and len(calls) == 2 * first, "an empty result was cached, freezing the outage in"
    assert not fake_redis.store


def test_untrusted_fallback_results_are_never_cached(monkeypatch, fake_redis):
    """With Tavily timing out, the backup engine answered a GSTR-3B question
    with dictionary pages; cached, they were served for the whole TTL."""
    calls: list[int] = []
    junk = [{"title": "DUE | meaning", "url": "https://dictionary.example.org/due",
             "content": "Due date for GSTR-3B monthly filers: dictionary meaning of due."}]
    _fake_searxng(monkeypatch, junk, calls)

    async def run():
        await websearch.web_search("What is the due date for GSTR-3B for monthly filers?")
        first = len(calls)
        await websearch.web_search("What is the due date for GSTR-3B for monthly filers?")
        return first

    first = asyncio.run(run())

    assert first >= 1 and len(calls) == 2 * first, "an untrusted-only result was cached"
    assert not fake_redis.store


def test_query_whitespace_and_case_share_one_entry(monkeypatch):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        await websearch.web_search("federal income tax")
        await websearch.web_search("  Federal   INCOME  tax ")

    asyncio.run(run())
    assert len(calls) == 1


def test_jurisdiction_is_part_of_the_key(monkeypatch):
    """Different jurisdictions resolve different allowlists, so they must not
    share a cache entry — a UK answer served for a US question would cite the
    wrong authority."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        await websearch.web_search("vat threshold", jurisdiction="UK")
        await websearch.web_search("vat threshold", jurisdiction="US")

    asyncio.run(run())
    assert len(calls) == 2


def test_expired_entry_is_refetched(monkeypatch):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "0.05")

    async def run():
        await websearch.web_search("federal income tax")
        await asyncio.sleep(0.1)
        await websearch.web_search("federal income tax")

    asyncio.run(run())
    assert len(calls) == 2


def test_ttl_of_zero_disables_the_cache(monkeypatch, fake_redis):
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "0")

    async def run():
        await websearch.web_search("federal income tax")
        await websearch.web_search("federal income tax")

    asyncio.run(run())
    assert len(calls) == 2
    assert not fake_redis.store


def test_entries_are_written_with_an_expiry(monkeypatch, fake_redis):
    """Expiry moved to the server when the dict went away.

    Nothing sweeps this cache any more, so a write without a TTL would sit in
    Redis until someone flushed it by hand — serving last month's guidance as
    though it were current.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setenv("SEARXNG_CACHE_TTL_SECONDS", "3600")

    asyncio.run(websearch.web_search("federal income tax"))

    assert len(fake_redis.writes) == 1
    key, ttl_ms, _ = fake_redis.writes[0]
    assert ttl_ms == 3_600_000
    assert key.startswith(websearch._CACHE_KEY_PREFIX), "cache key lost its version prefix"


def test_a_redis_outage_still_answers(monkeypatch):
    """Fail open. Losing the cache must cost the saved search, never the answer.

    This is the failure mode the dict could not have — it is the price of
    moving the cache out of process, and the reason every call is wrapped.
    """
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)
    monkeypatch.setattr(websearch, "_client", lambda: _BrokenRedis())

    async def run():
        first = await websearch.web_search("federal income tax")
        second = await websearch.web_search("federal income tax")
        return first, second

    first, second = asyncio.run(run())

    assert [s.url for s in first] == ["https://www.irs.gov/filing/rates"]
    assert [s.url for s in second] == ["https://www.irs.gov/filing/rates"]
    assert len(calls) == 2, "a dead cache should mean every query searches, not that it fails"


def test_an_unreadable_entry_is_treated_as_a_miss(monkeypatch, fake_redis):
    """Junk under a live key — a partial write, or a shape from an older build
    that shared this prefix — must refetch rather than raise."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    key = websearch._cache_key("federal income tax", "", 5)
    fake_redis.store[key] = (time.monotonic() + 60, "{not json at all")

    results = asyncio.run(websearch.web_search("federal income tax"))

    assert len(calls) == 1
    assert [s.url for s in results] == ["https://www.irs.gov/filing/rates"]


def test_provenance_fields_survive_the_round_trip(monkeypatch, fake_redis):
    """WebSource carries optional provenance. JSON is now in the middle of
    every hit, so a field dropped in encode/decode would silently strip
    freshness from a cached answer while the first answer kept it."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    source = WebSource(
        title="t",
        url="https://www.irs.gov/x",
        snippet="s",
        provider="searxng",
        fetched_at="2026-09-24T00:00:00Z",
        freshness="historical",
        source_id="doc-1",
    )
    assert websearch._decode(websearch._encode([source])) == [source]


def test_a_returned_list_cannot_mutate_the_cache(monkeypatch):
    """Callers get their own objects — appending to a result must not poison
    later hits."""
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)

    async def run():
        first = await websearch.web_search("federal income tax")
        first.append(WebSource(title="injected", url="https://example.com", snippet=""))
        return await websearch.web_search("federal income tax")

    second = asyncio.run(run())
    assert [s.url for s in second] == ["https://www.irs.gov/filing/rates"]


def test_trusted_domain_results_must_be_about_the_question():
    # Reported live: a compound-interest question was "source grounded" in
    # five OECD/ILO reports that merely sit on allowlisted domains.
    query = "If I invest $10,000 at 8% a year compounded annually, what will it be worth after 10 years?"
    unrelated = WebSource(
        title="Health at a Glance: Latin America and the Caribbean 2026 (EN)", url="https://www.oecd.org/x",
        snippet="The OECD, IDB and The World Bank shall not be liable for any content or error in this translation.",
    )
    assert not websearch._is_relevant(query, unrelated)
    relevant = WebSource(
        title="What to include in a VAT Return - GOV.UK", url="https://www.gov.uk/submit-vat-return",
        snippet="You can account for import VAT on your VAT Return.",
    )
    assert websearch._is_relevant("Who can sign off a VAT return in the UK?", relevant)


def _fake_tavily(monkeypatch, responses: list[list[dict]], bodies: list[dict]):
    """Stub Tavily: each POST returns the next result list in `responses`."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    queue = list(responses)

    class _Resp:
        def __init__(self, results):
            self._results = results

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": self._results}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *a, json=None, **kw):
            bodies.append(json)
            return _Resp(queue.pop(0) if queue else [])

        async def get(self, *a, **kw):
            raise AssertionError("SearXNG must not be called when Tavily answered")

    monkeypatch.setattr(websearch.httpx, "AsyncClient", _Client)


_TAVILY_HIT = [{
    "url": "https://www.gov.uk/guidance/authorise-an-agent-to-deal-with-certain-tax-services-for-you",
    "title": "Authorise an agent to deal with certain tax services for you - GOV.UK",
    "content": "If you authorise your agent for Making Tax Digital for VAT, they can submit VAT returns for you.",
    "score": 0.8,
}]


def test_tavily_is_searched_first_within_the_trusted_domains(monkeypatch):
    bodies: list[dict] = []
    _fake_tavily(monkeypatch, [_TAVILY_HIT], bodies)
    results = asyncio.run(websearch.web_search("Who can submit a VAT return in the UK?", read_pages=0))
    assert [s.url for s in results] == [_TAVILY_HIT[0]["url"]]
    assert bodies[0]["include_domains"] and bodies[0]["search_depth"] == "advanced"
    assert len(bodies) == 1


def test_tavily_widens_to_the_open_web_only_when_trusted_domains_are_empty(monkeypatch):
    bodies: list[dict] = []
    _fake_tavily(monkeypatch, [[], _TAVILY_HIT], bodies)
    results = asyncio.run(websearch.web_search("Who can submit a VAT return in the UK?", read_pages=0))
    assert results and len(bodies) == 2
    assert "include_domains" not in bodies[1] and bodies[1]["search_depth"] == "basic"


def test_tavily_failure_falls_back_to_searxng(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    calls: list[int] = []
    _fake_searxng(monkeypatch, _IRS_HIT, calls)  # its client has no post(): Tavily raises
    results = asyncio.run(websearch.web_search("federal income tax", read_pages=0))
    assert results and len(calls) == 1


def test_a_page_about_a_different_procedure_is_not_a_source():
    # Reported live: "Who can sign off a VAT return?" was answered with the
    # claimant-signature rules of the VAT refund page, even with a prompt rule.
    refund_page = WebSource(
        title="Refunds of UK VAT for non-UK businesses (VAT Notice 723A) - GOV.UK",
        url="https://www.gov.uk/guidance/refunds-of-uk-vat-for-non-uk-businesses",
        snippet="The claim must be signed by the claimant or an agent holding a power of attorney.",
    )
    assert not websearch._is_relevant("Who can sign off a VAT return in the UK?", refund_page)
    assert websearch._is_relevant("How do I claim a VAT refund as a non-UK business?", refund_page)


def test_a_slow_sub_question_does_not_discard_the_others(monkeypatch):
    monkeypatch.setattr(websearch, "_SUB_SEARCH_TIMEOUT_SECONDS", 0.2)

    async def fake_search(part, **kwargs):
        if "slow" in part:
            await asyncio.sleep(1)
        return [WebSource(title=part, url=f"https://www.gov.uk/{abs(hash(part))}", snippet=part)]

    monkeypatch.setattr(websearch, "web_search", fake_search)
    results = asyncio.run(websearch.web_search_each("What is the fast answer? What is the slow answer?"))
    assert [s.title for s in results] == ["What is the fast answer?"]


def test_question_count_sees_past_the_search_cap():
    message = " ".join(f"What is rule number {n} for VAT?" for n in range(1, 11))
    assert websearch.question_count(message) == 10
    assert len(websearch.sub_questions(message)) == websearch.MAX_SUB_QUESTIONS
    assert websearch.question_count("What is the UK VAT rate?") == 1


def test_history_pages_are_kept_out_unless_the_question_asks_about_the_past():
    """HMRC's "Previous changes" page gave an old £437,500 tolerance as the
    current cash-accounting exit rule."""
    from app.orchestration.websearch import WebSource, _is_relevant

    page = WebSource(title="VCAS9450 - Cash accounting scheme: Previous changes - HMRC internal manual",
                     url="https://www.gov.uk/hmrc-internal-manuals/vat-cash-accounting-scheme/vcas9450",
                     snippet="If a business exceeds the £437,500 tolerance it must leave the cash accounting scheme.")
    assert not _is_relevant("When must a business leave the VAT Cash Accounting Scheme?", page)
    assert _is_relevant("What was the cash accounting scheme exit tolerance in 2006?", page)


def test_a_shortened_source_keeps_the_sentence_that_answers_the_question():
    """"The Australian GST rate is 10%" sat past the cut of a long ATO page,
    and the rate was answered "not stated" beside a citation of that page."""
    from app.orchestration.websearch import WebSource, build_web_grounded_prompt

    long_page = ("Menu. Home. Contact us. " * 120) + "The Australian GST rate is 10%. " + ("Footer links. " * 120)
    sources = [WebSource(title=f"ATO page {n}", url=f"https://www.ato.gov.au/{n}", snippet=long_page) for n in range(8)]
    prompt = build_web_grounded_prompt("Australian GST rate and registration threshold?", sources)
    assert prompt.count("The Australian GST rate is 10%") == 8
    assert "â€" not in prompt


def test_a_rate_table_without_full_stops_survives_shortening():
    from app.orchestration.websearch import _focused_excerpt

    table = " | ".join(f"Item {n} | value {n}" for n in range(200)) + " | Profits over £250,000 | Main rate 25% | " + " | ".join(f"Row {n}" for n in range(200))
    page = "Intro sentence. " * 5 + table
    assert "Main rate 25%" in _focused_excerpt(page, "What is the UK corporation tax main rate?", 800)

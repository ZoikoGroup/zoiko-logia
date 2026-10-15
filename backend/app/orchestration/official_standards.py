"""Passages of the official text of IFRS Accounting Standards.

The governed Source Library holds no IFRS 18, IAS 1 or IAS 2 (one "FASB ASC"
source with no passages), so standards questions rested on web search alone —
and Tavily was failing — so answers about IFRS 18 or inventory write-down
reversals came back incomplete or went to review. The IFRS Foundation
publishes the full text of current standards; a question or claim naming one
also gets the part of that text most about it, as a cited source.
"""
from __future__ import annotations

import asyncio
import re

from app.orchestration.websearch import WebSource

# The IFRS Foundation publishes the full text of current standards. Search
# results carry a page summary ("IAS 1 sets out overall requirements…"), not
# the paragraph a claim is about, so 10 of 15 true claims came back "could
# not verify". A claim naming a standard is also checked against the part of
# the official text most about it. IAS 1 itself is no longer published there
# (superseded by IFRS 18); its claims rely on search results.
_OFFICIAL_STANDARD_URL = "https://www.ifrs.org/content/dam/ifrs/publications/html-standards/english/2026/issued/{code}.html"
_STANDARD_NAMED = re.compile(r"\b(IFRS|IAS)\s?(\d{1,2})\b")
_STANDARD_MAX_BYTES = 4_000_000
_STANDARD_TIMEOUT_SECONDS = 15.0
_STANDARD_CACHE_SECONDS = 24 * 3600
_STANDARD_EXCERPT_CHARS = 3000
_standard_cache: dict[str, tuple[float, str]] = {}
_standard_locks: dict[str, asyncio.Lock] = {}


async def _official_standard_text(code: str) -> str:
    """Plain text of one standard ("ifrs18"), or "" when it is not published."""
    import time

    # One download per standard: several claims about IFRS 18 wait for it.
    async with _standard_locks.setdefault(code, asyncio.Lock()):
        cached = _standard_cache.get(code)
        if cached and time.monotonic() - cached[0] < _STANDARD_CACHE_SECONDS:
            return cached[1]
        text = await _download_standard(code)
        _standard_cache[code] = (time.monotonic(), text)
        return text


async def _download_standard(code: str) -> str:
    import httpx

    from app.orchestration.websearch import _html_to_text

    text = ""
    try:
        async with httpx.AsyncClient(timeout=_STANDARD_TIMEOUT_SECONDS, follow_redirects=False,
                                     headers={"User-Agent": "Mozilla/5.0 (compatible; KritonResearch/1.0)"}) as client:
            async with client.stream("GET", _OFFICIAL_STANDARD_URL.format(code=code)) as response:
                if response.status_code == 200 and "html" in response.headers.get("content-type", ""):
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _STANDARD_MAX_BYTES:
                            body = bytearray()
                            break
                    text = _html_to_text(bytes(body).decode(response.encoding or "utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 — an unreachable standard leaves search results only
        text = ""
    return text


_SENTENCE_END = re.compile(r"(?<=[.;])\s+(?=[A-Z(\[])")
_STOP = frozenset("under with when from that this which there their have been into than about would could should "
                  "what does later standard entity".split())


def _stems(text: str) -> set[str]:
    return {word[:5] for word in re.findall(r"[a-z]{4,}", text.lower()) if word not in _STOP}


def best_passages(text: str, query: str, limit: int) -> str:
    """The sentences of a standard most about the query, each with the one
    after it, in the standard's order.

    Matched by word stem — "reversed" in a question must find "reversal" in
    IAS 2 paragraph 33 — and weighted by rarity (IDF) and sentence length:
    counting shared words picked the objective and long merged blocks that
    share "standard", "entity", "present" with any question."""
    import math

    sentences = [" ".join(part.split()) for part in _SENTENCE_END.split(text or "") if part.strip()]
    wanted = _stems(query)
    if not sentences or not wanted:
        return ""
    stem_sets = [_stems(sentence) for sentence in sentences]
    count = len(sentences)
    idf = {stem: math.log((count + 1) / (1 + sum(stem in each for each in stem_sets))) for stem in wanted}

    def score(index: int) -> float:
        matched = wanted & stem_sets[index]
        if len(matched) < 2:
            return 0.0
        return sum(idf[stem] for stem in matched) / math.sqrt(max(20, len(sentences[index].split())))

    ranked = sorted(range(count), key=lambda index: (-score(index), index))
    chosen: set[int] = set()
    used = 0
    for index in ranked:
        if score(index) <= 0 or used >= limit:
            break
        for each in (index, index + 1):
            if each < count and each not in chosen and used + len(sentences[each]) <= limit:
                chosen.add(each)
                used += len(sentences[each])
    return " … ".join(sentences[index] for index in sorted(chosen))


async def official_standard_excerpts(claim: str) -> list[WebSource]:

    found: list[WebSource] = []
    for family, number in list(dict.fromkeys(_STANDARD_NAMED.findall(claim)))[:2]:
        code = f"{family.lower()}{number}"
        text = await _official_standard_text(code)
        if not text:
            continue
        excerpt = best_passages(text, claim, _STANDARD_EXCERPT_CHARS)
        if excerpt:
            found.append(WebSource(title=f"{family} {number} — official text (IFRS Foundation)",
                                   url=_OFFICIAL_STANDARD_URL.format(code=code), snippet=excerpt,
                                   provider="IFRS Foundation"))
    return found



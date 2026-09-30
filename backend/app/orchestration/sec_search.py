"""Deeper SEC EDGAR access: full-text search across filings, and cross-company
XBRL peer ranking.

sec_edgar.py already answers "what was Apple's net income" from one company's
own filed XBRL. It cannot answer the two questions that follow from it:

  - "What do Apple's risk factors say about supply chain concentration?"
    Nothing in a companyconcept response contains prose. This searches the
    actual text of the filings instead.
  - "Which US companies spend the most on R&D?"
    companyconcept is one company at a time by construction, so answering this
    would mean N requests and no way to know N. The XBRL frames API returns
    every registrant's value for one tag and one period in a single response.

Both stay behind sec_edgar._user_agent(), deliberately imported rather than
re-read from the environment: the SEC blocks unidentified traffic, and one
place that decides whether this connector is allowed to speak at all is worth
more than a private module boundary.

THE TRAP IN FRAMES, AND WHY THE PERIOD IS ON EVERY ROW
`CY2023` does not mean "the 2023 calendar year". It means "the annual reporting
period a registrant filed that overlaps 2023", so Walmart's Revenues row is
Feb 2023 - Jan 2024 and Apple's is Sep 2022 - Sep 2023, both filed under the
same frame. A ranking that presented those two as like-for-like annual figures
would be wrong at the top of the table, and it would be wrong in the direction
that matters: it looks authoritative. Every row here therefore carries its own
start/end, and the source says on its face that the periods differ.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.sec_edgar import (
    _CONCEPTS, _load_registrants, _user_agent, _www_base,
    resolve_company,
)
from app.orchestration.websearch import WebSource

PROVIDER = "SEC EDGAR"

# Question shape only, never a topic. "What does X say about Y" says Y is the
# topic, so the shape is discarded and Y survives. These words can never be what
# a reader asked a filing about, so removing them is always safe.
_PROSE_SHAPE = re.compile(
    r"\b(?:what does .{0,40} say|how does .{0,40} describe|"
    r"in its own words|in the words of)\b",
    re.I,
)
# A question about what a filing SAYS, as opposed to what it reports a number
# for. Without this the full-text search would fire on any mention of a filing.
# This is a GATE, not a filter: none of these phrases is deleted from the text
# here, because "cybersecurity" and "risk factors" are also legitimate things to
# search a filing for. _search_phrase decides what to drop.
_FULLTEXT_HINT = re.compile(
    r"\b(?:risk factor|risk factors|management'?s discussion|\bMD&A\b|"
    r"legal proceedings|internal control|internal controls|auditor'?s report|"
    r"critical accounting|business combination|cybersecurity|disclosure controls)\b"
    r"|" + _PROSE_SHAPE.pattern,
    re.I,
)
# When the question names a filing SECTION and nothing else, that section is
# the search phrase. "Microsoft legal proceedings" is a question about where
# Microsoft discusses legal proceedings, not a question about the 11,000 times
# the word "Microsoft" appears in Microsoft's own filings.
_SECTION_TOPIC: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brisk factors?\b", re.I), "risk factors"),
    (re.compile(r"management'?s discussion|\bMD&A\b", re.I), "management's discussion"),
    (re.compile(r"\blegal proceedings\b", re.I), "legal proceedings"),
    (re.compile(r"\binternal controls?\b", re.I), "internal control"),
    (re.compile(r"auditor'?s report", re.I), "auditor's report"),
    (re.compile(r"critical accounting (?:polic(?:y|ies))?", re.I), "critical accounting policies"),
    (re.compile(r"\bbusiness combinations?\b", re.I), "business combination"),
    (re.compile(r"\bcybersecurity\b", re.I), "cybersecurity"),
    (re.compile(r"disclosure controls", re.I), "disclosure controls"),
)
# A question about ranking one metric ACROSS companies.
_PEER_HINT = re.compile(
    r"\b(?:largest|biggest|highest|top|most|rank|ranking|ranked|compare|comparison|"
    r"peer|peers|who (?:spends|has|reports)|which compan)\b",
    re.I,
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
# Words that carry no search meaning once the topic has been isolated.
_STOPWORDS = frozenset("""
a an the of in on at to for from by with about into over under is are was were be
been being do does did what which who whom whose that this these those and or but
if then than as so such me my our your their its his her them us we you they i
please tell show give find list top best most give me find all any some
""".split())


def _data_base() -> str:
    return os.getenv("SEC_EDGAR_API_BASE_URL", "https://data.sec.gov").rstrip("/")


def _ft_base() -> str:
    return os.getenv("SEC_EDGAR_FTS_BASE_URL", "https://efts.sec.gov").rstrip("/")


def _headers() -> dict[str, str]:
    return {"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"}


def _filing_url(cik: int, accn: str) -> str:
    bare = str(accn).replace("-", "")
    return f"{_www_base()}/Archives/edgar/data/{int(cik)}/{bare}/{accn}-index.htm"


def _clean_number(value: float | int) -> str:
    magnitude = abs(value)
    for limit, suffix in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if magnitude >= limit:
            return f"{value / limit:,.2f} {suffix}"
    return f"{value:,.0f}"


# ── Full-text search ──────────────────────────────────────────────────────────

def _company_variants(company: dict) -> list[str]:
    """Every spelling of the company's name a user might have written.

    EDGAR's index is an exact full-text matcher, so a leftover token in the
    phrase is fatal: searching "Apple's supply chain" matches nothing at all,
    while the intended "supply chain" matches filings. The title alone is not
    enough — users write "Apple", "Apple's", "AAPL" against a title of
    "Apple Inc." — so each variant is also matched optionally-possessive."""
    title = str(company.get("title") or "").strip()
    variants = [title, str(company.get("ticker") or "").strip()]
    # "Apple Inc." -> "Apple"; "Tesla, Inc." -> "Tesla" (the comma has to go
    # too, or the bare name still fails to match the way a user writes it).
    variants.append(re.sub(r"[\s,]+(?:inc|corp|corporation|co|ltd|plc|llc)\.?$", "", title, flags=re.I))
    return [v for v in variants if len(v) > 1]


def _search_phrase(query: str, company: dict) -> str | None:
    """The topical part of the question, with the company and the boilerplate
    removed. "What are Apple's risk factors about supply chain concentration"
    searches for "supply chain concentration", not for the whole sentence —
    EDGAR's index is a full-text matcher and will not find it inside a
    question."""
    text = query
    for name in _company_variants(company):
        text = re.sub(rf"{re.escape(name)}'?s?\b", " ", text, flags=re.I)

    section_pattern, section_topic = next(
        ((pattern, phrase) for pattern, phrase in _SECTION_TOPIC if pattern.search(text)),
        (None, None),
    )
    # Remove the question shape, then the section phrase it is wrapped in, so a
    # section name is a last resort rather than part of the phrase. "Apple
    # cybersecurity risk factors" is a question about cybersecurity; keeping
    # "risk factors" would search for a two-word phrase most filings never use
    # in that exact order, and answer a different question.
    text = _PROSE_SHAPE.sub(" ", text)
    if section_pattern is not None:
        text = section_pattern.sub(" ", text)
    words = [w for w in re.sub(r"[^\w\s'-]", " ", text).split()
             if w.lower() not in _STOPWORDS and len(w) > 2]
    topic = " ".join(words)
    # A topic stated in the question beats the section name it sits in.
    return topic or section_topic


@dataclass(frozen=True)
class FilingHit:
    company: str
    cik: int
    form: str
    filed: str
    accn: str
    section: str

    @property
    def url(self) -> str:
        return _filing_url(self.cik, self.accn)


async def _search_filings(
    phrase: str, *, cik: int | None = None, forms: str = "10-K",
) -> list[FilingHit]:
    params = {"q": f'"{phrase}"', "forms": forms}
    if cik is not None:
        params["ciks"] = f"{cik:010d}"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
            response = await client.get(
                f"{_ft_base()}/LATEST/search-index", params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    hits: list[FilingHit] = []
    for hit in (payload.get("hits") or {}).get("hits", []):
        source = hit.get("_source") or {}
        document_id = str(hit.get("_id") or "")
        if ":" not in document_id:
            continue
        accn, _, section = document_id.partition(":")
        ciks = source.get("ciks") or []
        names = source.get("display_names") or []
        hits.append(FilingHit(
            company=re.sub(r"\s*\(.*$", "", str(names[0])).strip() if names else "",
            cik=int(ciks[0]) if ciks else 0,
            form=str(source.get("form") or ""),
            filed=str(source.get("file_date") or ""),
            accn=accn, section=section.replace(".xml", ""),
        ))
    # EDGAR returns relevance order, which surfaces a 2010 10-K/A above a
    # current one. A question about what a company says means what it says
    # NOW, so recency decides.
    hits.sort(key=lambda hit: hit.filed, reverse=True)
    return hits


def _build_fulltext_source(phrase: str, hits: list[FilingHit]) -> WebSource:
    top = hits[0]
    lines = [
        f"Full-text search of {top.form or 'filings'} filed with the SEC for "
        f"{top.company or 'the registrant'} (CIK {top.cik:010d}) for the phrase "
        f"\"{phrase}\". {len(hits)} matching document(s) returned; the most "
        f"recent is {top.form} filed {top.filed}, section {top.section}."
    ]
    for hit in hits[1:4]:
        lines.append(
            f"Also in {hit.form} filed {hit.filed}, section {hit.section} "
            f"(accession {hit.accn})."
        )
    lines.append(
        "These are the locations of the text within the filings. The wording "
        "itself is in the linked documents and has not been reproduced here."
    )
    return WebSource(
        title=f"SEC EDGAR — filings of {top.company or 'registrant'} mentioning \"{phrase}\"",
        url=top.url,
        snippet=" ".join(lines),
        provider=PROVIDER,
        freshness="filing",
    )


async def fetch_sec_fulltext(query: str) -> list[WebSource]:
    """Sources locating where a registrant discusses a topic in its filings."""
    agent = _user_agent()
    if not agent or not _FULLTEXT_HINT.search(query or ""):
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=_headers()) as client:
            registrants = await _load_registrants(client)
    except Exception:
        return []
    company = resolve_company(query, registrants)
    if company is None:
        return []
    phrase = _search_phrase(query, company)
    if not phrase:
        return []
    hits = await _search_filings(phrase, cik=int(company["cik_str"]))
    if not hits:
        return []
    return [_build_fulltext_source(phrase, hits)]


# ── XBRL frames peer ranking ──────────────────────────────────────────────────

def _concept_for(query: str) -> tuple[str, str] | None:
    """(label, us-gaap tag) for a concept this question names, or None."""
    for pattern, label, tags in _CONCEPTS:
        if pattern.search(query or ""):
            for tag in tags:
                if tag:
                    return label, tag
    return None


def _periods(query: str) -> list[str]:
    """Candidate CY frames, most preferred first.

    Two independent axes, which is why this is a list and not a single code:

    - Duration vs instant. A revenue frame is CY2024 (a year of activity), but
      a balance-sheet concept like Total Assets is an instant and its frame is
      CY2024Q4I (a position on a date). Asking for CY2024 on Assets returns
      nothing at all, silently, so both spellings are tried rather than
      hardcoding which us-gaap concepts are which.

    - Which year. An explicit year in the question is the only year tried —
      asking for 2023 must not silently answer with 2022. With no year named,
      the last completed calendar year is tried first and earlier ones are
      fallbacks, because that frame is genuinely empty for part of every year:
      registrants file their accounts up to 60 days after the year end, so a
      frame is not populated until well into the following year.

    Falling back is safe because the frame actually used is named on the source
    and on every row."""
    match = _YEAR.search(query or "")
    years = (
        [int(match.group(0))]
        if match
        else [datetime.now(timezone.utc).year - offset for offset in (1, 2, 3)]
    )
    return [frame for year in years for frame in (f"CY{year}", f"CY{year}Q4I")]


@dataclass(frozen=True)
class PeerRow:
    company: str
    cik: int
    value: float
    start: str
    end: str
    accn: str

    @property
    def url(self) -> str:
        return _filing_url(self.cik, self.accn)


async def _fetch_frame(tag: str, period: str) -> list[PeerRow]:
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_headers()) as client:
            response = await client.get(
                f"{_data_base()}/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json",
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []
    rows: list[PeerRow] = []
    for point in payload.get("data") or []:
        value = point.get("val")
        if not isinstance(value, (int, float)):
            continue
        rows.append(PeerRow(
            company=str(point.get("entityName") or "").strip(),
            cik=int(point.get("cik") or 0), value=float(value),
            start=str(point.get("start") or ""), end=str(point.get("end") or ""),
            accn=str(point.get("accn") or ""),
        ))
    return rows


def _build_peer_source(label: str, tag: str, period: str, rows: list[PeerRow]) -> WebSource:
    # An "I" suffix is SEC shorthand for an instant frame: a position on one
    # date. Describing it as a reporting period would misstate what the
    # numbers are, and for a balance-sheet concept it is the whole answer.
    instant = period.endswith("I")
    if instant:
        caveat = (
            f"NOTE every row is a BALANCE as at a point in time, not a flow over "
            f"a year, and the dates differ between registrants: {period} is the "
            f"position at that quarter end, and a registrant with a non-calendar "
            f"financial year files a different date under the same frame."
        )
    else:
        caveat = (
            f"NOTE the periods DIFFER, because {period} is the annual reporting "
            f"period a registrant filed that overlaps that year, not the calendar "
            f"year: a registrant with a non-calendar financial year files a "
            f"different window under the same frame."
        )
    lines = [
        f"SEC XBRL cross-company comparison for {label} (us-gaap tag {tag}), "
        f"frame {period}. {len(rows)} registrants reported this tag in that "
        f"frame. The {len(rows)} largest, each with the exact period they filed "
        f"for — {caveat}",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row.company or f'CIK {row.cik:010d}'} — "
            f"${_clean_number(row.value)}, for the period {row.start or '?'} to "
            f"{row.end or '?'} (accession {row.accn})."
        )
    lines.append(
        "Do not present these as like-for-like figures across the table: "
        "quote each one with the period it actually covers, as given above."
    )
    return WebSource(
        title=f"SEC EDGAR — largest US registrants by {label} ({period})",
        url=rows[0].url if rows else f"{_data_base()}/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json",
        snippet=" ".join(lines),
        provider=PROVIDER,
        freshness="filing",
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=f"{label} — largest registrant", value=str(rows[0].value),
            unit="USD", period=rows[0].end or period, provider=PROVIDER,
            source_url=rows[0].url if rows else "",
            freshness="filing",
        ),
    )


async def fetch_sec_peer_rank(query: str, *, limit: int = 10) -> list[WebSource]:
    """One source ranking US registrants by a filed concept for a period."""
    agent = _user_agent()
    if not agent or not _PEER_HINT.search(query or ""):
        return []
    concept = _concept_for(query)
    if concept is None:
        return []
    label, tag = concept
    # A tag a company does not use is common — the registry lists several
    # synonyms per concept, and only some are populated across the population.
    # Trying them in order costs one extra request only on a miss.
    for candidate in (t for t in dict.fromkeys([tag] + _alternate_tags(label))):
        for period in _periods(query):
            rows = await _fetch_frame(candidate, period)
            if rows:
                rows.sort(key=lambda row: row.value, reverse=True)
                return [_build_peer_source(label, candidate, period, rows[:limit])]
    return []


def _alternate_tags(label: str) -> list[str]:
    for _, known_label, tags in _CONCEPTS:
        if known_label == label:
            return list(tags)
    return []

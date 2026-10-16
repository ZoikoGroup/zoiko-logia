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


# Sentence ends, and paragraph numbers ("… . 9 | Inventories shall …",
# "C1 | An entity shall apply …"): without the latter IAS 2 ¶9 stayed glued
# to ¶8 and the measurement rule was never selected on its own.
_SENTENCE_END = re.compile(r"(?<=[.;])\s+(?=[A-Z(\[])|\s+(?=[A-Z]{0,2}\d{1,3}[A-Z]?\s\|\s)")
_CROSS_REFERENCE = re.compile(r"\s*\[\s*(?:Refer|Link to)\b[^\]]*\]")
_PUNCT_SPACE = re.compile(r"[ \t]+([,.;:)])")
_JOIN = " … "
_CONTENTS_ENTRY = re.compile(r";\s*\d+:\s*\d+")
_PARAGRAPH_START = re.compile(r"[A-Z]{0,2}\d{1,3}[A-Z]?\s\|\s")
# The standard's own name is no evidence of relevance inside that standard:
# "IFRS 15 … contract liability" ranked agenda-decision commentary ("Applying
# IFRS 15, the educational institution…") above ¶106, which never names it.
_STOP = frozenset("under with when from that this which there their have been into than about would could should "
                  "what does later standard entity ifrs ifric "
                  # Framing of the request, not its accounting topic: "Explain …
                  # Identify the facts needed before concluding … today" drew
                  # ¶3 ("all relevant facts") instead of the revenue rules.
                  "explain identify describe facts needed before concluding conclude today much many "
                  "company cite applicable authoritative source sources".split())
# Interpretations Committee agenda decisions are reproduced inline as
# "[IFRIC® Update, March 2025, Agenda Decision, …]". They explain, they do not
# require; quoted ahead of the requirements they crowded out ¶31, ¶35, ¶106.
_AGENDA_DECISION = re.compile(r"\[\s*IFRIC")
_PARAGRAPH_LINE = re.compile(r"\n[A-Z]{0,2}\d{1,3}[A-Z]?\s\|\s")
_SUPPORTING_WEIGHT = 0.3
# "B4: (b);", "E7 – b.: ii.;": list markers left from the HTML, no words.
_WORDS = re.compile(r"[A-Za-z]{3,}")


# Everyday wording of a question, and the standard's own terms for it. The
# expansion only adds words to match on; what is quoted is still chosen from
# the official text. "Receives £120,000 upfront … revenue recognition" shares
# no word with ¶31 ("recognise revenue when (or as) the entity satisfies a
# performance obligation by transferring a promised good or service").
_CONCEPTS = [
    (r"\bup[- ]?front\b|\bin advance\b|\badvance (?:payment|fee)s?\b|\bpre-?paid\b|\bpre-?payments?\b"
     r"|\bpaid before\b|\breceived? before\b", "prepayment consideration contract liability"),
    (r"\bcash (?:receipt|received)\b|\breceipt of cash\b|\breceives? (?:cash|payment)\b", "consideration payment"),
    (r"\brevenue (?:recognition|is recogni[sz]ed|recogni[sz]ed)\b|\brecogni[sz]e revenue\b",
     "satisfies performance obligation transferring control"),
    (r"\b(?:service|subscription|support|maintenance) (?:contract|period|agreement)\b|\b\d+-month\b",
     "performance obligation satisfied over time"),
]


def _concept_terms(query: str) -> str:
    return " ".join(terms for pattern, terms in _CONCEPTS if re.search(pattern, query or "", re.I))


def _agenda_spans(text: str) -> list[tuple[int, int]]:
    """Where agenda decisions sit: to the matching bracket, or to the next
    numbered paragraph when the bracket never closes."""
    spans = []
    for match in _AGENDA_DECISION.finditer(text):
        depth, end = 0, len(text)
        for index in range(match.start(), len(text)):
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        following = _PARAGRAPH_LINE.search(text, match.start())
        spans.append((match.start(), min(end, following.start() if following else end)))
    return spans


def _stems(text: str) -> set[str]:
    # A final "y" becomes "i" so "apply" meets "application" and "early" meets
    # "earlier" (IFRS 18 C1, the effective date, was never picked without it).
    return {re.sub(r"y$", "i", word)[:5] for word in re.findall(r"[a-z]{4,}", text.lower()) if word not in _STOP}


def best_passages(text: str, query: str, limit: int) -> str:
    """The sentences of a standard that best cover the query, each quoted from
    the start of its paragraph and with the sentence after it, in the
    standard's order.

    Matched by word stem ("reversed" finds "reversal") and weighted by rarity
    (IDF) and sentence length. Agenda-decision commentary weighs less and
    word-less fragments are dropped. Requirement sentences ("shall") weigh more —
    a standard states its rules there — and each next pick must add query
    terms not yet covered: ranking alone filled the budget with sentences
    repeating one term, and IAS 2 ¶9 ("Inventories shall be measured at the
    lower of cost and net realisable value") was left out of an answer about
    measuring inventory below cost."""
    import math

    # The ifrs.org text carries cross-references ("lower of cost [ Refer:
    # paragraphs 10–27 ] and net realisable value") and a space before
    # punctuation ("operating , investing"); both split a rule's wording.
    text = _PUNCT_SPACE.sub(r"\1", _CROSS_REFERENCE.sub("", (text or "").replace("\u2060", "")))
    agenda = _agenda_spans(text)
    sentences, supporting, position = [], [], 0
    for boundary in [*_SENTENCE_END.finditer(text), None]:
        end = boundary.start() if boundary else len(text)
        part = " ".join(text[position:end].split())
        # Fragments without words are never quoted, not even as the sentence
        # after a pick.
        if len(_WORDS.findall(part)) >= 3:
            sentences.append(part)
            supporting.append(any(start <= position < stop for start, stop in agenda))
        position = boundary.end() if boundary else len(text)
    wanted = _stems(query + " " + _concept_terms(query))
    if not sentences or not wanted:
        return ""
    # The contents list ("… – OBJECTIVE: Effective date; 1: 140 …") names every
    # topic and outranked the paragraphs themselves.
    stem_sets = [set() if len(_CONTENTS_ENTRY.findall(sentence)) >= 3 else _stems(sentence) for sentence in sentences]
    count = len(sentences)
    idf = {stem: math.log((count + 1) / (1 + sum(stem in each for each in stem_sets))) for stem in wanted}
    requirement = re.compile(r"\b(?:shall|is measured|are measured|recognises|shall recognise)\b", re.I)

    covered: set[str] = set()
    chosen: set[int] = set()
    # Too long for the space left: never retried and never shown. These were
    # once added to `chosen` and joined in, so IFRS 15 excerpts ran to ~90,000
    # characters against a 3,000 limit.
    skipped: set[int] = set()
    used = 0
    while used < limit:
        def gain(index: int) -> float:
            matched = wanted & stem_sets[index]
            if index in chosen or index in skipped or len(matched) < 2:
                return 0.0
            weight = sum(idf[stem] * (0.35 if stem in covered else 1.0) for stem in matched)
            weight *= 1.5 if requirement.search(sentences[index]) else 1.0
            weight *= _SUPPORTING_WEIGHT if supporting[index] else 1.0
            return weight / math.sqrt(max(20, len(sentences[index].split())))
        best = max(range(count), key=lambda index: (gain(index), -index))
        if gain(best) <= 0:
            break
        added = False
        # Quote from the paragraph's start: "Earlier application is permitted"
        # matched, but the date is in C1's first sentence just before it.
        start = best
        while start > max(0, best - 3) and not _PARAGRAPH_START.match(sentences[start]):
            start -= 1
        if not _PARAGRAPH_START.match(sentences[start]):
            start = best
        # The sentence after continues the rule only inside its paragraph; the
        # next paragraph ("C8A | …" after B44) is a different rule.
        # Nor does agenda-decision commentary that follows a requirement (¶31
        # was "continued" by an agenda decision that filled the budget).
        continues = (best + 1 < count and not _PARAGRAPH_START.match(sentences[best + 1])
                     and supporting[best + 1] == supporting[best])
        stop = best + 2 if continues else best + 1
        # The matching sentence goes in first; its lead and continuation only
        # with it. A follow-on sentence quoted without the rule it follows
        # ("Findings and conclusion: …") says nothing.
        for each in [best, *(i for i in range(start, min(stop, count)) if i != best)]:
            # The budget counts the " … " joining each passage to the last.
            cost = len(sentences[each]) + (len(_JOIN) if chosen else 0)
            if each not in chosen and used + cost <= limit:
                chosen.add(each)
                used += cost
                covered |= wanted & stem_sets[each]
                added = True
            elif each == best and best not in chosen:
                break
        if not added:
            skipped.add(best)
    return _JOIN.join(sentences[index] for index in sorted(chosen))


# A topic names its standard when the question does not: "Under IFRS, how is
# inventory measured when net realisable value falls below cost?" named no
# standard, so IAS 2 was never read and the answer was "not stated". Only for
# an IFRS question (or one naming no other framework), never for US GAAP.
_TOPIC_STANDARDS = [
    (r"\binventor(?:y|ies)\b|\bnet realisable value\b|\bnet realizable value\b|\bnrv\b", ("IAS", "2")),
    (r"\brevenue (?:recognition|from contracts?)\b|\brevenue (?:is |be |was )?recogni[sz]\w*|\bcontracts? with customers\b"
     r"|\bperformance obligations?\b|\b(?:upfront|advance) (?:payment|fee|consideration)s?\b|\breceives? [^.?]{0,30}\bupfront\b",
     ("IFRS", "15")),
    (r"\bleases?\b|\bright[- ]of[- ]use\b|\blessee\b|\blessor\b", ("IFRS", "16")),
    (r"\bstatement of cash flows?\b|\bcash flow statement\b", ("IAS", "7")),
    (r"\bprovisions?\b|\bcontingent liabilit(?:y|ies)\b|\bcontingent assets?\b", ("IAS", "37")),
    (r"\bproperty,? plant and equipment\b|\bppe\b|\bdepreciation\b|\buseful life\b", ("IAS", "16")),
    (r"\bimpairment of (?:non-financial )?assets\b|\brecoverable amount\b|\bvalue in use\b", ("IAS", "36")),
    (r"\bintangible assets?\b", ("IAS", "38")),
    (r"\bincome tax(?:es)?\b|\bdeferred tax\b", ("IAS", "12")),
    (r"\bpresentation (?:and disclosure )?(?:of|in) financial statements\b|\bmanagement-defined performance\b", ("IFRS", "18")),
]
_OTHER_FRAMEWORK = re.compile(r"\b(?:US GAAP|ASC\s?\d|FRS 10[2-5]|Ind\s?AS)\b", re.I)


def standards_for(text: str) -> list[tuple[str, str]]:
    """The IFRS standards a question or claim is about: those it names, else
    those its topic belongs to (at most two)."""
    named = list(dict.fromkeys(_STANDARD_NAMED.findall(text or "")))
    if named:
        return named[:2]
    if _OTHER_FRAMEWORK.search(text or "") and not re.search(r"\bIFRS\b", text or ""):
        return []
    topical = [standard for pattern, standard in _TOPIC_STANDARDS if re.search(pattern, text or "", re.I)]
    return list(dict.fromkeys(topical))[:2]


async def official_standard_excerpts(claim: str) -> list[WebSource]:

    found: list[WebSource] = []
    for family, number in standards_for(claim):
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



"""Deterministic country resolution (design docs/country-resolution-design-2026-10-30.md,
built 30 Oct 2026; used only by the classifier shadow, behind
KRITON_COUNTRY_RESOLUTION, off by default).

A part's countries come only from evidence, never from a model's guess:
  E1 a country named in the part (less the other party's country)
  E2 a country named elsewhere in the request
  E3 a governed tax authority or central bank named in the part
  E4 registry terms of one country (registry/country_terms.json)
  E5 the user's selected or conversation jurisdiction
Ambiguous shared terms ("PAYE", "FBT", "GST") give a candidate set and decide
only with E5; a form-like code that is not in the registry is recorded as an
unmapped term. With no evidence the status is "unknown". Data is in
registry/country_resolution.json.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "registry" / "country_resolution.json"


def resolution_enabled() -> bool:
    return os.getenv("KRITON_COUNTRY_RESOLUTION", "").strip().lower() in {"1", "true", "yes", "on"}



@dataclass
class CountryResolution:
    status: str                                     # resolved | candidates | unknown
    countries: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    counterparties: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    unmapped_terms: list[str] = field(default_factory=list)


def _words(phrases) -> str:
    return "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in sorted(phrases, key=len, reverse=True))


@lru_cache(maxsize=1)
def _data() -> dict:
    data = json.loads(DATA.read_text())
    names = [(re.compile(rf"(?<![\w.]){_words([n])}(?![\w])", re.I), key) for key, ns in data["names"].items() for n in ns]
    authorities = [(re.compile(rf"(?<!\w){_words([a])}(?!\w)", re.I), key) for key, ns in data["authorities"].items() for a in ns]
    ambiguous = [(re.compile(rf"(?<!\w){_words([t])}(?!\w)", re.I), t, cands) for t, cands in data["ambiguous_candidates"].items()]
    all_names = _words([n for ns in data["names"].values() for n in ns])
    # A country word followed by a framework word is a framework ("US GAAP"), not a country.
    exclusions = re.compile(rf"(?<!\w)(?:{_words(data['name_exclusions'])}|(?:{all_names})\s+(?:{_words(data['framework_words'])}))(?!\w)", re.I)
    role, entity = _words(data["counterparty_role_nouns"]), _words(data["counterparty_entity_nouns"])
    article = r"(?:(?:a|an|the|its|our|their|his|her|one\s+of\s+its)\s+)?"
    verbs = (r"pays?|paying|paid|bills?|billing|invoices?|invoicing|hires?|hiring|serves?|charges?|charging|"
             r"sells?\s+to|selling\s+to|buys?\s+from|buying\s+from|licenses?\s+from|purchases?\s+from|imports?\s+from|"
             r"provides?\s+\w+\s+to|supplies|supplying")
    # Rule 1: a role noun ("client", "supplier") qualified by a country is the other party
    # after a preposition or a transaction verb: "from a German supplier", "pays an Indian developer".
    role_form = re.compile(rf"\b(?:to|from|for|with|by|of|{verbs})\s+{article}(?P<name>{all_names})\s+(?:[a-z]+\s+){{0,2}}(?:{role})\b", re.I)
    # Rule 2: an entity noun ("company", "business") is the other party only after a transaction
    # verb ("invoices a UK company"), or as the group or parent an entity belongs to ("of a UK
    # group", "to its US parent"); "apply to a New Zealand business" does not make it one.
    entity_form = re.compile(rf"\b(?:{verbs})\s+{article}(?P<name>{all_names})\s+(?:[a-z]+\s+){{0,2}}(?:{entity})\b"
                             rf"|\b(?:of|to|from)\s+(?:a|an|the|its|their)\s+(?P<owner>{all_names})\s+(?:group|parent)\b", re.I)
    # Rule 3: "a contractor in India", "customers based in the US" (role nouns only).
    in_form = re.compile(rf"\b(?:{role})\s+(?:in|from|based\s+in)\s+(?:the\s+)?(?P<name>{all_names})\b", re.I)
    # Rule 4: a country that qualifies the tax is the tax country and outranks the roles:
    # "UK VAT", "UK and US corporate tax", "German trade tax", "how does Canada tax", "taxed in Australia".
    tax = _words(data["tax_words"])
    chain = rf"(?:{all_names})(?:\s*(?:,|and|or|&|vs\.?|versus)\s*(?:{all_names}))*"
    modifiers = _words(data["tax_modifiers"])
    qualifier_before = re.compile(rf"(?<![\w])(?P<names>{chain})(?:'s)?\s+(?:(?:{modifiers})\s+){{0,3}}(?:{tax})(?!\w)", re.I)
    chain_the = rf"(?:the\s+)?(?:{all_names})(?:\s*(?:,|and|or|&|vs\.?|versus|with)\s*(?:the\s+)?(?:{all_names}))*"
    qualifier_after = re.compile(rf"(?<!\w)(?:{tax})(?!\w)[^.?!]{{0,30}}?\b(?:in|for)\s+(?P<names>{chain_the})(?!\w)", re.I)
    return {"names": names, "authorities": authorities, "ambiguous": ambiguous, "exclusions": exclusions,
            "role_form": role_form, "entity_form": entity_form, "in_form": in_form,
            "qualifier_before": qualifier_before, "qualifier_after": qualifier_after}


# A form-like code: "Form 8938", "IR10", "IT3(a)", "1095-C", "RC59", "GSTR-7".
_FORM_CODE = re.compile(r"\b(?i:form)\s+[A-Z0-9][\w\-()]*|\b[A-Z]{1,5}-?\d{1,5}(?:\([a-z]\)|-[A-Z]{1,2}|[A-Z])?(?!\w)"
                        r"|\b\d{3,4}-[A-Z]{1,3}\b|\b[A-Z]{2,5}-[A-Z]{1,2}\b")
# Accounting and auditing standards are not forms.
_STANDARD = re.compile(r"^(?:IFRS|IAS|ASC|ISA|ISAE|FRS|AASB|IND|GAAP|SFAS|IPSAS|SSAP|AS|SA)\b|^form\s", re.I)


def _clean_code(code: str) -> str:
    """"Form C-S)" from "Form C-S (Lite)": drop an unbalanced closing bracket."""
    return code[:-1] if code.endswith(")") and code.count("(") < code.count(")") else code


def _named(text: str) -> list[tuple[int, str, str]]:
    """Country names, longest match first: "Northern Ireland" is not also "Ireland"."""
    d = _data()
    cleaned = d["exclusions"].sub(lambda m: " " * len(m.group(0)), text or "")
    spans = sorted(((m.start(), m.end(), key, m.group(0)) for pattern, key in d["names"] for m in pattern.finditer(cleaned)),
                   key=lambda s: (s[0], -(s[1] - s[0])))
    hits, taken = [], []
    for start, end, key, matched in spans:
        if any(start >= s and end <= e for s, e in taken):
            continue
        taken.append((start, end))
        hits.append((start, key, matched))
    return sorted(hits)


def _counterparty_keys(text: str, forms: tuple[str, ...] = ("role_form", "entity_form", "in_form")) -> set[str]:
    d, keys = _data(), set()
    for form in (d[name] for name in forms):
        for match in form.finditer(text or ""):
            for group in ("name", "owner"):
                if group in match.re.groupindex and match.group(group):
                    keys |= {key for _, key, _ in _named(match.group(group))}
    return keys


def _qualifying_keys(text: str) -> list[str]:
    """Countries that qualify the tax itself (rule 4), in order."""
    d, found = _data(), []
    for form in (d["qualifier_before"], d["qualifier_after"]):
        for match in form.finditer(text or ""):
            found += [(match.start("names") + offset, key) for offset, key, _ in _named(match.group("names"))]
    return list(dict.fromkeys(key for _, key in sorted(found)))


def _keys(hits) -> list[str]:
    return list(dict.fromkeys(key for _, key, _ in hits))


def selected_key(value: str | None) -> str | None:
    """A selector or conversation value as a country key ("India" -> INDIA,
    "US-CA" -> US); "Any", "IFRS" and other non-country values give None."""
    from app.orchestration.source_taxonomy import _jurisdiction_key
    key = _jurisdiction_key(value or "")
    return key if key in json.loads(DATA.read_text())["names"] else None


def resolve(part: str, request: str = "", selected: str | None = None, conversation: str | None = None) -> CountryResolution:
    """The countries a part's official sources come from, with the evidence."""
    from app.orchestration.country_terms import implied_terms, implied_terms_with_status
    d = _data()
    part, request = part or "", request or ""
    evidence, conflicts = [], []
    context = list(dict.fromkeys(k for k in (selected_key(selected), selected_key(conversation)) if k))

    def finish(status, countries, counterparties=(), candidates=()):
        unmapped = []
        mapped = {m.lower() for _, _, m in implied_terms(part)}
        for match in _FORM_CODE.finditer(part):
            code = _clean_code(match.group(0))
            bare = re.sub(r"^form\s+", "", code, flags=re.I)
            if code.lower() not in mapped and bare.lower() not in mapped and not _STANDARD.match(bare) \
                    and not any(bare.lower() in m for m in mapped):
                unmapped.append(code)
        for key in context:
            if countries and key not in countries:
                conflicts.append({"kind": "E5", "value": key, "kept": countries})
        return CountryResolution(status, list(countries), list(candidates), sorted(counterparties), evidence, conflicts,
                                 list(dict.fromkeys(unmapped)))

    # E1: named in the part, less the other party.
    hits = _named(part)
    counterparties = _counterparty_keys(part)
    if hits:
        evidence += [{"kind": "E1", "value": key, "text": text} for _, key, text in hits]
        # Rule 4 first: the countries that qualify the tax; otherwise every named
        # country that is not the other party.
        qualifying = _qualifying_keys(part)
        if not qualifying and not [key for key in _keys(hits) if key not in counterparties]:
            # Every named country would be "the other party". A "<role> in X" match
            # is then the subject ("service providers in India"); a transaction
            # ("billing a US client") stays the other party.
            counterparties = _counterparty_keys(part, ("role_form", "entity_form"))
        tax = qualifying or [key for key in _keys(hits) if key not in counterparties]
        counterparties = {key for key in counterparties | set(_keys(hits)) if key not in tax} if qualifying else counterparties
        if tax:
            return finish("resolved", tax, counterparties)
    # E2: named elsewhere in the request (when the part names none).
    if not hits and request and request != part:
        others = _named(request)
        tax = _qualifying_keys(request) or [key for key in _keys(others) if key not in _counterparty_keys(request)]
        if tax:
            evidence += [{"kind": "E2", "value": key, "text": text} for _, key, text in others]
            return finish("resolved", tax, _counterparty_keys(request))
    # E3: a governed authority or central bank.
    placed = list(dict.fromkeys(key for pattern, key in d["authorities"] for _ in pattern.finditer(part)))
    if placed:
        evidence += [{"kind": "E3", "value": key} for key in placed]
        return finish("resolved", [k for k in placed if k not in counterparties] or placed, counterparties)
    # E4: registry terms. Only a term verified on its authority's page decides
    # (one country, or several as a comparison); an unverified term gives a
    # candidate (decision of 31 Oct 2026), below the user's own context.
    terms = implied_terms_with_status(part)
    evidence += [{"kind": "E4" if status == "verified" else "E4u", "value": key, "entry": entry, "text": text}
                 for key, entry, text, status in terms]
    verified = list(dict.fromkeys(key for key, _, _, status in terms if status == "verified"))
    if verified:
        return finish("resolved", verified, counterparties)
    # Ambiguous shared terms: candidates, decided only by the user's context.
    candidates: list[str] = []
    for pattern, term, cands in d["ambiguous"]:
        if pattern.search(part):
            evidence.append({"kind": "ambiguous", "value": term, "candidates": cands})
            if cands:
                candidates = [c for c in cands if not candidates or c in candidates] or candidates or list(cands)
    unverified = list(dict.fromkeys(key for key, _, _, status in terms if status != "verified"))
    if unverified:
        candidates = [c for c in candidates if c in unverified] or list(dict.fromkeys(candidates + unverified))
    # E5: the user's selected or conversation jurisdiction.
    if context:
        usable = [k for k in context if not candidates or k in candidates]
        if usable:
            evidence.append({"kind": "E5", "value": usable[0]})
            return finish("resolved", [usable[0]], counterparties)
    if candidates:
        return finish("candidates", [], counterparties, candidates)
    return finish("unknown", [], counterparties)

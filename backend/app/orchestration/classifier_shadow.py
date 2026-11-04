"""E3 live shadow of the model-first part classifier (built 30 Oct 2026; off
unless KRITON_CLASSIFIER_SHADOW is true).

After the Task Contract is built, a background task classifies the request's
parts with the design in docs/contract-classifier-design-2026-10-30.md
(revision 2): the model decides needs_official, fact type and tax countries;
deterministic guards decide calculations on the user's figures and exchange
rates supplied in the question, and remove counterparty countries; the period
reader decides period; the rule table is the fallback; search domains come
from the classified tax countries only. The result is logged beside the
contract (stage "classified") with the rule table's reading and whether they
disagree. The request never waits for it and nothing reads it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

logger = logging.getLogger("kriton.task_contract")
TIMEOUT_SECONDS = 2.5
_tasks: set[asyncio.Task] = set()


def shadow_enabled() -> bool:
    return os.getenv("KRITON_CLASSIFIER_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


def _domains(countries: list[str], part: str) -> list[str]:
    from app.orchestration.source_taxonomy import allowed_domains, detect_topics
    topics = detect_topics(part)
    return sorted({domain for key in countries for domain in allowed_domains(key, topics, "")})


# Fixed rules from the approved labelling rules (31 Oct 2026).
# S1: a request for an official source, guidance, website or authority needs
# official sources, for every country it names (none is "the other party").
_OFFICIAL_SOURCE = re.compile(
    r"\bofficial\s+(?:tax\s+authorit\w*|source|sources|guidance|website|websites|site|sites|authorit\w*|body)\b"
    r"|\b(?:which|what|the\s+relevant)\s+(?:tax|government)\s+(?:authorit\w*|department|agency)\b"
    r"|\bwhich\s+(?:authorit\w*|body|agency|department|websites?|sites?)\b"
    r"|\bwhere\s+(?:can|should)\s+(?:i|we)\s+(?:verify|check|find)\b|\bwho\s+(?:issues|publishes|collects|administers)\b"
    r"|\b(?:publishes|administers|collects)\s+(?:\w+\s+){0,3}(?:tax|gst|vat|standards?)\b|\bidentify\s+the\s+(?:relevant|official)\b"
    r"|\bfind\s+the\s+official\b|\bwhich\s+tax\s+authority\b|\bwhich\s+agency\b", re.I)
# R1/R2/R6: a named country (or its tax authority) and a tax, with a question
# about what applies or how that country's rule works, needs official sources.
_WHAT_APPLIES = re.compile(
    r"\b(?:considerations?|consider|points?|issues?|obligations?|implications?|treatment|what\s+happens|"
    r"(?:may|might|would|do|does)\s+apply|applies|which\s+country'?s?\s+(?:\w+\s+){0,2}rules|rules\s+(?:may\s+)?(?:be\s+)?relevant|"
    r"tax\s+questions|should\s+be\s+investigated|(?:may\s+)?need\s+to\s+be\s+considered|matter)\b", re.I)
_EXPLAIN_RULE = re.compile(r"^\s*explain\s+(?:how\s+[^?]{0,80}\b(?:works?|operates?|applies|apply)\b|the\s+purpose\s+of)\b", re.I)
_TAX_WORD = re.compile(r"\b(?:tax(?:es)?|vat|gst|hst|duty|duties|customs|tds|tcs|national\s+insurance|payroll|superannuation|super|"
                       r"withholding|sales\s+tax|allowance|depreciation|registration|returns?|form\s+\w+|scheme|credits?)\b", re.I)


def _resolver_on() -> bool:
    from app.orchestration.country_resolution import resolution_enabled
    return resolution_enabled()


# dev3 floors (labelling policy v2, 31 Oct 2026; docs/dev3-tuning-plan-2026-10-31.md), after the model.
# D1: what a country-specific item is, is for, shows, reports, contains or covers is a rule question.
_PURPOSE = re.compile(
    r"\bwhat\s+(?:is|are)\s+(?:an?|the)\b|\bused\s+for\b|\bpurpose\s+of\b|\bwhat\s+(?:role|income|details)\b|\bwho\s+receives\b"
    r"|\bwhy\s+would\b[^?]*\b(?:file|use|submit|need)\b"
    r"|\bwhat\s+(?:does|do)\b[^?]*\b(?:shows?|reports?|contains?|includes?|covers?|certif(?:y|ies)|reflects?|means?)\b", re.I)
# D2: a calculation needs the user's figures; the method of an official one is a rule question (P3).
_TAXY = re.compile(r"\b(?:tax(?:es)?|vat|gst|hst|sst|duty|duties|levy|levies|customs|excise|contributions?|charge|withholding|"
                   r"zakat|tds|tcs|national\s+insurance)\b", re.I)
_METHOD = re.compile(r"\bhow\s+(?:is|are|do|does|should)\b[^?]*\b(?:calculated|computed|worked\s+out|calculate|compute|work\s+out)\b", re.I)
# D3: when an official payment or return must be paid, submitted, filed or lodged is a deadline (P4); registration is not.
_WHEN_DUE = re.compile(r"^\s*(?:when\s+(?:must|is|are|do|does|should|will)|by\s+when)\b(?![^?]*\bregist)[^?]*"
                       r"\b(?:pay|paid|payments?|remit(?:ted)?|submit(?:ted)?|file[ds]?|lodge[ds]?|due|deposit(?:ed)?)\b", re.I)
# D4: the information needed for a named country's rule is a rule question.
_INFO_NEEDED = re.compile(r"\bwhat\s+(?:information|details|data)\b[^?]*\b(?:needed|required|need)\b", re.I)


# dev4 floors E1-E4 (approved development cycle, policy v2.1). These only
# classify the request; they never choose a country or change answer routing.
_TIME_QUESTION = re.compile(
    r"^\s*(?:when\s+(?:must|is|are|do|does|should|will)|by\s+when|within\s+how\s+many\s+(?:days|weeks|months))\b", re.I)
_COMPLIANCE_ACTION = re.compile(
    r"\b(?:notif(?:y|ied)|tell|told|inform(?:ed)?|report(?:ed)?|issu(?:e|ed)|giv(?:e|en)|send|sent|"
    r"obtain(?:ed)?|complet(?:e|ed)|generat(?:e|ed)|make|made)\b", re.I)
_COMPLIANCE_OBJECT = re.compile(
    r"\b(?:tax(?:es)?|returns?|invoices?|credit\s+notes?|statements?|contributions?|permits?|documentation|"
    r"deductions?|withholding|payroll|customs|excise)\b", re.I)
_TAX_CONTEXT = re.compile(r"\b(?:taxable|deductib\w*|exempt\w*|recoverab\w*|zero.rating)\b", re.I)
_PRACTICAL = re.compile(
    r"^\s*(?:is|are|can|may)\b[^?]*\b(?:deductible|taxable|exempt|recoverable)\b"
    r"|^\s*(?:must|should|do|does)\b[^?]*\b(?:charge|register|pay|deduct|withhold|keep|report)\b"
    r"|^\s*(?:what|which)\s+(?:records|evidence|information|penalties|conditions)\b"
    r"|^\s*how\s+(?:to\s+)?(?:(?:should|must|do|does)\b[^?]*\b)?(?:treat|handle|account\s+for)\b", re.I)
_ACCOUNTING_CONTEXT = re.compile(
    r"\b(?:ifrs|ias|asc|frs|ind\s+as|financial\s+statements?|accounts|capitalis\w*|capitaliz\w*|"
    r"recognis\w*|recogniz\w*|misstatements?)\b", re.I)
_INCLUDED_METHOD = re.compile(
    r"^\s*(?:which|what)\s+(?:(?:items|costs|deductions|expenses)\b[^?]*|[^?]{0,50})"
    r"\b(?:added\s+back|included|deducted|allowed|disallowed)\b[^?]*"
    r"\b(?:calculating|working\s+out|computing|worked\s+out|calculated|computed)\b", re.I)


def _form_code(part: str) -> bool:
    from app.orchestration.country_resolution import _FORM_CODE, _STANDARD
    return any(not _STANDARD.match(re.sub(r"^form\s+", "", m.group(0), flags=re.I)) for m in _FORM_CODE.finditer(part))


def _pattern_floors(part, terms, named, counterparties, source, official, fact):
    from app.orchestration.part_classifier import _RATE_GIVEN, _USER_FIGURES
    from app.orchestration.country_resolution import _data
    if fact == "calculation" and not (_USER_FIGURES.search(part) or _RATE_GIVEN.search(part)):     # D2
        taxy = bool(_TAXY.search(part) or terms or any(p.search(part) for p, _, _ in _data()["ambiguous"]))
        official, fact = (True, "rule") if taxy else (False, "explanation")
        source = f"{source}+rule:method_without_figures"
    if official and fact == "rule" and _METHOD.search(part) and not (_TAXY.search(part) or terms or named
                                                                     or any(p.search(part) for p, _, _ in _data()["ambiguous"])):  # D2b
        # P3 covers the method of an OFFICIAL calculation; an accounting method
        # ("how is reducing-balance depreciation calculated") stays explanation.
        official, fact, source = False, "explanation", f"{source}+rule:method_not_official"
    if not official and fact == "explanation" and (terms or _form_code(part)) and _PURPOSE.search(part):   # D1
        official, fact, source = True, "rule", f"{source}+rule:purpose_of_item"
    if fact != "deadline" and _WHEN_DUE.search(part):                                              # D3
        official, fact, source = True, "deadline", f"{source}+rule:when_due"
    if not official and _INFO_NEEDED.search(part) and [k for k in named if k not in counterparties]:   # D4
        official, fact, source = True, "rule", f"{source}+rule:information_needed"
    # E1: an action's timing, not an eligibility question containing "when".
    tax_context = bool(_TAXY.search(part) or _TAX_CONTEXT.search(part) or terms)
    compliance_context = bool(tax_context or _COMPLIANCE_OBJECT.search(part)
                              or any(p.search(part) for p, _ in _data()["authorities"]))
    if fact != "deadline" and _TIME_QUESTION.search(part) and _COMPLIANCE_ACTION.search(part) \
            and compliance_context and not re.search(r"\b(?:register|registers|registering|registration)\b", part, re.I):
        official, fact, source = True, "deadline", f"{source}+rule:compliance_deadline"
    # E2: practical tax compliance is a rule even with an unknown country.
    if fact == "explanation" and not named and tax_context and _PRACTICAL.search(part):
        official, fact, source = True, "rule", f"{source}+rule:practical_compliance"
    # E3: accounting judgement does not require an official tax source.
    if fact == "rule" and _ACCOUNTING_CONTEXT.search(part) and not tax_context:
        official, fact, source = False, "standard", f"{source}+rule:accounting_standard"
    # E4: asking what enters an official calculation asks for its rule.
    if fact == "explanation" and tax_context and _INCLUDED_METHOD.search(part):
        official, fact, source = True, "rule", f"{source}+rule:included_in_method"
    return source, official, fact


def override_enabled() -> bool:
    """The set-12 deterministic country override (off unless switched on)."""
    return os.getenv("KRITON_COUNTRY_OVERRIDE", "").strip().lower() in {"1", "true", "yes", "on"}


# Explicit country names and adjectives for every country key; when any is in
# the question, the registry never overrides (explicit names take precedence).
_COUNTRY_NAME = re.compile(
    r"\b(?:uk|u\.k\.|united\s+kingdom|britain|british|england|english|scotland|scottish|wales|welsh|northern\s+ireland|"
    r"us|u\.s\.|usa|u\.s\.a\.|united\s+states|america|american|india|indian|australia|australian|canada|canadian|"
    r"singapore|singaporean|new\s+zealand|nz|ireland|irish|uae|united\s+arab\s+emirates|emirati|dubai|abu\s+dhabi|"
    r"saudi\s+arabia|saudi|ksa|malaysia|malaysian|south\s+africa|south\s+african|germany|german|france|french|"
    r"bahrain|bahraini|oman|omani|qatar|qatari|jersey|guernsey|isle\s+of\s+man|manx|eu|european\s+union)\b", re.I)


def _named_countries(part: str) -> list[str]:
    """Countries a part names, or places by its tax authority or central bank,
    or by a country-specific term in the registry ("TPAR" is Australia's; no
    inference from a shared tax word such as "VAT" or "GST")."""
    from app.orchestration.classifier_support import _AUTHORITY_PLACE
    from app.orchestration.country_terms import implied_countries
    from app.orchestration.source_taxonomy import detect_jurisdictions
    named = detect_jurisdictions(part, infer_from_tax_terms=False)
    return list(dict.fromkeys(named + [key for pattern, key in _AUTHORITY_PLACE if pattern.search(part)]
                              + implied_countries(part)))


def _qualified_countries(part: str) -> list[str]:
    """Countries the tax itself is qualified with ("UK VAT", "Indian tax
    issues", "TDS rate applies in India"); the other countries a part names
    are usually the other party."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    found: list[str] = []
    for match in _TAX_WORD.finditer(part):
        before = part[max(0, match.start() - 30):match.start()].split()[-2:]
        after = re.match(r"[^.?]{0,25}?\bin\s+((?:the\s+)?\w+(?:\s+\w+)?)", part[match.end():])
        window = " ".join(before) + " " + (after.group(1) if after else "")
        found += detect_jurisdictions(window, infer_from_tax_terms=False)
    return list(dict.fromkeys(found))


def _final(text: str, request: str, model_part, selected: str | None = None) -> dict:
    """One part: guards, then the model (or the rule table when the model gave
    nothing), the fixed rules, counterparty removal, period, domains."""
    from app.orchestration.part_classifier import classify_part
    from app.orchestration.classifier_support import period_of
    from app.orchestration.task_contract import _PART_LABEL
    from app.orchestration.country_terms import implied_terms
    part = _PART_LABEL.sub("", text or "", count=1).strip()
    rule = classify_part(text, request)
    terms = implied_terms(part)
    guarded = rule.source in ("guard:user_figures", "guard:fx_rate_given")
    if guarded:
        source, official, fact, countries = rule.source, False, "calculation", rule.tax_countries
    elif model_part is not None:
        source, official, fact, countries = "model", model_part.needs_official, model_part.fact_type, list(model_part.tax_countries)
    else:
        source, official, fact, countries = "fallback", rule.needs_official, rule.fact_type, rule.tax_countries
    rule_counterparties = {c.country for c in rule.countries if c.role == "counterparty"}
    counterparties = set(rule_counterparties)
    if model_part is not None:
        counterparties |= set(model_part.counterparty_countries)
    named = _named_countries(part)
    from app.orchestration.country_resolution import resolution_enabled, resolve
    # The user's selected jurisdiction reaches the resolver (E5); it decides only without text evidence.
    resolution = resolve(part, request, selected=selected) if resolution_enabled() else None
    if resolution is not None:
        # Option 3: countries and the other party come only from the resolver's
        # evidence; the model's and the rule table's countries are not used.
        named = list(dict.fromkeys(resolution.countries + resolution.counterparties))
        counterparties = set(resolution.counterparties)
    official_source = not guarded and bool(_OFFICIAL_SOURCE.search(part))
    if official_source:                                                     # S1
        source, official = f"{source}+rule:official_source", True
        fact = fact if fact in ("rule", "rate", "threshold", "deadline") else "rule"
        countries = named or [key for key in countries if key in named]
    elif not guarded and not official and (_TAX_WORD.search(part) or terms) and \
            [key for key in named if key not in counterparties] and \
            (_WHAT_APPLIES.search(part) or _EXPLAIN_RULE.search(part)):     # R1 / R2 / R6
        source, official, fact = f"{source}+rule:what_applies", True, "rule"
        countries = [key for key in named if key not in counterparties]
        countries = [key for key in countries if key in _qualified_countries(part)] or countries
    if not guarded:
        source, official, fact = _pattern_floors(part, terms, named, counterparties, source, official, fact)
    if official and not official_source:
        # When every country is the other party (the model swapped the roles),
        # the country the user names for itself answers the part.
        own = [c.country for c in rule.countries if c.role == "tax_country" and c.country not in rule_counterparties]
        countries = [key for key in countries if key not in counterparties] or own or countries
    if official and not countries and terms:
        # An official part with no country: a registry term places it.
        countries = [key for key in dict.fromkeys(c for c, _, _ in terms) if key not in counterparties]
        source = f"{source}+registry:country_terms" if countries else source
    registry_countries = list(dict.fromkeys(c for c, _, _ in terms))
    if official and override_enabled() and len(registry_countries) == 1 and not _COUNTRY_NAME.search(request or text or "") \
            and countries != registry_countries:
        # Set-12 experiment: no country is named anywhere in the question and
        # every registry term in the part is one country's, so the registry
        # decides ("When must an employer file Form IR21?" is Singapore's,
        # whatever the model guessed).
        countries, source = registry_countries, f"{source}+override:country_terms"
    if resolution is not None:
        # An official-source request covers every country named (as before);
        # otherwise the resolved countries, or none when unknown/candidates.
        countries = (named if official_source else list(resolution.countries)) if official else []
        source = f"{source}+resolver:{resolution.status}"
    period = period_of(part, official=True).kind if official else "unspecified"
    return {"source": source, "needs_official": official, "fact_type": fact, "tax_countries": countries,
            "counterparties": sorted(counterparties), "period": period,
            "country_terms": [{"country": c, "entry": e, "matched": m} for c, e, m in terms],
            "country_resolution": resolution.__dict__ if resolution is not None else None,
            "domains": _domains(countries, part) if official else [],
            "rule": {"needs_official": rule.needs_official, "fact_type": rule.fact_type, "tax_countries": rule.tax_countries},
            "disagrees_with_rules": (rule.needs_official, rule.fact_type, sorted(rule.tax_countries)) != (official, fact, sorted(countries))}


async def _model_parts(request: str, texts: list[str], used: dict):
    """Plain-text JSON first; one low-reasoning retry only when the reply is
    rejected by parse() (a ValueError); any other failure goes to the rule
    table. Both calls share the one time limit."""
    from app.orchestration.model_part_classifier import classify_request
    try:
        parts, completion = await classify_request(request, texts, timeout=TIMEOUT_SECONDS, mode="text",
                                                  countries=not _resolver_on())
        used["tokens"] = completion.total_tokens
        return parts
    except ValueError as exc:
        used["rejected"] = str(exc)[:120]
    parts, completion = await classify_request(request, texts, timeout=TIMEOUT_SECONDS, mode="low",
                                                  countries=not _resolver_on())
    used["tokens"], used["retried"] = completion.total_tokens, True
    return parts


async def classify(contract, request: str, selected: str | None = None) -> dict:
    """The shadow classification of a contract's parts. Never raises."""
    texts = [part.text for part in getattr(contract, "parts", []) or []] or [request]
    started = time.monotonic()
    model_parts, error, used = None, None, {"tokens": None, "retried": False, "rejected": None}
    try:
        model_parts = await asyncio.wait_for(_model_parts(request, texts, used), timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — the rule table answers instead
        error = type(exc).__name__
    tokens = used["tokens"]
    parts = []
    for index, text in enumerate(texts):
        try:
            parts.append(_final(text, request, model_parts[index] if model_parts else None, selected))
        except Exception as exc:  # noqa: BLE001
            parts.append({"source": "error", "error": type(exc).__name__})
    return {"classifier": "model-first-rev2", "latency_ms": round((time.monotonic() - started) * 1000),
            "model_error": error, "tokens": tokens, "retried": used["retried"], "rejected": used["rejected"], "parts": parts,
            "disagreements": sum(bool(p.get("disagrees_with_rules")) for p in parts)}


async def _run_and_log(contract, request: str, query_id: str, selected: str | None = None) -> None:
    try:
        record = await classify(contract, request, selected)
        logger.info("Task contract query=%s stage=classified %s", query_id, json.dumps(record, default=str))
        from app.orchestration.task_contract import _LOG_FILE, _shadow_file_enabled
        if _shadow_file_enabled():
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_FILE.open("a") as handle:
                handle.write(json.dumps({"query_id": query_id, "stage": "classified", "classified": record}, default=str) + "\n")
    except Exception:  # noqa: BLE001 — shadow only
        logger.warning("classifier_shadow_failed", extra={"query_id": query_id})


def start(contract, request: str, query_id: str, selected: str | None = None) -> asyncio.Task | None:
    """Start the shadow classification in the background when enabled; the
    caller does not wait for it. Never raises."""
    try:
        if contract is None or not shadow_enabled():
            return None
        task = asyncio.get_running_loop().create_task(_run_and_log(contract, request, query_id, selected))
        _tasks.add(task)                      # keep a reference until it finishes
        task.add_done_callback(_tasks.discard)
        return task
    except Exception:  # noqa: BLE001
        return None

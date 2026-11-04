"""Rule-table part classifier (Stage E1, shadow only; 30 Oct 2026).

A declarative table of weighted signals per fact type replaces scattered
regular expressions for deciding, per request part: whether it needs an
official figure or rule, which fact type, which countries (with their role),
which period, and how confident each decision is. Hard guards decide the
clear cases first; the remaining parts are scored, and the margin between the
best official and best non-official reading is the confidence. Low-confidence
parts are the ones a model would see in the hybrid design
(docs/contract-classifier-design-2026-10-30.md).

Recorded only: no production decision reads it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CLASSIFIER_VERSION = "rule-table-e1"
OFFICIAL_FACTS = ("rate", "threshold", "deadline", "rule")


@dataclass(frozen=True)
class Signal:
    name: str
    pattern: re.Pattern
    weight: float


def _s(name: str, pattern: str, weight: float) -> Signal:
    return Signal(name, re.compile(pattern, re.I), weight)


# ── The table ──────────────────────────────────────────────────────────────────
# Official fact types: wording that asks for a figure, limit, date or rule.
FACT_SIGNALS: dict[str, list[Signal]] = {
    "rate": [
        _s("rate_word", r"\b(?:tax|vat|gst|interest|bank|base|cash|policy|repo|duty|withholding|tds|levy|mileage|"
                        r"standard|reduced|main|higher|additional|basic|top|marginal|contribution|guarantee|excise|"
                        r"refinancing|hst|futa|medicare|social\s+security)\s+(?:interest\s+)?rates?\b", 2.0),
        _s("rate_of_tax", r"\brates?\s+(?:of|on|for)\s+(?:\w+\s+){0,3}(?:tax|vat|gst|duty|tds|contributions?|insurance|interest)", 2.0),
        _s("what_rate", r"\b(?:what|which)(?:'s|\s+(?:is|are|was|were))\s+the\s+(?:[\w'-]+\s+){0,5}(?:rates?|target\s+range|slabs?|bands?)\b", 1.5),
        _s("percentage_of", r"\b(?:what\s+)?percentage\s+(?:of\s+)?(?:vat|gst|tax|duty)|\b(?:vat|gst|tax|duty)\s+percentage", 2.0),
        _s("how_much_tax", r"\bhow\s+much\s+(?:vat|gst|tax|duty|tds|levy|stamp\s+duty)\b", 1.5),
        _s("tax_on_item", r"\b(?:vat|gst|tax|duty|hst)\s+(?:do|does|is|are)\s+[\w\s'-]{0,40}\b(?:attract|carry|charged|pay|apply)", 1.0),
        _s("interest_charged", r"\binterest\b[^.?!]{0,40}\b(?:charge[sd]?|pay|paid)\b|\b(?:charge|pay)s?\b[^.?!]{0,30}\binterest\b", 1.5),
        _s("wage_or_levy", r"\bminimum\s+wage\b|\blevy\b|\bslabs?\b|\btax\s+bands?\b|\bbrackets?\b", 1.5),
        _s("how_many_currency", r"\bhow\s+many\s+(?:rupees|pounds|euros|dollars|yen)\b|\bworth\s+today\b", 2.0),
    ],
    "threshold": [
        _s("threshold_word", r"\bthresholds?\b|\bexemption\s+limit\b|\bturnover\s+limit\b|\bregistration\s+limits?\b|\bnil[- ]rate\s+band\b", 2.0),
        _s("allowance", r"\b(?:personal|marriage|dividend|trading|property|savings|employment|annual|tax[- ]free|blind\s+person'?s)\s+allowance\b", 2.0),
        _s("exemption_amount", r"\bexempt(?:ion)?\s+amount\b|\b(?:estate|gift|inheritance)\s+tax\s+(?:exemption|exclusion)s?\b|\bannual\s+exclusion\b|\bstandard\s+deduction\b|\bwage\s+base\b", 2.0),
        _s("limit_question", r"\b(?:at|from|above|below|over|under|up\s+to|between)\s+what\s+(?:[\w-]+\s+){0,2}(?:turnover|income|value|amount|profit|profits|level|receipts|sales|revenue|payment)", 2.0),
        _s("limit_noun", r"\b(?:limit|ceiling|cap)\s+(?:for|on)\b|\bmaximum\s+deduction\b|\bwrite-?off\s+limit\b|\bhow\s+much\s+can\b[^?]{0,40}\b(?:expense|deduct|claim|earn)", 1.5),
        _s("tax_free_allowance_q", r"\btax-?free\s+(?:allowance|threshold|amount)\b|\ballowance\s+for\b", 1.5),
    ],
    "deadline": [
        _s("deadline_word", r"\bdeadlines?\b|\bdue\s+dates?\b|\blast\s+date\b|\bfiling\s+date\b|\btime\s+limits?\b|\binstalment\s+dates?\b", 2.0),
        _s("when_must", r"\bwhen\s+(?:is|are|must|do|should|does|can)\b[^?.\n]{0,60}\b(?:due|file|filed|pay|paid|submit\w*|register|lodge|deregister)", 1.5),
        _s("by_what_date", r"\bby\s+(?:what|which)\s+date\b|\bby\s+when\b|\bon\s+which\s+dates?\b|\bhow\s+long\s+after\b|\bhow\s+often\s+must\b|\bwithin\s+how\s+(?:many|long)\b", 2.0),
        _s("how_many_days", r"\bhow\s+many\s+days\b", 1.5),
        # From the tuning sets: "How long must I keep VAT records?", "How far back can I reclaim VAT ...?"
        _s("how_long_far", r"\bhow\s+(?:long|far\s+back)\s+(?:must|do|can|should|does|may)\b", 2.0),
    ],
    "rule": [
        _s("penalty", r"\bpenalt(?:y|ies)\b|\blate\s+fees?\b|\bconsequences?\s+of\b|\bwhat\s+happens\s+if\b", 2.0),
        _s("section", r"\bsection\s+\d+\w*|\bunder\s+section\b|\bwhich\s+section\b|\bcite\s+the\s+provision\b|\b\d{3}[A-Z]{0,3}\s+of\s+the\b", 2.0),
        _s("eligibility", r"\b(?:allowed|eligible|deductible|exempt|taxable|required|permitted|mandatory|zero[- ]rated|subject\s+to|qualif(?:y|ies)\s+for|apply\s+to|applies\s+to)\b", 1.0),
        _s("yes_no_tax", r"(?:^|[.?!]\s+)(?:is\s+there|are\s+there|is|are|do|does|can|must|should|will)\s+(?!you\b)", 0.8),
        _s("who_which", r"\b(?:who\s+(?:can|must|is\s+eligible)|which\s+(?:form|scheme|provision|businesses))\b", 1.5),
        _s("register_question", r"\b(?:register|registration|deregister)\b[^?]{0,40}\?", 0.8),
        _s("reverse_charge", r"\breverse\s+charge\s+appl", 1.5),
    ],
}

# Non-official readings.
NON_OFFICIAL_SIGNALS: dict[str, list[Signal]] = {
    "explanation": [
        _s("why", r"^\s*why\b|\bexplain\s+why\b", 3.0),
        _s("difference", r"\b(?:difference|distinction|relationship)\s+between\b", 2.5),
        _s("how_affect", r"\bhow\s+(?:does|do|did|can|could|would|might)\s+[^?]{0,80}\b(?:affect|influence|impact|shape|work)\b", 2.5),
        _s("describe_how", r"^\s*(?:describe|explain|outline|discuss)\s+(?:how|what|the\s+(?:concept|purpose|idea|role))\b", 2.0),
        _s("what_makes", r"^\s*what\s+makes\b", 2.0),
        _s("explain_start", r"^\s*(?:explain|describe|outline|discuss)\b", 1.0),
    ],
    "standard": [
        _s("standard_named", r"\b(?:ifrs|ias|asc|frs|ind\s*as|aasb|sfrs|gaap|isa)\s*\d*", 1.5),
        _s("method_of", r"\b(?:method|model|exemption|approach|test(?:ing)?)\s+(?:under|in)\s+(?:ifrs|ias|asc|frs|gaap|ind\s*as)", 2.0),
    ],
    "calculation": [
        _s("compute_verb", r"\b(?:calculate|compute|work\s+out|determine|prepare|record|journali[sz]e|post)\b", 1.5),
        _s("ratio_or_return", r"\b(?:ratio|margin|return\s+on|roce|roe|rate\s+of\s+return|markup|break-?even)\b", 1.5),
        _s("if_given", r"\bif\b[^?]{0,80}[£$€₹]\s?\d|[£$€₹]\s?\d[^?]{0,80}\bwhat\s+is\b", 1.5),
    ],
}

# What makes a part about an official source at all.
OFFICIAL_SUBJECT = re.compile(
    r"\b(?:vat|gst|hst|tds|tcs|itc|igst|cgst|sgst|gstr-?\w*|paye|nic|national\s+insurance|corporation\s+tax|corporate\s+(?:income\s+)?tax|"
    r"income\s+tax|capital\s+gains|inheritance\s+tax|estate\s+tax|gift\s+tax|stamp\s+duty|excise|customs|sales\s+tax|withholding|"
    r"social\s+security|medicare|futa|superannuation|super\s+guarantee|bas|e-?invoice|e-?way|mtd|making\s+tax\s+digital|self\s+assessment|"
    r"hmrc|irs|ato|iras|cbic|fta|cra|bank\s+rate|base\s+rate|cash\s+rate|repo\s+rate|federal\s+funds|refinancing|minimum\s+wage|"
    r"mileage|tax\s+return|tax\s+year|act\b|section\s+\d)", re.I)
_USER_FIGURES = re.compile(r"[£$€₹¥]\s?\d|\b\d[\d,]*(?:\.\d+)?\s*(?:lakhs?|crores?|million|bn)\b|\bA\$\s?\d|\bS\$\s?\d|\bAED\s?\d", re.I)
_RATE_GIVEN = re.compile(r"\d+(?:\.\d+)?\s*%")
# A tax, duty, contribution or charged interest whose amount depends on an
# official rate. A calculation of one is the user's own only when the rate is
# given ("S$10,000 before GST, calculate the total" needs Singapore's current
# rate: design G1 "with the rate given", 30 Oct 2026). Profit before or after
# tax, and a tax amount the user states, need no rate.
_RATED_CHARGE = re.compile(
    r"\b(?:vat|gst|hst|pst|qst|sales\s+tax|use\s+tax|income\s+tax|corporation\s+tax|corporate\s+(?:income\s+)?tax|capital\s+gains\s+tax|"
    r"cgt|inheritance\s+tax|stamp\s+duty|duty|duties|excise|customs|national\s+insurance|nics?|paye|withholding(?:\s+tax)?|tds|tcs|"
    r"superannuation|super\s+guarantee|social\s+security|medicare|payroll\s+tax|zakat|tax|(?-i:NI))\b", re.I)
_NO_RATE_NEEDED = re.compile(
    r"\b(?:profit|earnings|income|loss)\s+(?:before|after)\s+tax\b|\b(?:pre|after)-?\s?tax\b|\btax\s+(?:expense|charge|paid)\s+(?:of\s+)?"
    r"[£$€₹]?\s?\d|\b(?:vat|gst|tax|duty)\s+(?:of|was|is|amount\s+of)\s+[£$€₹]\s?\d|\btax\s+base\b|\bdeferred\s+tax\b"
    # an amount the user gives for the charge itself: "£3,000 of VAT", "£600 PAYE deducted", "tax £8,000"
    r"|(?:[£$€₹]|\b[AS]\$)\s?\d[\d,]*(?:\.\d+)?(?:k\b)?\s(?:of\s+)?(?:vat|gst|hst|paye|nics?|national\s+insurance|tds|tcs|"
    r"withholding|tax|duty|super(?:annuation)?)\b"
    r"|\b(?:vat|gst|hst|paye|nics?|tds|tcs|withholding|tax|duty)\s*(?:paid|deducted|due)?\s*(?:of|=|:)?\s*(?:[£$€₹]|\b[AS]\$)\s?\d", re.I)


def _rate_missing(part: str) -> bool:
    """A rated charge is to be worked out but its rate is not given."""
    if _RATE_GIVEN.search(part):
        return False
    return bool(_RATED_CHARGE.search(_NO_RATE_NEEDED.sub(" ", part)))
_STATUTE = re.compile(r"\bsection\s+\d+\w*|\b\d{2,3}[A-Z]{1,3}(?:\(\w+\))?\b|\bact\b", re.I)


@dataclass(frozen=True)
class Country:
    country: str
    role: str  # tax_country | counterparty


@dataclass
class PartClassification:
    part: str
    needs_official: bool
    fact_type: str
    countries: list[Country]
    period_kind: str
    confidence: dict[str, str]
    source: str
    signals: list[str] = field(default_factory=list)
    version: str = CLASSIFIER_VERSION

    @property
    def tax_countries(self) -> list[str]:
        return [c.country for c in self.countries if c.role == "tax_country"]

    def as_record(self) -> dict:
        return {"needs_official": self.needs_official, "fact_type": self.fact_type,
                "countries": [{"country": c.country, "role": c.role} for c in self.countries],
                "period": self.period_kind, "confidence": dict(self.confidence), "source": self.source,
                "signals": self.signals[:8], "version": self.version}


def _score(table: dict[str, list[Signal]], text: str) -> tuple[dict[str, float], list[str]]:
    scores, fired = {}, []
    for kind, signals in table.items():
        total = 0.0
        for signal in signals:
            if signal.pattern.search(text):
                total += signal.weight
                fired.append(f"{kind}:{signal.name}")
        scores[kind] = total
    return scores, fired


def _band(margin: float) -> str:
    return "high" if margin >= 2.0 else "medium" if margin >= 1.0 else "low"


def _countries(part: str, context: str) -> tuple[list[Country], str]:
    """Tax countries and counterparties, with a confidence: named or placed by
    an authority in the part (high), from the request's context (medium), or
    inferred only from a tax term (low)."""
    from app.orchestration.source_taxonomy import detect_jurisdictions
    from app.orchestration.classifier_support import _COUNTERPARTY, _places
    strong_part = detect_jurisdictions(part, infer_from_tax_terms=False)
    placed = _places(part, context)
    # Counterparties, also when written with an adjective ("a German business client").
    counterparty = {key for match in _COUNTERPARTY.finditer(part) for name in match.groups() if name
                    for key in detect_jurisdictions(name, infer_from_tax_terms=False)}
    counterparty |= {key for match in _ADJECTIVE_COUNTERPARTY.finditer(part)
                     for key in detect_jurisdictions(match.group(1), infer_from_tax_terms=False)}
    weak_only = [key for key in placed if key not in strong_part and not _named_by_authority(part, key)]
    tax = [key for key in placed if key not in counterparty] or [key for key in placed]
    # A country inferred only from a shared tax word gives way to a named or placed one.
    if any(key not in weak_only for key in tax):
        tax = [key for key in tax if key not in weak_only] or tax
    countries = [Country(key, "tax_country") for key in tax] + [Country(key, "counterparty") for key in sorted(counterparty - set(tax))]
    if not tax:
        return countries, "high"
    if all(key in strong_part or _named_by_authority(part, key) for key in tax):
        confidence = "high"
    elif detect_jurisdictions(context, infer_from_tax_terms=False):
        confidence = "medium"
    else:
        confidence = "low"
    return countries, confidence


_ADJECTIVE_COUNTRY_WORDS = r"(?:German|French|British|American|Indian|Singaporean|Australian|Canadian|Irish|Emirati|Saudi|Chinese|Japanese|US|UK|EU)"
_ADJECTIVE_COUNTERPARTY = re.compile(
    rf"\b({_ADJECTIVE_COUNTRY_WORDS})\s+(?:[a-z]+\s+){{0,2}}(?:clients?|customers?|consumers?|buyers?|vendors?|suppliers?)\b")


def _named_by_authority(part: str, key: str) -> bool:
    from app.orchestration.classifier_support import _AUTHORITY_PLACE
    return any(country == key and pattern.search(part) for pattern, country in _AUTHORITY_PLACE)


def classify_part(text: str, context: str = "") -> PartClassification:
    """One part, with the request as context."""
    from app.orchestration.classifier_support import _fx, _FX_GIVEN, period_of
    from app.orchestration.task_contract import _PART_LABEL
    part = _PART_LABEL.sub("", text or "", count=1).strip()
    countries, country_confidence = _countries(part, context)
    tax_countries = [c.country for c in countries if c.role == "tax_country"]
    figures = bool(_USER_FIGURES.search(part))
    rate_given = bool(_RATE_GIVEN.search(part))

    def made(official, fact, source, confidence, signals):
        period = period_of(part, official=True).kind if official else "unspecified"
        period_confidence = "high" if period not in ("implied_current", "unspecified") else "medium"
        return PartClassification(part=part[:200], needs_official=official, fact_type=fact, countries=countries,
                                  period_kind=period, source=source, signals=signals,
                                  confidence={"needs_official": confidence, "fact_type": confidence,
                                              "countries": country_confidence, "period": period_confidence})

    # Hard guards.
    if _fx(part):
        if _FX_GIVEN.search(part):
            return made(False, "calculation", "guard:fx_rate_given", "high", ["guard:fx_given"])
        return made(True, "rate", "guard:fx_current", "high", ["guard:fx"])
    official_scores, fired = _score(FACT_SIGNALS, part)
    other_scores, fired_other = _score(NON_OFFICIAL_SIGNALS, part)
    signals = fired + fired_other
    if figures and (rate_given or other_scores["calculation"] > 0) and not _rate_missing(part) and not any(
            official_scores[k] >= 2.0 and not rate_given for k in OFFICIAL_FACTS):
        return made(False, "calculation", "guard:user_figures", "high", signals + ["guard:user_figures"])
    if other_scores["explanation"] >= 2.5 and not _STATUTE.search(part):
        return made(False, "explanation", "guard:conceptual", "high", signals + ["guard:conceptual"])

    subject = bool(tax_countries) or bool(OFFICIAL_SUBJECT.search(part))
    best_official = max(OFFICIAL_FACTS, key=lambda k: official_scores[k])
    official_score = official_scores[best_official] if subject else 0.0
    # The yes/no and eligibility signals mean little without an official subject.
    if best_official == "rule" and official_scores["rule"] < 1.5 and not subject:
        official_score = 0.0
    best_other = max(NON_OFFICIAL_SIGNALS, key=lambda k: other_scores[k])
    other_score = other_scores[best_other]
    if other_scores["explanation"] >= 1.0 and not tax_countries:
        other_score += 1.0          # "Explain …" with no country: not an official-figure request
    if official_score > other_score and official_score >= 0.8:
        runner_up = max([official_scores[k] for k in OFFICIAL_FACTS if k != best_official] + [other_score])
        return made(True, best_official, "rule_table", _band(official_score - runner_up), signals)
    fact = best_other if other_score > 0 else ("standard" if other_scores["standard"] else "explanation")
    if fact == "explanation" and other_scores["standard"] > 0:
        fact = "standard"
    return made(False, fact, "rule_table", _band(other_score - official_score) if other_score else "low", signals)

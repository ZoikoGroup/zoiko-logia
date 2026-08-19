"""
Topic-aware authoritative-source taxonomy for Ask Kriton™.

The allowlist used to be keyed on jurisdiction alone, so a payroll question and
an audit question in the UK were filtered against the same ten domains. This
module adds the second dimension — jurisdiction x topic — so a question is
matched against the bodies that actually have authority over it:

  "What is the UK VAT threshold?"     -> TAX      -> hmrc.gov.uk, tax.org.uk, …
  "ISA 315 risk assessment"           -> AUDIT    -> frc.org.uk, iaasb.org, …
  "PAYE RTI submission deadline"      -> PAYROLL  -> gov.uk, cipp.org.uk, …

Kept separate from websearch.py on purpose: that module owns HTTP and parsing,
this one owns policy. The taxonomy is the part a domain expert maintains and
that a governed product needs to be able to test and audit on its own.

Detection is keyword-based, not an LLM call — the same self-gating pattern used
by frankfurter.py and dbnomics.py. It costs nothing, adds no latency, and
returns a SET because real questions span topics ("payroll tax audit" is three).
Nothing here raises: an unrecognised question yields no topics, which falls back
to the full jurisdiction list exactly as before.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# ── Topics ──────────────────────────────────────────────────────────────────
# Deliberately seven. The eighteen-odd categories people name in conversation
# collapse into these: "tax authorities", "taxation bodies", "income tax
# bodies" and "income tax authorities" are all TAX; "international standards
# boards" and "local standards boards" are both ACCOUNTING. A finer taxonomy
# would be a matrix nobody keeps current.
TAX = "tax"
ACCOUNTING = "accounting"
AUDIT = "audit"
PAYROLL = "payroll"
MARKETS = "markets"
PROFESSION = "profession"
ECONOMY = "economy"
ACADEMIC = "academic"

ALL_TOPICS = (TAX, ACCOUNTING, AUDIT, PAYROLL, MARKETS, PROFESSION, ECONOMY, ACADEMIC)


# ── Keyword signals ─────────────────────────────────────────────────────────
# Matched case-insensitively on word boundaries, so "vat" does not fire on
# "private" and "isa" does not fire on "isaac". Overlap between topics is
# intentional — "independence" is both an AUDIT and a PROFESSION concern, and
# both sets of domains are worth searching.
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    TAX: (
        "tax", "taxation", "taxable", "vat", "gst", "sales tax", "income tax",
        "corporation tax", "corporate tax", "capital gains", "stamp duty",
        "customs", "excise", "tariff", "withholding", "tds", "deduction",
        "exemption", "allowance", "tax relief", "tax credit", "tax return",
        "self assessment", "transfer pricing", "double taxation", "hmrc",
        "irs", "cbdt", "cbic", "input credit", "reverse charge",
    ),
    ACCOUNTING: (
        "ifrs", "ias", "gaap", "ind as", "accounting standard", "asc",
        "revenue recognition", "depreciation", "amortisation", "amortization",
        "balance sheet", "income statement", "profit and loss", "cash flow",
        "journal entry", "ledger", "trial balance", "accrual", "provision",
        "impairment", "goodwill", "lease", "consolidation", "financial statement",
        "double entry", "bookkeeping", "retained earnings", "working capital",
        "fixed asset", "inventory valuation", "closing entries",
    ),
    AUDIT: (
        "audit", "auditor", "auditing", "isa", "assurance", "internal control",
        "materiality", "going concern", "audit evidence", "audit opinion",
        "audit risk", "sampling", "engagement letter", "pcaob", "substantive",
        "walkthrough", "test of control", "management letter", "qualified opinion",
    ),
    PAYROLL: (
        "payroll", "paye", "salary", "salaries", "wage", "wages", "pension",
        "national insurance", "provident fund", "epf", "esi", "gratuity",
        "rti", "p60", "p45", "p11d", "w-2", "form 16", "employee benefit",
        "statutory sick pay", "maternity pay", "minimum wage", "superannuation",
    ),
    MARKETS: (
        "share price", "stock price", "stock", "shares", "ticker", "listed",
        "securities", "sebi", "sec filing", "ipo", "dividend", "market cap",
        "shareholder", "equity market", "bond", "nasdaq", "nyse", "exchange",
        "quarterly results", "earnings report", "annual report", "prospectus",
        "insider trading", "disclosure requirement",
    ),
    PROFESSION: (
        "ethic", "ethics", "professional conduct", "cpd", "cpe", "membership",
        "chartered accountant", "cpa", "aca", "acca", "cima", "icai", "icaew",
        "code of ethics", "independence", "practising certificate", "licence",
        "disciplinary", "professional scepticism", "objectivity", "confidentiality",
        "conflict of interest", "qualification", "articleship",
    ),
    # Macro indicators. Separate from TAX because the authoritative body
    # differs: a GDP figure comes from a statistics agency (ONS, BEA, MOSPI),
    # not from a tax authority. Mirrors the hints in dbnomics.py so a question
    # that connector can answer also reaches the right web sources.
    ECONOMY: (
        "gdp", "gross domestic", "gni", "gnp", "inflation", "cpi",
        "consumer price", "unemployment", "interest rate", "repo rate",
        "base rate", "economic growth", "recession", "public debt",
        "government debt", "fiscal deficit", "budget deficit", "tax-to-gdp",
        "tax to gdp", "national income", "balance of payments",
        "money supply", "per capita income",
    ),
    ACADEMIC: (
        "research", "empirical", "literature", "academic", "study finds",
        "journal article", "peer reviewed", "theory of", "meta-analysis",
    ),
}

# Precompiled so detection stays cheap on the hot path. Multi-word phrases are
# matched as phrases; \b guards single words against substring false positives.
_TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    topic: re.compile(
        "|".join(rf"\b{re.escape(kw)}\b" for kw in keywords),
        re.IGNORECASE,
    )
    for topic, keywords in _TOPIC_KEYWORDS.items()
}


# ── Domain matrix: jurisdiction -> topic -> authoritative domains ────────────
# GLOBAL always applies on top of the resolved jurisdiction, so an IFRS or
# IAASB source is reachable from any country. Entries are registered bodies,
# statute, and standard-setters — the sources that define an answer rather than
# comment on it.
_TRUSTED_DOMAINS: dict[str, dict[str, list[str]]] = {
    "GLOBAL": {
        TAX: ["oecd.org"],
        ACCOUNTING: ["ifrs.org", "iasb.org"],
        AUDIT: ["iaasb.org", "ifac.org"],
        PAYROLL: ["ilo.org"],
        MARKETS: ["iosco.org"],
        PROFESSION: ["ifac.org", "ethicsboard.org"],
        ECONOMY: ["worldbank.org", "imf.org", "oecd.org", "db.nomics.world"],
        ACADEMIC: [],
    },
    "UK": {
        TAX: ["hmrc.gov.uk", "gov.uk", "legislation.gov.uk", "tax.org.uk", "att.org.uk"],
        ACCOUNTING: ["frc.org.uk", "icaew.com", "legislation.gov.uk"],
        AUDIT: ["frc.org.uk", "icaew.com"],
        PAYROLL: ["gov.uk", "cipp.org.uk", "legislation.gov.uk"],
        MARKETS: ["fca.org.uk", "londonstockexchange.com", "find-and-update.company-information.service.gov.uk"],
        PROFESSION: ["icaew.com", "accaglobal.com", "cimaglobal.com", "frc.org.uk"],
        ECONOMY: ["ons.gov.uk", "bankofengland.co.uk", "obr.uk"],
        ACADEMIC: ["tax.org.uk", "icaew.com"],
    },
    "US": {
        TAX: ["irs.gov", "treasury.gov", "law.cornell.edu"],
        ACCOUNTING: ["fasb.org", "sec.gov"],
        AUDIT: ["pcaobus.org", "aicpa.org", "gao.gov"],
        PAYROLL: ["irs.gov", "dol.gov", "ssa.gov"],
        MARKETS: ["sec.gov", "finra.org"],
        PROFESSION: ["aicpa.org", "nasba.org"],
        ECONOMY: ["bea.gov", "bls.gov", "federalreserve.gov", "cbo.gov"],
        ACADEMIC: ["journalofaccountancy.com"],
    },
    "EU": {
        TAX: ["europa.eu"],
        ACCOUNTING: ["efrag.org", "europa.eu"],
        AUDIT: ["europa.eu"],
        PAYROLL: ["europa.eu"],
        MARKETS: ["esma.europa.eu", "europa.eu"],
        PROFESSION: ["accountancyeurope.eu"],
        ECONOMY: ["ec.europa.eu", "ecb.europa.eu"],
        ACADEMIC: [],
    },
    "UAE": {
        TAX: ["tax.gov.ae", "mof.gov.ae"],
        ACCOUNTING: ["mof.gov.ae"],
        AUDIT: ["mof.gov.ae"],
        PAYROLL: ["mohre.gov.ae"],
        MARKETS: ["sca.gov.ae", "dfm.ae"],
        PROFESSION: ["mof.gov.ae"],
        ECONOMY: ["fcsc.gov.ae", "centralbank.ae"],
        ACADEMIC: [],
    },
    "INDIA": {
        TAX: ["incometax.gov.in", "cbic.gov.in", "gst.gov.in"],
        ACCOUNTING: ["icai.org", "mca.gov.in"],
        AUDIT: ["icai.org", "cag.gov.in"],
        PAYROLL: ["epfindia.gov.in", "esic.gov.in", "labour.gov.in"],
        MARKETS: ["sebi.gov.in", "nseindia.com", "bseindia.com"],
        PROFESSION: ["icai.org", "icsi.edu", "icmai.in"],
        ECONOMY: ["mospi.gov.in", "rbi.org.in", "indiabudget.gov.in"],
        ACADEMIC: ["icai.org"],
    },
}


def detect_topics(query: str) -> set[str]:
    """Topics the question touches. Empty set when nothing matches, which the
    caller treats as "no topic signal" rather than "no sources"."""
    if not query:
        return set()
    return {topic for topic, pattern in _TOPIC_PATTERNS.items() if pattern.search(query)}


def _jurisdiction_key(jurisdiction: str) -> str:
    return (jurisdiction or "").upper().split("-")[0]  # "US-CA" -> "US"


def allowed_domains(jurisdiction: str, topics: set[str] | None = None) -> list[str]:
    """Authoritative domains for this jurisdiction, narrowed to `topics` when
    any were detected. GLOBAL is always included.

    With no topics — an off-taxonomy question, or a caller that does not detect
    them — this returns every domain for the jurisdiction, which is the
    behaviour the jurisdiction-only allowlist had before topics existed.
    """
    keys = ["GLOBAL"]
    jkey = _jurisdiction_key(jurisdiction)
    if jkey in _TRUSTED_DOMAINS and jkey != "GLOBAL":
        keys.append(jkey)

    wanted = topics or set(ALL_TOPICS)
    domains: list[str] = []
    for key in keys:
        for topic in ALL_TOPICS:
            if topic in wanted:
                for d in _TRUSTED_DOMAINS[key].get(topic, []):
                    if d not in domains:          # preserve order, drop dupes
                        domains.append(d)
    return domains


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def matches_allowlist(url: str, domains: list[str]) -> bool:
    """True when the URL's host IS an allowed domain or a subdomain of one.

    Matched on the parsed hostname, not the raw URL. A plain substring test
    (the previous behaviour) also accepted look-alikes such as
    https://gov.uk.example.com/... and https://evil.com/?q=irs.gov, which is
    not a filter you want deciding what counts as an authoritative source.
    """
    host = _hostname(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def organisation_key(url: str, domains: list[str]) -> str:
    """Which ORGANISATION a URL belongs to, for spreading sources across bodies.

    Resolves to the most general allowlist entry the host matches, so
    www.gov.uk, hmrc.gov.uk and legislation.gov.uk all collapse to "gov.uk" —
    one organisation, the UK government. Without that, five HMRC manual pages
    look like five different sources when they carry a single body's view.

    Falls back to the bare hostname for anything off the allowlist, so
    general-web results are still spread rather than lumped together.
    """
    host = _hostname(url)
    if not host:
        return url
    matched = [d for d in domains if host == d or host.endswith("." + d)]
    if matched:
        return min(matched, key=len)
    # Off-allowlist (the advisory fallback path): group on the bare host, minus
    # a leading "www." so www.example.com and example.com are not counted as
    # two separate organisations.
    return host[4:] if host.startswith("www.") else host


# Engines start dropping or mis-parsing very long boolean queries, and the
# marginal domain adds little once the first several are covered.
_MAX_SITE_FILTERS = 8


def site_filter(domains: list[str]) -> str:
    """A `site:` clause biasing retrieval TOWARD the allowlist.

    The allowlist on its own only filters results after the fact, so a narrow
    question ("PAYE RTI deadline") could return twenty blog posts, have all of
    them dropped, and fall through to the untrusted general results. Asking the
    engines for those domains up front is what actually surfaces the guidance.

    Returns "" when there is nothing to bias with, so callers can concatenate
    unconditionally.
    """
    picked = domains[:_MAX_SITE_FILTERS]
    if not picked:
        return ""
    return "(" + " OR ".join(f"site:{d}" for d in picked) + ")"

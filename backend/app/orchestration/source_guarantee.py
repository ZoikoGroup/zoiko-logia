"""Every answer names where it comes from.

1. An answer built from an attached file lists that file, even when the
   model wrote no [REF-n] marker for it: cited_only() keeps only references
   the text cites, so a correct "Dr Depreciation 137,085" from a fixed-asset
   register could show no source at all.
2. An answer with no source at all (and not computed from the user's own
   figures) says which official sources to check. These are named
   publishers, never links presented as evidence and never invented
   citations: they go in the limitations note, labelled as suggestions.
"""
from __future__ import annotations

import re

_OFFICIAL: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:ind\s?as)\b", re.I), "Ministry of Corporate Affairs and ICAI (mca.gov.in, icai.org) for Ind AS"),
    (re.compile(r"\b(?:ifrs|ias\s?\d*|ifric|iasb)\b", re.I), "IFRS Foundation (ifrs.org) for IFRS and IAS standards"),
    (re.compile(r"\b(?:us\s?gaap|asc\s?\d+|fasb)\b", re.I), "FASB (fasb.org) for US GAAP"),
    (re.compile(r"\b(?:gst|gstr|cbic|input tax credit)\b", re.I), "CBIC and the GST portal (cbic-gst.gov.in, gst.gov.in) for Indian GST"),
    (re.compile(r"\b(?:tds|tcs|income[- ]tax act|itr|section\s+\d+[a-z]*)\b", re.I), "Income Tax Department (incometaxindia.gov.in) for Indian income tax"),
    (re.compile(r"\b(?:hmrc|vat|paye|national insurance|corporation tax|self assessment)\b", re.I), "HMRC (gov.uk/hmrc) for UK tax"),
    (re.compile(r"\b(?:irs|1040|1099|w-?2|federal tax|sales tax)\b", re.I), "IRS (irs.gov) for US federal tax"),
    (re.compile(r"\b(?:audit|isa\s?\d*|assurance|auditor)\b", re.I), "IAASB (iaasb.org) for International Standards on Auditing"),
    (re.compile(r"\b(?:companies act|director|annual return|companies house)\b", re.I), "the company registry for your country (e.g. mca.gov.in, gov.uk/companies-house)"),
    # A share-price question was pointed to the IFRS Foundation and the tax
    # authority (6 Nov 2026).
    (re.compile(r"\b(?:(?:share|stock|closing|opening|intraday)\s+prices?|ticker|stock\s+exchange|market\s+cap\w*|"
                r"nse|bse|nyse|nasdaq|lse|ftse|index\s+level)\b", re.I),
     "the stock exchange the security is listed on (e.g. nseindia.com, londonstockexchange.com, nasdaq.com) "
     "or the company's investor-relations page"),
)
_DEFAULT = "the IFRS Foundation (ifrs.org) or your country's tax authority and standard setter"
MAX_SUGGESTIONS = 3
_TAX_AUDIT = re.compile(
    r"\b(?:tax(?:ation)?\s+(?:audits?|controvers\w*|authorit\w*)|transfer[- ]pricing|"
    r"permanent establishment|withholding|intercompany|multi[- ]jurisdictional tax)\b", re.I)
_FINANCIAL_AUDIT = re.compile(r"\b(?:financial[- ]statement|statutory audit|isa\s*\d+|iaasb|assurance)\b", re.I)


def keep_document_citations(cited: list, available: list) -> list:
    """The cited references, plus the first excerpt of every attached file
    the answer was composed against that ended up with no reference."""
    kept = list(cited)
    shown_files = {c.source_id for c in kept if c.provider == "uploaded_document"}
    for citation in available:
        if citation.provider == "uploaded_document" and citation.source_id not in shown_files:
            shown_files.add(citation.source_id)
            kept.append(citation)
    return kept


# The country a publisher label serves, where it serves one. The labels match
# on terms several countries share ("GST", "VAT"): "What is the standard GST
# rate in Singapore?" was pointed to India's CBIC (29 Oct 2026).
_LABEL_COUNTRY = (("Indian", "INDIA"), ("UK tax", "UK"), ("US federal", "US"), ("US GAAP", "US"), ("Ind AS", "INDIA"))


def label_country(label: str) -> str | None:
    return next((key for marker, key in _LABEL_COUNTRY if marker in label), None)


def _authority_for(key: str, text: str) -> str | None:
    """The named country's authorities, from the domains retrieval already
    trusts for it (source_taxonomy); no source is added."""
    from app.orchestration.source_taxonomy import allowed_domains, detect_topics
    # The question's topics, not its wording: the wording of a question that
    # names several countries added each one's domains to the others.
    domains = [domain for domain in sorted(allowed_domains(key, detect_topics(text), "")) if domain != "oecd.org"]
    # Government domains first (irs.gov before law.cornell.edu).
    government = [domain for domain in domains if re.search(r"(?:^|\.)(?:gov|gouv|gc|europa)\.|\.gov$", domain)]
    domains = government or domains
    if not domains:
        return None
    name = {"UK": "the UK", "US": "the US", "UAE": "the UAE"}.get(key, key.replace("_", " ").title())
    return f"the authorities for {name} ({', '.join(domains[:3])})"


def official_sources_note(query: str) -> str:
    from app.orchestration.source_taxonomy import detect_jurisdictions
    text = query or ""
    named = detect_jurisdictions(text, infer_from_tax_terms=False)
    tax_audit = bool(_TAX_AUDIT.search(text))
    matches = (["OECD (oecd.org) for transfer pricing and international tax, and the relevant local tax authority for domestic audit procedures"]
               if tax_audit else [])
    labels = [label for pattern, label in _OFFICIAL if pattern.search(text)
              and not (tax_audit and label.startswith("IAASB") and not _FINANCIAL_AUDIT.search(text))]
    # A quote asked as "the price of XYZQ123" names no exchange term; the
    # market-data check that fetched (or failed to fetch) the quote decides
    # (6 Nov 2026: pointed to the IFRS Foundation).
    from app.domains.market_data.registry import INTENT_QUOTE, detect_intent
    exchange = _OFFICIAL[-1][1]
    if exchange not in labels and detect_intent(text) == INTENT_QUOTE:
        labels.insert(0, exchange)
    # Another country's authority is no suggestion for a named one; it is
    # replaced by the named country's own (nothing changes otherwise).
    wrong_country = [label for label in labels if named and label_country(label) and label_country(label) not in named]
    matches.extend(label for label in labels if label not in wrong_country)
    if wrong_country:
        served = {label_country(label) for label in matches}
        matches.extend(authority for key in named if key not in served and (authority := _authority_for(key, text)))
    suggestions = list(dict.fromkeys(matches))[:MAX_SUGGESTIONS] or [_DEFAULT]
    return ("No source was cited for this answer. Official sources to check (suggestions, not evidence): "
            + "; ".join(suggestions) + ".")

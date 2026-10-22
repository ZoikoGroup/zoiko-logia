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
)
_DEFAULT = "the IFRS Foundation (ifrs.org) or your country's tax authority and standard setter"
MAX_SUGGESTIONS = 3


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


def official_sources_note(query: str) -> str:
    matches = [label for pattern, label in _OFFICIAL if pattern.search(query or "")]
    suggestions = list(dict.fromkeys(matches))[:MAX_SUGGESTIONS] or [_DEFAULT]
    return ("No source was cited for this answer. Official sources to check (suggestions, not evidence): "
            + "; ".join(suggestions) + ".")

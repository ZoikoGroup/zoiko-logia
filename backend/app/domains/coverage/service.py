"""US accounting, tax, and audit source-coverage registry.

This is a conservative gap detector, not a claim that unlisted topics are
covered. It stops well-known unsupported subjects from being answered using a
nearby but irrelevant source (for example, answering an ASC 842 lease question
from the only available FASB document, ASC 606).
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from app.orchestration.schemas import SourceBundle


@dataclass(frozen=True)
class CoverageRule:
    domain: str
    topic: str
    patterns: tuple[str, ...]
    required_source_terms: tuple[str, ...]
    required_authority: str


@dataclass(frozen=True)
class CoverageDecision:
    applies: bool
    covered: bool
    domain: str = ""
    topic: str = ""
    required_authority: str = ""
    reason: str = ""
    action: str = "unsupported_coverage"
    message: str = ""


_RULES = (
    # Accounting — ASC 606 is present today; the other common Codification
    # topics deliberately require their own authoritative source.
    CoverageRule("accounting", "revenue", (r"\brevenue recognition\b", r"\basc\s*606\b"), ("asc 606",), "FASB ASC 606"),
    CoverageRule("accounting", "leases", (r"\blease accounting\b", r"\basc\s*842\b", r"\bright.of.use asset\b"), ("asc 842",), "FASB ASC 842"),
    CoverageRule("accounting", "income taxes", (r"\basc\s*740\b", r"\bdeferred tax (asset|liability)\b"), ("asc 740",), "FASB ASC 740"),
    CoverageRule("accounting", "inventory", (r"\basc\s*330\b", r"\binventory accounting\b"), ("asc 330",), "FASB ASC 330"),
    CoverageRule("accounting", "impairment", (r"\basc\s*360\b", r"\blong.lived asset impairment\b"), ("asc 360",), "FASB ASC 360"),
    CoverageRule("accounting", "business combinations", (r"\basc\s*805\b", r"\bbusiness combination accounting\b"), ("asc 805",), "FASB ASC 805"),
    CoverageRule("accounting", "consolidation", (r"\basc\s*810\b", r"\bconsolidation accounting\b", r"\bvariable interest entit"), ("asc 810",), "FASB ASC 810"),
    CoverageRule("accounting", "derivatives", (r"\basc\s*815\b", r"\bderivative accounting\b", r"\bhedge accounting\b"), ("asc 815",), "FASB ASC 815"),
    CoverageRule("accounting", "stock compensation", (r"\basc\s*718\b", r"\bstock.based compensation\b"), ("asc 718",), "FASB ASC 718"),
    CoverageRule("accounting", "pensions", (r"\basc\s*715\b", r"\bpension accounting\b"), ("asc 715",), "FASB ASC 715"),

    # Audit — current repository sources cover AS 2201 and a general GAAS
    # document, but not these distinct engagement frameworks.
    CoverageRule("audit", "internal control audit", (r"\basc?\s*2201\b", r"\baudit of internal control\b", r"\bicfr audit\b"), ("as 2201",), "PCAOB AS 2201"),
    CoverageRule("audit", "government audit", (r"\byellow book\b", r"\bgovernment auditing standards\b"), ("yellow book", "government auditing standards"), "GAO Yellow Book"),
    CoverageRule("audit", "single audit", (r"\bsingle audit\b", r"\buniform guidance audit\b", r"\b2\s*cfr\s*200\b"), ("single audit", "uniform guidance", "2 cfr 200"), "Uniform Guidance and Single Audit Compliance Supplement"),
    CoverageRule("audit", "SOC engagement", (r"\bsoc\s*[123]\b", r"\bservice organization control\b"), ("soc", "at-c 320"), "AICPA SOC and attestation guidance"),
    CoverageRule("audit", "review or compilation", (r"\breview engagement\b", r"\bcompilation engagement\b", r"\bssars\b"), ("ssars",), "AICPA SSARS"),

    # Explicit legislative status must come from the live Congress.gov bill
    # record, never from a tax document that merely mentions the bill.
    CoverageRule("legislation", "congressional bill status", (r"\bstatus\s+of\s+(h\.?\s*r\.?|s\.?)\s*\d+\b",), ("congress.gov",), "Congress.gov bill record"),

    # Tax — allow a matching primary regulatory/document source if one was
    # actually retrieved, but block broad specialties absent such evidence.
    CoverageRule("tax", "corporate tax", (r"\bcorporate (income )?tax\b", r"\bform\s*1120\b"), ("corporate tax", "form 1120", "26 cfr"), "IRC/CFR and current IRS corporate guidance"),
    CoverageRule("tax", "partnership tax", (r"\bpartnership tax\b", r"\bform\s*1065\b"), ("partnership", "form 1065", "26 cfr"), "IRC/CFR and current IRS partnership guidance"),
    CoverageRule("tax", "S corporation tax", (r"\bs[ -]?corporation tax\b", r"\bform\s*1120-s\b"), ("s corporation", "1120-s", "26 cfr"), "IRC/CFR and current IRS S corporation guidance"),
    CoverageRule("tax", "estate and gift tax", (r"\bestate tax\b", r"\bgift tax\b", r"\bform\s*70[69]\b"), ("estate tax", "gift tax", "26 cfr"), "IRC/CFR and current IRS estate/gift guidance"),
    CoverageRule("tax", "international tax", (r"\binternational tax\b", r"\bforeign tax credit\b", r"\bform\s*(1116|5471|8865)\b"), ("international tax", "foreign tax", "26 cfr"), "IRC/CFR and current IRS international guidance"),
    CoverageRule("tax", "state sales tax", (r"\bsales (and use |& use )?tax\b", r"\beconomic nexus\b"), ("sales tax", "revenue department"), "Applicable state revenue authority"),
    CoverageRule("tax", "property tax", (r"\bproperty tax\b",), ("property tax", "revenue department"), "Applicable state/local tax authority"),
)


def _source_haystack(source_bundle: SourceBundle | None) -> str:
    if source_bundle is None:
        return ""
    return " ".join(f"{source.id} {source.title} {source.category}" for source in source_bundle.sources).lower()


def _matches_any(query: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in patterns)


def assess_us_professional_coverage(query: str, source_bundle: SourceBundle | None) -> CoverageDecision:
    lowered = query.lower()
    source_text = _source_haystack(source_bundle)

    # Treasury's Fiscal Data Rates of Exchange dataset does not publish GBP.
    # Do not substitute unrelated prose for an actual live rate observation.
    if re.search(r"\b(?:british pound|pound sterling|gbp)\b", lowered):
        return CoverageDecision(
            applies=True, covered=False, domain="exchange-rate", topic="British pound exchange rate",
            required_authority="an approved live GBP exchange-rate source",
            action="clarification_required",
            reason="The configured US Treasury Rates of Exchange dataset does not publish GBP.",
            message=(
                "Kriton™ cannot obtain a British-pound rate from the configured US Treasury dataset. "
                "Add an approved live GBP source or ask for a currency covered by Treasury Fiscal Data."
            ),
        )

    # Annual dollar amounts cannot be answered honestly without a year. A
    # current-looking source may represent a different tax year.
    conceptual_standard_deduction = bool(re.search(
        r"\b(itemiz|whether|decision|flow[ -]?chart|when\s+to|when\s+should|how\s+(?:the\s+)?standard\s+deduction\s+works?|eligib)",
        lowered,
    ))
    if (
        re.search(r"\bstandard deduction\b", lowered)
        and not re.search(r"\b(?:19|20)\d{2}\b", lowered)
        and not conceptual_standard_deduction
    ):
        return CoverageDecision(
            applies=True, covered=False, domain="tax", topic="standard deduction amount",
            required_authority="applicable tax year", action="clarification_required",
            reason="The question does not specify a tax year.",
            message="Which tax year should Kriton™ use for the standard deduction amount?",
        )
    for rule in _RULES:
        if not _matches_any(lowered, rule.patterns):
            continue
        covered = any(term in source_text for term in rule.required_source_terms)
        return CoverageDecision(
            applies=True,
            covered=covered,
            domain=rule.domain,
            topic=rule.topic,
            required_authority=rule.required_authority,
            reason=(
                "Required authoritative source is present in the eligible bundle."
                if covered else
                f"The eligible source bundle does not contain {rule.required_authority}."
            ),
            message=(
                "" if covered else
                f"Kriton™ does not currently have an approved {rule.required_authority} "
                f"source for this {rule.topic} question. Add and approve that authority "
                "before requesting a grounded answer."
            ),
        )
    return CoverageDecision(applies=False, covered=True)

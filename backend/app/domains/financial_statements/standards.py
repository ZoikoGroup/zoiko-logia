"""Standards applicability and accounting-policy decision engine (ZoikoLogia
Document 03, ZL-FSR-ENG-003).

Produces a Reporting Rules Resolution (RRR) for one entity, perimeter,
period and report type, before any statement is drafted. Deterministic: the
same facts and rule pack give the same result. The flow is Document 03 §6:

  R0 identity → R1 duty → R2 GAAP candidates → R3 effective edition →
  R4 size / exemption → R5 presentation and notes → R6 policies →
  R7 approve / freeze → R8 hand-off.

Country is not framework and GBP is not FRS 102. Effective rules follow the
period START, never the report date. A size exemption is applied only with
the figures and history it needs. Unknown facts are blockers, not defaults.

The rule pack below encodes the date and threshold facts Document 03 cites
(FRC, GOV.UK, IFRS Foundation, FASB; checked 24 October 2026). It is an
UNREVIEWED test pack: until a technical accounting owner signs it off,
no resolution can permit a statutory claim (Document 03 §3.1 capability).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

# ── rule pack ───────────────────────────────────────────────────────────────

SOURCES = {
    "S1": "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-102/",
    "S2": "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-101/",
    "S3": "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-105/",
    "S4": "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-factsheets/",
    "S5": "https://www.gov.uk/government/publications/filing-your-companies-house-accounts/life-of-a-company-part-1-accounts",
    "S6": "https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/",
    "S7": "https://www.ifrs.org/issued-standards/list-of-standards/ifrs-19-subsidiaries-without-public-accountability-disclosures/",
    "S8": "https://www.ifrs.org/issued-standards/list-of-standards/ias-34-interim-financial-reporting/",
    "S9": "https://www.fasb.org/standards",
    "S10": "https://www.icaew.com/technical/corporate-reporting/uk-gaap/frs-102-the-financial-reporting-standard",
    "S11": "https://www.ifrs.org/content/dam/ifrs/shop/more-details/ifrs-smes-2025-more-details.pdf",
}

# UK company size thresholds (Companies Act 2006 ss.382-384, 465-467): two of
# three for two consecutive years. Raised for financial years beginning on or
# after 6 April 2025 — by the year's START, never its end (Document 03 §4).
_UK_THRESHOLD_CHANGE = date(2025, 4, 6)
_UK_THRESHOLDS = {
    "before": {"micro": (Decimal("632000"), Decimal("316000"), 10), "small": (Decimal("10200000"), Decimal("5100000"), 50),
               "medium": (Decimal("36000000"), Decimal("18000000"), 250)},
    "from": {"micro": (Decimal("1000000"), Decimal("500000"), 10), "small": (Decimal("15000000"), Decimal("7500000"), 50),
             "medium": (Decimal("54000000"), Decimal("27000000"), 250)},
}
# Entities the small/micro regimes exclude, whatever their size.
_SMALL_EXCLUSIONS = ("public_company", "listed", "bank", "insurer", "e_money", "mifid_investment_firm", "ucits_manager")
FRS102_PERIODIC_REVIEW = date(2026, 1, 1)       # principal 2024 amendments: periods beginning on/after
FRS102_SUPPLIER_FINANCE = date(2025, 1, 1)      # supplier-finance disclosures: earlier effective date
UK_ADAPTED_FORMATS_2027 = date(2027, 1, 1)      # Factsheet 12B formats: periods beginning on/after
IFRS18_EFFECTIVE = date(2027, 1, 1)
IFRS19_EFFECTIVE = date(2027, 1, 1)
IFRS_SMES_THIRD_EDITION = date(2027, 1, 1)

RULE_PACK = {
    "id": "UK_IFRS_USGAAP_2026_TEST",
    "status": "UNREVIEWED_TEST_PACK",            # becomes REVIEWED only on technical-accounting sign-off
    "checked": "2026-10-24",
    "capabilities": {"UK": "ELIGIBILITY_RESOLVER", "IFRS": "ELIGIBILITY_RESOLVER", "US": "REFERENCE_ONLY"},
}


def rule_pack_digest() -> str:
    payload = {"pack": RULE_PACK, "sources": SOURCES,
               "thresholds": {k: {s: [str(x) for x in v] for s, v in t.items()} for k, t in _UK_THRESHOLDS.items()},
               "dates": [str(d) for d in (_UK_THRESHOLD_CHANGE, FRS102_PERIODIC_REVIEW, FRS102_SUPPLIER_FINANCE,
                                          UK_ADAPTED_FORMATS_2027, IFRS18_EFFECTIVE, IFRS19_EFFECTIVE,
                                          IFRS_SMES_THIRD_EDITION)]}
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ── inputs and outputs ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class YearFigures:
    turnover: Decimal | None = None
    balance_sheet_total: Decimal | None = None
    employees: int | None = None


@dataclass(frozen=True)
class EntityFacts:
    entity_name: str = ""
    incorporation_jurisdiction: str = ""        # "GB-ENG", "GB-SCT", "IE", "US", … ; blank = unknown
    legal_form: str = ""                        # "private_limited", "public_limited", "llp", "charity", …
    scope: str = "individual"                   # "individual" | "group"
    report_type: str = "annual"                 # "annual" | "interim" | "management" | "educational"
    period_start: date | None = None
    period_end: date | None = None
    flags: tuple[str, ...] = ()                 # e.g. "listed", "bank", "sec_registrant", "subsidiary", "charity"
    current_year: YearFigures = field(default_factory=YearFigures)
    prior_year: YearFigures = field(default_factory=YearFigures)
    prior_year_size: str = ""                   # size class the entity held last year, if known
    framework_election: str = ""                # "FRS102", "FRS102_1A", "FRS105", "FRS101", "IFRS", "IFRS_SMES", "US_GAAP"
    early_adoption: tuple[str, ...] = ()        # e.g. "IFRS18", "FRS102_PERIODIC_REVIEW"
    requested_claim: str = "illustrative"       # "illustrative" | "statutory_ready"


@dataclass(frozen=True)
class Candidate:
    framework: str
    status: str                                 # PERMITTED | CONDITIONAL | PROHIBITED | UNKNOWN
    reason: str
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppliedRule:
    rule_id: str
    outcome: str
    effective: str
    source: str


@dataclass
class Resolution:
    state: str
    candidates: list[Candidate]
    selected_framework: str | None
    size_class: str
    rules: list[AppliedRule]
    statements: list[dict]
    blockers: list[str]
    reasons: dict[str, str]
    permit_illustrative_draft: bool
    permit_statutory_claim: bool
    permitted_exports: list[str]
    rule_pack: dict = field(default_factory=lambda: {**RULE_PACK, "digest": rule_pack_digest()})

    def to_dict(self) -> dict:
        return {"state": self.state, "selected_framework": self.selected_framework, "size_class": self.size_class,
                "candidates": [asdict(c) | {"sources": [SOURCES.get(s, s) for s in c.sources]} for c in self.candidates],
                "rules": [asdict(r) | {"source": SOURCES.get(r.source, r.source)} for r in self.rules],
                "statements": self.statements, "blockers": self.blockers, "reasons": self.reasons,
                "permit_illustrative_draft": self.permit_illustrative_draft,
                "permit_statutory_claim": self.permit_statutory_claim, "permitted_exports": self.permitted_exports,
                "rule_pack": self.rule_pack}


# ── R4: size ────────────────────────────────────────────────────────────────

def _meets(year: YearFigures, limits) -> bool | None:
    """Two of three criteria (turnover, balance sheet total, employees)."""
    values = (year.turnover, year.balance_sheet_total, year.employees)
    if any(v is None for v in values):
        return None
    return sum(v <= limit for v, limit in zip(values, limits)) >= 2


def uk_size_class(facts: EntityFacts) -> tuple[str, str]:
    """(size class or UNKNOWN, reason). Thresholds by period START; two
    consecutive years; exclusions apply whatever the size."""
    if facts.period_start is None:
        return "UNKNOWN", "The period start is needed to choose the thresholds."
    band = "from" if facts.period_start >= _UK_THRESHOLD_CHANGE else "before"
    limits = _UK_THRESHOLDS[band]
    label = ("thresholds for years beginning on or after 6 April 2025" if band == "from"
             else "thresholds for years beginning before 6 April 2025")
    excluded = [f for f in facts.flags if f in _SMALL_EXCLUSIONS] + (
        ["public_company"] if facts.legal_form == "public_limited" else [])
    for size in ("micro", "small", "medium"):
        current = _meets(facts.current_year, limits[size])
        if current is None:
            return "UNKNOWN", ("Turnover, balance sheet total and average employees are all needed for "
                               f"the current year ({label}).")
        if not current:
            continue
        prior = _meets(facts.prior_year, limits[size])
        if prior is None and facts.prior_year_size != size:
            return "UNKNOWN", (f"The current year meets the {size} criteria ({label}), but the two-year test needs "
                               f"the prior year's figures or its size class.")
        if prior is False and facts.prior_year_size != size:
            return "UNKNOWN", f"The {size} criteria are met this year only; the two-year rule needs review."
        if size in ("micro", "small") and excluded:
            return "medium_or_large", f"Meets the {size} criteria but is excluded from that regime ({', '.join(excluded)})."
        return size, f"Meets the {size} criteria for two years ({label})."
    return "large", f"Exceeds the medium criteria ({label})."


# ── R0–R6 ───────────────────────────────────────────────────────────────────

def _uk(jurisdiction: str) -> bool:
    return jurisdiction.upper().startswith(("GB", "UK"))


def resolve(facts: EntityFacts, *, approved: bool = False) -> Resolution:
    blockers: list[str] = []
    reasons: dict[str, str] = {}
    rules: list[AppliedRule] = []
    candidates: list[Candidate] = []

    def block(code: str, why: str) -> None:
        if code not in blockers:
            blockers.append(code)
        reasons[code] = f"{reasons[code]} {why}" if code in reasons and why not in reasons[code] else why

    # R0 identity and perimeter
    if not facts.incorporation_jurisdiction:
        block("UNKNOWN_ENTITY", "The registered jurisdiction is not stated; currency or address alone does not decide it.")
    if not facts.legal_form:
        block("UNKNOWN_ENTITY", "The legal form is not stated.")
    if facts.period_start is None or facts.period_end is None or (facts.period_end <= facts.period_start):
        block("EFFECTIVE_DATE_CONFLICT", "A valid period start and end are needed; effective rules follow the start.")

    jurisdiction = facts.incorporation_jurisdiction.upper()
    start = facts.period_start
    size, size_reason = ("UNKNOWN", "Not assessed.")
    sector = {"charity", "bank", "insurer", "pension_scheme", "public_sector"} & set(facts.flags)

    # R1–R2 duty and candidates
    if facts.report_type in ("management", "educational"):
        candidates.append(Candidate("MANAGEMENT_BASIS", "PERMITTED",
                                    "Management or teaching output: no statutory framework claim is made."))
    elif sector:
        block("REGIME_NOT_VERIFIED", f"Sector entity ({', '.join(sorted(sector))}): a tested sector pack (e.g. a SORP) "
                                     "is required; ordinary-company defaults are blocked.")
        candidates.append(Candidate("SECTOR_PACK", "UNKNOWN", "Specialist review required.", ()))
    elif _uk(jurisdiction):
        size, size_reason = uk_size_class(facts)
        reasons["SIZE"] = size_reason
        listed = "listed" in facts.flags
        candidates += [
            Candidate("FRS102", "PERMITTED" if not listed or facts.scope == "individual" else "CONDITIONAL",
                      "UK GAAP for UK companies; a listed group's consolidated accounts must use UK-adopted IFRS.",
                      ("S1", "S10")),
            Candidate("FRS102_1A", {"small": "PERMITTED", "micro": "PERMITTED", "UNKNOWN": "UNKNOWN"}.get(size, "PROHIBITED"),
                      f"Small-entity regime. {size_reason}", ("S1", "S5")),
            Candidate("FRS105", {"micro": "PERMITTED", "UNKNOWN": "UNKNOWN"}.get(size, "PROHIBITED"),
                      f"Micro-entity regime; not available to groups preparing group accounts. {size_reason}", ("S3",)),
            Candidate("FRS101", "CONDITIONAL" if "subsidiary" in facts.flags else "PROHIBITED",
                      "Reduced disclosure for qualifying members of a group whose consolidated accounts are publicly "
                      "available; needs shareholder notification and eligibility evidence.", ("S2",)),
            Candidate("IFRS", "PERMITTED", "UK-adopted international accounting standards may be elected; required for "
                                           "consolidated accounts of listed groups.", ("S6",)),
            Candidate("US_GAAP", "PROHIBITED", "Not a permitted framework for UK Companies Act accounts.", ("S9",)),
        ]
        if facts.scope == "group" and size in ("micro",):
            candidates = [c for c in candidates if c.framework != "FRS105"] + [
                Candidate("FRS105", "PROHIBITED", "FRS 105 is not available for group accounts.", ("S3",))]
        if size == "UNKNOWN" and facts.framework_election in ("FRS102_1A", "FRS105"):
            block("ELIGIBILITY_UNPROVEN", f"{facts.framework_election} needs proven eligibility: {size_reason}")
    elif jurisdiction.startswith("US") or "sec_registrant" in facts.flags:
        candidates += [
            Candidate("US_GAAP", "CONDITIONAL", "FASB Codification is authoritative; SEC registrants add the SEC "
                                                "overlay. This pack is reference only for US GAAP.", ("S9",)),
            Candidate("IFRS", "CONDITIONAL", "IFRS only for permitted filers (e.g. foreign private issuers).", ("S6",)),
        ]
        block("REGIME_NOT_VERIFIED", "US GAAP is reference-only in this pack; no statutory output is available.")
    elif jurisdiction:
        candidates.append(Candidate("IFRS", "CONDITIONAL", "IFRS as adopted locally; local adoption and "
                                                           "endorsement must be confirmed.", ("S6",)))
        candidates.append(Candidate("LOCAL_GAAP", "UNKNOWN", "No local GAAP pack is installed for this jurisdiction."))
        block("REGIME_NOT_VERIFIED", "No tested pack for this jurisdiction's statutory requirements.")

    # Election
    by_name = {c.framework: c for c in candidates}
    selected: str | None = None
    if facts.report_type in ("management", "educational"):
        selected = "MANAGEMENT_BASIS"
    elif facts.framework_election:
        chosen = by_name.get(facts.framework_election)
        if chosen is None or chosen.status == "PROHIBITED":
            block("FRAMEWORK_NOT_SELECTED", f"{facts.framework_election} is not permitted here"
                                            + (f": {chosen.reason}" if chosen else "."))
        elif chosen.status == "PERMITTED":
            selected = facts.framework_election
        else:
            block("FRAMEWORK_NOT_SELECTED", f"{facts.framework_election} is conditional: {chosen.reason}")
    else:
        block("FRAMEWORK_NOT_SELECTED", "No framework election is recorded; candidates are listed, none is chosen.")

    # R3 effective editions — by period START
    if start is not None:
        if selected and selected.startswith("FRS102"):
            early = "FRS102_PERIODIC_REVIEW" in facts.early_adoption
            amended = start >= FRS102_PERIODIC_REVIEW or early
            rules.append(AppliedRule(
                "FRS102.PERIODIC_REVIEW_2024", "APPLIES" if amended else "NOT_YET_EFFECTIVE",
                f"periods beginning on or after {FRS102_PERIODIC_REVIEW}" + (" (early adoption elected)" if early and start < FRS102_PERIODIC_REVIEW else ""),
                "S1"))
            rules.append(AppliedRule("FRS102.SUPPLIER_FINANCE_DISCLOSURES",
                                     "APPLIES" if start >= FRS102_SUPPLIER_FINANCE else "NOT_YET_EFFECTIVE",
                                     f"periods beginning on or after {FRS102_SUPPLIER_FINANCE}", "S10"))
            rules.append(AppliedRule("UK.FORMATS", "FACTSHEET_12B" if start >= UK_ADAPTED_FORMATS_2027 else "FACTSHEET_12A",
                                     f"adapted formats for periods beginning on or after {UK_ADAPTED_FORMATS_2027}", "S4"))
        if selected == "IFRS" or (selected is None and any(c.framework == "IFRS" for c in candidates) and not _uk(jurisdiction)):
            early18 = "IFRS18" in facts.early_adoption
            rules.append(AppliedRule("IFRS18", "APPLIES" if start >= IFRS18_EFFECTIVE or early18 else "NOT_YET_EFFECTIVE",
                                     f"annual periods beginning on or after {IFRS18_EFFECTIVE}"
                                     + (" (early application elected)" if early18 and start < IFRS18_EFFECTIVE else ""), "S6"))
            rules.append(AppliedRule("IAS1", "SUPERSEDED" if start >= IFRS18_EFFECTIVE or early18 else "APPLIES",
                                     f"until IFRS 18 applies", "S6"))
            if "subsidiary" in facts.flags:
                rules.append(AppliedRule("IFRS19", "ELIGIBLE_IF_PROVEN" if start >= IFRS19_EFFECTIVE else "NOT_YET_EFFECTIVE",
                                         f"periods beginning on or after {IFRS19_EFFECTIVE}; eligibility and local "
                                         f"adoption must be proved", "S7"))
        if size != "UNKNOWN":
            rules.append(AppliedRule("UK.SIZE_THRESHOLDS", size.upper(),
                                     "years beginning on or after 6 April 2025" if start >= _UK_THRESHOLD_CHANGE
                                     else "years beginning before 6 April 2025", "S5"))

    # R5 statements required
    statements = _statements(selected, size, facts)
    if facts.report_type == "interim":
        rules.append(AppliedRule("IAS34", "CONDENSED_INTERIM", "interim reporting basis", "S8"))
    # R6 / R7 / capability
    if RULE_PACK["status"] != "REVIEWED":
        reasons["RULE_PACK"] = "The rule pack has not been signed off by a technical accounting owner."
    statutory_possible = (not blockers and selected not in (None, "MANAGEMENT_BASIS")
                          and RULE_PACK["status"] == "REVIEWED")
    if facts.requested_claim == "statutory_ready" and not statutory_possible:
        block("REVIEW_APPROVAL_MISSING", "A statutory-ready claim needs a reviewed rule pack, no blockers and an "
                                         "approved resolution.")
    if blockers:
        state = "EVIDENCE_PENDING" if any(b in ("UNKNOWN_ENTITY", "ELIGIBILITY_UNPROVEN", "EFFECTIVE_DATE_CONFLICT")
                                          for b in blockers) else "REVIEW_REQUIRED"
    else:
        state = "APPROVED" if approved else "REVIEW_REQUIRED"
    permit_statutory = statutory_possible and approved
    return Resolution(
        state=state, candidates=candidates, selected_framework=selected, size_class=size, rules=rules,
        statements=statements, blockers=blockers, reasons=reasons, permit_illustrative_draft=True,
        permit_statutory_claim=permit_statutory,
        permitted_exports=["WATERMARKED_ILLUSTRATIVE"] + (["STATUTORY_DRAFT"] if permit_statutory else []))


def _statements(selected: str | None, size: str, facts: EntityFacts) -> list[dict]:
    """R5: the statement set the selection implies, with lawful omissions named."""
    if selected in (None, "MANAGEMENT_BASIS", "SECTOR_PACK", "LOCAL_GAAP"):
        return []
    rows = [("balance_sheet", "REQUIRED", ""), ("profit_or_loss", "REQUIRED", ""), ("notes", "REQUIRED", "")]
    if selected == "FRS105":
        rows += [("other_comprehensive_income", "NOT_APPLICABLE", "FRS 105 has no OCI"),
                 ("changes_in_equity", "EXEMPT", "Not required under FRS 105"),
                 ("cash_flows", "EXEMPT", "Not required under FRS 105")]
    elif selected == "FRS102_1A":
        rows += [("other_comprehensive_income", "CONDITIONAL", "Only if OCI items exist"),
                 ("changes_in_equity", "ENCOURAGED", "Section 1A encourages, does not require"),
                 ("cash_flows", "EXEMPT", "Small entities are exempt (FRS 102 Section 1A); verify no SORP requires it")]
    else:
        rows += [("other_comprehensive_income", "REQUIRED", "Or a single statement of comprehensive income"),
                 ("changes_in_equity", "REQUIRED", ""),
                 ("cash_flows", "CONDITIONAL" if selected == "FRS101" else "REQUIRED",
                  "FRS 101 qualifying entities may be exempt" if selected == "FRS101" else "")]
    if facts.scope == "group":
        rows.append(("consolidation", "REQUIRED", "Group accounts: eliminations, NCI, policies aligned"))
    rows.append(("comparatives", "REQUIRED", "Prior-period figures are required unless a framework exception applies"))
    return [{"statement": s, "requirement": r, "note": n} for s, r, n in rows]

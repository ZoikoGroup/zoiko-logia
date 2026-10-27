"""Standards applicability and accounting-policy decision engine (ZoikoLogia
Document 03, ZL-FSR-ENG-003).

Produces a Reporting Rules Resolution (RRR) for one entity, perimeter,
period and report type, before any statement is drafted. Deterministic: the
same facts, judgments, rule pack and as-of date give the same result. The
flow is Document 03 §6:

  R0 identity → R1 duty → R2 GAAP candidates → R3 effective edition →
  R4 size / exemption → R5 presentation and notes → R6 policies →
  R7 approve / freeze → R8 hand-off.

Country is not framework and GBP is not FRS 102. Effective rules follow the
period START, never the report date. A size exemption is applied only with
the figures and history it needs. Unknown facts are blockers, not defaults.
A parent's framework never decides a subsidiary's statutory framework.
Nothing here is inferred by an LLM; text in the facts is data, not
instructions (AT-16).

The rule pack below encodes the date and threshold facts Document 03 cites
(FRC, GOV.UK, IFRS Foundation, FASB; checked 24 October 2026). It is an
UNREVIEWED test pack: until a technical accounting owner signs it off,
no resolution can permit a statutory claim (Document 03 §3.1 capability).
An expired pack blocks compliance claims with no "closest version"
fallback (AT-15); a recorded source conflict is a hard stop until a
reviewer chooses with a reason (AT-14).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

# ── rule pack ───────────────────────────────────────────────────────────────

# Document 03 §16 reference register (S12 added: FRS 104 for UK GAAP interims).
SOURCES = {
    "S1": ("FRC", "FRS 102 standard editions and amendments",
           "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-102/"),
    "S2": ("FRC", "FRS 101 Reduced Disclosure Framework",
           "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-101/"),
    "S3": ("FRC", "FRS 105 Micro-entities",
           "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-105/"),
    "S4": ("FRC", "Factsheets 12A and 12B / presentation formats",
           "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-factsheets/"),
    "S5": ("GOV.UK", "Preparing / filing UK company accounts",
           "https://www.gov.uk/government/publications/filing-your-companies-house-accounts/life-of-a-company-part-1-accounts"),
    "S6": ("IFRS Foundation", "IFRS 18 Presentation and Disclosure in Financial Statements",
           "https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/"),
    "S7": ("IFRS Foundation", "IFRS 19 Subsidiaries without Public Accountability: Disclosures",
           "https://www.ifrs.org/issued-standards/list-of-standards/ifrs-19-subsidiaries-without-public-accountability-disclosures/"),
    "S8": ("IFRS Foundation", "IAS 34 Interim Financial Reporting",
           "https://www.ifrs.org/issued-standards/list-of-standards/ias-34-interim-financial-reporting/"),
    "S9": ("FASB", "Accounting Standards Codification", "https://www.fasb.org/standards"),
    "S10": ("ICAEW", "FRS 102 editions and effective-date guide",
            "https://www.icaew.com/technical/corporate-reporting/uk-gaap/frs-102-the-financial-reporting-standard"),
    "S11": ("IFRS Foundation", "IFRS for SMEs third edition",
            "https://www.ifrs.org/content/dam/ifrs/shop/more-details/ifrs-smes-2025-more-details.pdf"),
    "S12": ("FRC", "FRS 104 Interim Financial Reporting",
            "https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-104/"),
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
    "version": "2026.10.24",
    "status": "UNREVIEWED_TEST_PACK",            # becomes REVIEWED only on technical-accounting sign-off
    "checked": "2026-10-24",
    "valid_until": "2027-04-22",                 # registry staleness SLA: re-check sources by this date (§14.1)
    "owner": "Unassigned (technical accounting standards owner)",
    "capabilities": {"UK": "ELIGIBILITY_RESOLVER", "IFRS": "ELIGIBILITY_RESOLVER", "US": "REFERENCE_ONLY"},
    # Local endorsement of IASB-issued amendments, as verified in this pack (§10.2).
    "endorsement": {"IFRS18": "NOT_VERIFIED", "IFRS19": "NOT_VERIFIED", "IFRS_SMES_2025": "NOT_VERIFIED"},
    # Disagreeing official sources (AT-14): {"id", "rule_id", "sources", "summary"}; none recorded.
    "conflicts": [],
}

# §9.1 JurisdictionPack: statute, regulator, endorsement route and capability.
JURISDICTION_PACKS = {
    "UK": {"statute": "Companies Act 2006", "regulator": "Companies House; FRC",
           "endorsement": "UK Endorsement Board (UK-adopted international accounting standards)",
           "capability": "ELIGIBILITY_RESOLVER", "owner": "Unassigned"},
    "IFRS": {"statute": "Local adoption law", "regulator": "Local securities / company regulator",
             "endorsement": "Local endorsement must be confirmed per jurisdiction",
             "capability": "ELIGIBILITY_RESOLVER", "owner": "Unassigned"},
    "US": {"statute": "Securities Exchange Act (registrants)", "regulator": "SEC; FASB standard setter",
           "endorsement": "Not applicable (FASB ASC authoritative)", "capability": "REFERENCE_ONLY", "owner": "Unassigned"},
}

CAPABILITIES = ("REFERENCE_ONLY", "ELIGIBILITY_RESOLVER", "DRAFT_STATEMENTS", "VERIFIED_RELEASE_PIPELINE")

# §6.1 finite states.
STATES = ("NEW", "CONTEXT_CAPTURED", "CANDIDATES_RESOLVED", "EVIDENCE_PENDING", "REVIEW_REQUIRED", "APPROVED", "FROZEN",
          "INVALIDATED", "REVALIDATION_REQUIRED", "REJECTED", "UNSUPPORTED")

# Release-readiness detail for each blocker (control 07): severity, owner, exact action.
BLOCKERS = {
    "UNKNOWN_ENTITY": ("CRITICAL", "Preparer", "State the registered jurisdiction and legal form with evidence."),
    "SCOPE_CONFLICT": ("CRITICAL", "Preparer", "List the group perimeter (parent and subsidiaries) for group accounts."),
    "REGIME_NOT_VERIFIED": ("CRITICAL", "Technical accounting standards owner",
                            "Install a tested pack for this regime or route to specialist review."),
    "FRAMEWORK_NOT_SELECTED": ("CRITICAL", "Preparer, then authorised accountant",
                               "Record a permitted framework election with signed evidence."),
    "SOURCE_NOT_CURRENT": ("CRITICAL", "Technical accounting standards owner",
                           "Re-check the rule-pack sources and publish a current pack version."),
    "SOURCE_CONFLICT": ("CRITICAL", "Authorised accountancy reviewer",
                        "Choose between the conflicting sources and record the reason."),
    "EFFECTIVE_DATE_CONFLICT": ("CRITICAL", "Preparer", "Enter a valid period start and end (start before end)."),
    "ELIGIBILITY_UNPROVEN": ("CRITICAL", "Preparer",
                             "Provide two years of turnover, balance sheet total and employees, and exclusion evidence."),
    "REPORT_SET_INCOMPLETE": ("HIGH", "Preparer", "Add every required statement to the requested package."),
    "POLICY_JUDGMENT_PENDING": ("HIGH", "Authorised accountancy reviewer",
                                "Record the judgment with alternatives considered and the reason."),
    "REVIEW_APPROVAL_MISSING": ("CRITICAL", "Authorised accountancy reviewer",
                                "A statutory-ready claim needs a reviewed rule pack, zero blockers and an approval."),
}


def rule_pack_digest(pack: dict | None = None) -> str:
    pack = RULE_PACK if pack is None else pack
    payload = {"pack": pack, "sources": SOURCES, "jurisdictions": JURISDICTION_PACKS,
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
    election_signed_by: str = ""                # who signed the framework election (§9.1 EntityElection)
    early_adoption: tuple[str, ...] = ()        # e.g. "IFRS18", "FRS102_PERIODIC_REVIEW"
    requested_claim: str = "illustrative"       # "illustrative" | "statutory_ready"
    group_perimeter: tuple[str, ...] = ()       # parent and subsidiaries, for group accounts
    parent_framework: str = ""                  # the parent group's framework: context only, never inherited
    prior_framework: str = ""                   # framework used last period; a change needs a judgment
    first_time_adoption: bool = False
    policy_questions: tuple[str, ...] = ()      # open material accounting-policy judgments
    requested_statements: tuple[str, ...] = ()  # the package asked for; checked against obligations (G4)
    evidence: dict = field(default_factory=dict)  # evidence refs: framework_election, early_adoption, subsidiary, …


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
    adoption: str = "MANDATORY"                 # MANDATORY | EARLY_ADOPTED | NOT_YET_EFFECTIVE | CONDITIONAL
    endorsement: str = ""                       # local endorsement as verified in the pack, where relevant


@dataclass
class Resolution:
    state: str
    candidates: list[Candidate]
    selected_framework: str | None
    framework_edition: str | None
    size_class: str
    eligibility: dict
    rules: list[AppliedRule]
    statements: list[dict]
    blockers: list[str]
    reasons: dict[str, str]
    pending_judgments: list[dict]
    judgments: dict
    permit_illustrative_draft: bool
    permit_statutory_claim: bool
    permitted_exports: list[str]
    as_of: str
    rule_pack: dict

    def findings(self) -> list[dict]:
        out = []
        for code in self.blockers:
            severity, owner, action = BLOCKERS.get(code, ("HIGH", "Reviewer", "Review."))
            out.append({"code": code, "severity": severity, "owner": owner, "reason": self.reasons.get(code, ""),
                        "action": action})
        return out

    def gates(self) -> list[dict]:
        b = set(self.blockers)
        reviewed = self.rule_pack["status"] == "REVIEWED"
        management = self.selected_framework == "MANAGEMENT_BASIS"
        rows = [
            ("G0", "Identity", not b & {"UNKNOWN_ENTITY", "SCOPE_CONFLICT", "EFFECTIVE_DATE_CONFLICT"},
             "Legal entity, jurisdiction, perimeter and period known."),
            ("G1", "Sources", reviewed and not b & {"SOURCE_NOT_CURRENT", "SOURCE_CONFLICT", "REGIME_NOT_VERIFIED"},
             "Every consequential rule resolves to a reviewed, current, unconflicted source."
             + ("" if reviewed else " The pack is not reviewed.")),
            ("G2", "Eligibility", "ELIGIBILITY_UNPROVEN" not in b, "Size and exemption tests complete."),
            ("G3", "Elections", "FRAMEWORK_NOT_SELECTED" not in b and "POLICY_JUDGMENT_PENDING" not in b,
             "Signed framework election and recorded judgments."),
            ("G4", "Content", "REPORT_SET_INCOMPLETE" not in b and (bool(self.statements) or management),
             "Required statements and exemptions computed and in the package."),
            ("G5", "Release", self.permit_statutory_claim, "Zero blockers, an approval and a reviewed pack."),
        ]
        return [{"gate": g, "title": t, "passed": bool(p), "detail": d} for g, t, p, d in rows]

    def outputs(self) -> list[dict]:
        return [
            {"type": "ILLUSTRATIVE_DRAFT", "allowed": self.permit_illustrative_draft,
             "gate": "Always watermarked; makes no compliance claim."},
            {"type": "STATUTORY_READY", "allowed": self.permit_statutory_claim,
             "gate": "Zero blockers, an approved and frozen resolution, and a reviewed rule pack."},
            {"type": "FILING_READY", "allowed": False,
             "gate": "Needs the filing and release-certification engines (Documents 06 and 07)."},
        ]

    def explanation(self) -> list[str]:
        """Kriton explanation layer (§10.1): plain language from the resolved result only."""
        lines = []
        if self.selected_framework:
            lines.append(f"Framework: {self.selected_framework.replace('_', ' ')}"
                         + (f" ({self.framework_edition})." if self.framework_edition else "."))
        else:
            lines.append("No framework is selected yet; the permitted candidates are listed.")
        if self.size_class != "UNKNOWN" or "SIZE" in self.reasons:
            lines.append(f"Size: {self.size_class.replace('_', ' ')}. {self.reasons.get('SIZE', '')}".strip())
        for rule in self.rules:
            lines.append(f"{rule.rule_id}: {rule.outcome.replace('_', ' ').lower()} ({rule.effective}).")
        if self.blockers:
            lines.append(f"{len(self.blockers)} blocker(s) stop a statutory claim: "
                         + ", ".join(b.replace("_", " ").lower() for b in self.blockers) + ".")
        lines.append("Statutory claim: " + ("permitted." if self.permit_statutory_claim else "not permitted."))
        return lines

    def to_dict(self) -> dict:
        used = sorted({s for c in self.candidates for s in c.sources} | {r.source for r in self.rules})
        return {"state": self.state, "selected_framework": self.selected_framework,
                "framework_edition": self.framework_edition, "size_class": self.size_class,
                "eligibility": self.eligibility,
                "candidates": [asdict(c) | {"sources": list(c.sources)} for c in self.candidates],
                "rules": [asdict(r) for r in self.rules], "statements": self.statements,
                "blockers": self.blockers, "reasons": self.reasons, "findings": self.findings(),
                "pending_judgments": self.pending_judgments, "judgments": self.judgments, "gates": self.gates(),
                "outputs": self.outputs(), "explanation": self.explanation(),
                "permit_illustrative_draft": self.permit_illustrative_draft,
                "permit_statutory_claim": self.permit_statutory_claim, "permitted_exports": self.permitted_exports,
                "citations": {s: {"publisher": SOURCES[s][0], "title": SOURCES[s][1], "url": SOURCES[s][2],
                                  "checked": self.rule_pack["checked"], "snapshot": None} for s in used if s in SOURCES},
                "as_of": self.as_of, "rule_pack": self.rule_pack}


# ── R4: size ────────────────────────────────────────────────────────────────

def _criteria(year: YearFigures, limits) -> tuple[bool | None, list[dict]]:
    """Two of three criteria (turnover, balance sheet total, employees), with the calculation shown."""
    values = (year.turnover, year.balance_sheet_total, year.employees)
    rows = [{"criterion": name, "value": None if v is None else str(v), "limit": str(limit),
             "within": None if v is None else v <= limit}
            for name, v, limit in zip(("turnover", "balance_sheet_total", "employees"), values, limits)]
    if any(v is None for v in values):
        return None, rows
    return sum(r["within"] for r in rows) >= 2, rows


def uk_size_evaluation(facts: EntityFacts) -> dict:
    """§9.1 EligibilityEvaluation: thresholds by period START; two consecutive
    years; exclusions apply whatever the size. Calculations are kept."""
    if facts.period_start is None:
        return {"result": "UNKNOWN", "reason": "The period start is needed to choose the thresholds.", "tests": []}
    band = "from" if facts.period_start >= _UK_THRESHOLD_CHANGE else "before"
    limits = _UK_THRESHOLDS[band]
    label = ("thresholds for years beginning on or after 6 April 2025" if band == "from"
             else "thresholds for years beginning before 6 April 2025")
    excluded = [f for f in facts.flags if f in _SMALL_EXCLUSIONS] + (
        ["public_company"] if facts.legal_form == "public_limited" else [])
    tests = []

    def done(result: str, reason: str) -> dict:
        return {"result": result, "reason": reason, "band": label, "exclusions": excluded, "tests": tests,
                "rule": "Two of three criteria, met in this and the previous year (Companies Act 2006 ss.382-384)."}

    for size in ("micro", "small", "medium"):
        current, current_rows = _criteria(facts.current_year, limits[size])
        prior, prior_rows = _criteria(facts.prior_year, limits[size])
        tests.append({"size": size, "current": current, "prior": prior,
                      "current_criteria": current_rows, "prior_criteria": prior_rows})
        if current is None:
            return done("UNKNOWN", "Turnover, balance sheet total and average employees are all needed for "
                                   f"the current year ({label}).")
        if not current:
            continue
        if prior is None and facts.prior_year_size != size:
            return done("UNKNOWN", f"The current year meets the {size} criteria ({label}), but the two-year test needs "
                                   f"the prior year's figures or its size class.")
        if prior is False and facts.prior_year_size != size:
            return done("UNKNOWN", f"The {size} criteria are met this year only; the two-year rule needs review.")
        if size in ("micro", "small") and excluded:
            return done("medium_or_large", f"Meets the {size} criteria but is excluded from that regime "
                                           f"({', '.join(excluded)}).")
        return done(size, f"Meets the {size} criteria for two years ({label}).")
    return done("large", f"Exceeds the medium criteria ({label}).")


def uk_size_class(facts: EntityFacts) -> tuple[str, str]:
    """(size class or UNKNOWN, reason)."""
    evaluation = uk_size_evaluation(facts)
    return evaluation["result"], evaluation["reason"]


# ── R0–R6 ───────────────────────────────────────────────────────────────────

def _uk(jurisdiction: str) -> bool:
    return jurisdiction.upper().startswith(("GB", "UK"))


def _edition(selected: str | None, start: date | None, early: tuple[str, ...]) -> str | None:
    """The framework as identifier and edition, pinned with the resolution (§8.1)."""
    if selected is None or start is None:
        return None
    if selected in ("FRS102", "FRS102_1A", "FRS105"):
        amended = start >= FRS102_PERIODIC_REVIEW or "FRS102_PERIODIC_REVIEW" in early
        return f"{selected}@" + ("2024-09 (Periodic Review 2024)" if amended else "2022-01")
    if selected == "IFRS":
        return "IFRS@" + ("IFRS 18 presentation" if start >= IFRS18_EFFECTIVE or "IFRS18" in early else "IAS 1 presentation")
    if selected == "IFRS_SMES":
        return "IFRS_SMES@" + ("2025 third edition" if start >= IFRS_SMES_THIRD_EDITION or "IFRS_SMES_2025" in early
                               else "2015 second edition")
    if selected == "US_GAAP":
        return "US_GAAP@ASC (reference only)"
    if selected == "MANAGEMENT_BASIS":
        return None
    return f"{selected}@pinned by pack {RULE_PACK['version']}"


def resolve(facts: EntityFacts, *, approved: bool = False, judgments: dict | None = None,
            pack: dict | None = None, as_of: date | None = None) -> Resolution:
    pack = RULE_PACK if pack is None else pack
    judgments = judgments or {}
    as_of = as_of or date.today()
    blockers: list[str] = []
    reasons: dict[str, str] = {}
    rules: list[AppliedRule] = []
    candidates: list[Candidate] = []
    pending: list[dict] = []
    evidence = {k: v for k, v in (facts.evidence or {}).items() if v}

    def block(code: str, why: str) -> None:
        if code not in blockers:
            blockers.append(code)
        reasons[code] = f"{reasons[code]} {why}" if code in reasons and why not in reasons[code] else why

    def judgment(key: str, question: str, sources: tuple[str, ...] = ()) -> None:
        decided = judgments.get(key)
        pending.append({"key": key, "question": question, "sources": list(sources), "decided": decided is not None})
        if decided is None:
            block("POLICY_JUDGMENT_PENDING" if key.startswith("POLICY:") else "SOURCE_CONFLICT", question)

    # Registry currency (AT-15): an expired pack blocks claims, with no fallback.
    if as_of > date.fromisoformat(pack["valid_until"]):
        block("SOURCE_NOT_CURRENT", f"Rule pack {pack['id']} expired on {pack['valid_until']}; no closest-version "
                                    "fallback is used.")

    # R0 identity and perimeter
    if not facts.incorporation_jurisdiction:
        block("UNKNOWN_ENTITY", "The registered jurisdiction is not stated; currency or address alone does not decide it.")
    if not facts.legal_form:
        block("UNKNOWN_ENTITY", "The legal form is not stated.")
    if facts.period_start is None or facts.period_end is None or (facts.period_end <= facts.period_start):
        block("EFFECTIVE_DATE_CONFLICT", "A valid period start and end are needed; effective rules follow the start.")
    if facts.scope == "group" and not facts.group_perimeter:
        block("SCOPE_CONFLICT", "Group accounts need the group perimeter (parent and subsidiaries).")
    if facts.parent_framework and facts.parent_framework != facts.framework_election:
        reasons["PARENT_FRAMEWORK"] = (f"The parent reports under {facts.parent_framework}; that group package is a "
                                       "separate resolution and does not decide this entity's statutory framework.")

    jurisdiction = facts.incorporation_jurisdiction.upper()
    start = facts.period_start
    size, size_reason, eligibility = "UNKNOWN", "Not assessed.", {}
    sector = {"charity", "bank", "insurer", "pension_scheme", "public_sector"} & set(facts.flags)
    subsidiary_proven = "subsidiary" in facts.flags and bool(evidence.get("subsidiary"))

    # R1–R2 duty and candidates
    if facts.report_type in ("management", "educational"):
        candidates.append(Candidate("MANAGEMENT_BASIS", "PERMITTED",
                                    "Management or teaching output: no statutory framework claim is made."))
    elif sector:
        block("REGIME_NOT_VERIFIED", f"Sector entity ({', '.join(sorted(sector))}): a tested sector pack (e.g. a SORP) "
                                     "is required; ordinary-company defaults are blocked.")
        candidates.append(Candidate("SECTOR_PACK", "UNKNOWN", "Specialist review required.", ()))
    elif _uk(jurisdiction):
        eligibility = uk_size_evaluation(facts)
        size, size_reason = eligibility["result"], eligibility["reason"]
        reasons["SIZE"] = size_reason
        listed = "listed" in facts.flags
        frs101_ready = subsidiary_proven and bool(evidence.get("shareholder_notification"))
        candidates += [
            Candidate("FRS102", "PERMITTED" if not listed or facts.scope == "individual" else "CONDITIONAL",
                      "UK GAAP for UK companies; a listed group's consolidated accounts must use UK-adopted IFRS.",
                      ("S1", "S10")),
            Candidate("FRS102_1A", {"small": "PERMITTED", "micro": "PERMITTED", "UNKNOWN": "UNKNOWN"}.get(size, "PROHIBITED"),
                      f"Small-entity regime. {size_reason}", ("S1", "S5")),
            Candidate("FRS105", {"micro": "PERMITTED", "UNKNOWN": "UNKNOWN"}.get(size, "PROHIBITED"),
                      f"Micro-entity regime; not available to groups preparing group accounts. {size_reason}", ("S3",)),
            Candidate("FRS101", "PERMITTED" if frs101_ready else "CONDITIONAL" if "subsidiary" in facts.flags else "PROHIBITED",
                      "Reduced disclosure for qualifying members of a group whose consolidated accounts are publicly "
                      "available; needs group-membership evidence and shareholder notification."
                      + (" Both are evidenced." if frs101_ready else ""), ("S2",)),
            Candidate("IFRS", "PERMITTED", "UK-adopted international accounting standards may be elected; required for "
                                           "consolidated accounts of listed groups.", ("S6",)),
            Candidate("IFRS_SMES", "PROHIBITED", "Not a framework for UK Companies Act accounts; FRS 102 draws on it "
                                                 "but is not it.", ("S11",)),
            Candidate("US_GAAP", "PROHIBITED", "Not a permitted framework for UK Companies Act accounts.", ("S9",)),
        ]
        if facts.scope == "group":
            candidates = [c for c in candidates if c.framework not in ("FRS105", "FRS102_1A")] + [
                Candidate("FRS105", "PROHIBITED", "FRS 105 is not available for group accounts.", ("S3",)),
                Candidate("FRS102_1A", "CONDITIONAL" if size in ("small", "micro") else "PROHIBITED",
                          "Small groups may use Section 1A only on the group size test.", ("S1", "S5"))]
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
        candidates.append(Candidate("IFRS_SMES", "CONDITIONAL", "Only where local law permits IFRS for SMEs.", ("S11",)))
        candidates.append(Candidate("LOCAL_GAAP", "UNKNOWN", "No local GAAP pack is installed for this jurisdiction."))
        block("REGIME_NOT_VERIFIED", "No tested pack for this jurisdiction's statutory requirements.")

    # Election (G3): a permitted candidate, elected with signed evidence.
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
            if not evidence.get("framework_election") or not facts.election_signed_by:
                block("FRAMEWORK_NOT_SELECTED", f"{selected} is elected but the signed election (who signed it and "
                                                "the evidence) is not recorded.")
        else:
            block("FRAMEWORK_NOT_SELECTED", f"{facts.framework_election} is conditional: {chosen.reason}")
    else:
        block("FRAMEWORK_NOT_SELECTED", "No framework election is recorded; candidates are listed, none is chosen.")

    # R3 effective editions — by period START
    early_unevidenced = False
    if start is not None:
        if selected and selected.startswith(("FRS102", "FRS105")):
            early = "FRS102_PERIODIC_REVIEW" in facts.early_adoption and start < FRS102_PERIODIC_REVIEW
            amended = start >= FRS102_PERIODIC_REVIEW or early
            early_unevidenced |= early
            rules.append(AppliedRule(
                "FRS102.PERIODIC_REVIEW_2024", "APPLIES" if amended else "NOT_YET_EFFECTIVE",
                f"periods beginning on or after {FRS102_PERIODIC_REVIEW}" + (" (early adoption elected)" if early else ""),
                "S1", "EARLY_ADOPTED" if early else "MANDATORY" if amended else "NOT_YET_EFFECTIVE"))
            rules.append(AppliedRule("FRS102.SUPPLIER_FINANCE_DISCLOSURES",
                                     "APPLIES" if start >= FRS102_SUPPLIER_FINANCE else "NOT_YET_EFFECTIVE",
                                     f"periods beginning on or after {FRS102_SUPPLIER_FINANCE}", "S10",
                                     "MANDATORY" if start >= FRS102_SUPPLIER_FINANCE else "NOT_YET_EFFECTIVE"))
        if selected and selected.startswith(("FRS102", "FRS105", "FRS101")):
            rules.append(AppliedRule("UK.FORMATS", "FACTSHEET_12B" if start >= UK_ADAPTED_FORMATS_2027 else "FACTSHEET_12A",
                                     f"adapted formats for periods beginning on or after {UK_ADAPTED_FORMATS_2027}", "S4"))
        if selected == "IFRS" or (selected is None and any(c.framework == "IFRS" for c in candidates) and not _uk(jurisdiction)):
            early18 = "IFRS18" in facts.early_adoption and start < IFRS18_EFFECTIVE
            early_unevidenced |= early18 and selected == "IFRS"
            applies18 = start >= IFRS18_EFFECTIVE or early18
            rules.append(AppliedRule("IFRS18", "APPLIES" if applies18 else "NOT_YET_EFFECTIVE",
                                     f"annual periods beginning on or after {IFRS18_EFFECTIVE}"
                                     + (" (early application elected)" if early18 else ""), "S6",
                                     "EARLY_ADOPTED" if early18 else "MANDATORY" if applies18 else "NOT_YET_EFFECTIVE",
                                     pack["endorsement"].get("IFRS18", "")))
            rules.append(AppliedRule("IAS1", "SUPERSEDED" if applies18 else "APPLIES", "until IFRS 18 applies", "S6"))
            if "subsidiary" in facts.flags:
                rules.append(AppliedRule("IFRS19", "ELIGIBLE_IF_PROVEN" if start >= IFRS19_EFFECTIVE else "NOT_YET_EFFECTIVE",
                                         f"periods beginning on or after {IFRS19_EFFECTIVE}; eligibility and local "
                                         f"adoption must be proved", "S7", "CONDITIONAL",
                                         pack["endorsement"].get("IFRS19", "")))
        if selected == "IFRS_SMES":
            early_smes = "IFRS_SMES_2025" in facts.early_adoption and start < IFRS_SMES_THIRD_EDITION
            early_unevidenced |= early_smes
            third = start >= IFRS_SMES_THIRD_EDITION or early_smes
            rules.append(AppliedRule("IFRS_SMES.THIRD_EDITION", "APPLIES" if third else "NOT_YET_EFFECTIVE",
                                     f"periods beginning on or after {IFRS_SMES_THIRD_EDITION}", "S11",
                                     "EARLY_ADOPTED" if early_smes else "MANDATORY" if third else "NOT_YET_EFFECTIVE",
                                     pack["endorsement"].get("IFRS_SMES_2025", "")))
        if size != "UNKNOWN":
            rules.append(AppliedRule("UK.SIZE_THRESHOLDS", size.upper(),
                                     "years beginning on or after 6 April 2025" if start >= _UK_THRESHOLD_CHANGE
                                     else "years beginning before 6 April 2025", "S5"))
    if facts.report_type == "interim":
        if selected and selected.startswith("FRS"):
            rules.append(AppliedRule("FRS104", "CONDENSED_INTERIM", "interim reporting under UK GAAP", "S12"))
        else:
            rules.append(AppliedRule("IAS34", "CONDENSED_INTERIM", "interim reporting basis", "S8"))

    # Source conflicts recorded in the pack (AT-14): visible, and a hard stop until judged.
    applied_ids = {r.rule_id for r in rules}
    for conflict in pack.get("conflicts", []):
        if conflict["rule_id"] in applied_ids:
            judgment(f"CONFLICT:{conflict['id']}", f"{conflict['rule_id']}: {conflict['summary']}",
                     tuple(conflict.get("sources", ())))

    # R5 statements required
    statements = _statements(selected, size, facts)
    if facts.requested_statements and statements:
        missing = [s["statement"] for s in statements if s["requirement"] == "REQUIRED"
                   and s["statement"] not in facts.requested_statements]
        if missing:
            block("REPORT_SET_INCOMPLETE", "The requested package omits required: "
                                           + ", ".join(m.replace("_", " ") for m in missing) + ".")

    # R6 accounting policies: material choices are judgments by an authorised reviewer.
    if selected not in (None, "MANAGEMENT_BASIS"):
        if facts.prior_framework and facts.prior_framework != selected:
            judgment("POLICY:framework_change", f"Framework changes from {facts.prior_framework} to {selected}: transition "
                                                "disclosures, opening balances and comparatives must be converted.", ("S1",))
        if facts.first_time_adoption:
            judgment("POLICY:first_time_adoption", "First-time adoption: transition exemptions and the opening "
                                                   "balance sheet need a recorded decision.", ("S1",))
        if early_unevidenced and not evidence.get("early_adoption"):
            judgment("POLICY:early_adoption", "Early adoption is elected; permissibility, the decision and its "
                                              "disclosure need evidence.", ("S1", "S6"))
        for question in facts.policy_questions:
            judgment(f"POLICY:{question}", f"Accounting-policy judgment: {question.replace('_', ' ')}.")

    # R7 capability and approval
    if pack["status"] != "REVIEWED":
        reasons["RULE_PACK"] = "The rule pack has not been signed off by a technical accounting owner."
    statutory_possible = (not blockers and selected not in (None, "MANAGEMENT_BASIS") and pack["status"] == "REVIEWED")
    if facts.requested_claim == "statutory_ready" and not statutory_possible:
        block("REVIEW_APPROVAL_MISSING", "A statutory-ready claim needs a reviewed rule pack, no blockers and an "
                                         "approved resolution.")
    if "REGIME_NOT_VERIFIED" in blockers:
        state = "UNSUPPORTED"
    elif blockers:
        state = "EVIDENCE_PENDING" if any(b in ("UNKNOWN_ENTITY", "ELIGIBILITY_UNPROVEN", "EFFECTIVE_DATE_CONFLICT",
                                                "SCOPE_CONFLICT") for b in blockers) else "REVIEW_REQUIRED"
    else:
        state = "APPROVED" if approved else "REVIEW_REQUIRED"
    permit_statutory = statutory_possible and approved
    return Resolution(
        state=state, candidates=candidates, selected_framework=selected,
        framework_edition=_edition(selected, start, facts.early_adoption), size_class=size, eligibility=eligibility,
        rules=rules, statements=statements, blockers=blockers, reasons=reasons, pending_judgments=pending,
        judgments=judgments, permit_illustrative_draft=True, permit_statutory_claim=permit_statutory,
        permitted_exports=["WATERMARKED_ILLUSTRATIVE"] + (["STATUTORY_DRAFT"] if permit_statutory else []),
        as_of=as_of.isoformat(), rule_pack={**pack, "digest": rule_pack_digest(pack)})


def _statements(selected: str | None, size: str, facts: EntityFacts) -> list[dict]:
    """R5: the statement set the selection implies, with lawful omissions named."""
    if selected in (None, "MANAGEMENT_BASIS", "SECTOR_PACK", "LOCAL_GAAP"):
        return []
    if facts.report_type == "interim":
        # IAS 34 / FRS 104 condensed package: not the annual template (AT-10).
        rows = [("condensed_balance_sheet", "REQUIRED", "Compared with the last annual balance sheet date"),
                ("condensed_profit_or_loss", "REQUIRED", "Current interim and year to date, with comparable prior periods"),
                ("condensed_changes_in_equity", "REQUIRED", "Year to date, with the comparable prior year to date"),
                ("condensed_cash_flows", "REQUIRED", "Year to date, with the comparable prior year to date"),
                ("selected_explanatory_notes", "REQUIRED", "Significant events and changes since the last annual report")]
        return [{"statement": s, "requirement": r, "note": n} for s, r, n in rows]
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

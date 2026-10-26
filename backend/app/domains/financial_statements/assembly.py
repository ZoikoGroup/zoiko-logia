"""Financial statement assembly, cross-statement reconciliation and
disclosure completeness (ZoikoLogia Document 05, ZL-FSR-ENG-005).

Consumes the two upstream decisions and never overrides them:
  * Document 04 — an APPROVED trial-balance snapshot (approved mappings plus
    approved journals; its content hash pins it);
  * Document 03 — a FROZEN Reporting Rules Resolution (framework, edition,
    statement set and exemptions).

Assembly order (§5): resolve → freeze → build → measure → assemble → tie out
→ disclose. Every amount is a Decimal calculation over approved concepts; no
model writes a number. Each statement is drawn from the same canonical
facts; the reconcilers recompute from presented lines and from the
concepts, and record the exact residual — nothing is plugged or rounded away
(AS-025, §11). Missing evidence is a finding, never an invented figure: no
comparatives without a prior approved snapshot (AT-16), no cash flow
statement without cash-movement data (AS-036, AT-36), no dividend without
declaration evidence (AS-026), no tax payable inferred from the tax charge
(AT-14), no note text without evidence (AS-039, AS-042).

Release invariant: no applicable framework, no approved source, a mandatory
gap or a cross-statement failure blocks statutory release; a watermarked
draft may still be shown. The assembly and disclosure rule set below is an
UNREVIEWED test pack, like Document 03's.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .journals import RESTATING
from .mapping import LINES

ZERO = Decimal("0")
RULESET = {"id": "FS-ASSEMBLY-2026.10-TEST", "version": "2026.10.26", "status": "UNREVIEWED_TEST_PACK",
           "owner": "Unassigned (technical accounting standards owner)"}

ASSETS = ("bs.intangibles", "bs.ppe", "bs.inventories", "bs.trade_receivables", "bs.cash")
LIABILITIES = ("bs.trade_payables", "bs.tax_payable", "bs.borrowings", "bs.deferred_tax", "bs.provisions")
INCOME = ("pl.revenue", "pl.other_income", "pl.finance_income")
CREDIT_NORMAL = (*LIABILITIES, "eq.share_capital", "eq.retained_earnings", *INCOME)

# Cash-movement data a cash flow statement needs (AS-030 to AS-034); 0 is a valid answer, blank is not.
CASH_FLOW_DATA = {
    "depreciation_amortisation": "Depreciation and amortisation charged in the period",
    "fixed_asset_additions": "Cash paid for property, plant, equipment and intangibles",
    "disposal_proceeds": "Cash received from fixed-asset disposals",
    "disposals_nbv": "Carrying amount of fixed assets disposed of",
    "current_tax_charge": "Current tax charge (the rest of the tax charge is deferred)",
    "tax_paid": "Tax paid in cash",
    "interest_paid": "Interest paid in cash",
    "interest_received": "Interest received in cash",
    "borrowings_drawn": "New borrowings drawn",
    "borrowings_repaid": "Borrowings repaid",
    "shares_issued": "Cash from shares issued",
    "dividends_paid": "Dividends paid in cash",
    "fx_effect": "Effect of exchange-rate changes on cash",
}

OWNER = {"P0": "Preparer, then technical reviewer", "P1": "Preparer", "P2": "Technical reviewer", "P3": "Preparer"}


# ── inputs ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Snapshot:
    """An approved Document 04 snapshot, as Document 05 consumes it."""
    trial_balance_id: str
    content_hash: str
    approved: bool
    line_totals: dict                       # line_id -> net debit (Decimal) from approved mappings
    journals: tuple = ()                    # approved journals: {"journal_id", "correction_type", "lines": [...]}
    period_end: str = ""
    units: str = "units"
    supporting: dict = field(default_factory=dict)   # line_id -> {"kind", "total", "agreed"}
    findings: tuple = ()                    # Document 04 findings (codes, severities)


@dataclass(frozen=True)
class PackageInputs:
    snapshot: Snapshot
    resolution: dict | None = None          # stored Document 03 resolution view
    prior: Snapshot | None = None           # the approved prior-period snapshot, for comparatives
    schedules: dict = field(default_factory=dict)    # evidence schedules: cash movements, splits, first_period, …
    disclosures: dict = field(default_factory=dict)  # requirement_id -> submission
    dispositions: dict = field(default_factory=dict)  # finding code -> reviewer disposition (P2)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str                           # P0 hard stop | P1 high | P2 review | P3 informational
    message: str
    rule: str
    action: str
    refs: tuple = ()
    release_only: bool = False              # blocks statutory release, not internal approval

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message, "rule": self.rule,
                "owner": OWNER[self.severity], "action": self.action, "refs": list(self.refs),
                "release_only": self.release_only}


def _d(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


# ── build and measure (§5 steps 2–3) ────────────────────────────────────────

def concepts(snapshot: Snapshot) -> tuple[dict[str, Decimal], list[str]]:
    """Net debit per concept: approved mappings plus approved journals. Unknown concepts are orphans."""
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line_id, amount in snapshot.line_totals.items():
        totals[line_id] += _d(amount) or ZERO
    for journal in snapshot.journals:
        for line in journal.get("lines", ()):
            totals[line["line_id"]] += (_d(line.get("debit")) or ZERO) - (_d(line.get("credit")) or ZERO)
    orphans = sorted(k for k in totals if k not in LINES)
    return dict(totals), orphans


def presented(net: dict[str, Decimal]) -> dict[str, Decimal]:
    """Presentation sign: assets, expenses and distributions as debits; the rest as credits."""
    return {k: (-v if k in CREDIT_NORMAL else v) for k, v in net.items()}


def profit_and_loss(p: dict[str, Decimal]) -> dict[str, Decimal]:
    g = lambda k: p.get(k, ZERO)  # noqa: E731
    gross = g("pl.revenue") - g("pl.cost_of_sales")
    operating = gross - g("pl.distribution_costs") - g("pl.administrative_expenses") + g("pl.other_income")
    before_financing = operating + g("pl.finance_income")            # IFRS 18 subtotal
    pbt = operating + g("pl.finance_income") - g("pl.finance_costs")
    return {"revenue": g("pl.revenue"), "cost_of_sales": g("pl.cost_of_sales"), "gross_profit": gross,
            "distribution_costs": g("pl.distribution_costs"), "administrative_expenses": g("pl.administrative_expenses"),
            "other_income": g("pl.other_income"), "operating_profit": operating,
            "finance_income": g("pl.finance_income"), "profit_before_financing_and_tax": before_financing,
            "finance_costs": g("pl.finance_costs"), "profit_before_tax": pbt, "tax": g("pl.tax"),
            "profit": pbt - g("pl.tax")}


def balance_sheet(p: dict[str, Decimal], profit: Decimal, borrowings_after_one_year: Decimal | None) -> dict[str, Decimal]:
    g = lambda k: p.get(k, ZERO)  # noqa: E731
    long_borrowings = borrowings_after_one_year if borrowings_after_one_year is not None else ZERO
    short_borrowings = g("bs.borrowings") - long_borrowings
    fixed = g("bs.intangibles") + g("bs.ppe")
    current = g("bs.inventories") + g("bs.trade_receivables") + g("bs.cash")
    due_within = g("bs.trade_payables") + g("bs.tax_payable") + short_borrowings
    provisions = g("bs.provisions") + g("bs.deferred_tax")
    retained = g("eq.retained_earnings") + profit - g("eq.distributions")
    return {"intangibles": g("bs.intangibles"), "ppe": g("bs.ppe"), "fixed_assets": fixed,
            "inventories": g("bs.inventories"), "receivables": g("bs.trade_receivables"), "cash": g("bs.cash"),
            "current_assets": current, "total_assets": fixed + current,
            "trade_payables": g("bs.trade_payables"), "tax_payable": g("bs.tax_payable"),
            "borrowings_current": short_borrowings, "creditors_within_one_year": due_within,
            "net_current_assets": current - due_within, "total_assets_less_current_liabilities": fixed + current - due_within,
            "borrowings_non_current": long_borrowings, "provisions": g("bs.provisions"), "deferred_tax": g("bs.deferred_tax"),
            "provisions_total": provisions, "total_liabilities": due_within + long_borrowings + provisions,
            "net_assets": fixed + current - due_within - long_borrowings - provisions,
            "share_capital": g("eq.share_capital"), "retained_earnings": retained,
            "total_equity": g("eq.share_capital") + retained}


# ── layouts (AS-003, AS-018, AS-019): framework-specific, from the same facts ─

def _family(resolution: dict | None) -> str:
    result = (resolution or {}).get("result") or {}
    selected = result.get("selected_framework")
    if selected in ("FRS102", "FRS102_1A", "FRS101", "FRS105"):
        return "UK_COMPANIES_ACT"
    if selected == "IFRS":
        applies18 = any(r["rule_id"] == "IFRS18" and r["outcome"] == "APPLIES" for r in result.get("rules", []))
        return "IFRS18" if applies18 else "IAS1"
    if selected == "IFRS_SMES":
        return "IAS1"
    if selected == "US_GAAP":
        return "US_GAAP_REFERENCE"
    return "MANAGEMENT"


_PL_LAYOUTS = {
    "UK_COMPANIES_ACT": [("revenue", "Turnover", "line"), ("cost_of_sales", "Cost of sales", "line"),
                         ("gross_profit", "Gross profit", "subtotal"), ("distribution_costs", "Distribution costs", "line"),
                         ("administrative_expenses", "Administrative expenses", "line"),
                         ("other_income", "Other operating income", "line"), ("operating_profit", "Operating profit", "subtotal"),
                         ("finance_income", "Interest receivable and similar income", "line"),
                         ("finance_costs", "Interest payable and similar expenses", "line"),
                         ("profit_before_tax", "Profit before taxation", "subtotal"), ("tax", "Tax on profit", "line"),
                         ("profit", "Profit for the financial year", "total")],
    "IAS1": [("revenue", "Revenue", "line"), ("cost_of_sales", "Cost of sales", "line"),
             ("gross_profit", "Gross profit", "subtotal"), ("other_income", "Other income", "line"),
             ("distribution_costs", "Distribution costs", "line"), ("administrative_expenses", "Administrative expenses", "line"),
             ("operating_profit", "Operating profit (entity-presented subtotal under IAS 1)", "subtotal"),
             ("finance_income", "Finance income", "line"), ("finance_costs", "Finance costs", "line"),
             ("profit_before_tax", "Profit before tax", "subtotal"), ("tax", "Income tax expense", "line"),
             ("profit", "Profit for the year", "total")],
    "IFRS18": [("revenue", "Revenue", "line"), ("cost_of_sales", "Cost of sales", "line"),
               ("gross_profit", "Gross profit", "subtotal"), ("other_income", "Other operating income", "line"),
               ("distribution_costs", "Distribution costs", "line"), ("administrative_expenses", "Administrative expenses", "line"),
               ("operating_profit", "Operating profit", "subtotal"),
               ("finance_income", "Investing category: interest income on cash and deposits", "line"),
               ("profit_before_financing_and_tax", "Profit before financing and income taxes", "subtotal"),
               ("finance_costs", "Financing category: interest expense on borrowings", "line"),
               ("profit_before_tax", "Profit before income taxes", "subtotal"), ("tax", "Income tax expense", "line"),
               ("profit", "Profit for the year", "total")],
}
_PL_LAYOUTS["US_GAAP_REFERENCE"] = _PL_LAYOUTS["MANAGEMENT"] = [
    ("revenue", "Revenue", "line"), ("cost_of_sales", "Cost of sales", "line"), ("gross_profit", "Gross profit", "subtotal"),
    ("distribution_costs", "Selling and distribution", "line"), ("administrative_expenses", "General and administrative", "line"),
    ("other_income", "Other operating income", "line"), ("operating_profit", "Result from operations", "subtotal"),
    ("finance_income", "Interest income", "line"), ("finance_costs", "Interest expense", "line"),
    ("profit_before_tax", "Result before tax", "subtotal"), ("tax", "Tax", "line"), ("profit", "Net result", "total")]

_BS_LAYOUTS = {
    "UK_COMPANIES_ACT": [("intangibles", "Intangible assets", "line"), ("ppe", "Tangible assets", "line"),
                         ("fixed_assets", "Fixed assets", "subtotal"), ("inventories", "Stocks", "line"),
                         ("receivables", "Debtors", "line"), ("cash", "Cash at bank and in hand", "line"),
                         ("current_assets", "Current assets", "subtotal"), ("trade_payables", "Trade and other creditors", "line"),
                         ("tax_payable", "Corporation tax", "line"), ("borrowings_current", "Bank loans and overdrafts", "line"),
                         ("creditors_within_one_year", "Creditors: amounts falling due within one year", "subtotal"),
                         ("net_current_assets", "Net current assets", "subtotal"),
                         ("total_assets_less_current_liabilities", "Total assets less current liabilities", "subtotal"),
                         ("borrowings_non_current", "Creditors: amounts falling due after more than one year", "line"),
                         ("provisions_total", "Provisions for liabilities", "line"), ("net_assets", "Net assets", "total"),
                         ("share_capital", "Called up share capital", "line"),
                         ("retained_earnings", "Profit and loss account", "line"),
                         ("total_equity", "Shareholders' funds", "total")],
}
_BS_LAYOUTS["IAS1"] = _BS_LAYOUTS["IFRS18"] = _BS_LAYOUTS["US_GAAP_REFERENCE"] = _BS_LAYOUTS["MANAGEMENT"] = [
    ("ppe", "Property, plant and equipment", "line"), ("intangibles", "Intangible assets", "line"),
    ("fixed_assets", "Non-current assets", "subtotal"), ("inventories", "Inventories", "line"),
    ("receivables", "Trade and other receivables", "line"), ("cash", "Cash and cash equivalents", "line"),
    ("current_assets", "Current assets", "subtotal"), ("total_assets", "Total assets", "total"),
    ("share_capital", "Share capital", "line"), ("retained_earnings", "Retained earnings", "line"),
    ("total_equity", "Total equity", "total"), ("borrowings_non_current", "Non-current borrowings", "line"),
    ("deferred_tax", "Deferred tax liabilities", "line"), ("provisions", "Provisions", "line"),
    ("trade_payables", "Trade and other payables", "line"), ("tax_payable", "Current tax liabilities", "line"),
    ("borrowings_current", "Current borrowings", "line"), ("total_liabilities", "Total liabilities", "total")]

_CONCEPTS_OF = {
    "revenue": ("pl.revenue",), "cost_of_sales": ("pl.cost_of_sales",), "distribution_costs": ("pl.distribution_costs",),
    "administrative_expenses": ("pl.administrative_expenses",), "other_income": ("pl.other_income",),
    "finance_income": ("pl.finance_income",), "finance_costs": ("pl.finance_costs",), "tax": ("pl.tax",),
    "intangibles": ("bs.intangibles",), "ppe": ("bs.ppe",), "inventories": ("bs.inventories",),
    "receivables": ("bs.trade_receivables",), "cash": ("bs.cash",), "trade_payables": ("bs.trade_payables",),
    "tax_payable": ("bs.tax_payable",), "borrowings_current": ("bs.borrowings",), "borrowings_non_current": ("bs.borrowings",),
    "provisions": ("bs.provisions",), "deferred_tax": ("bs.deferred_tax",), "provisions_total": ("bs.provisions", "bs.deferred_tax"),
    "share_capital": ("eq.share_capital",), "retained_earnings": ("eq.retained_earnings", "eq.distributions"),
}


def _lines(layout, current: dict, prior: dict | None) -> list[dict]:
    return [{"line_id": key, "label": label, "kind": kind, "amount": _s(current.get(key, ZERO)),
             "prior": _s(prior.get(key, ZERO)) if prior is not None else None,
             "concepts": list(_CONCEPTS_OF.get(key, ()))} for key, label, kind in layout]


# ── assembly ────────────────────────────────────────────────────────────────

_STATEMENT_ALIASES = {"condensed_balance_sheet": "balance_sheet", "condensed_profit_or_loss": "profit_or_loss",
                      "condensed_changes_in_equity": "changes_in_equity", "condensed_cash_flows": "cash_flows",
                      "selected_explanatory_notes": "notes"}
_DEFAULT_MANIFEST = [("balance_sheet", "REQUIRED", ""), ("profit_or_loss", "REQUIRED", ""),
                     ("changes_in_equity", "REQUIRED", ""), ("cash_flows", "CONDITIONAL", "Management basis"),
                     ("notes", "REQUIRED", ""), ("comparatives", "REQUIRED", "")]
_COMPLIANCE_CLAIM = re.compile(r"\b(?:in\s+(?:full\s+)?compliance\s+with|compl(?:y|ies)\s+with|compliant\s+with|"
                               r"prepared\s+in\s+accordance\s+with|true\s+and\s+fair)\b", re.I)
_NO_RELATED_PARTIES = re.compile(r"\bno\s+related[\s-]+part(?:y|ies)\b|\bno\s+(?:such\s+)?transactions\s+with\s+related", re.I)


def assemble(inputs: PackageInputs) -> dict:
    findings: list[Finding] = []
    add = findings.append
    snap, prior, resolution, schedules = inputs.snapshot, inputs.prior, inputs.resolution, inputs.schedules or {}
    result = (resolution or {}).get("result") or {}
    facts = (resolution or {}).get("facts") or {}
    family = _family(resolution)

    # 0 Resolve (AS-001, AS-002, AS-007)
    if resolution is None:
        add(Finding("FRAMEWORK_UNRESOLVED", "P0", "No Reporting Rules Resolution is attached; this is a management "
                    "draft only.", "AS-001", "Attach a frozen Document 03 resolution for this entity and period."))
    elif resolution.get("state") == "UNSUPPORTED" or "REGIME_NOT_VERIFIED" in result.get("blockers", []):
        add(Finding("SCOPE_UNSUPPORTED", "P0", "The resolved regime is not supported by a tested pack; no statutory "
                    "output is available.", "AT-34", "Route to specialist review."))
    elif resolution.get("state") != "FROZEN":
        add(Finding("FRAMEWORK_NOT_APPROVED", "P0", f"The resolution is {resolution.get('state', '').lower()}, not "
                    "approved and frozen.", "AS-001", "Approve the Document 03 resolution (a different person)."))
    if resolution is not None and not result.get("permit_statutory_claim"):
        add(Finding("STATUTORY_NOT_PERMITTED", "P0", "The resolution does not permit a statutory claim (rule pack "
                    f"{result.get('rule_pack', {}).get('status', 'unknown').lower().replace('_', ' ')}).", "AS-007",
                    "Needs a reviewed rule pack and an approved resolution with no blockers.", release_only=True))
    profile = {
        "family": family, "framework": result.get("selected_framework"), "edition": result.get("framework_edition"),
        "resolution_id": (resolution or {}).get("id"), "resolution_revision": (resolution or {}).get("revision"),
        "resolution_state": (resolution or {}).get("state"), "rule_pack_digest": (resolution or {}).get("rule_pack_digest"),
        "entity": facts.get("entity_name", ""), "period_start": facts.get("period_start", ""),
        "period_end": facts.get("period_end", "") or snap.period_end, "scope": facts.get("scope", "individual"),
        "report_type": facts.get("report_type", "annual"), "units": snap.units, "ruleset": RULESET,
    }
    if facts.get("period_end") and snap.period_end and facts["period_end"] != snap.period_end:
        add(Finding("PERIOD_MISMATCH", "P0", f"The trial balance is dated {snap.period_end} but the resolution's period "
                    f"ends {facts['period_end']}.", "AS-014", "Use the trial balance for the resolved period."))
    manifest = [(s["statement"], s["requirement"], s.get("note", "")) for s in result.get("statements", [])] \
        or _DEFAULT_MANIFEST
    interim = any(s.startswith("condensed_") for s, _, _ in manifest)

    # 1 Freeze (AS-007): only an approved snapshot is reported from.
    halted = None
    if not snap.approved:
        halted = "SOURCE_UNAPPROVED"
        add(Finding("SOURCE_UNAPPROVED", "P0", "The trial balance has no approved snapshot (Document 04); nothing is "
                    "assembled from unapproved data.", "§5 step 1", "Approve the trial-balance snapshot first."))
    if prior is not None and not prior.approved:
        add(Finding("PRIOR_UNAPPROVED", "P0", "The prior-period trial balance is not an approved snapshot.", "AT-16",
                    "Approve the prior-period snapshot or remove it."))
        prior = None
    if prior is not None and prior.content_hash == snap.content_hash:
        add(Finding("DUPLICATE_PERIOD", "P0", "The prior period is the same snapshot as the current period.", "AT-22",
                    "Select the prior-period trial balance."))
        prior = None
    if prior is not None and snap.period_end and prior.period_end and prior.period_end >= snap.period_end:
        add(Finding("PRIOR_PERIOD_ORDER", "P0", f"The prior snapshot ({prior.period_end}) is not before the current "
                    f"period end ({snap.period_end}).", "AS-014", "Select the preceding period."))
        prior = None
    if any(f.get("code") == "MIXED_CURRENCY" for f in snap.findings):
        add(Finding("FX_POLICY_REQUIRED", "P0", "The source contains more than one currency; an approved functional/"
                    "presentation currency and translation policy is required.", "AS-046, AT-24",
                    "Record the FX policy and translated balances."))
    if profile["scope"] == "group":
        add(Finding("CONSOLIDATION_NOT_SUPPORTED", "P0", "Group statements need component snapshots, eliminations and "
                    "NCI; this engine does not consolidate, and never sums entity balances.", "§12, AT-21",
                    "Prepare consolidation entries in a tested group pack."))

    # 2–3 Build and measure
    current_net, orphans = concepts(snap) if not halted else ({}, [])
    if orphans:
        halted = "CALCULATION_INTEGRITY_FAIL"
        add(Finding("ORPHAN_CONCEPT", "P0", "Amounts reference unknown statement concepts: " + ", ".join(orphans) + ".",
                    "§4.1", "Map them to catalogue lines in Document 04.", tuple(orphans)))
    if halted:
        return _result(inputs, "SCOPE_RESOLVED" if resolution else "CREATED", halted, profile, manifest, [], [], [],
                       findings, {}, schedules)

    prior_net = concepts(prior)[0] if prior is not None else None
    p, pp = presented(current_net), presented(prior_net) if prior_net is not None else None
    pl, ppl = profit_and_loss(p), profit_and_loss(pp) if pp is not None else None
    split = _d(schedules.get("borrowings_due_after_one_year"))
    bs = balance_sheet(p, pl["profit"], split)
    pbs = balance_sheet(pp, ppl["profit"], _d(schedules.get("prior_borrowings_due_after_one_year"))) if pp else None

    # Facts that need evidence before they are presented as such.
    if p.get("bs.borrowings", ZERO) and split is None:
        add(Finding("BORROWINGS_MATURITY_MISSING", "P1", "Borrowings are shown as falling due within one year until "
                    "their maturity is evidenced.", "AS-010", "Enter the amount due after more than one year."))
    if split is not None and not (ZERO <= split <= p.get("bs.borrowings", ZERO)):
        add(Finding("BORROWINGS_SPLIT_INVALID", "P0", "The long-term borrowings amount is outside the borrowings "
                    "balance.", "AS-010", "Correct the maturity split."))
    if not any(k.startswith("pl.") and v for k, v in current_net.items()):
        add(Finding("NO_PROFIT_OR_LOSS_BALANCES", "P1", "No profit-or-loss balances: the trial balance may be "
                    "post-closing, so profit cannot be presented.", "AS-017", "Use the pre-closing trial balance."))
    if p.get("eq.distributions", ZERO) and not schedules.get("dividends_evidence"):
        add(Finding("DIVIDEND_UNSUBSTANTIATED", "P1", f"Distributions of {p['eq.distributions']} have no declaration "
                    "evidence; shown in equity as unresolved, never as an expense.", "AS-026, AT-15",
                    "Attach the board minute or declaration and the payment evidence."))
    if family == "UK_COMPANIES_ACT" and result.get("selected_framework") == "FRS105":
        add(Finding("FORMAT_BY_NATURE_REQUIRED", "P1", "FRS 105 micro-entity formats analyse costs by nature; the "
                    "approved lines are by function.", "AS-018", "Map expenses by nature for the micro format."))
    if family == "IFRS18" and p.get("pl.finance_income", ZERO):
        add(Finding("IFRS18_CATEGORY_REVIEW", "P2", "Interest income is placed in the investing category; confirm the "
                    "entity has no main business activity of investing or financing.", "AS-004",
                    "Record the main-business-activity assessment."))
    restating = [j for j in snap.journals if j.get("correction_type") in RESTATING]
    if restating:
        if family in ("IAS1", "IFRS18"):
            add(Finding("THIRD_BALANCE_SHEET_REQUIRED", "P0", "A retrospective correction or policy change needs an "
                        "opening statement of financial position for the earliest comparative period.", "AS-016, AT-05",
                        "Provide the approved opening balances for the earliest comparative period."))
        add(Finding("RESTATEMENT_DISCLOSURE_REQUIRED", "P1", "A prior-period error or policy change needs restated "
                    "comparatives and a restatement note.", "§13", "Prepare the restatement reconciliation."))
    first_period = str(schedules.get("first_period", "")).lower() in ("true", "1", "yes")
    if prior is None and not first_period:
        add(Finding("COMPARATIVES_MISSING", "P0", "No approved prior-period snapshot: comparatives are not invented.",
                    "AT-16", "Attach the approved prior-period trial balance, or evidence that this is the first period."))

    # 4 Assemble
    statements: list[dict] = []
    for name, requirement, note in manifest:
        kind = _STATEMENT_ALIASES.get(name, name)
        condensed = name.startswith("condensed_")
        title = name.replace("_", " ").capitalize()
        if kind == "balance_sheet":
            statements.append({"statement_id": name, "title": "Balance sheet" if family == "UK_COMPANIES_ACT"
                               else "Statement of financial position", "requiredness": requirement, "status": "ASSEMBLED",
                               "layout": family, "condensed": condensed, "note": note,
                               "lines": _lines(_BS_LAYOUTS[family], bs, pbs)})
        elif kind == "profit_or_loss":
            statements.append({"statement_id": name, "title": "Profit and loss account" if family == "UK_COMPANIES_ACT"
                               else "Statement of profit or loss", "requiredness": requirement, "status": "ASSEMBLED",
                               "layout": family, "condensed": condensed, "note": note,
                               "lines": _lines(_PL_LAYOUTS[family], pl, ppl)})
        elif kind == "other_comprehensive_income":
            status = "NOT_APPLICABLE" if requirement in ("NOT_APPLICABLE", "EXEMPT") else "ASSEMBLED"
            statements.append({"statement_id": name, "title": "Other comprehensive income", "requiredness": requirement,
                               "status": status, "layout": family, "condensed": condensed,
                               "note": note or "No OCI concepts exist in the approved snapshot; total comprehensive "
                                               "income equals profit.",
                               "lines": [] if status != "ASSEMBLED" else _lines(
                                   [("profit", "Profit for the year", "line"), ("oci", "Other comprehensive income", "line"),
                                    ("total_comprehensive_income", "Total comprehensive income", "total")],
                                   {"profit": pl["profit"], "oci": ZERO, "total_comprehensive_income": pl["profit"]},
                                   {"profit": ppl["profit"], "oci": ZERO, "total_comprehensive_income": ppl["profit"]}
                                   if ppl else None)})
        elif kind == "changes_in_equity":
            statements.append(_changes_in_equity(name, requirement, note, p, pp, pl, ppl, bs, schedules, findings))
        elif kind == "cash_flows":
            statements.append(_cash_flows(name, requirement, note, family, p, pp, pl, schedules, findings))
        elif kind in ("notes", "comparatives", "consolidation"):
            continue
        else:
            statements.append({"statement_id": name, "title": title, "requiredness": requirement, "status": "BLOCKED",
                               "layout": family, "note": "No builder for this component.", "lines": []})

    # 5 Tie out
    assertions = reconcile(statements, current_net, prior_net, bs, pbs, pl, ppl, p, pp, snap, schedules, profile,
                           first_period)
    for a in assertions:
        if a["status"] == "FAIL":
            add(Finding(f"{a['assertion_id']}_FAILED", a["severity"], f"{a['title']}: {a['detail']}", a["assertion_id"],
                        "Find the difference in the source; no plug or rounding is applied.", tuple(a["candidates"])))

    # 6 Disclose
    notes = disclosures(family, result, facts, p, current_net, snap, prior is not None or first_period, interim,
                        inputs.disclosures, findings)
    return _result(inputs, None, None, profile, manifest, statements, assertions, notes, findings,
                   {"revenue": pl["revenue"], "profit_before_tax": pl["profit_before_tax"], "profit": pl["profit"],
                    "net_assets": bs["net_assets"], "total_equity": bs["total_equity"], "cash": bs["cash"]}, schedules)


def _changes_in_equity(name, requirement, note, p, pp, pl, ppl, bs, schedules, findings) -> dict:
    if requirement in ("EXEMPT", "NOT_APPLICABLE"):
        return {"statement_id": name, "title": "Statement of changes in equity", "requiredness": requirement,
                "status": requirement, "note": note, "lines": []}
    g = lambda k: p.get(k, ZERO)  # noqa: E731
    issued = _d(schedules.get("shares_issued_nominal")) or ZERO
    opening_sc = pp.get("eq.share_capital", ZERO) if pp is not None else _d(schedules.get("share_capital_opening"))
    if opening_sc is None:
        opening_sc = g("eq.share_capital") - issued
        findings.append(Finding("SHARE_CAPITAL_OPENING_UNEVIDENCED", "P1", "Opening share capital is taken as closing "
                                "less recorded issues; it is not evidenced by a prior snapshot.", "AS-013",
                                "Attach the prior-period snapshot or the share register."))
    opening_re = g("eq.retained_earnings")
    rows = [("opening", "Balance at the start of the period", opening_sc, opening_re),
            ("profit", "Profit for the period", ZERO, pl["profit"]),
            ("oci", "Other comprehensive income", ZERO, ZERO),
            ("issues", "Shares issued", issued, ZERO),
            ("distributions", "Dividends (distributions to owners)", ZERO, -g("eq.distributions")),
            ("closing", "Balance at the end of the period", opening_sc + issued,
             opening_re + pl["profit"] - g("eq.distributions"))]
    return {"statement_id": name, "title": "Statement of changes in equity", "requiredness": requirement,
            "status": "ASSEMBLED", "note": note, "components": ["share_capital", "retained_earnings", "total"],
            "lines": [{"line_id": k, "label": label, "kind": "total" if k == "closing" else "line",
                       "share_capital": _s(sc), "retained_earnings": _s(re_), "amount": _s(sc + re_), "prior": None,
                       "concepts": ["eq.share_capital", "eq.retained_earnings", "eq.distributions"]}
                      for k, label, sc, re_ in rows]}


def _cash_flows(name, requirement, note, family, p, pp, pl, schedules, findings) -> dict:
    base = {"statement_id": name, "title": "Statement of cash flows", "requiredness": requirement, "note": note,
            "layout": family, "lines": []}
    if requirement == "EXEMPT":
        return {**base, "status": "EXEMPT", "note": note or "Omitted under a framework exemption verified by the "
                                                            "resolution (AS-006, AT-03)."}
    if requirement == "NOT_APPLICABLE":
        return {**base, "status": "NOT_APPLICABLE"}
    missing = [k for k in CASH_FLOW_DATA if _d(schedules.get(k)) is None]
    if pp is None or missing:
        needs = (["an approved prior-period snapshot (opening balances)"] if pp is None else []) + \
                [CASH_FLOW_DATA[k] for k in missing]
        if requirement == "REQUIRED":
            findings.append(Finding("CASH_FLOW_DATA_MISSING", "P0", "A cash flow statement is required but is not "
                                    "prepared from a closing trial balance alone. Needed: " + "; ".join(needs) + ".",
                                    "AS-036, AT-36", "Provide the cash-movement data listed."))
        return {**base, "status": "BLOCKED", "data_required": needs,
                "note": "Not generated: cash movements are not evidenced (no figure is inferred)."}
    s = {k: _d(schedules.get(k)) for k in CASH_FLOW_DATA}
    g = lambda d, k: d.get(k, ZERO)  # noqa: E731
    ifrs18 = family == "IFRS18"
    start_label, start = ("Operating profit", pl["operating_profit"]) if ifrs18 else ("Profit for the period", pl["profit"])
    lines = [("start", start_label, start)]
    if not ifrs18:
        lines += [("add_tax", "Tax expense", g(p, "pl.tax")), ("add_finance_costs", "Finance costs", g(p, "pl.finance_costs")),
                  ("less_finance_income", "Finance income", -g(p, "pl.finance_income"))]
    gain = s["disposal_proceeds"] - s["disposals_nbv"]
    working = [("depreciation", "Depreciation and amortisation", s["depreciation_amortisation"]),
               ("disposal_gain", "(Gain) / loss on disposal of fixed assets", -gain),
               ("inventories", "(Increase) / decrease in inventories", g(pp, "bs.inventories") - g(p, "bs.inventories")),
               ("receivables", "(Increase) / decrease in receivables", g(pp, "bs.trade_receivables") - g(p, "bs.trade_receivables")),
               ("payables", "Increase / (decrease) in payables", g(p, "bs.trade_payables") - g(pp, "bs.trade_payables")),
               ("provisions", "Increase / (decrease) in provisions", g(p, "bs.provisions") - g(pp, "bs.provisions"))]
    lines += working
    generated = sum((v for _, _, v in lines), ZERO)
    lines += [("cash_generated", "Cash generated from operations", generated), ("tax_paid", "Tax paid", -s["tax_paid"])]
    operating = generated - s["tax_paid"]
    investing = -s["fixed_asset_additions"] + s["disposal_proceeds"] + s["interest_received"]
    financing = s["borrowings_drawn"] - s["borrowings_repaid"] + s["shares_issued"] - s["dividends_paid"] - s["interest_paid"]
    opening = g(pp, "bs.cash")
    lines += [("operating", "Net cash from operating activities", operating),
              ("fixed_asset_additions", "Purchase of fixed assets", -s["fixed_asset_additions"]),
              ("disposal_proceeds", "Proceeds from disposals", s["disposal_proceeds"]),
              ("interest_received", "Interest received", s["interest_received"]),
              ("investing", "Net cash from investing activities", investing),
              ("borrowings_drawn", "Borrowings drawn", s["borrowings_drawn"]),
              ("borrowings_repaid", "Borrowings repaid", -s["borrowings_repaid"]),
              ("shares_issued", "Shares issued", s["shares_issued"]), ("dividends_paid", "Dividends paid", -s["dividends_paid"]),
              ("interest_paid", "Interest paid", -s["interest_paid"]),
              ("financing", "Net cash from financing activities", financing),
              ("net_change", "Net change in cash", operating + investing + financing),
              ("opening_cash", "Cash at the start of the period", opening), ("fx_effect", "Effect of exchange rates", s["fx_effect"]),
              ("closing_cash", "Cash at the end of the period", opening + operating + investing + financing + s["fx_effect"])]
    totals = {"cash_generated", "operating", "investing", "financing", "net_change", "closing_cash"}
    return {**base, "status": "ASSEMBLED", "method": "indirect", "starting_point": start_label,
            "policy": "Interest received: investing; interest paid and dividends paid: financing.",
            "lines": [{"line_id": k, "label": label, "kind": "subtotal" if k in totals else "line", "amount": _s(v),
                       "prior": None, "concepts": []} for k, label, v in lines]}


# ── 5 tie out (§11 X-01 to X-10) ────────────────────────────────────────────

def _assert(aid, title, formula, operands: dict, residual: Decimal | None, *, severity="P0", status=None,
            detail="", candidates=()) -> dict:
    ok = residual == ZERO if status is None else None
    return {"assertion_id": aid, "title": title, "formula": formula,
            "operands": {k: _s(v) for k, v in operands.items()}, "residual": _s(residual),
            "status": status or ("PASS" if ok else "FAIL"), "severity": severity, "detail": detail,
            "candidates": list(candidates)}


def _first(*differences: Decimal) -> Decimal:
    """The first non-zero difference: separate checks never offset each other."""
    return next((d for d in differences if d != ZERO), ZERO)


def _line(statement: dict | None, line_id: str, column: str = "amount") -> Decimal:
    for l in (statement or {}).get("lines", []):
        if l["line_id"] == line_id:
            return _d(l.get(column)) or ZERO
    return ZERO


def reconcile(statements, net, prior_net, bs, pbs, pl, ppl, p, pp, snap: Snapshot, schedules, profile,
              first_period) -> list[dict]:
    by = {s["statement_id"].replace("condensed_", ""): s for s in statements}
    sfp, plst = by.get("balance_sheet"), by.get("profit_or_loss")
    soce, cf = by.get("changes_in_equity"), by.get("cash_flows")
    out = []
    uk = profile["family"] == "UK_COMPANIES_ACT"

    # X-01: from the presented lines, not the stored totals.
    assets = sum((_line(sfp, k) for k in ("intangibles", "ppe", "inventories", "receivables", "cash")), ZERO)
    liabilities = sum((_line(sfp, k) for k in ("trade_payables", "tax_payable", "borrowings_current",
                                                "borrowings_non_current")), ZERO) + (
        _line(sfp, "provisions_total") if uk else _line(sfp, "provisions") + _line(sfp, "deferred_tax"))
    equity = _line(sfp, "share_capital") + _line(sfp, "retained_earnings")
    presented_equity = _line(sfp, "total_equity")
    out.append(_assert("X-01", "Statement of financial position", "Σ assets − Σ liabilities − Σ equity = 0",
                       {"assets": assets, "liabilities": liabilities, "equity": equity},
                       _first(assets - liabilities - equity, presented_equity - equity),
                       detail="Recomputed from the presented lines at full precision.",
                       candidates=("an unbalanced source", "a misclassified line") if assets - liabilities - equity else ()))

    # X-02: profit on the face of P&L = profit from the concepts; individual accounts have no NCI.
    from_concepts = -sum((v for k, v in net.items() if k.startswith("pl.")), ZERO)
    face = _line(plst, "profit")
    lines_sum = sum((_line(plst, k) * (1 if k in ("revenue", "other_income", "finance_income") else -1)
                     for k in ("revenue", "cost_of_sales", "distribution_costs", "administrative_expenses", "other_income",
                               "finance_income", "finance_costs", "tax")), ZERO)
    out.append(_assert("X-02", "Profit for the period", "P&L lines = reported profit = concepts (owners 100%, no NCI)",
                       {"reported": face, "lines": lines_sum, "concepts": from_concepts},
                       _first(face - from_concepts, lines_sum - face) if profile["scope"] != "group" else None,
                       status="FAIL" if profile["scope"] == "group" else None,
                       detail="Group attribution to owners and NCI is not supported." if profile["scope"] == "group" else ""))

    # X-03: no OCI concepts exist; total comprehensive income = profit.
    oci = by.get("other_comprehensive_income")
    out.append(_assert("X-03", "Other comprehensive income", "TCI = profit + OCI",
                       {"profit": pl["profit"], "oci": ZERO}, None, status="PASS" if oci is None or
                       _line(oci, "total_comprehensive_income") == _line(oci, "profit") + _line(oci, "oci") else "FAIL",
                       detail="No OCI concepts in the approved snapshot."))

    # X-04: equity roll-forward by component = SFP equity.
    if soce and soce.get("status") == "ASSEMBLED":
        rows = {l["line_id"]: l for l in soce["lines"]}
        rolled = sum((_d(rows[k]["amount"]) or ZERO for k in ("opening", "profit", "oci", "issues", "distributions")), ZERO)
        closing = _d(rows["closing"]["amount"]) or ZERO
        out.append(_assert("X-04", "Changes in equity", "opening + movements = closing = SFP equity",
                           {"rolled": rolled, "closing": closing, "sfp_equity": presented_equity},
                           _first(rolled - closing, closing - presented_equity),
                           candidates=("an unexplained equity movement", "a share issue without evidence")
                           if rolled != presented_equity else ()))
    else:
        out.append(_assert("X-04", "Changes in equity", "opening + movements = closing", {}, None, status="NOT_EVALUATED",
                           severity="P1", detail="No statement of changes in equity was assembled."))

    # X-05 and X-06: cash roll-forward and SFP cash.
    if cf and cf.get("status") == "ASSEMBLED":
        rolled = _line(cf, "opening_cash") + _line(cf, "operating") + _line(cf, "investing") + _line(cf, "financing") + \
            _line(cf, "fx_effect")
        out.append(_assert("X-05", "Cash flow roll-forward", "opening + operating + investing + financing + FX = closing",
                           {"rolled": rolled, "sfp_cash": bs["cash"]}, rolled - bs["cash"],
                           candidates=("an exchange-rate effect", "the cash-equivalents definition",
                                       "a missing or mis-stated cash movement") if rolled != bs["cash"] else ()))
    else:
        status = cf.get("status") if cf else "NOT_APPLICABLE"
        out.append(_assert("X-05", "Cash flow roll-forward", "opening + flows + FX = closing", {}, None,
                           status="EXEMPT" if status == "EXEMPT" else "NOT_EVALUATED" if status == "BLOCKED" else "NOT_APPLICABLE",
                           detail=(cf or {}).get("note", "")))
    bank = snap.supporting.get("bs.cash")
    if bank and _d(bank.get("total")) is not None:
        out.append(_assert("X-06", "Cash to bank reconciliation", "SFP cash = reconciled bank balance",
                           {"sfp_cash": bs["cash"], "bank_reconciliation": _d(bank["total"])}, bs["cash"] - _d(bank["total"])))
    else:
        out.append(_assert("X-06", "Cash to bank reconciliation", "SFP cash = reconciled bank balance", {"sfp_cash": bs["cash"]},
                           None, status="NOT_EVALUATED", severity="P1", detail="No bank reconciliation is attached."))

    # X-07: note schedules agree to the lines they support; fixed-asset roll-forward.
    for line_id, key in (("bs.ppe", "ppe"), ("bs.trade_receivables", "receivables"), ("bs.inventories", "inventories")):
        sup = snap.supporting.get(line_id)
        if sup and _d(sup.get("total")) is not None:
            out.append(_assert(f"X-07.{key}", f"Note schedule: {LINES[line_id][0]}", "note schedule total = SFP line",
                               {"schedule": _d(sup["total"]), "sfp_line": bs[key]}, _d(sup["total"]) - bs[key],
                               candidates=(f"the {sup.get('kind', 'schedule').replace('_', ' ')} total",)))
    if pp is not None and all(_d(schedules.get(k)) is not None for k in
                              ("fixed_asset_additions", "depreciation_amortisation", "disposals_nbv")):
        rolled = pp.get("bs.ppe", ZERO) + pp.get("bs.intangibles", ZERO) + _d(schedules["fixed_asset_additions"]) - \
            _d(schedules["depreciation_amortisation"]) - _d(schedules["disposals_nbv"])
        closing = p.get("bs.ppe", ZERO) + p.get("bs.intangibles", ZERO)
        out.append(_assert("X-07.fixed_assets", "Fixed-asset roll-forward", "opening + additions − depreciation − disposals = closing",
                           {"rolled": rolled, "closing": closing}, rolled - closing))
        if _d(schedules.get("borrowings_drawn")) is not None and _d(schedules.get("borrowings_repaid")) is not None:
            rolled_b = pp.get("bs.borrowings", ZERO) + _d(schedules["borrowings_drawn"]) - _d(schedules["borrowings_repaid"])
            out.append(_assert("X-07.borrowings", "Financing liabilities roll-forward (AS-034)",
                               "opening + drawn − repaid = closing", {"rolled": rolled_b, "closing": p.get("bs.borrowings", ZERO)},
                               rolled_b - p.get("bs.borrowings", ZERO)))

    # X-08: tax movement; never infer tax paid from the charge (AT-14).
    has_tax = any(net.get(k) for k in ("pl.tax", "bs.tax_payable", "bs.deferred_tax"))
    current_charge, tax_paid = _d(schedules.get("current_tax_charge")), _d(schedules.get("tax_paid"))
    if has_tax and pp is not None and current_charge is not None and tax_paid is not None:
        rolled = pp.get("bs.tax_payable", ZERO) + current_charge - tax_paid
        deferred = pp.get("bs.deferred_tax", ZERO) + (p.get("pl.tax", ZERO) - current_charge)
        out.append(_assert("X-08", "Tax", "opening payable + current charge − paid = closing; deferred moves by the deferred charge",
                           {"current_rolled": rolled, "current_closing": p.get("bs.tax_payable", ZERO),
                            "deferred_rolled": deferred, "deferred_closing": p.get("bs.deferred_tax", ZERO)},
                           _first(rolled - p.get("bs.tax_payable", ZERO), deferred - p.get("bs.deferred_tax", ZERO)),
                           severity="P1"))
    elif has_tax:
        out.append(_assert("X-08", "Tax", "tax movement schedule", {"tax_charge": p.get("pl.tax", ZERO)}, None,
                           status="FAIL", severity="P1",
                           detail="No tax movement schedule (opening balances, current charge, tax paid); tax payable is "
                                  "not assumed to equal the charge.", candidates=("a tax computation",)))
    else:
        out.append(_assert("X-08", "Tax", "tax movement", {}, None, status="NOT_APPLICABLE"))

    # X-09: group.
    out.append(_assert("X-09", "Consolidation", "consolidated = components + entries − eliminations", {}, None,
                       status="FAIL" if profile["scope"] == "group" else "NOT_APPLICABLE",
                       detail="Consolidation is not supported." if profile["scope"] == "group" else "Individual accounts."))

    # X-10: comparatives — the prior closing equity is this period's opening (AT-08, AT-09).
    if pp is not None:
        prior_re = pp.get("eq.retained_earnings", ZERO) + ppl["profit"] - pp.get("eq.distributions", ZERO)
        out.append(_assert("X-10", "Comparatives", "prior closing retained earnings = current opening retained earnings",
                           {"prior_closing": prior_re, "current_opening": p.get("eq.retained_earnings", ZERO)},
                           prior_re - p.get("eq.retained_earnings", ZERO),
                           candidates=("a direct posting to reserves", "a prior-period adjustment",
                                       "an artificial balancing entry") if prior_re != p.get("eq.retained_earnings", ZERO) else ()))
    else:
        out.append(_assert("X-10", "Comparatives", "prior version + adjustments", {}, None,
                           status="NOT_APPLICABLE" if first_period else "NOT_EVALUATED",
                           detail="First period of reporting (evidenced)." if first_period else "No prior-period snapshot."))
    return out


# ── 6 disclose (§10): requirement → evidence → state ─────────────────────────

@dataclass(frozen=True)
class Requirement:
    rid: str
    title: str
    rule: str
    severity: str
    applies: object                         # (ctx) -> "REQUIRED" | "CONDITIONAL" | "NOT_APPLICABLE" | "EXEMPT"
    evidence: str
    auto: object = None                     # (ctx) -> (state, text, amount) for system-supported notes


def _has(*lines):
    return lambda c: "REQUIRED" if any(c["p"].get(l) for l in lines) else "NOT_APPLICABLE"


def _basis(c):
    edition = c["result"].get("framework_edition") or c["family"].replace("_", " ").title()
    if c["result"].get("permit_statutory_claim"):
        return "SUPPORTED", f"These financial statements have been prepared under {edition}.", None
    return "SUPPORTED", (f"Draft prepared on the basis of {edition} as resolved for this entity and period; it is not "
                         "represented as compliant until the statutory gates pass."), None


def _employees(c):
    staff = ((c["facts"].get("current_year") or {}).get("employees"))
    if staff in (None, ""):
        return "REQUIRED_MISSING", "The average number of employees is not recorded in the resolution.", None
    return "SUPPORTED", f"Average number of persons employed: {staff}.", None


def _cash_flow_exemption(c):
    return "SUPPORTED", "No statement of cash flows is presented: " + (c["cf_note"] or "framework exemption") + ".", None


def _comparatives(c):
    return ("SUPPORTED", "Comparatives are evidenced: an approved prior-period snapshot, or an evidenced first "
                         "period of reporting.", None) if c["has_prior"] else \
        ("REQUIRED_MISSING", "No approved prior-period snapshot.", None)


def _schedule_note(line_id):
    def run(c):
        sup = c["supporting"].get(line_id)
        amount = c["p"].get(line_id, ZERO)
        if sup and sup.get("agreed"):
            return "SUPPORTED", f"Agreed to the {sup['kind'].replace('_', ' ')} ({sup['total']}).", amount
        return "REQUIRED_MISSING", "No agreed supporting schedule for this line.", amount
    return run


def _uk(c):
    return c["family"] == "UK_COMPANIES_ACT"


def _full(c):
    return c["result"].get("selected_framework") not in ("FRS102_1A", "FRS105")


REQUIREMENTS = (
    Requirement("N01", "Basis of preparation", "AS-001; FRS 102 s3 / IAS 1.16", "P0", lambda c: "REQUIRED",
                "The resolved framework and edition.", _basis),
    Requirement("N02", "Accounting policy: revenue recognition", "AT-13; FRS 102 s23 / IFRS 15", "P0",
                _has("pl.revenue"), "The entity's approved revenue policy."),
    Requirement("N03", "Going concern", "AS-039; FRS 102 3.8 / IAS 1.25", "P0", lambda c: "REQUIRED",
                "The directors' going-concern assessment."),
    Requirement("N04", "Average number of employees", "Companies Act 2006 s411", "P1",
                lambda c: "REQUIRED" if _uk(c) else "NOT_APPLICABLE", "Average staff numbers.", _employees),
    Requirement("N05", "Tangible fixed assets / PPE", "AS-012, AT-12", "P0", _has("bs.ppe"),
                "An agreed fixed asset register.", _schedule_note("bs.ppe")),
    Requirement("N06", "Debtors / receivables", "AS-011", "P1", _has("bs.trade_receivables"),
                "An agreed receivables ageing.", _schedule_note("bs.trade_receivables")),
    Requirement("N07", "Stocks / inventories", "AS-012", "P1", _has("bs.inventories"),
                "An agreed inventory listing.", _schedule_note("bs.inventories")),
    Requirement("N08", "Borrowings: maturity and security", "AS-010, AS-034", "P1", _has("bs.borrowings"),
                "Loan agreements: maturity, security and interest."),
    Requirement("N09", "Share capital", "AS-013", "P1", _has("eq.share_capital"), "The share register: classes and numbers."),
    Requirement("N10", "Tax: charge and reconciliation", "AS-024, AT-14", "P1",
                lambda c: ("REQUIRED" if _full(c) else "CONDITIONAL") if c["p"].get("pl.tax") else "NOT_APPLICABLE",
                "The tax computation and rate reconciliation."),
    Requirement("N11", "Related party transactions", "AS-039, AT-27; FRS 102 s33 / IAS 24", "P1", lambda c: "REQUIRED",
                "A related-party register reviewed for the period."),
    Requirement("N12", "Events after the reporting period", "AS-039; FRS 102 s32 / IAS 10", "P1", lambda c: "REQUIRED",
                "Directors' review of post-period events."),
    Requirement("N13", "Dividends", "AS-026, AT-15", "P1", _has("eq.distributions"),
                "Declaration minutes and payment evidence."),
    Requirement("N14", "Supplier finance arrangements", "FRS 102 (2025) / IAS 7.44F, AT-32", "P1",
                lambda c: "CONDITIONAL" if any(r["rule_id"] == "FRS102.SUPPLIER_FINANCE_DISCLOSURES" and r["outcome"] == "APPLIES"
                                               for r in c["result"].get("rules", [])) or c["family"] in ("IAS1", "IFRS18")
                else "NOT_APPLICABLE", "Whether supplier finance arrangements exist, with their terms."),
    Requirement("N15", "Cash flow statement exemption", "AS-006, AT-03", "P1",
                lambda c: "REQUIRED" if c["cf_requirement"] == "EXEMPT" else "NOT_APPLICABLE",
                "The exemption verified by the resolution.", _cash_flow_exemption),
    Requirement("N16", "Comparative information", "AT-16", "P0", lambda c: "REQUIRED",
                "The approved prior-period snapshot.", _comparatives),
    Requirement("N17", "Critical judgements and estimation uncertainty", "FRS 102 8.6 / IAS 1.122", "P1",
                lambda c: "REQUIRED" if _full(c) and c["family"] != "MANAGEMENT" else "NOT_APPLICABLE",
                "The judgements and estimates recorded by the reviewer."),
    Requirement("N18", "Management-defined performance measures", "IFRS 18 (MPM)", "P1",
                lambda c: "CONDITIONAL" if c["family"] == "IFRS18" else "NOT_APPLICABLE",
                "Whether MPMs are communicated, with reconciliations."),
    Requirement("N19", "Interim: selected explanatory notes", "IAS 34 / FRS 104, AT-26", "P1",
                lambda c: "REQUIRED" if c["interim"] else "NOT_APPLICABLE",
                "Significant events and changes since the last annual report."),
)


def _check_text(text: str, rid: str, statutory: bool, evidence_ref: str) -> list[tuple[str, str, str, str]]:
    """(code, severity, message, rule) for claims the text may not make. The text is data, never instruction."""
    issues = []
    if _COMPLIANCE_CLAIM.search(text) and not statutory:
        issues.append(("COMPLIANCE_CLAIM_REFUSED", "P0", "The note claims compliance, which the package does not "
                       "permit; the claim is refused and the package stays a draft.", "AT-19, AS-042"))
    if _NO_RELATED_PARTIES.search(text) and not evidence_ref:
        issues.append(("UNSUPPORTED_ASSERTION", "P1", "'No related parties' needs a reviewed related-party register.",
                       "AT-27"))
    return issues


def disclosures(family, result, facts, p, net, snap: Snapshot, has_prior, interim, submissions, findings) -> list[dict]:
    statements = {s["statement"]: s for s in result.get("statements", [])}
    cf = statements.get("cash_flows") or statements.get("condensed_cash_flows") or {}
    ctx = {"family": family, "result": result, "facts": facts, "p": p, "supporting": snap.supporting,
           "has_prior": has_prior, "interim": interim, "cf_requirement": cf.get("requirement"), "cf_note": cf.get("note", "")}
    statutory = bool(result.get("permit_statutory_claim"))
    out = []
    for req in REQUIREMENTS:
        applicability = req.applies(ctx)
        sub = submissions.get(req.rid) or {}
        row = {"requirement_id": req.rid, "title": req.title, "rule": req.rule, "applicability": applicability,
               "evidence_needed": req.evidence, "severity": req.severity, "text": "", "amount": None, "evidence_ref": "",
               "submitted_by": sub.get("submitted_by"), "approved_by": sub.get("approved_by"), "issues": []}
        if applicability == "NOT_APPLICABLE":
            out.append({**row, "state": "NOT_APPLICABLE", "text": "Not triggered by the approved snapshot or the resolution."})
            continue
        if applicability == "EXEMPT":
            out.append({**row, "state": "EXEMPT", "text": "Exempt under the resolution."})
            continue
        if req.auto is not None:
            state, text, amount = req.auto(ctx)
            if state == "SUPPORTED" or not sub:
                out.append({**row, "state": state, "text": text, "amount": _s(amount)})
                if state == "REQUIRED_MISSING":
                    findings.append(Finding(f"NOTE_MISSING_{req.rid}", req.severity, f"{req.title}: {text}", req.rule,
                                            f"Provide: {req.evidence}"))
                continue
        decision = sub.get("decision")
        text, evidence_ref = (sub.get("text") or "").strip(), (sub.get("evidence_ref") or "").strip()
        if decision == "exempt":
            findings.append(Finding(f"EXEMPTION_WITHOUT_AUTHORITY_{req.rid}", "P0", f"{req.title}: an exemption was "
                                    "requested but the resolution grants none for this note.", "AT-33",
                                    "Raise a standards query; the note stays required."))
            out.append({**row, "state": "REQUIRED_MISSING", "issues": ["EXEMPTION_WITHOUT_AUTHORITY"]})
            continue
        if decision == "not_applicable":
            rationale = (sub.get("rationale") or "").strip()
            if not rationale or not evidence_ref:
                state = "REQUIRED_MISSING"
            else:
                state = "NOT_APPLICABLE" if sub.get("approved_by") else "PENDING_APPROVAL"
            out.append({**row, "state": state, "text": rationale, "evidence_ref": evidence_ref})
            if state != "NOT_APPLICABLE":
                findings.append(Finding(f"NOTE_PENDING_{req.rid}", req.severity if state == "REQUIRED_MISSING" else "P2",
                                        f"{req.title}: non-applicability needs a rationale, evidence and a disclosure "
                                        "owner's approval.", req.rule, "Complete and approve the rationale."))
            continue
        if decision == "include":
            issues = _check_text(text, req.rid, statutory, evidence_ref)
            if not evidence_ref:
                issues.append(("UNSOURCED_NOTE", "P1", "Note text without evidence is not accepted.", "AS-042, AT-32"))
            for code, severity, message, rule in issues:
                findings.append(Finding(f"{code}_{req.rid}", severity, f"{req.title}: {message}", rule,
                                        "Revise the note with evidence."))
            if issues:
                out.append({**row, "state": "REQUIRED_MISSING", "text": text, "evidence_ref": evidence_ref,
                            "issues": [i[0] for i in issues]})
                continue
            state = "SUPPORTED" if sub.get("approved_by") else "PENDING_APPROVAL"
            out.append({**row, "state": state, "text": text, "evidence_ref": evidence_ref})
            if state == "PENDING_APPROVAL":
                findings.append(Finding(f"NOTE_PENDING_{req.rid}", "P2", f"{req.title}: awaiting the disclosure "
                                        "owner's approval.", "AS-043", "A disclosure owner (not the author) approves."))
            continue
        state = "CONDITIONAL_UNDECIDED" if applicability == "CONDITIONAL" else "REQUIRED_MISSING"
        out.append({**row, "state": state})
        findings.append(Finding(f"NOTE_MISSING_{req.rid}", "P1" if applicability == "CONDITIONAL" else req.severity,
                                f"{req.title}: " + ("a recorded decision is needed." if applicability == "CONDITIONAL"
                                                    else "required and not yet evidenced."), req.rule,
                                f"Provide: {req.evidence}"))
    return out


# ── result, state and exports ───────────────────────────────────────────────

def fingerprint(inputs: PackageInputs) -> str:
    res = inputs.resolution or {}
    payload = {"snapshot": inputs.snapshot.content_hash, "approved": inputs.snapshot.approved,
               "prior": inputs.prior.content_hash if inputs.prior else None,
               "resolution": [res.get("id"), res.get("revision"), res.get("state"), res.get("rule_pack_digest")],
               "schedules": inputs.schedules, "disclosures": inputs.disclosures, "dispositions": inputs.dispositions,
               "ruleset": RULESET}
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _result(inputs, state, halted, profile, manifest, statements, assertions, notes, findings, headline, schedules) -> dict:
    disposed = inputs.dispositions or {}
    rows = []
    for f in findings:
        d = f.to_dict()
        d["disposition"] = disposed.get(f.code)
        rows.append(d)
    open_ = [f for f in rows if not (f["severity"] == "P2" and f["disposition"])]
    blocking = [f for f in open_ if f["severity"] in ("P0", "P1") and not f["release_only"]]
    if state is None:
        failed = any(a["status"] == "FAIL" and a["severity"] in ("P0", "P1") for a in assertions)
        notes_open = any(n["state"] not in ("SUPPORTED", "NOT_APPLICABLE", "EXEMPT") for n in notes)
        state = "ASSEMBLED" if failed else "RECONCILED" if notes_open else "DISCLOSURES_COMPLETE"
    counts = {s: sum(1 for f in open_ if f["severity"] == s) for s in ("P0", "P1", "P2", "P3")}
    release_reasons = [f["message"] for f in open_ if f["severity"] in ("P0", "P1")]
    package = {
        "state": state, "halted": halted, "profile": profile,
        "manifest": [{"statement": s, "requirement": r, "note": n} for s, r, n in manifest],
        "statements": statements, "assertions": assertions, "notes": notes, "findings": rows,
        "counts": counts, "headline": {k: _s(v) for k, v in headline.items()},
        "ready_for_signoff": state == "DISCLOSURES_COMPLETE" and not blocking
                             and not any(f["severity"] == "P2" and not f["disposition"] for f in rows),
        "release_reasons": release_reasons, "watermark": "DRAFT — NOT FOR STATUTORY USE",
        "cash_flow_data_fields": CASH_FLOW_DATA, "fingerprint": fingerprint(inputs),
        "source": {"trial_balance_id": inputs.snapshot.trial_balance_id, "snapshot_hash": inputs.snapshot.content_hash,
                   "prior_trial_balance_id": inputs.prior.trial_balance_id if inputs.prior else None,
                   "prior_snapshot_hash": inputs.prior.content_hash if inputs.prior else None},
        "schedules": schedules,
    }
    return package


def export(package: dict, fmt: str, *, package_id: str, version: int, statutory: bool) -> tuple[str, str]:
    """(media type, body). JSON and CSV carry the same values and the same content hash (AT-20)."""
    rows = [(s["statement_id"], l["line_id"], l["label"], l.get("amount"), l.get("prior"))
            for s in package["statements"] for l in s.get("lines", [])]
    digest = "sha256:" + hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    mark = None if statutory else package["watermark"]
    if fmt == "json":
        return "application/json", json.dumps({"package_id": package_id, "version": version, "watermark": mark,
                                               "content_hash": digest, "profile": package["profile"],
                                               "lines": [dict(zip(("statement", "line_id", "label", "amount", "prior"), r))
                                                         for r in rows]}, indent=2)
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["# package", package_id, "version", version, "content_hash", digest])
        writer.writerow(["# watermark", mark or ""])
        writer.writerow(["statement", "line_id", "label", "amount", "prior"])
        writer.writerows([[c if c is not None else "" for c in r] for r in rows])
        return "text/csv", buffer.getvalue()
    raise ValueError("The export format is json or csv; Word and PDF publication is Document 06.")

"""Kriton chat on the Financial Statements engine.

Review ZL-FSR-COR-20261103 (C01–C05) and Supplement A found that the chat
built trial-balance statements in its own calculation (document_figures.py)
and never called the engine in app/domains/financial_statements, which
already classifies on evidence, finds suspense balances and hashes the
source. Here the engine's stateless intake does the work and chat only
presents it: the figures, the classification choices still open (with the
result under each), the source checks and anything left unreconciled.

The engine is called, not changed. KRITON_FS_ENGINE_CHAT=0 switches chat back
to the previous calculation.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

from app.domains.financial_statements import mapping as fs_mapping
from app.domains.financial_statements import workflow as fs_workflow
from app.domains.financial_statements.normalize import TRIAL_BALANCE
from app.domains.financial_statements.service import run_intake

ZERO = Decimal("0")
# A trial balance takes about a second; past this the run is reported as not
# run, inside the request's own deadline.
ENGINE_SECONDS = 20
_OPERATING = {"pl.cost_of_sales", "pl.distribution_costs", "pl.administrative_expenses"}
_ASSETS = {"bs.ppe", "bs.intangibles", "bs.inventories", "bs.trade_receivables", "bs.cash"}
_LIABILITIES = {"bs.trade_payables", "bs.tax_payable", "bs.borrowings", "bs.deferred_tax", "bs.provisions"}
# Engine gap, reported to its owners: "Accumulated depreciation" matches the
# needs-evidence "depreciation" rule and is offered P&L lines. It reduces PPE.
_ACCUMULATED = re.compile(r"accumulated\s+(?:depreciation|amorti[sz]ation)", re.I)

# The statement built for this request, for the notes added after the answer.
current_statement: ContextVar["ChatStatement | None"] = ContextVar("kriton_fs_statement", default=None)
# The file the engine failed on for this request (DC-11): said, never hidden.
engine_failure: ContextVar[str | None] = ContextVar("kriton_fs_engine_failure", default=None)


class EngineRejected(Exception):
    """The engine refused the file (macros, unreadable): said, not replaced by
    the general reader's figures without a word (DC-06, DC-11)."""


def failure_note(filename: str) -> str:
    return (f"The Financial Statements engine did not run for {filename}. Any statement figures shown come from "
            "the general file reader and were not checked by the engine; they are not verified (ENGINE_FAILED).")


def enabled() -> bool:
    return os.environ.get("KRITON_FS_ENGINE_CHAT", "1").strip() != "0"


@dataclass
class Choice:
    """An account whose line the engine could not decide from its name and
    that moves operating profit: shown on one line, with the other."""
    account: str
    amount: Decimal
    shown: str
    alternative: str
    operating_effect: Decimal        # change in operating profit under the alternative
    shown_line: str = ""
    alternative_line: str = ""
    balance: Decimal = ZERO
    # What the engine says would decide it (Document 01 §1.3, CLS-01–04),
    # instead of a generic "invoices or cost centres".
    evidence: str = ""


# Engine findings that are shown beside the answer whatever the model writes
# (DC-06, NB26-05, FS-043). The others have their own notes: UNBALANCED
# (ARITHMETIC_FAIL), SUSPENSE_BALANCE (the reconciliation note),
# COMPARATIVE_MISSING (the comparatives note), UNITS_THOUSANDS (the units note).
_NOTED_FINDINGS = ("HIDDEN_CONTENT", "EXTERNAL_LINKS", "DUPLICATE_ACCOUNT", "MIXED_CURRENCY", "SIGN_ANOMALY",
                   "SIGN_UNRESOLVED", "CONTROL_TOTAL_MISMATCH", "CUTOFF_AFTER_PERIOD_END", "MISSING_ACCOUNT_CODE",
                   "AMBIGUOUS_SCHEMA", "VOUCHER_UNBALANCED")


@dataclass
class ChatStatement:
    filename: str
    sha256: str
    accounts: int
    period_end: str | None
    total_debits: Decimal
    total_credits: Decimal
    lines: dict[str, list[tuple[str, Decimal]]] = field(default_factory=dict)
    figures: dict[str, Decimal] = field(default_factory=dict)
    choices: list[Choice] = field(default_factory=list)
    # Every subtotal with each open choice on its other line. The model wrote
    # the alternative table itself and gave operating expenses 573,000 for
    # 574,000 (retest of 4 Nov 2026): it is computed here instead.
    alternative: dict[str, Decimal] = field(default_factory=dict)
    # Each open choice moved on its own: interest income and bank charges are
    # separate questions, and the two endpoints hid 230,600 and 221,500
    # (decision ZL-FSR-DEC-20261104 D-01, DC-02).
    sensitivities: list[tuple[Choice, dict[str, Decimal]]] = field(default_factory=list)
    cost_of_sales_candidates: list[tuple[str, Decimal]] = field(default_factory=list)
    # Operating accounts whose function (cost of sales, distribution or
    # administration) the engine could not decide; placed in administration.
    function_open: list[tuple[str, Decimal]] = field(default_factory=list)
    unmapped: list[tuple[str, Decimal]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    # The engine findings in _NOTED_FINDINGS: shown beside the answer for review.
    source_flags: list[str] = field(default_factory=list)
    # "thousands" when the file's heading says so: a £000 file was presented
    # as pounds unless the model repeated the finding (FS-043, SD-004).
    units: str = "units"
    caption_flags: list[str] = field(default_factory=list)
    dividends: list[tuple[str, Decimal]] = field(default_factory=list)
    tax_payable: Decimal | None = None

    @property
    def residual(self) -> Decimal:
        return self.figures.get("net_assets", ZERO) - self.figures.get("equity_including_profit", ZERO)

    @property
    def balanced(self) -> bool:
        return self.total_debits == self.total_credits


def _fmt(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    text = f"{abs(value):,.2f}"
    text = text[:-3] if text.endswith(".00") else text
    return f"-{text}" if value < 0 else text


def _line_for(proposal) -> tuple[str | None, str | None]:
    """(line shown, alternative that moves operating profit) for a proposal."""
    if proposal.status in (fs_mapping.SUGGESTED, fs_mapping.APPROVED):
        return proposal.line_id, None
    if proposal.status != fs_mapping.NEEDS_EVIDENCE:
        return None, None
    if _ACCUMULATED.search(proposal.account_name):
        return "bs.ppe", None
    candidates = set(proposal.candidates)
    if candidates <= _OPERATING:
        # Inside operating profit whichever it is; only gross profit can move.
        return "pl.administrative_expenses", None
    if "pl.finance_costs" in candidates:
        # Routine bank fees are operating; borrowing costs are finance costs.
        return "pl.administrative_expenses", "pl.finance_costs"
    if "pl.finance_income" in candidates:
        return "pl.finance_income", "pl.other_income"
    return proposal.candidates[0] if proposal.candidates else None, None


def build(filename: str, content: bytes) -> ChatStatement | None:
    """The engine's draft statement for an uploaded trial balance, or None
    when the file is not one the engine reads as a trial balance."""
    result = run_intake(filename, content, "kriton-chat")
    if result.state == fs_workflow.REJECTED_SOURCE:
        raise EngineRejected("; ".join(f.message for f in result.findings) or "the file was rejected")
    if result.tb.kind != TRIAL_BALANCE or not result.mappings:
        return None
    statement = ChatStatement(
        filename=filename, sha256=result.manifest.to_dict().get("sha256", ""), accounts=len(result.mappings),
        period_end=result.tb.period_end.isoformat() if result.tb.period_end else None,
        total_debits=result.report.total_debits, total_credits=result.report.total_credits,
        findings=[f"{f.code}: {f.message}" for f in result.findings],
        source_flags=list(dict.fromkeys(f.message for f in result.findings if f.code in _NOTED_FINDINGS)),
        units=result.tb.units,
    )
    placed: dict[str, list[tuple[str, Decimal]]] = {}
    for proposal in result.mappings:
        line, alternative = _line_for(proposal)
        name, balance = proposal.account_name, proposal.balance
        if line is None:
            statement.unmapped.append((name, balance))
            continue
        placed.setdefault(line, []).append((name, balance))
        if proposal.status == fs_mapping.NEEDS_EVIDENCE and "pl.cost_of_sales" in proposal.candidates \
                and line.startswith("pl.") and line != "pl.cost_of_sales":
            statement.cost_of_sales_candidates.append((name, balance))
        if proposal.status == fs_mapping.NEEDS_EVIDENCE and set(proposal.candidates) <= _OPERATING \
                and line == "pl.administrative_expenses":
            statement.function_open.append((name, balance))
        if alternative:
            # Moving a cost out of operating expenses raises operating profit;
            # moving income into other operating income raises it too.
            statement.choices.append(Choice(name, abs(balance), fs_mapping.LINES[line][0],
                                            fs_mapping.LINES[alternative][0], abs(balance),
                                            shown_line=line, alternative_line=alternative, balance=balance,
                                            evidence=proposal.evidence_required))
        if line.startswith("pl.") and re.search(r"\bpayable\b", name, re.I):
            # SA-T07: "Interest payable" with a debit balance in the expense
            # codes reads as an expense, but the caption also names a liability.
            statement.caption_flags.append(
                f"{name} ({_fmt(balance)}) is presented as {fs_mapping.LINES[line][0].lower()}; its caption also "
                "describes a liability. Confirm from the ledger that it is the period's expense and not an accrual.")
    statement.lines = placed
    statement.figures = _figures(placed)
    if statement.choices:
        statement.alternative = _figures(_moved(placed, statement.choices))
        if len(statement.choices) > 1:
            statement.sensitivities = [(c, _figures(_moved(placed, [c]))) for c in statement.choices]
    statement.dividends = [(n, b) for n, b in placed.get("eq.distributions", [])]
    if placed.get("bs.tax_payable"):
        statement.tax_payable = -sum((b for _, b in placed["bs.tax_payable"]), ZERO)
    return statement


def _moved(placed: dict[str, list[tuple[str, Decimal]]], choices: list[Choice]) -> dict[str, list[tuple[str, Decimal]]]:
    """The placement with these choices on their other line."""
    moved = {line: list(entries) for line, entries in placed.items()}
    for choice in choices:
        moved[choice.shown_line] = [e for e in moved[choice.shown_line] if e[0] != choice.account]
        moved.setdefault(choice.alternative_line, []).append((choice.account, choice.balance))
    return moved


def _figures(placed: dict[str, list[tuple[str, Decimal]]]) -> dict[str, Decimal]:
    """Every subtotal of the draft statements from accounts placed on lines."""
    def credit(line: str) -> Decimal:
        return -sum((b for _, b in placed.get(line, [])), ZERO)

    def debit(line: str) -> Decimal:
        return sum((b for _, b in placed.get(line, [])), ZERO)

    f: dict[str, Decimal] = {}
    f["revenue"] = credit("pl.revenue")
    f["cost_of_sales"] = debit("pl.cost_of_sales")
    f["gross_profit"] = f["revenue"] - f["cost_of_sales"]
    f["other_operating_income"] = credit("pl.other_income")
    f["operating_expenses"] = debit("pl.distribution_costs") + debit("pl.administrative_expenses")
    f["operating_profit"] = f["gross_profit"] + f["other_operating_income"] - f["operating_expenses"]
    f["finance_income"] = credit("pl.finance_income")
    f["finance_costs"] = debit("pl.finance_costs")
    f["net_finance"] = f["finance_income"] - f["finance_costs"]
    f["profit_before_tax"] = f["operating_profit"] + f["net_finance"]
    f["tax"] = debit("pl.tax")
    f["profit_for_the_year"] = f["profit_before_tax"] - f["tax"]
    f["assets"] = sum((debit(line) for line in _ASSETS), ZERO)
    f["liabilities"] = sum((credit(line) for line in _LIABILITIES), ZERO)
    f["net_assets"] = f["assets"] - f["liabilities"]
    f["equity_before_profit"] = sum((credit(line) for line in ("eq.share_capital", "eq.retained_earnings",
                                                               "eq.distributions")), ZERO)
    f["equity_including_profit"] = f["equity_before_profit"] + f["profit_for_the_year"]
    return f


def _pct(part: Decimal, whole: Decimal) -> str:
    return "not computable (zero denominator)" if not whole else f"{(part / whole * 100):.2f}%"


def facts_block(s: ChatStatement, format_1: bool = False) -> str:
    """The figures and findings the answer may use, and how to present them.
    With format_1 (FRS 102 / Companies Act named), the face keeps
    distribution costs and administrative expenses apart (Document 01 FS-023)."""
    f = s.figures
    out = ["\n\n=== Statement figures from the Financial Statements engine (use only these) ===",
           f"Source: {s.filename}; SHA-256 {s.sha256[:16]}…; {s.accounts} accounts. Trial balance: total debits "
           f"{_fmt(s.total_debits)}, total credits {_fmt(s.total_credits)}, difference "
           f"{_fmt(s.total_debits - s.total_credits)}.",
           f"Period end: {s.period_end or 'not stated in the file (head the statement: reporting period not confirmed)'}."]
    if s.units == "thousands":
        out.append("Units: the file states its amounts in thousands. Every amount below is in thousands; say so in "
                   "the heading (for example \"£000\") and never present them as whole currency units.")
    if not s.balanced:
        # FS-009 / G5: an unbalanced trial balance stops the statements, as
        # the general reader already did; the engine path gave every subtotal.
        out.append(f"The trial balance does not balance: debits exceed credits by "
                   f"{_fmt(s.total_debits - s.total_credits)}. Give no statement totals, subtotals, margins or "
                   "alternative classifications: state the difference, list the accounts if asked, and ask for the "
                   "corrected trial balance.")
        out.extend("Engine finding: " + finding for finding in s.findings)
        return "\n".join(out)
    out.append("Income statement, draft classification (account names under each heading; no account codes on "
               "statement lines):")
    distribution, administrative = (("Distribution costs", "Administrative expenses") if format_1
                                    else ("Operating expenses", "Operating expenses"))
    for label, line in (("Revenue", "pl.revenue"), ("Cost of sales", "pl.cost_of_sales"),
                        ("Other operating income", "pl.other_income"),
                        (distribution, "pl.distribution_costs"), (administrative, "pl.administrative_expenses"),
                        ("Finance income", "pl.finance_income"), ("Finance costs", "pl.finance_costs"),
                        ("Tax", "pl.tax")):
        for name, balance in s.lines.get(line, []):
            out.append(f"- {label}: {name} {_fmt(abs(balance))}")
    if format_1:
        lines = s.lines
        out.append("Format 1 (FRS 102 / Companies Act): show Distribution costs "
                   f"{_fmt(sum((b for _, b in lines.get('pl.distribution_costs', [])), ZERO))} and Administrative "
                   f"expenses {_fmt(sum((b for _, b in lines.get('pl.administrative_expenses', [])), ZERO))} as separate "
                   "face lines, not one operating expenses line; their total is the operating expenses subtotal below.")
        if s.function_open:
            out.append("Placed in administrative expenses because the file does not establish their function: "
                       + ", ".join(f"{n} {_fmt(abs(b))}" for n, b in s.function_open)
                       + ". Each could be cost of sales or distribution costs; that would move gross profit or the "
                         "split between the two lines, not operating profit. Say so beside the statement.")
    out.append(
        f"Subtotals: revenue {_fmt(f['revenue'])}; cost of sales {_fmt(f['cost_of_sales'])}; gross profit "
        f"{_fmt(f['gross_profit'])}; other operating income {_fmt(f['other_operating_income'])}; operating expenses "
        f"{_fmt(f['operating_expenses'])}; operating profit {_fmt(f['operating_profit'])}; finance income "
        f"{_fmt(f['finance_income'])}; finance costs {_fmt(f['finance_costs'])}; net finance "
        f"{_fmt(f['net_finance'])}; profit before tax {_fmt(f['profit_before_tax'])}; tax {_fmt(f['tax'])}; "
        f"profit for the year {_fmt(f['profit_for_the_year'])}.")
    if f["revenue"]:
        out.append(f"Margins (management analysis): gross {_pct(f['gross_profit'], f['revenue'])}; operating "
                   f"{_pct(f['operating_profit'], f['revenue'])}; net {_pct(f['profit_for_the_year'], f['revenue'])}; "
                   f"effective tax rate {_pct(f['tax'], f['profit_before_tax'])} (does not validate the tax charge).")
    if s.choices:
        a = s.alternative
        out.append("Classification review pending (operating profit depends on it): " + "; ".join(
            f"{c.account} {_fmt(c.amount)} shown as {c.shown.lower()}, could be {c.alternative.lower()}"
            for c in s.choices)
            + f". Under the alternative, operating profit is {_fmt(a['operating_profit'])} (a difference of "
              f"{_fmt(a['operating_profit'] - f['operating_profit'])}); profit before tax is unchanged. State both.")
        out.append("Evidence that would decide each: " + "; ".join(
            f"{c.account}: {c.evidence or 'the nature of the transactions'}" for c in s.choices) + ".")
        out.append(
            "Alternative classification, every line in statement order (copy these; do not recompute): revenue "
            f"{_fmt(a['revenue'])}; cost of sales {_fmt(a['cost_of_sales'])}; gross profit {_fmt(a['gross_profit'])}; "
            f"other operating income {_fmt(a['other_operating_income'])}; operating expenses "
            f"{_fmt(a['operating_expenses'])}; operating profit {_fmt(a['operating_profit'])}; finance income "
            f"{_fmt(a['finance_income'])}; finance costs {_fmt(a['finance_costs'])}; net finance "
            f"{_fmt(a['net_finance'])}; profit before tax {_fmt(a['profit_before_tax'])}; tax {_fmt(a['tax'])}; "
            f"profit for the year {_fmt(a['profit_for_the_year'])}. Other operating income sits above operating "
            "profit. Prefer a short comparison of the lines that change over a second full statement.")
        # The account rows too: a second table listed Bank charges under
        # operating expenses and again in finance costs, beside a 574,000
        # total that excludes it (retest of 4 Nov 2026).
        out.append("In the alternative, these accounts move and appear only under their new heading: " + "; ".join(
            f"{c.account} {_fmt(c.amount)} from {c.shown.lower()} to {c.alternative.lower()}" for c in s.choices)
            + ". Every other account stays where it is. The rows under each heading must add up to its subtotal.")
        if s.sensitivities:
            out.append("Each choice on its own (sensitivities, not statutory options; copy these): " + "; ".join(
                f"moving only {c.account} to {c.alternative.lower()}: operating profit {_fmt(x['operating_profit'])}, "
                f"net finance {_fmt(x['net_finance'])}" for c, x in s.sensitivities)
                + f". Profit before tax is {_fmt(f['profit_before_tax'])} in every case. Show all "
                  f"{len(s.sensitivities) + 2} operating profits; no placement is established without evidence of "
                  "each account's nature.")
    if s.cost_of_sales_candidates:
        total = sum((abs(b) for _, b in s.cost_of_sales_candidates), ZERO)
        out.append("Shown in operating expenses but could be cost of sales: " + ", ".join(
            n for n, _ in s.cost_of_sales_candidates) + f" (together {_fmt(total)}); that would lower gross profit, "
            "not operating profit.")
    for flag in s.caption_flags:
        out.append("Caption to confirm: " + flag)
    out.append(f"Balance sheet check: net assets {_fmt(f['net_assets'])}; equity before profit "
               f"{_fmt(f['equity_before_profit'])}; equity including profit {_fmt(f['equity_including_profit'])}; "
               f"residual (net assets minus equity) {_fmt(s.residual)}.")
    if s.unmapped:
        out.append("Accounts the engine could not place: " + "; ".join(f"{n} {_fmt(b)}" for n, b in s.unmapped)
                   + ". State them beside the statement. An equal amount elsewhere is an investigation lead, not an "
                     "explanation; do not propose a correcting entry.")
    if s.dividends:
        out.append("Dividends: " + "; ".join(f"{n} {_fmt(b)}" for n, b in s.dividends) + " are outside profit and "
                   "reduce equity; whether declared, paid or proposed is not established by the file.")
    if f["tax"] and s.tax_payable is not None:
        out.append(f"Tax: charge {_fmt(f['tax'])}; closing tax payable {_fmt(s.tax_payable)}. No opening payable or "
                   "tax payments are in the file, so the tax reconciliation is incomplete; never conclude from equal "
                   "amounts that no tax was paid. The split between current and deferred tax and the reconciliation "
                   "of the charge to the tax rate are not established.")
    for finding in s.findings:
        out.append("Engine finding: " + finding)
    out.append("Do not say the statements reconcile, are verified or are complete while a residual, an unplaced "
               "account or a classification review remains.")
    return "\n".join(out)


def statement_notes(s: ChatStatement) -> list[str]:
    """Notes shown with the answer whatever the model writes (review C01, C04, SA-C01)."""
    f = s.figures
    notes = [f"Source checked by the Financial Statements engine: {s.filename} (SHA-256 {s.sha256[:12]}…), "
             f"{s.accounts} accounts; trial balance debits {_fmt(s.total_debits)}, credits {_fmt(s.total_credits)}."]
    if s.units == "thousands":
        notes.append("Amounts are in thousands, as the file states; read every figure as thousands (UNITS_THOUSANDS).")
    if not s.balanced:
        # No subtotal, alternative or residual is meaningful until it balances.
        notes.append(f"The trial balance does not balance: difference {_fmt(s.total_debits - s.total_credits)}. "
                     "No statement totals are given until the difference is found (ARITHMETIC_FAIL).")
        if s.source_flags:
            notes.append("Source to review before relying on the figures: " + " ".join(s.source_flags)
                         + " (SOURCE_REVIEW)")
        return notes
    if s.choices:
        alternative = s.alternative["operating_profit"]
        notes.append("Classification review pending: " + ", ".join(f"{c.account} ({_fmt(c.amount)})" for c in s.choices)
                     + f" can be operating or finance items. Operating profit is {_fmt(f['operating_profit'])} as shown, "
                       f"{_fmt(alternative)} under the alternative (difference "
                       f"{_fmt(alternative - f['operating_profit'])})"
                     + "".join(f", {_fmt(x['operating_profit'])} with only {c.account} moved" for c, x in s.sensitivities)
                     + "; profit before tax is unchanged. Evidence that decides it: "
                     + "; ".join(f"{c.account}: {c.evidence or 'the nature of the transactions'}" for c in s.choices)
                     + " (CLASSIFICATION_REVIEW).")
    if s.unmapped or s.residual:
        notes.append(f"Reconciliation unresolved: net assets {_fmt(f['net_assets'])} against equity including profit "
                     f"{_fmt(f['equity_including_profit'])}, a residual of {_fmt(s.residual)}"
                     + (f"; not placed: {', '.join(f'{n} {_fmt(b)}' for n, b in s.unmapped)}" if s.unmapped else "")
                     + ". The statements do not reconcile until it is resolved (RECONCILIATION_UNRESOLVED).")
    if f["tax"]:
        notes.append("Tax: the split between current and deferred tax, and the reconciliation of the charge to the "
                     "tax rate and to tax paid, are not established by the file; an equal charge and payable is not "
                     "a reconciliation (TAX_REVIEW).")
    if s.source_flags:
        notes.append("Source to review before relying on the figures: " + " ".join(s.source_flags) + " (SOURCE_REVIEW)")
    return notes


WORKSPACE_NOTE = ("To decide the open items with their evidence and take the statements through review, open them "
                  "in the Financial Statements workspace (/financial-statements).")
_FRAMEWORK_ELECTION = (("FRS102_1A", r"FRS\s*102\s*(?:section\s*)?1A"), ("FRS105", r"FRS\s*105"),
                       ("FRS101", r"FRS\s*101"), ("FRS102", r"FRS\s*102|UK\s+GAAP"),
                       ("IFRS_SMES", r"IFRS\s+for\s+SMEs"), ("US_GAAP", r"US\s+GAAP"), ("IFRS", r"\bIFRS\b"))


def framework_note(query: str, period_end: str | None) -> str | None:
    """What the engine's standards resolver says about the framework named in
    the question, from the facts chat actually has (Document 03; gap analysis
    of 6 Nov 2026): never a date, size or jurisdiction chat would have to guess."""
    from datetime import date as _date

    from app.domains.financial_statements import standards
    election = next((code for code, pattern in _FRAMEWORK_ELECTION if re.search(pattern, query or "", re.I)), None)
    if election is None:
        return None
    statutory = bool(re.search(r"\bstatutory|for\s+filing|companies\s+house\b", query or "", re.I))
    resolution = standards.resolve(standards.EntityFacts(
        framework_election=election, period_end=_date.fromisoformat(period_end) if period_end else None,
        requested_claim="statutory_ready" if statutory else "illustrative"))
    blockers = ", ".join(code.replace("_", " ").lower() for code in resolution.blockers)
    return (f"Standards check by the Financial Statements engine for {election.replace('_', ' ')}: statutory claim "
            + ("permitted" if resolution.permit_statutory_claim else "not permitted")
            + (f"; open: {blockers}" if blockers else "")
            + ". It needs the entity's jurisdiction and legal form, the period start and end, size figures and a "
              "signed framework election (FRAMEWORK_CHECK).")


# A narrative figure must be the engine's (review NB26-08): "operating margin
# 12.62%" beside a 218,600 statement is removed. Only a label followed by its
# figure is checked ("operating profit is 218,600"), never an account row.
_AMOUNT_LABELS = {
    "revenue": ("revenue", "turnover"), "cost_of_sales": ("cost of sales",), "gross_profit": ("gross profit",),
    "operating_expenses": ("operating expenses",), "operating_profit": ("operating profit",),
    "net_finance": ("net finance (?:costs?|income|expenses?)", "net finance"),
    "finance_costs": ("(?<!net )finance costs",), "finance_income": ("(?<!net )finance income",),
    "profit_before_tax": ("profit before tax(?:ation)?",),
    "tax": ("tax charge", "tax expense", "income tax expense", "corporation tax charge"),
    "profit_for_the_year": ("profit for the year", "profit after tax", "net profit"),
}
_RATE_LABELS = {"gross margin": ("gross_profit", "revenue"), "operating margin": ("operating_profit", "revenue"),
                "net margin": ("profit_for_the_year", "revenue"),
                "effective tax rate": ("tax", "profit_before_tax")}
_GAP = (r"[\s:=£$€(]*(?:(?:of|is|was|at|to|totals?|totalling|equals?|stands\s+at|would\s+be|becomes|falls\s+to|"
        r"rises\s+to|GBP|USD|EUR)\b[\s:=£$€(]*)*")
_NUMBER = r"(-?\d[\d,]*(?:\.\d+)?)"
# A sentence about another placement may use the alternative's figures.
_ALTERNATIVE_CUE = re.compile(r"\b(?:alternative\w*|if|would|could|under|moved?|moving|reclassif\w*|scenario|"
                              r"instead|sensitivit\w*|options?|cases?|otherwise|either)\b", re.I)


def _scenarios(s: ChatStatement) -> list[dict[str, Decimal]]:
    return [s.figures] + ([s.alternative] if s.alternative else []) + [x for _, x in s.sensitivities]


def _wrong_figures(sentence: str, s: ChatStatement) -> list[str]:
    # An unbalanced trial balance has no statement figures at all (FS-009).
    scenarios = [] if not s.balanced else _scenarios(s) if _ALTERNATIVE_CUE.search(sentence) else [s.figures]
    wrong = []
    for key, labels in _AMOUNT_LABELS.items():
        allowed = {abs(x[key]).quantize(Decimal("1")) for x in scenarios if key in x}
        # "operating profit is 14,900 higher": a difference between placements.
        if s.balanced:
            allowed |= {abs(x[key] - s.figures[key]).quantize(Decimal("1")) for x in _scenarios(s) if key in x}
        for match in re.finditer(rf"\b(?:{'|'.join(labels)})\b{_GAP}{_NUMBER}(?!\s*%|[\d,.]*\s*%)", sentence, re.I):
            value = abs(Decimal(match.group(1).replace(",", ""))).quantize(Decimal("1"))
            if value not in allowed:
                wrong.append(match.group(0).strip())
    for label, (part, whole) in _RATE_LABELS.items():
        allowed = set()
        for x in scenarios:
            if x.get(whole):
                rate = x[part] / x[whole] * 100
                allowed |= {f"{rate:.{places}f}" for places in (0, 1, 2)}
        for match in re.finditer(rf"\b{label}\b{_GAP}{_NUMBER}\s*%", sentence, re.I):
            shown = match.group(1).replace(",", "")
            places = len(shown.split(".")[1]) if "." in shown else 0
            if f"{Decimal(shown):.{places}f}" not in allowed:
                wrong.append(match.group(0).strip())
    return wrong


def remove_unsupported_figures(text: str, s: ChatStatement) -> tuple[str, list[str]]:
    """The answer without narrative sentences stating a statement figure the
    engine did not compute; and the figures removed. Tables are kept: their
    rows are account lines, not labelled claims."""
    removed: list[str] = []
    lines = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith(("|", "```")) or "\t" in line:
            lines.append(line)
            continue
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", line):
            wrong = _wrong_figures(sentence, s)
            if wrong:
                removed.extend(wrong)
            else:
                kept.append(sentence)
        if kept or not line.strip():
            lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), removed

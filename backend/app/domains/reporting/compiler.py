"""Deterministic financial compiler (ZL-RPT-007 §7, gate G2).

One fact graph drives every statement: balances come from the sealed
snapshot, each presented amount is a typed fact with a stable fact_id,
lineage and source journals. Values are full-precision Decimal; rounding is a
presentation concern and never happens here.

Sign convention: assets and expenses are presented debit-positive;
liabilities, equity and revenue credit-positive.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .ledger import DEBIT_NORMAL
from .mapping import AccountMap
from .snapshot import SealedSnapshot

ZERO = Decimal("0")
STATEMENTS = ("balance_sheet", "profit_or_loss", "cash_flow", "changes_in_equity")


@dataclass(frozen=True)
class FinancialFact:
    fact_id: str
    concept: str
    label: str
    context: str                 # "instant" or "duration"
    period_start: date | None    # None for an instant
    period_end: date
    currency: str
    value: Decimal
    source_refs: tuple[str, ...]
    lineage: str
    snapshot_hash: str
    mapping_version: str


@dataclass(frozen=True)
class StatementLine:
    concept: str
    label: str
    section: str
    fact_id: str
    value: Decimal
    is_total: bool = False


@dataclass
class CompiledReport:
    snapshot: SealedSnapshot
    account_map: AccountMap
    facts: dict[str, FinancialFact] = field(default_factory=dict)
    statements: dict[str, list[StatementLine]] = field(default_factory=dict)
    exceptions: list[dict] = field(default_factory=list)

    def line(self, statement: str, concept: str) -> StatementLine:
        for item in self.statements[statement]:
            if item.concept == concept:
                return item
        raise KeyError(f"{statement} has no line {concept}")


def _presented(account_type: str, net_debit: Decimal) -> Decimal:
    return net_debit if account_type in DEBIT_NORMAL else -net_debit


class _Builder:
    def __init__(self, snapshot: SealedSnapshot, account_map: AccountMap):
        self.report = CompiledReport(snapshot=snapshot, account_map=account_map)
        self.snapshot = snapshot

    def fact(self, statement: str, section: str, concept: str, label: str, value: Decimal,
             context: str, refs, lineage: str, is_total: bool = False) -> None:
        snap = self.snapshot
        start = None if context == "instant" else snap.period_start
        end = snap.period_start if concept.endswith(".opening") else snap.period_end
        identity = "|".join([snap.snapshot_hash, self.report.account_map.version, statement, concept, context,
                             start.isoformat() if start else "", end.isoformat()])
        fact_id = "fct_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        self.report.facts[fact_id] = FinancialFact(
            fact_id=fact_id, concept=concept, label=label, context=context, period_start=start,
            period_end=end, currency=snap.currency, value=value, source_refs=tuple(sorted(set(refs))),
            lineage=lineage, snapshot_hash=snap.snapshot_hash, mapping_version=self.report.account_map.version,
        )
        self.report.statements.setdefault(statement, []).append(
            StatementLine(concept=concept, label=label, section=section, fact_id=fact_id, value=value, is_total=is_total))


def compile_report(snapshot: SealedSnapshot, account_map: AccountMap, exceptions: list[dict]) -> CompiledReport:
    builder = _Builder(snapshot, account_map)
    report = builder.report
    report.exceptions.extend(exceptions)
    accounts, lines = snapshot.accounts, account_map.lines

    opening: dict[str, Decimal] = defaultdict(lambda: ZERO)
    movement: dict[str, Decimal] = defaultdict(lambda: ZERO)
    refs: dict[str, set[str]] = defaultdict(set)
    in_period = []
    for journal in snapshot.journals:
        if journal.posted_on < snapshot.period_start:
            target = opening
        elif journal.posted_on <= snapshot.period_end:
            target = movement
            in_period.append(journal)
        else:
            continue
        for line in journal.lines:
            target[line.account] += line.net_debit
            refs[line.account].add(journal.source_id)

    def grouped(account_types, balance):
        """Accounts of these types aggregated onto their mapped lines, in map order."""
        out: dict[str, dict] = {}
        for code, account in accounts.items():
            if account.type not in account_types or code not in lines:
                continue
            mapped = lines[code]
            slot = out.setdefault(mapped.line, {"label": mapped.label, "value": ZERO, "refs": set(), "codes": []})
            slot["value"] += _presented(account.type, balance(code))
            slot["refs"] |= refs[code]
            slot["codes"].append(code)
        return dict(sorted(out.items()))

    closing = lambda code: opening[code] + movement[code]  # noqa: E731

    # ── Profit or loss (duration) ───────────────────────────────────────
    revenue_total = expense_total = ZERO
    pl_refs: set[str] = set()
    for section, types in (("revenue", ("revenue",)), ("expenses", ("expense",))):
        for concept, slot in grouped(types, lambda c: movement[c]).items():
            builder.fact("profit_or_loss", section, concept, slot["label"], slot["value"], "duration",
                         slot["refs"], f"sum(period movement of {', '.join(slot['codes'])})")
            pl_refs |= slot["refs"]
            if section == "revenue":
                revenue_total += slot["value"]
            else:
                expense_total += slot["value"]
    net_result = revenue_total - expense_total
    builder.fact("profit_or_loss", "result", "pl.net_result", "Result for the period", net_result, "duration",
                 pl_refs, "sum(revenue lines) - sum(expense lines)", is_total=True)

    # Results of earlier periods not yet closed to an equity account.
    unclosed_prior = -sum((opening[c] for c, a in accounts.items() if a.type in ("revenue", "expense")), ZERO)

    # ── Balance sheet (instant at period end) ───────────────────────────
    totals = {}
    for section, account_type in (("assets", "asset"), ("liabilities", "liability"), ("equity", "equity")):
        total, section_refs = ZERO, set()
        for concept, slot in grouped((account_type,), closing).items():
            builder.fact("balance_sheet", section, concept, slot["label"], slot["value"], "instant",
                         slot["refs"], f"closing balance of {', '.join(slot['codes'])}")
            total += slot["value"]
            section_refs |= slot["refs"]
        if section == "equity":
            if unclosed_prior != ZERO:
                builder.fact("balance_sheet", section, "bs.unclosed_prior_results", "Unclosed results of prior periods",
                             unclosed_prior, "instant", [], "-(opening revenue + expense balances)")
                total += unclosed_prior
            builder.fact("balance_sheet", section, "bs.current_period_result", "Result for the period",
                         net_result, "instant", pl_refs, "pl.net_result")
            total += net_result
            section_refs |= pl_refs
        totals[section] = total
        builder.fact("balance_sheet", section, f"bs.total_{section}", f"Total {section}", total, "instant",
                     section_refs, f"sum({section} lines)", is_total=True)

    # ── Cash flow (indirect classification of each cash journal) ────────
    cash_codes = {code for code, account in accounts.items() if account.is_cash}
    flows = {name: ZERO for name in ("operating", "investing", "financing", "fx_effect")}
    flow_refs: dict[str, set[str]] = defaultdict(set)
    for journal in in_period:
        cash_delta = sum((l.net_debit for l in journal.lines if l.account in cash_codes), ZERO)
        if cash_delta == ZERO:
            continue
        classes = {lines[l.account].cash_flow for l in journal.lines
                   if l.account not in cash_codes and l.account in lines}
        classes.discard(None)
        if len(classes) != 1:
            report.exceptions.append({
                "code": "cash_classification_ambiguous", "journal": journal.source_id,
                "detail": f"cash movement {cash_delta} has counterpart classes {sorted(classes) or 'none'}",
            })
            continue
        (flow_class,) = classes
        flows[flow_class] += cash_delta
        flow_refs[flow_class].add(journal.source_id)

    opening_cash = sum((opening[c] for c in cash_codes), ZERO)
    builder.fact("cash_flow", "cash", "cf.cash.opening", "Cash at beginning of period", opening_cash, "instant",
                 [r for c in cash_codes for r in refs[c]], "sum(opening balances of cash accounts)")
    labels = {"operating": "Net cash from operating activities", "investing": "Net cash from investing activities",
              "financing": "Net cash from financing activities", "fx_effect": "Effect of exchange rate changes"}
    for name, label in labels.items():
        builder.fact("cash_flow", name, f"cf.{name}", label, flows[name], "duration", flow_refs[name],
                     f"sum(cash movement of journals classified {name})")
    closing_cash = sum((closing(c) for c in cash_codes), ZERO)
    builder.fact("cash_flow", "cash", "cf.cash.closing", "Cash at end of period", closing_cash, "instant",
                 [r for c in cash_codes for r in refs[c]], "sum(closing balances of cash accounts)", is_total=True)

    # ── Changes in equity ───────────────────────────────────────────────
    equity_codes = [c for c, a in accounts.items() if a.type == "equity"]
    opening_equity = sum((_presented("equity", opening[c]) for c in equity_codes), ZERO) + unclosed_prior
    builder.fact("changes_in_equity", "equity", "eq.opening", "Equity at beginning of period", opening_equity,
                 "instant", [r for c in equity_codes for r in refs[c]], "sum(opening equity) + unclosed prior results")
    builder.fact("changes_in_equity", "movements", "eq.result", "Result for the period", net_result, "duration",
                 pl_refs, "pl.net_result")
    movements: dict[str, dict] = {}
    for code in equity_codes:
        if movement[code] == ZERO:
            continue
        kind = (lines[code].equity_movement if code in lines else None) or "other_movements"
        slot = movements.setdefault(kind, {"value": ZERO, "refs": set(), "codes": []})
        slot["value"] += _presented("equity", movement[code])
        slot["refs"] |= refs[code]
        slot["codes"].append(code)
    for kind, slot in sorted(movements.items()):
        builder.fact("changes_in_equity", "movements", f"eq.{kind}", kind.replace("_", " ").capitalize(),
                     slot["value"], "duration", slot["refs"], f"period movement of {', '.join(slot['codes'])}")
    closing_equity = opening_equity + net_result + sum((s["value"] for s in movements.values()), ZERO)
    builder.fact("changes_in_equity", "equity", "eq.closing", "Equity at end of period", closing_equity, "instant",
                 [r for c in equity_codes for r in refs[c]] + list(pl_refs),
                 "eq.opening + eq.result + equity movements", is_total=True)
    return report

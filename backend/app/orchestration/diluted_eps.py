"""Basic and diluted EPS for convertible preferred stock and bonds, computed
by the application (if-converted method) and given to the model to explain.

With a method note alone the model still worked "incremental EPS" as (net
income + add-back) ÷ (all shares), called both convertibles antidilutive and
reported diluted EPS equal to basic, $2.13 instead of about $2.00 (23 Oct
2026). The schedule is deterministic; the model explains it.

Only a scenario read unambiguously is computed: net income, shares
outstanding, and every convertible's terms. Options, warrants or anything
needing the treasury-stock method leave it to the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_N = r"\$?\s?(\d[\d,]*(?:\.\d+)?)"
_ASKS = re.compile(r"\bdiluted\s+(?:EPS|earnings\s+per\s+share)\b", re.I)
_TREASURY = re.compile(r"\b(?:options?|warrants?|rights\s+issue|RSUs?|restricted\s+stock|contingently)\b", re.I)
# A money amount or a comma-grouped figure, never the year in "net income for
# 2026 is $900,000" (it was read as 2,026).
_NET_INCOME = re.compile(
    r"\bnet\s+income\b[^\n]{0,40}?(?:\$\s?(\d[\d,]*(?:\.\d+)?)|(?<![\d,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\b)", re.I)
_SHARES = re.compile(r"(\d[\d,]*)\s+(?:shares\s+of\s+)?(?:common\s+)?(?:shares|stock)\b[^.\n]{0,40}?\boutstanding\b"
                     r"|\boutstanding\b[^.\n]{0,20}?(\d[\d,]*)\s+(?:common\s+)?shares\b", re.I)
_PREFERRED = re.compile(
    r"(\d[\d,]*)\s+shares\s+of\s+(\d+(?:\.\d+)?)\s?%,?\s+\$(\d[\d,]*(?:\.\d+)?)\s+par[^.\n]*?\bconvertible\b[^.\n]*?"
    r"\bpreferred\b(?P<rest>[^\n]*)", re.I)
_PREFERRED_ALT = re.compile(
    r"(\d[\d,]*)\s+shares\s+of\s+(\d+(?:\.\d+)?)\s?%,?\s+\$(\d[\d,]*(?:\.\d+)?)\s+par[^.\n]*?\bpreferred\b[^.\n]*?"
    r"\bconvertible\b(?P<rest>[^\n]*)", re.I)
_EACH_INTO = re.compile(r"\beach\b[^.\n]{0,40}?\bconvertible\s+into\s+(\d+(?:\.\d+)?)\s+(?:shares\s+of\s+)?common", re.I)
_BONDS = re.compile(rf"{_N}\s+of\s+(\d+(?:\.\d+)?)\s?%\s+convertible\s+bonds?\b(?P<rest>[^\n]*)", re.I)
_TOTAL_INTO = re.compile(r"\bconvertible\s+into\s+(?:a\s+total\s+of\s+)?(\d[\d,]*)\s+(?:shares\s+of\s+)?common", re.I)
_TAX = re.compile(r"\btax\s+rate\b[^%\n]{0,20}?(\d+(?:\.\d+)?)\s?%|(\d+(?:\.\d+)?)\s?%\s+(?:corporate\s+|income\s+)?tax\s+rate",
                  re.I)

_CENT = Decimal("0.01")
_FOUR = Decimal("0.0001")


def _d(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


@dataclass(frozen=True)
class Convertible:
    name: str
    add_back: Decimal          # earnings effect of conversion
    add_back_working: str
    shares: Decimal
    shares_working: str

    @property
    def incremental(self) -> Decimal:
        return self.add_back / self.shares


@dataclass(frozen=True)
class EpsSchedule:
    net_income: Decimal
    shares: Decimal
    preferred_dividend: Decimal
    convertibles: tuple[Convertible, ...]
    steps: tuple[tuple[str, Decimal, Decimal, Decimal, Decimal, bool], ...]  # name, incr, num, den, eps, dilutive

    @property
    def basic_numerator(self) -> Decimal:
        return self.net_income - self.preferred_dividend

    @property
    def basic(self) -> Decimal:
        return self.basic_numerator / self.shares

    @property
    def diluted(self) -> Decimal:
        included = [step for step in self.steps if step[5]]
        return included[-1][4] if included else self.basic

    def prompt_block(self) -> str:
        money = lambda v: f"${v.quantize(_CENT, ROUND_HALF_UP):,}"  # noqa: E731
        eps = lambda v: f"${v.quantize(_FOUR, ROUND_HALF_UP)}"  # noqa: E731
        lines = [
            "\n\nVERIFIED EPS SCHEDULE (computed by the application with the if-converted method; use these "
            "figures and conclusions, explain them, and do not recompute or contradict them):",
            f"- Preferred dividend deducted for basic EPS: {money(self.preferred_dividend)}",
            f"- Basic EPS = ({money(self.net_income)} − {money(self.preferred_dividend)}) ÷ {self.shares:,} shares "
            f"= {money(self.basic_numerator)} ÷ {self.shares:,} = {eps(self.basic)}",
        ]
        for item in self.convertibles:
            lines.append(f"- {item.name}: earnings effect {item.add_back_working} = {money(item.add_back)}; shares on "
                         f"conversion {item.shares_working} = {item.shares:,}; incremental EPS = "
                         f"{money(item.add_back)} ÷ {item.shares:,} = {eps(item.incremental)}")
        # An answer stated the test as "lower than the EPS that would result
        # after its inclusion" (23 Oct 2026): the comparison is with the EPS
        # before it is added.
        lines.append("- Dilution test, most dilutive (lowest incremental EPS) first. State the rule exactly as: a "
                     "security is dilutive, and included, when its incremental EPS is below the running EPS before "
                     "it is added (starting from basic EPS); otherwise it is antidilutive and excluded.")
        for name, incremental, numerator, denominator, result, dilutive in self.steps:
            if dilutive:
                lines.append(f"  - {name}: incremental {eps(incremental)} is below the running EPS, so it is "
                             f"DILUTIVE and included: {money(numerator)} ÷ {denominator:,} = {eps(result)}")
            else:
                lines.append(f"  - {name}: incremental {eps(incremental)} is not below the running EPS, so it is "
                             f"ANTIDILUTIVE and excluded")
        lines.append(f"- Diluted EPS = {eps(self.diluted)} (never above basic EPS {eps(self.basic)})")
        lines.append("- Present this schedule as the answer. Do not add journal entries, conversion entries or "
                     "disclosure tables the question does not ask for.")
        return "\n".join(lines)


def _preferred(question: str, tax: Decimal | None) -> Convertible | None:
    match = _PREFERRED.search(question) or _PREFERRED_ALT.search(question)
    if not match:
        return None
    count, rate, par = _d(match.group(1)), _d(match.group(2)), _d(match.group(3))
    each = _EACH_INTO.search(match.group(0))
    if not each:
        return None
    ratio = _d(each.group(1))
    dividend = count * par * rate / 100
    return Convertible("Convertible preferred stock", dividend,
                       f"preferred dividend added back {count:,} × ${par:,} × {rate}%", count * ratio,
                       f"{count:,} × {ratio}")


def _bonds(question: str, tax: Decimal | None) -> Convertible | None | bool:
    match = _BONDS.search(question)
    if not match:
        return None
    face, rate = _d(match.group(1)), _d(match.group(2))
    into = _TOTAL_INTO.search(match.group("rest"))
    if not into or tax is None:
        return False                      # bonds present but not readable
    shares = _d(into.group(1))
    interest = face * rate / 100
    after_tax = interest * (1 - tax / 100)
    return Convertible("Convertible bonds", after_tax,
                       f"after-tax interest ${face:,} × {rate}% × (1 − {tax}%)", shares, f"{shares:,}")


def eps_schedule(question: str) -> EpsSchedule | None:
    """The deterministic schedule, or None when the scenario is not one this
    reads with certainty."""
    text = question or ""
    if not _ASKS.search(text) or _TREASURY.search(text):
        return None
    income = _NET_INCOME.search(text)
    shares = _SHARES.search(text)
    if not income or not shares:
        return None
    tax_match = _TAX.search(text)
    tax = _d(next(g for g in tax_match.groups() if g)) if tax_match else None
    preferred = _preferred(text, tax)
    bonds = _bonds(text, tax)
    if bonds is False or (re.search(r"\bconvertible\s+preferred|\bpreferred\b[^.\n]*\bconvertible", text, re.I)
                          and preferred is None):
        return None                       # a convertible is named but its terms were not read
    convertibles = tuple(item for item in (preferred, bonds) if item)
    if not convertibles:
        return None
    net_income, outstanding = _d(next(g for g in income.groups() if g)), _d(next(g for g in shares.groups() if g))
    if net_income < 1000 or outstanding < 100:
        return None                       # not a figure this reads with certainty
    dividend = preferred.add_back if preferred else Decimal(0)
    numerator, denominator = net_income - dividend, outstanding
    steps = []
    for item in sorted(convertibles, key=lambda c: c.incremental):
        running = numerator / denominator
        if item.incremental < running:
            numerator, denominator = numerator + item.add_back, denominator + item.shares
            steps.append((item.name, item.incremental, numerator, denominator, numerator / denominator, True))
        else:
            steps.append((item.name, item.incremental, numerator, denominator, running, False))
    return EpsSchedule(net_income, outstanding, dividend, convertibles, tuple(steps))


def verified_eps_block(question: str) -> str:
    schedule = eps_schedule(question)
    return schedule.prompt_block() if schedule else ""

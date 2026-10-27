"""Normalise a parsed trial balance or ledger (Document 04 stage P2, rules
SD-004 to SD-009).

Amounts are exact Decimal. A blank cell, a zero, a dash and an unreadable
value are different states and never coerced into one another. A single
signed "balance" column without a stated convention is not guessed: the
sign convention must be confirmed. Locale-ambiguous numbers ("1.234,56") are
not converted. Every line keeps its sheet and row so it can be traced to the
original cell.

Two shapes are read: a trial balance (one line per account, optionally with
opening and closing balances around the period's movements) and a ledger
(dated entries, many per account, with references), whose lines are summed
per account for classification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .findings import HARD_STOP, INFO, Finding
from .intake import Cell, ParsedSource

ZERO = Decimal("0")
TRIAL_BALANCE, LEDGER = "TRIAL_BALANCE", "LEDGER"
_HEADER_SCAN_ROWS = 25
_ACCOUNT_NAME = re.compile(r"\b(?:account\s*name|account|name|description|ledger|nominal)\b", re.I)
_ACCOUNT_CODE = re.compile(r"\b(?:code|no\.?|number|ref|nominal\s*code|account\s*code|gl)\b", re.I)
_DEBIT = re.compile(r"^\s*(?:(?:period\s+|movement\s+)?debit|dr)\b", re.I)
_CREDIT = re.compile(r"^\s*(?:(?:period\s+|movement\s+)?credit|cr)\b", re.I)
_BALANCE = re.compile(r"\b(?:balance|amount|net)\b", re.I)
_OPENING = re.compile(r"\b(?:opening|b/?f|brought\s+forward)\b", re.I)
_CLOSING = re.compile(r"\b(?:closing|c/?f|carried\s+forward)\b", re.I)
_DATE_COL = re.compile(r"^\s*(?:posting\s+|transaction\s+|entry\s+)?date\s*$", re.I)
_REFERENCE = re.compile(r"\b(?:voucher|journal|jv|reference|ref|document|doc)\b", re.I)
_NARRATIVE = re.compile(r"\b(?:description|narrative|details|memo|particulars)\b", re.I)
_CURRENCY_COL = re.compile(r"\b(?:currency|ccy)\b", re.I)
_SIGN_STATED = re.compile(r"(?:debit|dr)\s*(?:=|is|as)?\s*\+|positive\s*=\s*debit|\(dr\s*\+", re.I)
_THOUSANDS = re.compile(r"£\s*000|'000|\$\s*000|€\s*000|in\s+thousands|\(000s?\)", re.I)
_TOTAL = re.compile(r"^\s*(?:grand\s+)?(?:sub)?totals?\b", re.I)
_DASHES = {"-", "–", "—", "nil"}
_PLAIN = re.compile(r"^\(?-?[£$€₹¥]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?-?$|^\(?-?[£$€₹¥]?\d+(?:\.\d+)?\)?-?$")
_EUROPEAN = re.compile(r"^-?\d{1,3}(?:\.\d{3})+,\d+$|^-?\d+,\d{1,2}$")
_SYMBOLS = re.compile(r"[£$€₹¥]")
_PERIOD_END = re.compile(r"\b(?:as\s+at|as\s+of|year\s+ended|period\s+ended|ended|to)\s+"
                         r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", re.I)


@dataclass(frozen=True)
class Amount:
    value: Decimal | None
    status: str                    # PRESENT | ZERO | BLANK | INVALID | LOCALE_AMBIGUOUS
    raw: str


def parse_amount(text: str) -> Amount:
    raw = (text or "").strip()
    if not raw:
        return Amount(None, "BLANK", raw)
    if raw.lower() in _DASHES:
        return Amount(ZERO, "ZERO", raw)
    compact = re.sub(r"\s", "", raw)
    if _EUROPEAN.match(compact):
        return Amount(None, "LOCALE_AMBIGUOUS", raw)
    if not _PLAIN.match(compact):
        return Amount(None, "INVALID", raw)
    negative = compact.startswith("(") and compact.endswith(")") or compact.startswith("-") or compact.endswith("-")
    digits = re.sub(r"[^\d.]", "", compact)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return Amount(None, "INVALID", raw)
    value = -value if negative else value
    return Amount(value, "ZERO" if value == 0 else "PRESENT", raw)


def parse_date(text: str) -> date | None:
    value = (text or "").strip().split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}", (text or "").strip()) else (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


_BLANK = Amount(None, "BLANK", "")


@dataclass(frozen=True)
class TBLine:
    key: str                       # stable account key: code, else name
    account_code: str
    account_name: str
    debit: Amount
    credit: Amount
    currency: str
    sheet: str
    row: int
    hidden: bool = False
    opening: Amount = _BLANK       # signed, debit positive
    closing: Amount = _BLANK       # signed, debit positive
    posted_on: date | None = None
    reference: str = ""
    narrative: str = ""

    @property
    def ref(self) -> str:
        return f"{self.sheet}!R{self.row}"

    @property
    def movement(self) -> Decimal:
        return (self.debit.value or ZERO) - (self.credit.value or ZERO)

    @property
    def net_debit(self) -> Decimal:
        """The account's balance: the closing balance when the file states
        one, otherwise debit minus credit."""
        return self.closing.value if self.closing.value is not None else self.movement

    def to_dict(self) -> dict:
        out = {"key": self.key, "account_code": self.account_code, "account_name": self.account_name,
               "debit": str(self.debit.value) if self.debit.value is not None else None,
               "credit": str(self.credit.value) if self.credit.value is not None else None,
               "debit_status": self.debit.status, "credit_status": self.credit.status,
               "currency": self.currency, "source": self.ref, "hidden": self.hidden}
        if self.opening.status != "BLANK" or self.closing.status != "BLANK":
            out.update(opening=str(self.opening.value) if self.opening.value is not None else None,
                       closing=str(self.closing.value) if self.closing.value is not None else None)
        if self.posted_on or self.reference:
            out.update(posted_on=self.posted_on.isoformat() if self.posted_on else None, reference=self.reference,
                       narrative=self.narrative)
        return out


@dataclass
class NormalizedTB:
    lines: list[TBLine] = field(default_factory=list)
    control_totals: list[tuple[str, Amount, Amount]] = field(default_factory=list)   # (ref, debit, credit)
    units: str = "units"
    sign_convention: str = "DEBIT_CREDIT_COLUMNS"
    year_columns: tuple[str, ...] = ()
    kind: str = TRIAL_BALANCE
    period_end: date | None = None
    has_rollforward: bool = False
    findings: list[Finding] = field(default_factory=list)

    def account_lines(self) -> list[TBLine]:
        """One line per account: a ledger's entries summed per account."""
        if self.kind != LEDGER:
            return self.lines
        totals: dict[str, list] = {}
        for line in self.lines:
            entry = totals.setdefault(line.key, [line, ZERO, ZERO])
            entry[1] += line.debit.value or ZERO
            entry[2] += line.credit.value or ZERO
        return [TBLine(key=first.key, account_code=first.account_code, account_name=first.account_name,
                       debit=Amount(dr, "PRESENT" if dr else "ZERO", str(dr)),
                       credit=Amount(cr, "PRESENT" if cr else "ZERO", str(cr)),
                       currency=first.currency, sheet=first.sheet, row=first.row)
                for first, dr, cr in totals.values()]


def _find_header(rows: list[list[Cell]]):
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        texts = [re.sub(r"[_\-]+", " ", c.text) for c in row]     # "account_code" is "account code"
        debit = next((i for i, t in enumerate(texts) if _DEBIT.search(t)), None)
        credit = next((i for i, t in enumerate(texts) if _CREDIT.search(t)), None)
        opening = next((i for i, t in enumerate(texts) if _OPENING.search(t)), None)
        closing = next((i for i, t in enumerate(texts) if _CLOSING.search(t)), None)
        balance = next((i for i, t in enumerate(texts) if _BALANCE.search(t) and i not in (opening, closing)), None)
        name = next((i for i, t in enumerate(texts) if _ACCOUNT_NAME.search(t)
                     and i not in (debit, credit) and not re.search(r"code|no\.?$|number", t, re.I)
                     and not _REFERENCE.search(t)), None)
        if name is None:
            continue
        if (debit is not None and credit is not None) or balance is not None or closing is not None:
            code = next((i for i, t in enumerate(texts) if i != name and re.search(r"code|^no\.?$|number|^ref$", t, re.I)
                         and not _REFERENCE.search(t)), None)
            pick = lambda pattern, exclude=(): next((i for i, t in enumerate(texts)  # noqa: E731
                                                     if pattern.search(t) and i not in exclude), None)
            column = lambda i: None if i is None else row[i].column  # noqa: E731 — the sheet's own column number
            narrative = pick(_NARRATIVE, (name,))
            return index, {"name": column(name), "code": column(code), "debit": column(debit), "credit": column(credit),
                           "balance": column(balance) if (debit is None or credit is None) and closing is None else None,
                           "opening": column(opening), "closing": column(closing),
                           "currency": column(pick(_CURRENCY_COL)), "date": column(pick(_DATE_COL)),
                           "reference": column(pick(_REFERENCE, (name, code))), "narrative": column(narrative)}
    return None, None


def normalize(parsed: ParsedSource) -> NormalizedTB:
    tb = NormalizedTB()
    rows = parsed.rows
    header_index, cols = _find_header(rows)
    if cols is None:
        tb.findings.append(Finding("AMBIGUOUS_SCHEMA", HARD_STOP,
                                   "No account and debit/credit (or balance) columns were found.", "SD-004"))
        return tb
    header_row = rows[header_index]
    title_text = " ".join(c.text for r in rows[:header_index + 1] for c in r)
    if _THOUSANDS.search(title_text):
        tb.units = "thousands"
        tb.findings.append(Finding("UNITS_THOUSANDS", INFO, "Amounts are stated in thousands.", "SD-004"))
    if (period := _PERIOD_END.search(title_text)) and (end := parse_date(period.group(1))):
        tb.period_end = end
    tb.year_columns = tuple(sorted({y for c in header_row for y in re.findall(r"\b(?:19|20)\d{2}\b", c.text)}))
    tb.has_rollforward = cols["opening"] is not None and cols["closing"] is not None
    single = cols["balance"] is not None
    if single:
        tb.sign_convention = "SIGNED_BALANCE"
        if not _SIGN_STATED.search(title_text):
            tb.findings.append(Finding("SIGN_UNRESOLVED", HARD_STOP,
                                       "A single balance column has no stated sign convention (is debit positive?). "
                                       "Confirm it before the balances are used.", "SD-007"))
    symbols: set[str] = set()

    def text(row: list[Cell], column: int | None) -> str:
        if column is None:
            return ""
        return next((c.text for c in row if c.column == column), "")

    for row in rows[header_index + 1:]:
        if row and row[0].sheet != header_row[0].sheet:
            continue
        name, code = text(row, cols["name"]), text(row, cols["code"])
        if single:
            amount = parse_amount(text(row, cols["balance"]))
            if amount.value is not None and amount.value < 0:
                debit, credit = Amount(ZERO, "BLANK", ""), Amount(-amount.value, amount.status, amount.raw)
            else:
                debit, credit = amount, Amount(None, "BLANK", "")
        else:
            debit, credit = parse_amount(text(row, cols["debit"])), parse_amount(text(row, cols["credit"]))
        opening, closing = parse_amount(text(row, cols["opening"])), parse_amount(text(row, cols["closing"]))
        if not name and not code and all(a.status == "BLANK" for a in (debit, credit, opening, closing)):
            continue
        for amount in (debit, credit, opening, closing):
            symbols |= set(_SYMBOLS.findall(amount.raw))
        if _TOTAL.match(name or code):
            tb.control_totals.append((f"{row[0].sheet}!R{row[0].row}", debit, credit))
            continue
        tb.lines.append(TBLine(key=code or name, account_code=code, account_name=name or code, debit=debit,
                               credit=credit, currency=text(row, cols["currency"]).upper(), sheet=row[0].sheet,
                               row=row[0].row, hidden=any(c.hidden for c in row), opening=opening, closing=closing,
                               posted_on=parse_date(text(row, cols["date"])) if cols["date"] else None,
                               reference=text(row, cols["reference"]), narrative=text(row, cols["narrative"])))
    keys = [line.key.lower() for line in tb.lines]
    if cols["date"] is not None and len(set(keys)) < len(keys):
        tb.kind = LEDGER
    if len(symbols) > 1:
        tb.findings.append(Finding("MIXED_CURRENCY", HARD_STOP,
                                   f"Amounts use more than one currency symbol ({', '.join(sorted(symbols))}).", "SD-005"))
    currencies = {line.currency for line in tb.lines if line.currency}
    if len(currencies) > 1:
        tb.findings.append(Finding("MIXED_CURRENCY", HARD_STOP,
                                   f"Lines are in more than one currency ({', '.join(sorted(currencies))}); they "
                                   f"cannot be summed without an approved translation.", "SD-005"))
    return tb

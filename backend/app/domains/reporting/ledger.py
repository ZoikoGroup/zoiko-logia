"""Typed ledger input (ZL-RPT-007 §6.1 steps 02–03).

Amounts arrive as decimal strings and stay Decimal. A JSON number, a blank or
a missing amount is rejected rather than coerced — a missing receivable must
never become zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")
DEBIT_NORMAL = frozenset({"asset", "expense"})


class LedgerError(ValueError):
    """Input that cannot be trusted as source truth. Carries a stable code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    type: str
    is_cash: bool = False


@dataclass(frozen=True)
class JournalLine:
    account: str
    debit: Decimal
    credit: Decimal

    @property
    def net_debit(self) -> Decimal:
        return self.debit - self.credit


@dataclass(frozen=True)
class Journal:
    source_id: str
    version: int
    posted_on: date
    description: str
    lines: tuple[JournalLine, ...]
    reverses: str | None = None


def parse_amount(value: object, where: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError("amount_invalid", f"{where}: amount must be a non-empty decimal string, got {value!r}")
    try:
        amount = Decimal(value.strip())
    except InvalidOperation:
        raise LedgerError("amount_invalid", f"{where}: {value!r} is not a decimal") from None
    if not amount.is_finite():
        raise LedgerError("amount_invalid", f"{where}: {value!r} is not finite")
    if amount < 0:
        raise LedgerError("sign_invalid", f"{where}: debit/credit amounts are non-negative; use the other side")
    return amount


def parse_accounts(raw: list[dict]) -> dict[str, Account]:
    accounts: dict[str, Account] = {}
    for item in raw:
        code = str(item.get("code", "")).strip()
        if not code:
            raise LedgerError("account_invalid", "account without a code")
        if code in accounts:
            raise LedgerError("account_duplicate", f"account {code} listed twice")
        if item.get("type") not in ACCOUNT_TYPES:
            raise LedgerError("account_invalid", f"account {code}: type must be one of {ACCOUNT_TYPES}")
        is_cash = bool(item.get("is_cash", False))
        if is_cash and item["type"] != "asset":
            raise LedgerError("account_invalid", f"account {code}: only an asset can be cash")
        accounts[code] = Account(code=code, name=str(item.get("name", code)), type=item["type"], is_cash=is_cash)
    return accounts


def parse_journal(raw: dict, accounts: dict[str, Account]) -> Journal:
    source_id = str(raw.get("source_id", "")).strip()
    if not source_id:
        raise LedgerError("journal_invalid", "journal without a source_id")
    version = raw.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise LedgerError("journal_invalid", f"{source_id}: version must be a positive integer")
    try:
        posted_on = date.fromisoformat(str(raw.get("posted_on")))
    except ValueError:
        raise LedgerError("journal_invalid", f"{source_id}: posted_on must be YYYY-MM-DD") from None

    lines = []
    for index, line in enumerate(raw.get("lines") or []):
        where = f"{source_id} line {index + 1}"
        code = str(line.get("account", "")).strip()
        if code not in accounts:
            raise LedgerError("account_unknown", f"{where}: account {code!r} is not in the chart of accounts")
        debit = parse_amount(line.get("debit", "0"), where)
        credit = parse_amount(line.get("credit", "0"), where)
        if (debit == 0) == (credit == 0):
            raise LedgerError("sign_invalid", f"{where}: exactly one of debit or credit must be non-zero")
        lines.append(JournalLine(account=code, debit=debit, credit=credit))
    if len(lines) < 2:
        raise LedgerError("journal_invalid", f"{source_id}: a journal needs at least two lines")

    return Journal(
        source_id=source_id, version=version, posted_on=posted_on,
        description=str(raw.get("description", "")), lines=tuple(lines),
        reverses=(str(raw["reverses"]).strip() if raw.get("reverses") else None),
    )

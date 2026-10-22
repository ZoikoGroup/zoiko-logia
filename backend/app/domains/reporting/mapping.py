"""Versioned account map (ZL-RPT-007 §6.2).

Each ledger account maps to exactly one statement line. Several accounts may
share a line; one account may not be split across lines (that needs an
approved allocation basis, which this gate does not support). An unmapped
account is an exception, never a silent "Other".
"""
from __future__ import annotations

from dataclasses import dataclass

from .ledger import Account, LedgerError

CASH_FLOW_CLASSES = ("operating", "investing", "financing", "fx_effect")
SECTIONS = {
    "asset": "assets", "liability": "liabilities", "equity": "equity",
    "revenue": "revenue", "expense": "expenses",
}


@dataclass(frozen=True)
class LineMapping:
    account: str
    line: str                    # stable semantic line ID, e.g. "bs.trade_receivables"
    label: str
    cash_flow: str | None        # how this account's cash counterpart is classified
    equity_movement: str | None  # equity accounts: how a period movement is presented


@dataclass(frozen=True)
class AccountMap:
    version: str
    lines: dict[str, LineMapping]


def parse_account_map(raw: dict) -> AccountMap:
    version = str(raw.get("version", "")).strip()
    if not version:
        raise LedgerError("mapping_invalid", "the account map needs a version")
    lines: dict[str, LineMapping] = {}
    for code, item in (raw.get("accounts") or {}).items():
        line = str(item.get("line", "")).strip()
        if not line:
            raise LedgerError("mapping_invalid", f"account {code}: no statement line")
        cash_flow = item.get("cash_flow")
        if cash_flow is not None and cash_flow not in CASH_FLOW_CLASSES:
            raise LedgerError("mapping_invalid", f"account {code}: cash_flow must be one of {CASH_FLOW_CLASSES}")
        lines[code] = LineMapping(
            account=code, line=line, label=str(item.get("label", line)),
            cash_flow=cash_flow, equity_movement=item.get("equity_movement"),
        )
    return AccountMap(version=version, lines=lines)


def mapping_exceptions(accounts: dict[str, Account], account_map: AccountMap) -> list[dict]:
    """Accounts the compiler cannot place. Each one blocks reconciliation."""
    problems = []
    for code, account in sorted(accounts.items()):
        mapped = account_map.lines.get(code)
        if mapped is None:
            problems.append({"code": "account_unmapped", "account": code,
                             "detail": f"{account.name} has no approved statement line"})
            continue
        prefix = "bs." if account.type in ("asset", "liability", "equity") else "pl."
        if not mapped.line.startswith(prefix):
            problems.append({"code": "mapping_section_mismatch", "account": code,
                             "detail": f"a {account.type} account cannot map to {mapped.line}"})
        if not account.is_cash and mapped.cash_flow is None:
            problems.append({"code": "cash_flow_class_missing", "account": code,
                             "detail": f"{account.name} needs a cash-flow classification"})
    return problems

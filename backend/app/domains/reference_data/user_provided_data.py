"""Governed evidence and deterministic presentation for values in a query."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

USER_PROVIDED_DATA_GOVERNED_SOURCE_ID = "src-kriton-user-provided-data"
USER_PROVIDED_DATA_NODE_PREFIX = "user-provided-data-"
_NUMBER = r"[$£€]?\s*(\d(?:\d|,(?=\d))*(?:\.\d+)?)"
_PERIOD = r"(Q[1-4]|January|February|March|April|May|June|July|August|September|October|November|December)"
_PERIOD_RESULTS = re.compile(rf"\b{_PERIOD}\b[^.;]*?revenue\s*{_NUMBER}[^.;]*?expenses?\s*{_NUMBER}", re.I)
_BUDGET_ACTUAL = re.compile(rf"\b([A-Za-z][A-Za-z &/-]*?)\s+budget\s*{_NUMBER}\s*(?:and|,)?\s*actual\s*{_NUMBER}", re.I)
_BALANCE = re.compile(rf"\b(cash|(?:accounts?\s+)?receivables?|inventory)\s*(?:balance\s*)?{_NUMBER}", re.I)
_CATEGORY_VALUE = re.compile(
    rf"(?:^|[:,;]|\band\b)\s*([A-Za-z][A-Za-z &/-]{{0,40}}?)\s+{_NUMBER}", re.I
)


@dataclass(frozen=True)
class UserDataTable:
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str | Decimal, ...], ...]
    explanation: str = ""


def _decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def _label(raw: str) -> str:
    value = re.sub(r"^and\s+", "", raw.strip(), flags=re.I)
    return " ".join(value.split()).title()


def extract_user_data_table(query: str) -> UserDataTable | None:
    """Recognise supported multi-value datasets without guessing any value."""
    period_rows = []
    for period, revenue, expenses in _PERIOD_RESULTS.findall(query):
        revenue_value, expense_value = _decimal(revenue), _decimal(expenses)
        period_rows.append((period.upper() if period.upper().startswith("Q") else period.title(), revenue_value, expense_value, revenue_value - expense_value))
    if period_rows:
        period_kind = "Quarterly" if all(str(row[0]).startswith("Q") for row in period_rows) else "Monthly"
        return UserDataTable(f"{period_kind} revenue, expenses, and profit", ("Period", "Revenue", "Expenses", "Profit"), tuple(period_rows), "Profit is calculated deterministically as revenue minus expenses for each period.")

    budget_rows = []
    for category, budget, actual in _BUDGET_ACTUAL.findall(query):
        budget_value, actual_value = _decimal(budget), _decimal(actual)
        budget_rows.append((_label(category), budget_value, actual_value, actual_value - budget_value))
    if budget_rows:
        return UserDataTable("Budget versus actual expenses", ("Category", "Budget", "Actual", "Variance"), tuple(budget_rows), "Variance is actual minus budget; a positive value is over budget.")

    balance_rows = tuple((_label(name), _decimal(value)) for name, value in _BALANCE.findall(query))
    if len(balance_rows) >= 2:
        return UserDataTable("Balance comparison", ("Account", "Balance"), balance_rows, "These are the balances supplied in the request.")

    category_rows = tuple((_label(name), _decimal(value)) for name, value in _CATEGORY_VALUE.findall(query))
    if len(category_rows) >= 2:
        return UserDataTable("Category comparison", ("Category", "Amount"), category_rows, "These are the amounts supplied in the request.")
    return None


def extract_quarterly_results(query: str) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    table = extract_user_data_table(query)
    if table is None or not table.title.startswith("Quarterly"):
        return []
    return [tuple(row) for row in table.rows]  # type: ignore[list-item]


def _money(value: Decimal) -> str:
    absolute = abs(value)
    formatted = f"${absolute:,.2f}" if absolute % 1 else f"${absolute:,.0f}"
    return f"-{formatted}" if value < 0 else formatted


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'))}%"


def _professional_analysis(table: UserDataTable, ref: str | None = None) -> list[str]:
    """Return accounting-focused insights calculated only from table values."""
    cite = f" [{ref}]" if ref else ""
    rows = table.rows
    if table.headers == ("Period", "Revenue", "Expenses", "Profit"):
        total_revenue = sum((row[1] for row in rows), Decimal(0))
        total_expenses = sum((row[2] for row in rows), Decimal(0))
        total_profit = sum((row[3] for row in rows), Decimal(0))
        overall_margin = total_profit / total_revenue * 100 if total_revenue else Decimal(0)
        first_profit, last_profit = rows[0][3], rows[-1][3]
        profit_change = (last_profit - first_profit) / abs(first_profit) * 100 if first_profit else None
        first_margin = first_profit / rows[0][1] * 100 if rows[0][1] else Decimal(0)
        last_margin = last_profit / rows[-1][1] * 100 if rows[-1][1] else Decimal(0)
        direction = "increased" if last_profit >= first_profit else "decreased"
        change_display = _percent(abs(profit_change)) if profit_change is not None else ""
        article = "an" if re.match(r"^(?:8|11|18)", change_display) else "a"
        headline = (
            f"**Key insight:** Profit {direction} from {_money(first_profit)} in {rows[0][0]} "
            f"to {_money(last_profit)} in {rows[-1][0]}"
            + (f", {article} {change_display} change" if profit_change is not None else "")
            + f".{cite}"
        )
        return [
            headline,
            f"- **Total revenue:** {_money(total_revenue)}{cite}",
            f"- **Total expenses:** {_money(total_expenses)}{cite}",
            f"- **Total profit:** {_money(total_profit)}{cite}",
            f"- **Overall profit margin:** {_percent(overall_margin)}{cite}",
            f"- **Margin movement:** {_percent(first_margin)} in {rows[0][0]} to {_percent(last_margin)} in {rows[-1][0]}.{cite}",
        ]
    if table.headers == ("Category", "Budget", "Actual", "Variance"):
        total_budget = sum((row[1] for row in rows), Decimal(0))
        total_actual = sum((row[2] for row in rows), Decimal(0))
        net_variance = total_actual - total_budget
        largest = max(rows, key=lambda row: abs(row[3]))
        status = "over" if net_variance > 0 else "under" if net_variance < 0 else "on"
        return [
            f"**Key insight:** Overall spending is {_money(abs(net_variance))} {status} budget.{cite}",
            f"- **Total budget:** {_money(total_budget)}{cite}",
            f"- **Total actual:** {_money(total_actual)}{cite}",
            f"- **Largest category variance:** {largest[0]} at {_money(largest[3])}.{cite}",
        ]
    if table.headers in {("Account", "Balance"), ("Category", "Amount")}:
        total = sum((row[1] for row in rows), Decimal(0))
        largest = max(rows, key=lambda row: row[1])
        share = largest[1] / total * 100 if total else Decimal(0)
        return [
            f"**Key insight:** {largest[0]} is the largest item at {_money(largest[1])}, representing {_percent(share)} of the displayed total.{cite}",
            f"- **Displayed total:** {_money(total)}{cite}",
        ]
    return []


def compose_user_provided_results(query: str, ref: str) -> str | None:
    table = extract_user_data_table(query)
    if table is None:
        return None
    analysis = _professional_analysis(table, ref)
    lines = [f"## {table.title}", ""]
    if analysis:
        lines.extend([analysis[0], "", "### Executive summary", "", *analysis[1:], ""])
    lines.extend([table.explanation, "", "| " + " | ".join(table.headers) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(table.headers))) + "|"])
    for row in table.rows:
        cells = [str(row[0])]
        cells.extend(f"{_money(value)} [{ref}]" if isinstance(value, Decimal) else str(value) for value in row[1:])
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def compose_quarterly_results(query: str, ref: str) -> str | None:
    """Compatibility alias; now supports all reviewed user-data layouts."""
    return compose_user_provided_results(query, ref)


def to_user_provided_data_rag_chunk(query: str) -> dict:
    table = extract_user_data_table(query)
    verified = ""
    if table is not None:
        if table.headers == ("Period", "Revenue", "Expenses", "Profit"):
            verified = "\n".join(
                f"Verified arithmetic for {row[0]}: {_money(row[1])} - {_money(row[2])} = {_money(row[3])}."
                for row in table.rows
            )
        elif table.headers == ("Category", "Budget", "Actual", "Variance"):
            verified = "\n".join(
                f"Verified arithmetic for {row[0]}: {_money(row[2])} - {_money(row[1])} = {_money(row[3])}."
                for row in table.rows
            )
        else:
            verified = "\n".join("Verified row: " + ", ".join(str(value) if not isinstance(value, Decimal) else _money(value) for value in row) for row in table.rows)
        analysis = _professional_analysis(table)
        if analysis:
            verified += "\n\nVerified derived summary:\n" + "\n".join(analysis)
    return {
        "text": "User-provided data for the current request. Treat only the values explicitly written below as inputs; do not add or infer missing values.\n\n" + query + "\n\n" + verified,
        "metadata": {"source_id": USER_PROVIDED_DATA_GOVERNED_SOURCE_ID, "title": "Data supplied by the user in this request", "version": "current-request", "jurisdiction": "GLOBAL", "mandatory_source": True},
        "score": 1.0,
        "node_id": f"{USER_PROVIDED_DATA_NODE_PREFIX}current",
    }

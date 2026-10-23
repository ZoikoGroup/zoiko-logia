"""Verified figures computed from the tables in attached documents.

A financial statement or analysis of an uploaded file needs figures the file
does not state: column totals, totals per customer or category, a group's
share, the top three customers together, counts by status, a margin. Left
to the model, those are computed in its head, and gate G4
(figure_reconciliation.py) rightly rejects them as unverifiable, sending the
answer to human review. This module computes them deterministically and
states them, so the model can use them and the unchanged gate can confirm
them against the evidence.

Tables are read from every attached file type:
  xlsx / csv / docx / pptx   tab-separated rows, as the extractors write them
  scanned pdf                tab-separated rows, as the OCR reader writes them
  pdf                        consecutive text lines of a label followed by
                             the same count of numbers ("Software 1,199,000 588,000")

Messy tables are tolerated: title and "key: value" rows above the header,
section rows inside a table, a sheet split into ranges without a repeated
header, the overlap between split chunks, formula cells, "-" for zero,
currency codes, and rate / % columns (averaged, never summed).

Only deterministic arithmetic over the documents' own numbers; nothing is
estimated. Rows labelled Total / Subtotal are skipped so a sheet's own totals
are not counted twice. The output is bounded.
"""
from __future__ import annotations

import math
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

from app.orchestration.websearch import WebSource

MAX_LINES = 260
MAX_NUMERIC_COLUMNS = 6
MAX_CATEGORY_COLUMNS = 8
# Category columns most worth grouping by come first, in this order.
_CATEGORY_PRIORITY = (
    re.compile(r"customer|client", re.IGNORECASE),
    re.compile(r"product|category|service|item", re.IGNORECASE),
    re.compile(r"region|segment|department|vendor|supplier|country|branch|account", re.IGNORECASE),
    re.compile(r"status|type|month|quarter|period", re.IGNORECASE),
)
_NOT_CATEGORY = re.compile(r"\b(id|code|date|email|phone|address|description|notes?)\b|_id$|_date$", re.IGNORECASE)
_DATE_LIKE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")
MAX_GROUPS_LISTED = 12
TOP_N = (2, 3, 4, 5, 10)
# Two column totals are compared (share, difference) only when they are of a
# like size: revenue against cost, not revenue against a headcount.
MIN_COMPARABLE_RATIO = 0.05

_DOC_TITLE = re.compile(r"^(?P<file>.*?)\s+—\s+.+$")
_TOTAL_ROW = re.compile(r"^\s*(grand\s+)?(sub)?total\b|^\s*sum\b", re.IGNORECASE)
_NUM = re.compile(r"^\(?-?[£$€₹¥]?\d[\d,]*(?:\.\d+)?\)?%?-?$")
_PDF_ROW = re.compile(r"^(?P<label>[A-Za-z][^\d£$€₹¥()]*?)\s+(?P<values>(?:\(?-?[£$€₹¥]?\d[\d,]*(?:\.\d+)?\)?%?\s*){1,12})$")
# A spreadsheet formula cell as the extractor writes it: "=C2-D2 => 138000".
_FORMULA = re.compile(r"^=.*=>\s*(?P<value>.*)$")
_CURRENCY_CODE = re.compile(
    r"^(?:USD|GBP|EUR|INR|AED|SGD|AUD|CAD|Rs\.?|US\$)\s*|\s*(?:USD|GBP|EUR|INR|AED|SGD|AUD|CAD)$", re.IGNORECASE)
# Accounting notation for zero.
_ZERO = {"-", "–", "—", "nil"}
# Rates and percentages are averaged, never summed.
_RATE_HEADER = re.compile(r"%|percent|\brate\b|ratio", re.IGNORECASE)
# A fixed-asset register: cost and useful life give the straight-line charge
# (cost ÷ life) that a depreciation journal needs and the register does not
# state. A useful life is averaged like a rate, never summed.
_LIFE_HEADER = re.compile(r"useful[\s_-]*life|\blife[\s_-]*(?:in[\s_-]*)?(?:years?|yrs)\b|^life$", re.IGNORECASE)
_COST_HEADER = re.compile(r"(?:^|[\s_])(?:gross[\s_]*|original[\s_]*|acquisition[\s_]*|historical[\s_]*)?cost(?:[\s_]|$)", re.IGNORECASE)
_NOT_COST = re.compile(r"accumulated|depreciat|net|total|book", re.IGNORECASE)
_RESIDUAL_HEADER = re.compile(r"residual|salvage|scrap", re.IGNORECASE)
MAX_ASSETS_LISTED = 40
_YEAR = re.compile(r"^(19|20)\d{2}$")
# A ledger's dated rows give totals per month, which the file never states:
# "Show monthly totals as a bar chart" of a 600-row ledger was refused for
# want of them.
MAX_MONTHS_LISTED = 36
_DATE_PARTS = re.compile(r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})")
_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _to_number(cell: str) -> float | None:
    text = (cell or "").strip()
    formula = _FORMULA.match(text)
    if formula:
        text = formula.group("value").strip()
    if text.lower() in _ZERO:
        return 0.0
    text = re.sub(r"\s", "", _CURRENCY_CODE.sub("", text))
    if not text or not _NUM.match(text):
        return None
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-") or text.endswith("-")
    digits = re.sub(r"[^\d.]", "", text)
    if not digits or digits == ".":
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if negative else value


def _fmt(value: float) -> str:
    text = f"{value:,.2f}"
    return text[:-3] if text.endswith(".00") else text


def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.2f}%" if whole else "n/a"


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)
    key: str = ""               # the document a table belongs to
    sheet: str = ""             # the workbook sheet it came from, when known


def _file_of(source: WebSource) -> str:
    match = _DOC_TITLE.match(source.title or "")
    return match.group("file") if match else (source.title or "document")


# "book.xlsx — 'Bank Statement'!1:16" → "Bank Statement"
_SHEET = re.compile(r"\s+—\s+'?(?P<sheet>[^'!]+?)'?!\S*$")


def _sheet_of(title: str) -> str:
    match = _SHEET.search(title or "")
    return match.group("sheet") if match else ""


def _is_header(cells: list[str], width: int) -> bool:
    """A header row: most columns filled, and no numbers other than years."""
    filled = [c for c in cells if c.strip()]
    return (len(filled) >= max(2, math.ceil(width * 0.6))
            and not any(_to_number(c) is not None and not _YEAR.match(c.strip()) for c in filled))


def _split_block(title: str, key: str, block: list[list[str]]) -> Table | None:
    """A run of tab rows as a table. Title / "key: value" rows above the
    header are dropped. With no header row (a sheet range continuing an
    earlier one), the table is returned with headers [] for the caller to
    attach to the table it continues."""
    width = max(sum(bool(c.strip()) for c in row) for row in block)
    for index, row in enumerate(block):
        if _is_header(row, width):
            if len(block) - index >= 2:
                return Table(title, row, block[index + 1:], key)
            return None
        filled = [c for c in row if c.strip()]
        if len(filled) >= max(2, math.ceil(width * 0.6)) and any(_to_number(c) is not None for c in filled):
            break  # a full data row before any header: a continuation
    return Table(title, [], block, key)


def _tab_tables(title: str, key: str, text: str) -> list[Table]:
    tables, block = [], []
    lines = text.splitlines() + [""]
    for position, line in enumerate(lines):
        if "\t" in line:
            block.append([cell.strip() for cell in line.split("\t")])
            continue
        # A section row inside a table ("North region") has a single cell.
        # Keep the table going when data rows follow it.
        following = lines[position + 1] if position + 1 < len(lines) else ""
        if (len(block) >= 2 and line.strip() and "\t" in following
                and any(_to_number(c) is not None for c in following.split("\t") if c.strip())):
            continue
        if block:
            table = _split_block(title, key, block)
            if table is not None:
                tables.append(table)
        block = []
    return tables


def _pdf_tables(title: str, key: str, text: str) -> list[Table]:
    """Runs of >= 3 lines that are a label followed by the same count of
    numbers. The line before a run, or a first row of years, names the columns."""
    tables, run, width, previous = [], [], None, ""
    for line in text.splitlines() + [""]:
        line = line.strip()
        match = _PDF_ROW.match(line)
        values = match.group("values").split() if match else []
        if match and (width is None or len(values) == width):
            if not run:
                header_line = previous
            width = len(values)
            run.append([match.group("label").strip(), *values])
            continue
        if len(run) >= 3:
            tables.append(_pdf_table(title, key, header_line, run, width))
        if match:
            header_line, run, width = previous, [[match.group("label").strip(), *values]], len(values)
        else:
            run, width = [], None
        previous = line
    return tables


def _pdf_table(title: str, key: str, header_line: str, run: list[list[str]], width: int) -> Table:
    headers = ["Item", *(f"Column {i}" for i in range(1, width + 1))]
    if all(_YEAR.match(v) for v in run[0][1:]) and not all(_YEAR.match(v) for v in run[1][1:]):
        return Table(title, run[0], run[1:], key)              # "Item 2024 2025"
    tokens = header_line.split()
    # Only a line of capitalised words names the columns ("Product Revenue Cost"),
    # not a sentence ("Revenue by product").
    if tokens and all(t[0].isupper() or t[0].isdigit() for t in tokens):
        if len(tokens) == width + 1:
            headers = tokens
        elif len(tokens) == width:
            headers = ["Item", *tokens]
    return Table(title, headers, run, key)


def _join_split_chunks(sources: list[WebSource]) -> list[tuple[str, str, str, str]]:
    """(file, document key, text, block title) per extracted block. A long block is stored
    as several chunks with the same location that overlap by a few hundred
    characters; they are joined back without the overlap, so no row is
    counted twice."""
    joined: list[list[str]] = []
    for source in sources:
        title, text = source.title or "", source.snippet or ""
        if joined and joined[-1][0] == title and joined[-1][3] == (source.source_id or ""):
            previous = joined[-1][2]
            overlap = next((k for k in range(min(len(previous), len(text), 600), 19, -1)
                            if previous.endswith(text[:k])), 0)
            joined[-1][2] = previous + ("" if overlap else "\n") + text[overlap:]
        else:
            joined.append([title, _file_of(source), text, source.source_id or ""])
    return [(file, f"{sid}:{file}", text, title) for title, file, text, sid in joined]


def tables_from_sources(sources: list[WebSource]) -> list[Table]:
    """Every table in the attached documents. A sheet split into several
    extracted ranges is merged back into one table: by its repeated header,
    or, for a range with no header row, onto the table it continues. The
    header the extractor repeats in each range is dropped."""
    merged: "OrderedDict[tuple, Table]" = OrderedDict()
    last: dict[str, Table] = {}
    # Keep each document's chunks together, in their original order.
    order = {key: n for n, key in enumerate(dict.fromkeys(f"{s.source_id or ''}:{_file_of(s)}" for s in sources))}
    ordered = sorted(sources, key=lambda s: order[f"{s.source_id or ''}:{_file_of(s)}"])
    for file, key, text, block_title in _join_split_chunks(ordered):
        sheet = _sheet_of(block_title)
        found = _tab_tables(file, key, text) or _pdf_tables(file, key, text)
        for table in found:
            if not table.headers:
                previous = last.get(key)
                if previous is not None:
                    previous.rows.extend(table.rows)
                continue
            # Two sheets with the same columns (a bank statement and a cash
            # book) are different tables; ranges of one sheet still merge.
            merge_key = (key, sheet, tuple(h.lower() for h in table.headers))
            target = merged.setdefault(merge_key, Table(table.title, table.headers, key=key, sheet=sheet))
            target.rows.extend(r for r in table.rows if [c.lower() for c in r] != list(merge_key[2]))
            last[key] = target
    return list(merged.values())


def _columns(table: Table) -> tuple[list[int], list[int], set[int]]:
    """(numeric column indexes, category column indexes, rate columns)."""
    numeric, category, rates = [], [], set()
    for i, header in enumerate(table.headers):
        cells = [row[i] for row in table.rows if i < len(row) and row[i].strip()]
        if not cells:
            continue
        numbers = [_to_number(c) for c in cells]
        share_numeric = sum(n is not None for n in numbers) / len(cells)
        distinct = len(set(cells))
        # "account_code" is a code, not an amount: \b alone missed it after "_".
        if (share_numeric >= 0.8 and any(numbers) and not re.search(r"(?:\b|_)(id|year|no|number|code|date)(?:\b|_)", header, re.IGNORECASE)):
            numeric.append(i)
            if (_RATE_HEADER.search(header) or _LIFE_HEADER.search(header)
                    or sum(c.strip().endswith("%") for c in cells) >= len(cells) / 2):
                rates.add(i)
        elif (share_numeric < 0.2 and 1 < distinct <= 50 and not _NOT_CATEGORY.search(header)
              and not all(_DATE_LIKE.match(c) for c in cells)):
            # Unique values are allowed: one row per customer still ranks
            # customers ("top 3 customers").
            category.append(i)
    def priority(i: int) -> tuple[int, int]:
        header = table.headers[i] or ""
        rank = next((n for n, pattern in enumerate(_CATEGORY_PRIORITY) if pattern.search(header)), len(_CATEGORY_PRIORITY))
        return rank, len({row[i] for row in table.rows if i < len(row)})

    category.sort(key=priority)
    return numeric[:MAX_NUMERIC_COLUMNS], category[:MAX_CATEGORY_COLUMNS], rates


def _straight_line_depreciation(table: Table, numeric: list[int], category: list[int]) -> list[str]:
    """The annual straight-line charge (cost ÷ useful life) per asset, per
    category and in total, when the table has a cost and a useful-life column."""
    cost = next((i for i in numeric if _COST_HEADER.search(table.headers[i] or "")
                 and not _NOT_COST.search(table.headers[i] or "")), None)
    life = next((i for i in numeric if _LIFE_HEADER.search(table.headers[i] or "")), None)
    if cost is None or life is None:
        return []
    # A residual value is not depreciated: Forklift 38,000, residual 4,000,
    # 8 years was charged 4,750 instead of 4,250.
    residual = next((i for i in numeric if _RESIDUAL_HEADER.search(table.headers[i] or "")), None)
    charges: list[tuple[str, str, float]] = []
    for row in table.rows:
        amount = _to_number(row[cost]) if cost < len(row) else None
        years = _to_number(row[life]) if life < len(row) else None
        if amount is None or not years or years <= 0:
            continue
        kept = (_to_number(row[residual]) if residual is not None and residual < len(row) else None) or 0.0
        group = row[category[0]].strip() if category and category[0] < len(row) else ""
        charges.append(((row[0] or "").strip(), group, round((amount - kept) / years, 2)))
    if not charges:
        return []
    total = round(sum(c for _, _, c in charges), 2)
    basis = (f"({table.headers[cost]} − {table.headers[residual]}) ÷ {table.headers[life]}" if residual is not None
             else f"{table.headers[cost]} ÷ {table.headers[life]}; no residual value")
    lines = [f"- Annual straight-line depreciation ({basis}; "
             f"a full year's charge): total = {_fmt(total)} for {len(charges)} assets"]
    if category:
        groups: dict[str, float] = defaultdict(float)
        for _, group, charge in charges:
            groups[group] += charge
        lines.append(f"- Annual depreciation by {table.headers[category[0]]}: " + "; ".join(
            f"{g} = {_fmt(round(v, 2))}" for g, v in sorted(groups.items(), key=lambda x: -x[1])))
    lines.append("- Annual depreciation per asset: " + "; ".join(
        f"{label} = {_fmt(charge)}" for label, _, charge in charges[:MAX_ASSETS_LISTED]))
    return lines


def _month_of(cell: str) -> tuple[int, int] | None:
    """(year, month) of a date cell: 2026-01-31, 31/01/2026 (day first, as in
    UK ledgers) or 01/31/2026 (when the second part cannot be a month)."""
    match = _DATE_PARTS.match((cell or "").strip())
    if not match:
        return None
    a, b, c = (int(part) for part in match.groups())
    if len(match.group(1)) == 4:
        year, month = a, b
    elif len(match.group(3)) == 4:
        year, month = c, (a if b > 12 else b)
    else:
        return None
    return (year, month) if 1 <= month <= 12 else None


def _date_column(table: Table) -> int | None:
    for i, header in enumerate(table.headers):
        cells = [row[i] for row in table.rows if i < len(row) and row[i].strip()]
        if cells and sum(_month_of(c) is not None for c in cells) / len(cells) >= 0.8:
            return i
    return None


def _months(table: Table, date_col: int) -> list[tuple[int, int]]:
    """The table's calendar months in date order, or [] when too few or too many."""
    months = sorted({m for m in (_month_of(r[date_col]) for r in table.rows if date_col < len(r)) if m})
    return months if 2 <= len(months) <= MAX_MONTHS_LISTED else []


def _month_label(month: tuple[int, int]) -> str:
    return f"{_MONTH_NAMES[month[1] - 1]} {month[0]}"


def _monthly_lines(table: Table, totals: dict[int, float], category: list[int] | None = None,
                   by_group: bool = False) -> list[str]:
    """Totals per calendar month, in date order, from the table's date column.
    With by_group, also per value of the leading category column: a ledger's
    Credit by month mixes every account, so "monthly revenue" needs the
    Revenue account's own months."""
    name = lambda i: table.headers[i] or f"Column {i + 1}"  # noqa: E731
    date_col = _date_column(table)
    if date_col is None:
        return []
    months = _months(table, date_col)
    if not months:
        return []
    label = _month_label
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for r in table.rows:
        month = _month_of(r[date_col]) if date_col < len(r) else None
        if month:
            counts[month] += 1
    lines = [f"- Rows by month (from {name(date_col)}): " + "; ".join(f"{label(m)} = {counts[m]}" for m in months)]
    for i in list(totals)[:3]:
        groups: dict[tuple[int, int], float] = defaultdict(float)
        for r in table.rows:
            month = _month_of(r[date_col]) if date_col < len(r) else None
            value = _to_number(r[i]) if i < len(r) else None
            if month and value is not None:
                groups[month] += value
        lines.append(f"- {name(i)} by month (from {name(date_col)}): " + "; ".join(
            f"{label(m)} = {_fmt(round(groups[m], 2))}" for m in months))
    if not (by_group and category):
        return lines
    c = category[0]
    values = list(dict.fromkeys(r[c].strip() for r in table.rows if c < len(r) and r[c].strip()))
    if not 2 <= len(values) <= MAX_GROUPS_LISTED:
        return lines
    for value in values:
        for i in list(totals)[:3]:
            per_month: dict[tuple[int, int], float] = defaultdict(float)
            for r in table.rows:
                month = _month_of(r[date_col]) if date_col < len(r) else None
                amount = _to_number(r[i]) if i < len(r) else None
                if month and amount is not None and c < len(r) and r[c].strip() == value:
                    per_month[month] += amount
            if any(per_month.values()):
                lines.append(f"- {name(i)} by month for {name(c)} = {value} (from {name(date_col)}): " + "; ".join(
                    f"{label(m)} = {_fmt(round(per_month[m], 2))}" for m in months))
    return lines


# A question about months or trends gets the per-group monthly lines; others
# do not, to keep the block within the model's request size.
_MONTHLY_QUESTION = re.compile(r"month|trend|over\s+time|season|period|quarter", re.IGNORECASE)


# "Top N together" lines are about 40% of the block and answer only ranking
# questions; with them, "Show total sales by month as a bar chart" of a
# 40-row sales file went over the model's request-size limit.
_RANKING_QUESTION = re.compile(r"\btop\b|largest|biggest|highest|lowest|smallest|rank|share|concentrat|most|least|"
                               r"major|main|key\s+customers?|pareto|80\s*/\s*20", re.IGNORECASE)


# A dated statement's running balance: "Total Balance = 884,975" was given
# for a bank statement, and its closing balance was never stated, so a bank
# reconciliation started from the wrong row.
_BALANCE_HEADER = re.compile(r"\bbalance\b", re.IGNORECASE)


def _running_balance_column(table: Table) -> int | None:
    if _date_column(table) is None:
        return None
    return next((i for i, h in enumerate(table.headers) if _BALANCE_HEADER.search(h or "")), None)


def _balances(table: Table, column: int) -> list[tuple[list[str], float]]:
    return [(r, v) for r in table.rows if column < len(r) and (v := _to_number(r[column])) is not None]


def _row_label(table: Table, row: list[str]) -> str:
    date_col = _date_column(table)
    text = [c for i, c in enumerate(row) if c.strip() and i != date_col and _to_number(c) is None]
    date = row[date_col] if date_col is not None and date_col < len(row) else ""
    return ", ".join(part for part in (date, text[0] if text else "") if part)


def _running_balance_line(table: Table, column: int) -> str:
    values = _balances(table, column)
    (first, opening), (last, closing) = values[0], values[-1]
    return (f"- {table.headers[column]} is a running balance (never add it up): opening = {_fmt(opening)} "
            f"({_row_label(table, first)}); closing = {_fmt(closing)} ({_row_label(table, last)})")


# "Summarise sales by VAT treatment" of a file of sales and purchases was not
# answered: VAT treatment totals mixed both, and Type totals mixed every
# treatment. A column of 2-4 kinds (Sale / Purchase) gives each kind's own
# breakdown, for the kinds the question names.
MAX_KINDS = 4


def _names_kind(query: str | None, value: str) -> bool:
    if query is None:
        return False     # only for a question that names the kind
    asked = re.findall(r"[a-z]{3,}", query.lower())
    words = re.findall(r"[a-z]{3,}", value.lower())
    return bool(words) and all(any(a == w or a.rstrip("s") == w.rstrip("s") for a in asked) for w in words)


def _kind_lines(rows: list[list[str]], name, category: list[int], keys: list[int], query: str | None) -> list[str]:
    lines = []
    for split in category:
        kinds = list(dict.fromkeys(r[split].strip() for r in rows if split < len(r) and r[split].strip()))
        if not 2 <= len(kinds) <= MAX_KINDS:
            continue
        for kind in (k for k in kinds if _names_kind(query, k)):
            subset = [r for r in rows if split < len(r) and r[split].strip() == kind]
            for c in (c for c in category if c != split):
                for i in keys[:2]:
                    groups: dict[str, float] = defaultdict(float)
                    for r in subset:
                        value = _to_number(r[i]) if i < len(r) else None
                        if value is not None and c < len(r) and r[c].strip():
                            groups[r[c].strip()] += value
                    if len(groups) < 2 or len(groups) == len(subset):   # one row each: an invoice number
                        continue
                    total = sum(groups.values())
                    lines.append(f"- {name(i)} by {name(c)} for {name(split)} = {kind} (total {_fmt(round(total, 2))}): "
                                 + "; ".join(f"{k} = {_fmt(round(v, 2))} ({_pct(v, total)})" for k, v in
                                             sorted(groups.items(), key=lambda x: -x[1])[:MAX_GROUPS_LISTED]))
    return lines


def _table_lines(table: Table, include_top_n: bool = True, by_month_group: bool = True,
                 query: str | None = None) -> list[str]:
    # The label is the first filled cell: a trial balance's Total row has an
    # empty account code before it, and was counted as an account (50%).
    rows = [r for r in table.rows if not _TOTAL_ROW.match(next((c for c in r if c.strip()), ""))]
    if not rows:
        return []
    table = Table(table.title, table.headers, rows, table.key, table.sheet)
    numeric, category, rates = _columns(table)
    if not numeric:
        return []
    name = lambda i: table.headers[i] or f"Column {i + 1}"  # noqa: E731
    lines = [f"Table '{table.title}' ({', '.join(h for h in table.headers if h)}): {len(rows)} data rows"]
    running = _running_balance_column(table)
    totals: dict[int, float] = {}
    for i in numeric:
        values = [v for v in (_to_number(r[i]) for r in rows if i < len(r)) if v is not None]
        if not values:
            continue
        if i == running:
            lines.append(_running_balance_line(table, i))
            continue
        if i in rates:
            lines.append(f"- {name(i)}: average {_fmt(sum(values) / len(values))}; "
                         f"highest {_fmt(max(values))}; lowest {_fmt(min(values))}")
            continue
        totals[i] = sum(values)
        lines.append(f"- Total {name(i)} = {_fmt(totals[i])}; average {_fmt(totals[i] / len(values))}; "
                     f"highest {_fmt(max(values))}; lowest {_fmt(min(values))}")
    lines.extend(_straight_line_depreciation(table, numeric, category))
    lines.extend(_monthly_lines(table, totals, category, by_month_group))
    keys = list(totals)
    for a in keys:
        for b in keys:
            big, small = max(abs(totals[a]), abs(totals[b])), min(abs(totals[a]), abs(totals[b]))
            if a != b and totals[a] and big and small / big >= MIN_COMPARABLE_RATIO:
                lines.append(f"- {name(b)} as a share of {name(a)} = {_pct(totals[b], totals[a])}; "
                             f"{name(a)} minus {name(b)} = {_fmt(totals[a] - totals[b])}")
    for c in category:
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            if c < len(r) and r[c].strip():
                counts[r[c].strip()] += 1
        if any(v > 1 for v in counts.values()):  # a count of 1 per value says nothing
            lines.append(f"- Rows by {name(c)}: " + "; ".join(f"{k} = {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])[:MAX_GROUPS_LISTED]))
        for i in keys[:3]:
            groups: dict[str, float] = defaultdict(float)
            for r in rows:
                value = _to_number(r[i]) if i < len(r) else None
                if value is not None and c < len(r) and r[c].strip():
                    groups[r[c].strip()] += value
            ranked = sorted(groups.items(), key=lambda x: -x[1])
            if len(ranked) < 2:
                continue
            total = totals[i]
            lines.append(f"- {name(i)} by {name(c)}: " + "; ".join(
                f"{k} = {_fmt(v)} ({_pct(v, total)})" for k, v in ranked[:MAX_GROUPS_LISTED]))
            running = 0.0
            for n, (_, v) in enumerate(ranked if include_top_n else [], start=1):
                running += v
                if n in TOP_N and n < len(ranked):
                    rest = total - running
                    lines.append(f"- Top {n} {name(c)} by {name(i)} together = {_fmt(running)} ({_pct(running, total)}); "
                                 f"the other {len(ranked) - n} together = {_fmt(rest)} ({_pct(rest, total)})")
    lines.extend(_kind_lines(rows, name, category, keys, query))
    return lines


# A trial balance (account name, debit, credit) gives the primary statements.
# "Prepare the financial statements from this trial balance" was answered
# with revenue and interest in the balance sheet and no profit figures: the
# model classified and summed the accounts itself. Accounts are classified
# here by name and balance side, in this order; one the rules cannot place
# is named, and then no statement totals are given.
_DEBIT_HEADER = re.compile(r"^\s*(?:debit|dr)\b", re.IGNORECASE)
_CREDIT_HEADER = re.compile(r"^\s*(?:credit|cr)\b", re.IGNORECASE)
_NAME_HEADER = re.compile(r"name|account|description|ledger", re.IGNORECASE)
_TB_RULES: tuple[tuple[str, str, re.Pattern], ...] = (
    ("suspense", "any", re.compile(r"suspense", re.I)),
    ("tax_charge", "debit", re.compile(r"tax\s+(?:charge|expense)|income\s+tax\b(?!.*payable)", re.I)),
    ("finance_cost", "debit", re.compile(r"interest|finance\s+(?:cost|charge)|bank\s+charges", re.I)),
    ("cost_of_sales", "debit", re.compile(r"cost\s+of\s+(?:sales|goods)|purchases|direct\s+costs?", re.I)),
    ("revenue", "credit", re.compile(r"revenue|sales|turnover|fee\s+income", re.I)),
    ("other_income", "credit", re.compile(r"income|gain", re.I)),
    ("equity", "credit", re.compile(r"share\s+capital|share\s+premium|retained\s+earnings|reserves?|capital\s+account", re.I)),
    ("non_current_liability", "credit", re.compile(r"deferred\s+tax|long[\s-]term|non[\s-]current|mortgage|debenture|bond|"
                                                   r"repayable\s+(?:in\s+)?20\d\d|after\s+(?:more\s+than\s+)?one\s+year", re.I)),
    ("current_liability", "credit", re.compile(r"payable|accrual|overdraft|vat|paye|provision|deferred\s+income|loan|tax", re.I)),
    ("non_current_asset", "debit", re.compile(r"property|plant|equipment|intangible|goodwill|investment|right[\s-]of[\s-]use|vehicles?|fixtures|machinery|"
                                              r"\bland\b|buildings?|computer|furniture|software\s+licen", re.I)),
    ("current_asset", "debit", re.compile(r"inventor|stock|receivable|debtors|cash|bank|prepayment", re.I)),
    ("operating_expense", "debit", re.compile(r"expense|administrat|distribution|selling|wages|salar|rent|depreciation|amortisation|utilities|marketing|insurance|"
                                              r"pension|national\s+insurance|employer|payroll|staff|fees|professional|legal|audit|accountancy|"
                                              r"consult|office|repairs|maintenance|travel|telephone|postage|subscription|training|cleaning|"
                                              r"advertis|printing|stationery|motor\s+costs|bad\s+debt", re.I)),
)
# Balances on the "wrong" side that reduce their group: accumulated
# depreciation and a doubtful-debt allowance reduce assets, dividends reduce
# equity. A trial balance with them gave no statements at all (unclassified).
_TB_CONTRA: tuple[tuple[str, str, re.Pattern], ...] = (
    ("non_current_asset", "credit", re.compile(r"accumulated\s+(?:depreciation|amortisation)|depreciation\s+provision", re.I)),
    ("current_asset", "credit", re.compile(r"allowance\s+for|doubtful\s+debt|bad\s+debt\s+provision|impairment\s+of\s+receivables", re.I)),
    ("equity", "debit", re.compile(r"dividends?\b|drawings", re.I)),
)
_TB_LABEL = {
    "revenue": "Revenue", "other_income": "Other income", "cost_of_sales": "Cost of sales",
    "operating_expense": "Operating expenses", "finance_cost": "Finance costs", "tax_charge": "Tax charge",
    "non_current_asset": "Non-current assets", "current_asset": "Current assets",
    "current_liability": "Current liabilities", "non_current_liability": "Non-current liabilities", "equity": "Equity",
}


# Income and expense groups of a ledger's monthly statement, with the side
# that increases them.
_PL_GROUPS = (("revenue", "credit"), ("other_income", "credit"), ("cost_of_sales", "debit"),
              ("operating_expense", "debit"), ("finance_cost", "debit"), ("tax_charge", "debit"))


def _ledger_monthly_lines(table: Table, debit: int, credit: int, name: int) -> list[str]:
    """A general ledger (dated debit / credit lines, many per account) gives
    income and expenses per month. Each account is classified by name, on
    either side: a ledger posts both sides of an account."""
    date_col = _date_column(table)
    if date_col is None:
        return []
    months = _months(table, date_col)
    if not months:
        return []
    side = dict(_PL_GROUPS)
    per_group: dict[str, dict[tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    members: dict[str, list[str]] = defaultdict(list)
    for row in table.rows:
        label = row[name].strip() if name < len(row) else ""
        month = _month_of(row[date_col]) if date_col < len(row) else None
        if not label or not month or _TOTAL_ROW.match(label):
            continue
        group = next((g for g, _, pattern in _TB_RULES if pattern.search(label)), None)
        if group not in side:
            continue
        dr = (_to_number(row[debit]) if debit < len(row) else None) or 0.0
        cr = (_to_number(row[credit]) if credit < len(row) else None) or 0.0
        per_group[group][month] += (cr - dr) if side[group] == "credit" else (dr - cr)
        if label not in members[group]:
            members[group].append(label)
    if not per_group:
        return []
    by_month = lambda values: "; ".join(f"{_month_label(m)} = {_fmt(round(values[m], 2))}" for m in months)  # noqa: E731
    lines = [f"Ledger '{table.title}': income and expenses by month (from {table.headers[date_col]}; "
             f"accounts classified by name; check against the chart of accounts)"]
    for group, _ in _PL_GROUPS:
        if group in per_group:
            lines.append(f"- {_TB_LABEL[group]} by month ({', '.join(members[group])}): {by_month(per_group[group])}")
    income = {m: per_group["revenue"][m] + per_group["other_income"][m] for m in months}
    expenses = {m: sum(per_group[g][m] for g, s in _PL_GROUPS if s == "debit") for m in months}
    if "other_income" in per_group:   # otherwise it repeats Revenue by month
        lines.append(f"- Total income by month: {by_month(income)}")
    lines.append(f"- Total expenses by month: {by_month(expenses)}")
    lines.append(f"- Profit (total income minus total expenses) by month: "
                 f"{by_month({m: income[m] - expenses[m] for m in months})}")
    lines.append(f"- For the whole period: total income = {_fmt(round(sum(income.values()), 2))}; total expenses = "
                 f"{_fmt(round(sum(expenses.values()), 2))}; profit = {_fmt(round(sum(income.values()) - sum(expenses.values()), 2))}")
    return lines


def _trial_balance_lines(table: Table, by_month: bool = True) -> list[str]:
    headers = table.headers
    debit = next((i for i, h in enumerate(headers) if _DEBIT_HEADER.search(h or "")), None)
    credit = next((i for i, h in enumerate(headers) if _CREDIT_HEADER.search(h or "")), None)
    if debit is None or credit is None:
        return []
    name = next((i for i, h in enumerate(headers) if i not in (debit, credit) and _NAME_HEADER.search(h or "")
                 and not re.search(r"code|number|no\b", h or "", re.I)), None)
    if name is None:
        return []
    # A trial balance lists each account once. Repeated accounts make it a
    # ledger: its 252 lines were classified one by one, and "Cash at bank" on
    # the credit side stopped every statement total.
    labels = [row[name].strip() for row in table.rows
              if name < len(row) and row[name].strip() and not _TOTAL_ROW.match(row[name])]
    if labels and len(set(labels)) < len(labels) * 0.8:
        return _ledger_monthly_lines(table, debit, credit, name) if by_month else []
    groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    unplaced, total_dr, total_cr = [], 0.0, 0.0
    for row in table.rows:
        label = row[name].strip() if name < len(row) else ""
        if not label or _TOTAL_ROW.match(label):
            continue
        dr = (_to_number(row[debit]) if debit < len(row) else None) or 0.0
        cr = (_to_number(row[credit]) if credit < len(row) else None) or 0.0
        total_dr, total_cr = total_dr + dr, total_cr + cr
        side, amount = ("debit", dr - cr) if dr >= cr else ("credit", cr - dr)
        contra = next((g for g, s, pattern in _TB_CONTRA if s == side and pattern.search(label)), None)
        if contra is not None:
            groups[contra].append((label, -amount))
            continue
        group = next((g for g, s, pattern in _TB_RULES if (s in (side, "any")) and pattern.search(label)), None)
        if group is None:
            unplaced.append(label)
            continue
        groups[group].append((label, amount))
    lines = [f"Trial balance '{table.title}': total debits = {_fmt(round(total_dr, 2))}; total credits = "
             f"{_fmt(round(total_cr, 2))}; difference = {_fmt(round(total_dr - total_cr, 2))}"]
    if unplaced:
        lines.append("- Accounts not classified (state them, and give no statement totals): " + "; ".join(unplaced))
        return lines
    total = lambda g: round(sum(v for _, v in groups.get(g, [])), 2)  # noqa: E731
    def line(g: str) -> str:
        members = ", ".join(f"{k} {_fmt(v)}" for k, v in groups.get(g, []))
        return f"{_TB_LABEL[g]} = {_fmt(total(g))}" + (f" ({members})" if members else "")
    revenue, gross = total("revenue"), round(total("revenue") - total("cost_of_sales"), 2)
    operating = round(gross + total("other_income") - total("operating_expense"), 2)
    before_tax = round(operating - total("finance_cost"), 2)
    after_tax = round(before_tax - total("tax_charge"), 2)
    lines.append("- Income statement (accounts classified by name; check against the chart of accounts): "
                 + "; ".join([line("revenue"), line("cost_of_sales"), f"Gross profit = {_fmt(gross)}",
                              *([line("other_income")] if groups.get("other_income") else []),
                              line("operating_expense"), f"Operating profit = {_fmt(operating)}",
                              line("finance_cost"), f"Profit before tax = {_fmt(before_tax)}",
                              line("tax_charge"), f"Profit for the year = {_fmt(after_tax)}"]))
    assets = round(total("non_current_asset") + total("current_asset"), 2)
    liabilities = round(total("current_liability") + total("non_current_liability"), 2)
    net_assets = round(assets - liabilities, 2)
    equity_close = round(total("equity") + after_tax, 2)
    lines.append("- Statement of financial position: " + "; ".join([
        line("non_current_asset"), line("current_asset"), f"Total assets = {_fmt(assets)}",
        line("current_liability"), line("non_current_liability"), f"Total liabilities = {_fmt(liabilities)}",
        f"Net assets = {_fmt(net_assets)}", line("equity") + " (before the profit for the year)",
        f"Equity including the profit for the year = {_fmt(equity_close)}"]))
    if revenue:
        lines.append(f"- Gross margin = {_pct(gross, revenue)}; operating margin = {_pct(operating, revenue)}; "
                     f"net margin = {_pct(after_tax, revenue)}")
    if total("current_liability"):
        inventory = sum(v for k, v in groups.get("current_asset", []) if re.search(r"inventor|stock", k, re.I))
        lines.append(f"- Current ratio = {total('current_asset') / total('current_liability'):.2f}; quick ratio = "
                     f"{(total('current_asset') - inventory) / total('current_liability'):.2f}")
    if groups.get("suspense"):
        suspense = total("suspense")
        lines.append(f"- Suspense account balance = {_fmt(suspense)} ({'; '.join(k for k, _ in groups['suspense'])}): "
                     f"unexplained; it must be investigated and cleared before the statements are final. "
                     f"Net assets ({_fmt(net_assets)}) and equity including the profit for the year "
                     f"({_fmt(equity_close)}) differ by {_fmt(round(abs(equity_close - net_assets), 2))}.")
    return lines


# A bank statement and a cash book give a bank reconciliation. Left to the
# model, one was prepared from the wrong closing balance, missed a £1,025
# direct debit, called a cash-book error a bank error, and its steps were
# removed as unverifiable. Lines are matched here by amount and direction.
_BANK_SIDE = re.compile(r"bank\s*statement|statement", re.IGNORECASE)
_BOOK_SIDE = re.compile(r"cash\s*book|cashbook|bank\s*(?:ledger|account)|\bledger\b", re.IGNORECASE)
_PAIR_DAYS = 7
# Words that say what kind of line it is, not whose it is.
_GENERIC_WORDS = {"receipt", "receipts", "payment", "payments", "cheque", "check", "direct", "debit", "credit",
                  "transfer", "bank", "from", "with", "recorded", "shows", "deposit", "deposited", "charges",
                  "interest", "received", "presented", "credited", "standing", "order", "invoice"}


@dataclass
class _Entry:
    when: tuple[int, int, int] | None
    label: str
    amount: float
    inflow: bool


def _day_of(cell: str) -> tuple[int, int, int] | None:
    match = _DATE_PARTS.match((cell or "").strip())
    month = _month_of(cell)
    if not match or not month:
        return None
    a, _, c = (int(part) for part in match.groups())
    day = c if len(match.group(1)) == 4 else (a if int(match.group(2)) <= 12 else int(match.group(2)))
    return (month[0], month[1], day)


def _days_apart(a: tuple[int, int, int] | None, b: tuple[int, int, int] | None) -> int:
    if not a or not b:
        return 0
    from datetime import date
    try:
        return abs((date(*a) - date(*b)).days)
    except ValueError:
        return 0


def _statement(table: Table) -> tuple[list[_Entry], float] | None:
    """A dated table with a running balance: its in / out lines and closing
    balance. Whether a column is money in or out is read from how the
    balance moves, not from its name: a cash book's Debit is money in, a bank
    statement's Debit is money out."""
    balance = _running_balance_column(table)
    date_col = _date_column(table)
    if balance is None or date_col is None:
        return None
    numeric, _, _ = _columns(table)
    amounts = [i for i in numeric if i != balance]
    if len(amounts) != 2:
        return None
    direction: dict[int, int] = defaultdict(int)       # +1 per row the column raised the balance
    previous = None
    for row in table.rows:
        current = _to_number(row[balance]) if balance < len(row) else None
        if current is None:
            continue
        if previous is not None:
            for i in amounts:
                value = _to_number(row[i]) if i < len(row) else None
                if value and abs(abs(current - previous) - value) < 0.005:
                    direction[i] += 1 if current > previous else -1
        previous = current
    inflow = [i for i in amounts if direction[i] > 0]
    outflow = [i for i in amounts if direction[i] < 0]
    if len(inflow) != 1 or len(outflow) != 1:
        return None
    entries = []
    for row in table.rows:
        for i, is_in in ((inflow[0], True), (outflow[0], False)):
            value = _to_number(row[i]) if i < len(row) else None
            if value:
                entries.append(_Entry(_day_of(row[date_col]) if date_col < len(row) else None,
                                      _row_label(table, row), abs(value), is_in))
    return entries, _balances(table, balance)[-1][1]


def _words(label: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", label.lower()) if w not in _GENERIC_WORDS}


def _bank_reconciliation_lines(tables: list[Table]) -> list[str]:
    def side(table: Table, pattern: re.Pattern) -> bool:
        return bool(pattern.search(table.sheet or table.title or ""))
    banks = [t for t in tables if side(t, _BANK_SIDE) and not side(t, _BOOK_SIDE)]
    books = [t for t in tables if side(t, _BOOK_SIDE) and not side(t, _BANK_SIDE)]
    if len(banks) != 1 or len(books) != 1:
        return []
    bank, book = _statement(banks[0]), _statement(books[0])
    if bank is None or book is None:
        return []
    (bank_lines, bank_close), (book_lines, book_close) = bank, book
    # Same amount and direction is the same item; the nearest date wins.
    unmatched_bank = list(bank_lines)
    unmatched_book: list[_Entry] = []
    for entry in book_lines:
        candidates = [b for b in unmatched_bank if b.inflow == entry.inflow and abs(b.amount - entry.amount) < 0.005]
        if candidates:
            unmatched_bank.remove(min(candidates, key=lambda b: _days_apart(b.when, entry.when)))
        else:
            unmatched_book.append(entry)
    # One item at two amounts: same direction, a shared name, close dates.
    errors: list[tuple[_Entry, _Entry]] = []
    for entry in list(unmatched_book):
        pair = next((b for b in unmatched_bank if b.inflow == entry.inflow and _words(b.label) & _words(entry.label)
                     and _days_apart(b.when, entry.when) <= _PAIR_DAYS), None)
        if pair is not None:
            errors.append((entry, pair))
            unmatched_book.remove(entry)
            unmatched_bank.remove(pair)
    item = lambda e: f"{e.label} {_fmt(e.amount)}"  # noqa: E731
    group = lambda entries: "; ".join(item(e) for e in entries) or "none"  # noqa: E731
    book_in = [e for e in unmatched_book if e.inflow]
    book_out = [e for e in unmatched_book if not e.inflow]
    bank_in = [e for e in unmatched_bank if e.inflow]
    bank_out = [e for e in unmatched_bank if not e.inflow]
    # The bank's figure is taken as right; the cash book is corrected.
    correction = round(sum((b.amount - e.amount) * (1 if e.inflow else -1) for e, b in errors), 2)
    adjusted_bank = round(bank_close + sum(e.amount for e in book_in) - sum(e.amount for e in book_out), 2)
    adjusted_book = round(book_close + sum(e.amount for e in bank_in) - sum(e.amount for e in bank_out) + correction, 2)
    name = lambda t: f"'{t.sheet or t.title}'"  # noqa: E731
    lines = [
        f"Bank reconciliation (bank statement {name(banks[0])}, cash book {name(books[0])}; lines matched by amount "
        f"and direction): bank statement closing balance = {_fmt(bank_close)}; cash book closing balance = "
        f"{_fmt(book_close)}; difference = {_fmt(round(book_close - bank_close, 2))}",
        f"- In the cash book, not yet on the bank statement: receipts not yet credited (add to the bank balance): "
        f"{group(book_in)}; payments not yet presented (deduct from the bank balance): {group(book_out)}",
        f"- On the bank statement, not in the cash book: credits (add to the cash book): {group(bank_in)}; "
        f"debits (deduct from the cash book): {group(bank_out)}",
    ]
    if errors:
        lines.append("- Same item at a different amount (the bank figure is taken as correct, so the cash book is "
                     "corrected; check the source document): " + "; ".join(
                         f"{b.label}: cash book {_fmt(e.amount)}, bank {_fmt(b.amount)}, cash book "
                         f"{'understated' if (b.amount - e.amount) * (1 if e.inflow else -1) > 0 else 'overstated'} by "
                         f"{_fmt(abs(round(b.amount - e.amount, 2)))}" for e, b in errors))
    lines.append(f"- Adjusted cash book balance = {_fmt(adjusted_book)}; adjusted bank balance = {_fmt(adjusted_bank)}; "
                 f"unexplained difference = {_fmt(round(adjusted_book - adjusted_bank, 2))}")
    return lines


def verified_document_figures(sources: list[WebSource], query: str | None = None) -> str:
    """A bounded prompt block of figures computed from the documents' tables,
    or "" when the documents hold no numeric table. With a question, the
    "top N together" lines are kept only for a ranking question."""
    include_top_n = query is None or bool(_RANKING_QUESTION.search(query))
    by_month = query is None or bool(_MONTHLY_QUESTION.search(query))
    tables = tables_from_sources(sources)
    lines: list[str] = _bank_reconciliation_lines(tables)
    for table in tables:
        statement = _trial_balance_lines(table, by_month)
        lines.extend(statement)
        # A ledger's monthly income and expenses already cover its accounts'
        # months; repeating them per account pushed a 252-line ledger over
        # the provider's request-size limit.
        ledger = bool(statement) and statement[0].startswith("Ledger ")
        lines.extend(_table_lines(table, include_top_n, by_month and not ledger, query))
        if len(lines) >= MAX_LINES:
            break
    if not lines:
        return ""
    return (
        "\n\n=== Verified figures computed by Kriton from the attached documents ===\n"
        "These are exact sums, shares and differences of the documents' own numbers. "
        "Use these figures; do not compute totals, shares or rankings yourself. "
        "If a figure you need is not here or in the documents, say it is not available.\n"
        + "\n".join(lines[:MAX_LINES])
    )

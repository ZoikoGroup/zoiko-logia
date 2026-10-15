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
_YEAR = re.compile(r"^(19|20)\d{2}$")


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


def _file_of(source: WebSource) -> str:
    match = _DOC_TITLE.match(source.title or "")
    return match.group("file") if match else (source.title or "document")


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


def _join_split_chunks(sources: list[WebSource]) -> list[tuple[str, str, str]]:
    """(file, document key, text) per extracted block. A long block is stored
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
    return [(file, f"{sid}:{file}", text) for _, file, text, sid in joined]


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
    for file, key, text in _join_split_chunks(ordered):
        found = _tab_tables(file, key, text) or _pdf_tables(file, key, text)
        for table in found:
            if not table.headers:
                previous = last.get(key)
                if previous is not None:
                    previous.rows.extend(table.rows)
                continue
            merge_key = (key, tuple(h.lower() for h in table.headers))
            target = merged.setdefault(merge_key, Table(table.title, table.headers, key=key))
            target.rows.extend(r for r in table.rows if [c.lower() for c in r] != list(merge_key[1]))
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
        if (share_numeric >= 0.8 and any(numbers) and not re.search(r"\b(id|year|no|number|code|date)\b", header, re.IGNORECASE)):
            numeric.append(i)
            if _RATE_HEADER.search(header) or sum(c.strip().endswith("%") for c in cells) >= len(cells) / 2:
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


def _table_lines(table: Table) -> list[str]:
    rows = [r for r in table.rows if not (r and _TOTAL_ROW.match(r[0] or ""))]
    if not rows:
        return []
    table = Table(table.title, table.headers, rows)
    numeric, category, rates = _columns(table)
    if not numeric:
        return []
    name = lambda i: table.headers[i] or f"Column {i + 1}"  # noqa: E731
    lines = [f"Table '{table.title}' ({', '.join(h for h in table.headers if h)}): {len(rows)} data rows"]
    totals: dict[int, float] = {}
    for i in numeric:
        values = [v for v in (_to_number(r[i]) for r in rows if i < len(r)) if v is not None]
        if not values:
            continue
        if i in rates:
            lines.append(f"- {name(i)}: average {_fmt(sum(values) / len(values))}; "
                         f"highest {_fmt(max(values))}; lowest {_fmt(min(values))}")
            continue
        totals[i] = sum(values)
        lines.append(f"- Total {name(i)} = {_fmt(totals[i])}; average {_fmt(totals[i] / len(values))}; "
                     f"highest {_fmt(max(values))}; lowest {_fmt(min(values))}")
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
            for n, (_, v) in enumerate(ranked, start=1):
                running += v
                if n in TOP_N and n < len(ranked):
                    rest = total - running
                    lines.append(f"- Top {n} {name(c)} by {name(i)} together = {_fmt(running)} ({_pct(running, total)}); "
                                 f"the other {len(ranked) - n} together = {_fmt(rest)} ({_pct(rest, total)})")
    return lines


def verified_document_figures(sources: list[WebSource]) -> str:
    """A bounded prompt block of figures computed from the documents' tables,
    or "" when the documents hold no numeric table."""
    lines: list[str] = []
    for table in tables_from_sources(sources):
        lines.extend(_table_lines(table))
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

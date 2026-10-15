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
  pdf                        consecutive text lines of a label followed by
                             the same count of numbers ("Software 1,199,000 588,000")

Only deterministic arithmetic over the documents' own numbers; nothing is
estimated. Rows labelled Total / Subtotal are skipped so a sheet's own totals
are not counted twice. The output is bounded.
"""
from __future__ import annotations

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
_NUM = re.compile(r"^\(?-?[£$€₹¥]?\s?\d[\d,]*(?:\.\d+)?\)?%?$")
_PDF_ROW = re.compile(r"^(?P<label>[A-Za-z][^\d£$€₹¥()]*?)\s+(?P<values>(?:\(?-?[£$€₹¥]?\d[\d,]*(?:\.\d+)?\)?%?\s*){1,12})$")


def _to_number(cell: str) -> float | None:
    text = (cell or "").strip().replace(" ", "").replace(" ", "")
    if not text or not _NUM.match(text):
        return None
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-")
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


def _file_of(source: WebSource) -> str:
    match = _DOC_TITLE.match(source.title or "")
    return match.group("file") if match else (source.title or "document")


def _tab_tables(source: WebSource) -> list[Table]:
    tables, block = [], []
    for line in (source.snippet or "").splitlines() + [""]:
        if "\t" in line:
            block.append([cell.strip() for cell in line.split("\t")])
            continue
        if len(block) >= 2:
            tables.append(Table(_file_of(source), block[0], block[1:]))
        block = []
    return tables


def _pdf_tables(source: WebSource) -> list[Table]:
    """Runs of >= 3 lines that are a label followed by the same count of numbers."""
    tables, run, width = [], [], None
    for line in (source.snippet or "").splitlines() + [""]:
        match = _PDF_ROW.match(line.strip())
        values = match.group("values").split() if match else []
        if match and (width is None or len(values) == width):
            width = len(values)
            run.append([match.group("label").strip(), *values])
            continue
        if len(run) >= 3:
            tables.append(Table(_file_of(source), ["Item", *(f"Column {i}" for i in range(1, width + 1))], run))
        run, width = ([[match.group("label").strip(), *values]], len(values)) if match else ([], None)
    return tables


def tables_from_sources(sources: list[WebSource]) -> list[Table]:
    """Every table in the attached documents. A sheet split into several
    extracted ranges (same file, same header) is merged back into one table,
    and the header the extractor repeats in each range is dropped."""
    merged: "OrderedDict[tuple, Table]" = OrderedDict()
    for source in sources:
        found = _tab_tables(source)
        if not found:
            found = _pdf_tables(source)
        for table in found:
            key = (table.title, tuple(h.lower() for h in table.headers))
            target = merged.setdefault(key, Table(table.title, table.headers))
            target.rows.extend(r for r in table.rows if [c.lower() for c in r] != list(key[1]))
    return list(merged.values())


def _columns(table: Table) -> tuple[list[int], list[int]]:
    """(numeric column indexes, category column indexes)."""
    numeric, category = [], []
    for i, header in enumerate(table.headers):
        cells = [row[i] for row in table.rows if i < len(row) and row[i].strip()]
        if not cells:
            continue
        numbers = [_to_number(c) for c in cells]
        share_numeric = sum(n is not None for n in numbers) / len(cells)
        distinct = len(set(cells))
        if share_numeric >= 0.8 and not re.search(r"\b(id|year|no|number|code|date)\b", header, re.IGNORECASE):
            numeric.append(i)
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
    return numeric[:MAX_NUMERIC_COLUMNS], category[:MAX_CATEGORY_COLUMNS]


def _table_lines(table: Table) -> list[str]:
    rows = [r for r in table.rows if not (r and _TOTAL_ROW.match(r[0] or ""))]
    if not rows:
        return []
    table = Table(table.title, table.headers, rows)
    numeric, category = _columns(table)
    if not numeric:
        return []
    name = lambda i: table.headers[i] or f"Column {i + 1}"  # noqa: E731
    lines = [f"Table '{table.title}' ({', '.join(h for h in table.headers if h)}): {len(rows)} data rows"]
    totals: dict[int, float] = {}
    for i in numeric:
        values = [v for v in (_to_number(r[i]) for r in rows if i < len(r)) if v is not None]
        if not values:
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

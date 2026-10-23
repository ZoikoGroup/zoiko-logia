"""Which chart would show an answer's figures best, offered rather than drawn.

An answer with a table of figures (cash flows by year, a cost breakdown,
budget against actual) used to end without any visual unless the question
asked for one. Kriton now picks the chart that fits the data and offers it;
the user decides. Clicking the offer sends "Show this as a <type> chart.",
which supplied_charts.py answers from the same table with this module's
reader, so the chart drawn is exactly the one offered.

Deterministic and conservative: only a table whose chosen column is a number
in every row is offered, figures are read as the answer states them (the
result after "=" or "→" in a worked cell), and nothing is offered for prose,
a single figure, mixed units or mixed currencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# A figure as an answer writes it: "$676,886.75", "−400 000", "(30,000)",
# "26.07 days", "9.00 %". Grouping by commas or by ordinary, no-break, narrow
# no-break or thin spaces (the same set the grader reads).
_NUMBER = re.compile(r"[-−–]?\(?[-−]?\s?(?:[$£€₹¥]\s?)?\d{1,3}(?:[, \u00a0\u202f\u2009]\d{3})+(?:\.\d+)?\)?|[-−–]?\(?[-−]?\s?(?:[$£€₹¥]\s?)?\d+(?:\.\d+)?\)?")
_EMPTY = re.compile(r"^\s*(?:[-–—]|n/?a|nil|—|)\s*$", re.I)
_UNIT_WORDS = r"(?:days?|months?|years?|times|x|×|bbl|units?|shares?|usd|gbp|eur|inr|brl|aud|cad|jpy|per\s+share)"
_PERIOD = re.compile(
    r"^\s*(?:year|yr|fy|q[1-4]|quarter|h[12]|half|month|week|day|period|t)\s*[-‑]?\s*\d{1,4}\b"
    r"|^\s*(?:19|20)\d{2}(?:\s*[-/–]\s*\d{2,4})?\s*$"
    r"|^\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+\d{2,4})?\s*$"
    r"|^\s*\d{1,2}\s*(?:\(.*\))?\s*$", re.I)
_TOTAL_ROW = re.compile(r"^\s*(?:\*\*)?\s*(?:total|sum|grand\s+total|overall)\b", re.I)
_SHARE_WORDS = re.compile(r"\b(?:share|split|mix|allocation|allocated|breakdown|composition|weights?|proportion)\b", re.I)
_JOURNAL = re.compile(r"\b(?:debit|credit|dr|cr|account|accounts|treatment|criteri\w*|rationale)\b", re.I)
_CURRENCY = re.compile(r"[$£€₹¥]|\b(?:USD|GBP|EUR|INR|BRL|AUD|CAD|JPY)\b", re.I)


@dataclass(frozen=True)
class ChartOffer:
    chart_type: str          # line | bar | pie
    title: str
    question: str            # what clicking the offer sends
    reason: str              # why this type fits, shown to the user
    chart: dict              # the chart that question will draw (render_chart shape)


def _bare_number(text: str) -> str | None:
    """The number when the text is one number and units, else None."""
    text = re.sub(r"\(\s*(?:computed|rounded|exact|approx\.?)[^)]*\)", "", text, flags=re.I).strip()
    numbers = _NUMBER.findall(text)
    if len(numbers) != 1:
        return None
    # Anything else must be a unit, not words or a formula.
    rest = text.replace(numbers[0], " ", 1)
    return None if re.sub(rf"\s|%|{_UNIT_WORDS}|[$£€₹¥]", "", rest, flags=re.I) else numbers[0]


_WORD = re.compile(r"[A-Za-z]{3,}")
_UNIT_WORDS = {"times", "year", "years", "month", "months", "days", "items", "units", "usd", "inr", "gbp", "eur",
               "aud", "cad", "per", "share", "shares", "million", "thousand", "lakh", "lakhs", "crore", "crores",
               "approx", "about", "nil", "rounded"}


def _series_name(header: str) -> str:
    """A column's name without its formula or footnote mark: "Deflated
    inventory (base-year cost) = Inventory ÷ Index" is "Deflated inventory
    (base-year cost)"."""
    return re.split(r"\s+=\s+", _clean_label(header))[0].rstrip("*† ").strip()


def _value(cell: str) -> Decimal | None:
    """The figure a table cell states, or None when it states no single one.
    A worked cell states its result as the part that is a bare number:
    "1.44 = 1.20 × 1.20" is 1.44, "1.20 × 1.20 = 1.44" too, and
    "676,886.754138 → 676,886.75" is the rounded 676,886.75 shown last."""
    text = re.sub(r"\*\*|__|`", "", cell or "").strip()
    if _EMPTY.match(text):
        return None
    # A sentence is not a figure, even one ending "= $22,000": "Add layer of
    # $20,000 (base-year cost) → valued at 1.10 → … = $22,000" was offered as
    # a "Layer activity" series (23 Oct 2026). Units ("1.67 times") are fine.
    if len([word for word in _WORD.findall(text) if word.lower() not in _UNIT_WORDS]) > 2:
        return None
    bare = [number for part in re.split(r"=|→|->|≈", text) if (number := _bare_number(part)) is not None]
    if not bare:
        return None
    raw = bare[-1]
    negative = raw.strip().startswith(("-", "−", "–")) or ("(" in raw and ")" in raw)
    digits = re.sub(r"[^\d.]", "", raw)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


# A summary restates figures shown above it, usually of different kinds
# (allocations, revenue, a liability): "Amount by item" charted them as
# comparable bars (23 Oct 2026).
_SUMMARY_HEADING = re.compile(r"\bsummary\b|\bkey\s+(?:figures|results|metrics)\b|\bat\s+a\s+glance\b", re.I)


def _heading_before(text: str, start: int) -> str:
    lines = [line for line in text[:start].splitlines() if line.strip()]
    return " ".join(lines[-2:])


def _tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables = []
    for match in re.finditer(r"(?:^[ \t]*\|[^\n]*\|[ \t]*\n?){3,}", text or "", re.M):
        block = match.group(0)
        if _SUMMARY_HEADING.search(_heading_before(text, match.start())):
            continue
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in block.strip().splitlines()]
        if len(rows) < 4 or not all(re.fullmatch(r"\s*:?-{2,}:?\s*", cell) for cell in rows[1]):
            continue
        header, data = rows[0], [row for row in rows[2:] if len(row) == len(rows[0])]
        if len(header) >= 2 and len(data) >= 2:
            tables.append((header, data))
    return tables


def _unit(header: str, cells: list[str]) -> str:
    sample = header + " " + " ".join(cells)
    if "%" in sample:
        return "percent"
    if re.search(r"\bdays?\b", sample, re.I):
        return "days"
    currency = sorted({match.group(0).upper() for match in _CURRENCY.finditer(sample)})
    if currency:
        return "money:" + "/".join(currency)
    return "number"


def _clean_label(label: str) -> str:
    return re.sub(r"\*\*|__|`", "", label).strip()


def _choose(header: list[str], data: list[list[str]]) -> tuple[str, dict, str] | None:
    """The chart type, chart and reason for one table, or None."""
    # A journal entry or a rule table is not a dataset: debits and credits
    # plotted as bars mean nothing.
    if any(_JOURNAL.search(cell) for cell in header):
        return None
    columns = list(zip(*data))
    numeric = {}
    for index in range(len(header)):
        values = [_value(cell) for cell in columns[index]]
        stated = [value for value in values if value is not None]
        unstated = [cell for cell, value in zip(columns[index], values) if value is None and not _EMPTY.match(cell)]
        # Money beside plain counts in one column is not one measure: "$870,750",
        # "420,000" shares and "$2.07" EPS were offered as one bar series.
        money = {bool(_CURRENCY.search(cell)) for cell, value in zip(columns[index], values) if value is not None}
        if len(stated) >= 2 and not unstated and len(money) == 1:
            numeric[index] = values
    labels_at = next((index for index in range(len(header)) if index not in numeric), None)
    if labels_at is None and len(numeric) >= 2:
        # Every column is a number: the first one labels the rows ("| 1 |
        # 3,500,000 | 5.17 | 676,886.75 |" is Year 1).
        labels_at = 0
        numeric.pop(0)
    if labels_at is None or not numeric:
        return None
    categories = [_clean_label(cell) for cell in columns[labels_at]]
    if len(set(categories)) != len(categories):
        return None
    # The result columns come last in a worked table.
    primary = max(numeric)
    primary_unit = _unit(header[primary], list(columns[primary]))
    if primary_unit.startswith("money:") and "/" in primary_unit:
        return None
    # Plotted together only when measured in the same unit (budget and actual,
    # 2025 and 2026); a rate column beside an amount column is left out.
    chosen = [index for index in sorted(numeric)
              if _unit(header[index], list(columns[index])) == primary_unit]
    if len(chosen) > 4:
        chosen = [primary]
    totals = [i for i, label in enumerate(categories) if _TOTAL_ROW.match(label)]
    keep = [i for i in range(len(categories)) if i not in totals and all(numeric[c][i] is not None for c in chosen)]
    if len(keep) < 2:
        return None
    series = [dict(name=_series_name(header[c]) or "Value", data=[float(numeric[c][i]) for i in keep]) for c in chosen]
    labels = [categories[i] for i in keep]
    label_header = _clean_label(header[labels_at])
    if label_header and all(re.fullmatch(r"\d{1,2}", label) for label in labels):
        labels = [f"{label_header} {label}" for label in labels]  # "1" under "Year" is "Year 1"
    by = _series_name(header[labels_at]).lower() or "item"
    names = [s["name"] for s in series]
    # "A, B, C and D by year" read as a sentence; more than two measures are
    # named by the first.
    title = (f"{names[0]} by {by}" if len(names) == 1 else f"{names[0]} and {names[1]} by {by}" if len(names) == 2
             else f"{names[0]} and {len(names) - 1} other measures by {by}")
    periods = all(_PERIOD.match(label) for label in labels)
    if periods:
        kind = "line" if len(labels) >= 4 else "bar"
        reason = ("The figures run over time, so a line shows the trend." if kind == "line"
                  else "A few periods side by side compare best as bars.")
    else:
        values = series[0]["data"]
        total = sum(values)
        stated_total = numeric[primary][totals[0]] if totals and numeric[primary][totals[0]] is not None else None
        sums_to_total = stated_total is not None and abs(float(stated_total) - total) <= max(abs(total) * 0.005, 0.01)
        part_to_whole = (len(series) == 1 and 2 <= len(values) <= 8 and all(v > 0 for v in values)
                         and (sums_to_total or _SHARE_WORDS.search(header[primary]) or primary_unit == "percent"
                              and abs(total - 100) <= 0.5))
        if part_to_whole:
            kind, reason = "pie", "The parts add up to a whole, so a pie shows each one's share."
        else:
            kind = "bar"
            reason = ("Two or more measures across the same items compare best as grouped bars." if len(series) > 1
                      else "Separate items compare best as bars.")
    chart = (dict(type="pie", title=title, data=[dict(name=n, value=v) for n, v in zip(labels, series[0]["data"])])
             if kind == "pie" else dict(type=kind, title=title, categories=labels, series=series))
    return kind, chart, reason


def chart_from_answer(text: str) -> tuple[str, dict, str] | None:
    """The best chart for the answer's largest chartable table."""
    best = None
    for header, data in _tables(text):
        chosen = _choose(header, data)
        if chosen is None:
            continue
        size = len(chosen[1].get("categories") or chosen[1].get("data") or [])
        if best is None or size >= best[0]:
            best = (size, chosen)
    return best[1] if best else None


_DECLINED = re.compile(
    r"\b(?:only|just)\s+(?:(?:a|any|the)\s+)?(?:tables?|text)\b|\b(?:tables?|text)\s+only\b"
    r"|\b(?:no|without|skip|omit)\s+(?:a\s+|any\s+|the\s+)?(?:charts?|graphs?|plots?|visuals?)\b"
    r"|\b(?:do not|don't|don’t|never)\s+(?:(?:draw|show|make|include|create|add)\s+(?:(?:a|any|the)\s+)?)?"
    r"(?:charts?|graphs?|plots?|visuals?)\b", re.I)


def chart_declined(question: str) -> bool:
    """The user asked for no chart, or for text or a table only. Unlike the
    automatic-chart guard, a condition ("if the correlation was not
    perfect") does not stop an offer: the user still chooses."""
    return bool(_DECLINED.search(question or ""))


def offer_chart(text: str) -> ChartOffer | None:
    chosen = chart_from_answer(text)
    if chosen is None:
        return None
    kind, chart, reason = chosen
    from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence
    import json
    try:
        build_chart_fence(json.dumps(chart, allow_nan=False))
    except (ChartToolError, ValueError):
        return None
    return ChartOffer(chart_type=kind, title=chart["title"], question=f"Show this as a {kind} chart.",
                      reason=reason, chart=chart)


def offer_spec_id(offer: ChartOffer) -> str:
    """Named by its content: the same answer always offers the same chart
    (a request id made otherwise identical responses differ)."""
    import hashlib
    import json
    return "offer-" + hashlib.sha256(json.dumps(offer.chart, sort_keys=True).encode()).hexdigest()[:16]


def offer_visualization(offer: ChartOffer, answer_text: str, spec_id: str):
    """The offered chart as the visualization the page draws, from the same
    table, or None. Accepting the offer used to send a new question with the
    user's original question as context; its numbers, not the answer's
    table, were then charted (a 38.46% / 61.54% pie of a $240,000 contract,
    23 Oct 2026). Drawn from this spec there is no second question."""
    from app.orchestration.visualization.spec import DonutSlice, VisualizationSpec
    from app.orchestration.visualization.validator import VisualizationValidator
    chart = offer.chart
    if chart["type"] == "pie":
        parts = [(str(item["name"]), float(item["value"])) for item in chart["data"]]
        total = sum(value for _, value in parts)
        if total <= 0 or any(value < 0 for _, value in parts):
            return None
        spec = VisualizationSpec(
            id=spec_id, type="DONUT", family="COMPOSITION", renderer="ECHARTS", title=chart["title"], unit="%",
            summary=f"Each part's share of the total, from the answer's table. {offer.reason}",
            donut=[DonutSlice(label=label, value=value / total * 100, is_estimated=False) for label, value in parts])
        return spec if VisualizationValidator().validate(spec).passed else None
    from app.orchestration.supplied_charts import SuppliedChart, typed_supplied_chart
    return typed_supplied_chart(SuppliedChart(f"From the answer's table. {offer.reason}", chart), answer_text, spec_id)

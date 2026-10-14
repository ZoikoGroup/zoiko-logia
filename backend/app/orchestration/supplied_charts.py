"""Provider-independent charts from complete, explicitly supplied datasets.

Only whole payloads are accepted. History is screened by the caller and remains
conversation data, never independently verified market evidence.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence
from app.orchestration.calculation_service import needs_lookup
from app.orchestration.chart_intent import allows_automatic_chart

_AMOUNT = r"[+−-]?(?:[$£€₹]\s*)?\d[\d,]*(?:\.\d+)?%?"
_PAIR = re.compile(rf"\s*([A-Za-z][A-Za-z0-9 &/()'-]*?)\s*[:=]?\s+({_AMOUNT})\s*(?:,|;|$)")
_FOLLOWUP = re.compile(
    r"^\s*(?:now\s+)?(?:show|make|draw|plot|display|turn|convert)\s+"
    r"(?:it|this|that|them|the same(?: data| chart)?)(?:\s+as|\s+into)?\s+"
    r"(?:a\s+)?(?:bar|line|area|pie|scatter|radar|heatmap|waterfall)\s*"
    r"(?:chart)?(?:\s+instead)?[.!?]?\s*$", re.I,
)


@dataclass(frozen=True)
class SuppliedChart:
    text: str
    chart: dict | None
    response_kind: Literal["calculation", "chart", "chart_explanation"] = "chart"
    clarification: str | None = None

    def markdown(self) -> str:
        if self.chart is None:
            return self.text
        return self.text + "\n\n" + build_chart_fence(json.dumps(self.chart, allow_nan=False))


def _number(value: str) -> Decimal:
    return Decimal(re.sub(r"[$£€₹,%\s]", "", value).replace("−", "-"))


def _pairs(payload: str) -> list[tuple[str, Decimal]] | None:
    result = []
    position = 0
    while position < len(payload):
        match = _PAIR.match(payload, position)
        if not match:
            return None
        result.append((match[1].strip(), _number(match[2])))
        position = match.end()
    if not 2 <= len(result) <= 500 or len({name.casefold() for name, _ in result}) != len(result):
        return None
    return result


def _format(value: Decimal, *, money: bool = False) -> str:
    rendered = f"{value:,.2f}"
    return rendered if money else rendered.rstrip("0").rstrip(".")


def _currency(text: str) -> str | None:
    aliases = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}
    found = re.findall(r"\b(?:USD|EUR|GBP|INR|JPY|CAD|AUD)\b|[$£€₹]", text, re.I)
    units = {aliases.get(item, item.upper()) for item in found}
    return next(iter(units)) if len(units) == 1 else None


def _mixed_currencies(text: str) -> bool:
    aliases = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}
    return len({aliases.get(item, item.upper()) for item in re.findall(
        r"\b(?:USD|EUR|GBP|INR|JPY|CAD|AUD)\b|[$£€₹]", text, re.I,
    )}) > 1



def _validated(text: str, chart: dict) -> SuppliedChart | None:
    try:
        build_chart_fence(json.dumps(chart, allow_nan=False))
    except (ChartToolError, ValueError):
        return None
    calculated = chart["type"] in {"waterfall", "scatter", "sankey"} or bool(
        re.search(r"\b(?:Total|Top category):", text)
    )
    return SuppliedChart(text, chart, "calculation" if calculated else "chart")


def _from_query(query: str) -> SuppliedChart | None:
    kind_match = re.search(r"\b(waterfall|sankey|heatmap|scatter|line|bar|area|pie)\b", query, re.I)
    if not kind_match or needs_lookup(query):
        return None
    kind = kind_match[1].lower()
    # Strip instructions after the supplied dataset, not arbitrary prose.
    payload = re.split(r"\.\s+(?:show|compare|plot|draw|does|tell)\b", query, maxsplit=1, flags=re.I)[0].strip().rstrip(".")
    title, colon, values = payload.partition(":")
    if not colon:
        title, values = "Supplied figures", payload
    values = values.strip()
    if kind == "scatter":
        matches = list(re.finditer(rf"\(\s*({_AMOUNT})\s*,\s*({_AMOUNT})\s*\)", values))
        remainder = re.sub(rf"\(\s*({_AMOUNT})\s*,\s*({_AMOUNT})\s*\)", "", values)
        if not 2 <= len(matches) <= 500 or remainder.strip(" ,;"):
            return None
        points = [[float(_number(m[1])), float(_number(m[2]))] for m in matches]
        xs, ys = zip(*points)
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denominator = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
        text = "The chart shows the supplied pairs."
        if denominator:
            r = sum((x-mx)*(y-my) for x,y in points) / denominator
            text += f" Pearson correlation r = {r:.3f} across {len(points)} observations. This measures association, not causation."
        else:
            text += " Pearson correlation is undefined because one or both series are constant."
        return _validated(text, dict(type=kind, title=title, xName="First value", yName="Second value", series=[dict(name=title, points=points)]))
    if kind == "heatmap":
        rows = []
        for row in values.split(";"):
            match = re.fullmatch(r"\s*([A-Za-z][\w ]*?)\s*(?:—|:|–)\s*(.+)", row)
            pairs = _pairs(match[2]) if match else None
            if not pairs:
                return None
            rows.append((match[1].strip(), pairs))
        if len(rows) < 2 or len({name for name, _ in rows}) != len(rows):
            return None
        categories = [name for name, _ in rows[0][1]]
        if any([name for name, _ in pairs] != categories for _, pairs in rows):
            return None
        return _validated("The heatmap uses the supplied figures and units.", dict(type=kind, title=title, categories=categories, yCategories=[name for name,_ in rows], cells=[[x,y,float(v)] for y,(_,pairs) in enumerate(rows) for x,(_,v) in enumerate(pairs)]))
    if kind == "sankey":
        # Allocation form: Revenue 1,000,000 → Salaries 450,000, ...
        # Explicit edge-list forms remain handled by chart_tables.py.
        source, arrow, destinations = re.split(r"(→|->)", values, maxsplit=1) if re.search(r"→|->", values) else ("", "", "")
        origin = _PAIR.fullmatch(source.strip()) if arrow else None
        pairs = _pairs(destinations.strip()) if arrow else None
        if not origin or not pairs or any(v < 0 for _,v in pairs):
            return None
        name, total = origin[1].strip(), _number(origin[2])
        if total != sum(v for _,v in pairs) or name in [label for label,_ in pairs]:
            return None
        return _validated(f"Total allocated: {_format(total)}.", dict(type=kind, title=title, nodes=[dict(name=n) for n in [name]+[n for n,_ in pairs]], links=[dict(source=name,target=n,value=float(v)) for n,v in pairs]))
    pairs = _pairs(values)
    if not pairs:
        return None
    total = sum(v for _,v in pairs)
    money = _currency(values) is not None
    if kind == "pie":
        if _mixed_currencies(values):
            return SuppliedChart("These amounts use different currencies and cannot form a meaningful pie chart. Use a labelled table instead.", None, "chart_explanation")
        if any(v < 0 for _,v in pairs) or total <= 0:
            return SuppliedChart("A pie chart requires non-negative parts with a positive total. Use a bar chart for signed values.", None, "chart_explanation")
        return _validated(f"Total: {_format(total, money=money)}.", dict(type=kind,title=title,data=[dict(name=n,value=float(v)) for n,v in pairs]))
    names = [n for n,_ in pairs]
    numbers = [float(v) for _,v in pairs]
    text = "The chart uses the supplied figures."
    if kind == "waterfall":
        label = "Closing balance" if re.search(r"opening cash|closing balance", query, re.I) else "Net profit" if re.search(r"net profit",query,re.I) else "Closing total"
        names.append(label)
        numbers.append(float(total))
        text = f"{label}: {_format(total, money=money)}."
    elif re.search(r"\btotal\b", query, re.I):
        text += f" Total: {_format(total, money=money)}."
    if re.search(r"\btop\b", query, re.I):
        name, value = max(pairs, key=lambda pair: pair[1])
        text += f" Top category: {name} ({_format(value)})."
    # Missing observations remain absent; disclose the gap rather than imply zero.
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    positions = {month.casefold(): i for i, month in enumerate(months)}
    positions.update({month[:3].casefold(): i for i, month in enumerate(months)})
    indexes = [positions.get(name.casefold()) for name in names]
    if indexes and all(index is not None for index in indexes):
        missing = [months[i] for i in range(min(indexes), max(indexes)+1) if i not in indexes]
        if missing:
            text += f" {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing; no value has been inferred for {'it' if len(missing) == 1 else 'them'}."
    return _validated(text, dict(type=kind,title=title,categories=names,series=[dict(name=title,data=numbers)]))


def _table_chart(text: str) -> SuppliedChart | None:
    """Read an earlier answer's complete Markdown table, with numeric columns.

    Live charts can be carried separately from answer text, so their visible
    data table is also useful context. Metadata/date tables do not qualify.
    """
    for block in re.findall(r"(?:^\|[^\n]*\|[ \t]*\n?){3,}", text, re.M):
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
                for line in block.strip().splitlines()]
        if len(rows) < 3 or not all(re.fullmatch(r":?-+:?", cell) for cell in rows[1]):
            continue
        header, data = rows[0], rows[2:]
        if len(header) < 2 or any(len(row) != len(header) for row in data):
            continue
        if any(not re.fullmatch(_AMOUNT, cell) for row in data for cell in row[1:]):
            continue
        return _validated("", dict(
            type="line", title="Previous dataset", categories=[row[0] for row in data],
            series=[dict(name=name, data=[float(_number(row[i])) for row in data])
                    for i, name in enumerate(header[1:], start=1)],
        ))
    return None


def _supplied_total(query: str) -> SuppliedChart | None:
    """A complete labelled list followed by a request for its total only.

    Do not remove arbitrary prose: the entire instruction must match so a
    request for advice or other outputs cannot be silently answered by a sum.
    """
    if needs_lookup(query):
        return None
    parts = re.split(r"\.\s+(?=[A-Za-z])", query.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    dataset, instruction = parts
    if not re.fullmatch(
        r"(?:(?:do not|don't|don’t)\s+(?:show|draw|include)\s+(?:a |any |the )?chart[;,]?\s*)?"
        r"(?:only\s+)?(?:give|show|calculate|compute|tell me)\s+(?:me\s+)?(?:the\s+)?"
        r"total(?:\s+only)?[.!?]?", instruction, re.I,
    ):
        return None
    title, separator, payload = dataset.partition(":")
    if not separator or "%" in payload:
        return None
    # The same whole-payload reader accepts explicit missing-value tokens.
    # Known values may form a subtotal, never an apparently complete total.
    missing_value = r"unknown|missing|n/a|none|null|not provided|\?"
    pattern = re.compile(
        rf"\s*([A-Za-z][A-Za-z0-9 &/()'-]*?)\s*[:=]?\s+({_AMOUNT}|{missing_value})\s*(?:,|;|$)", re.I,
    )
    matches, position = [], 0
    while position < len(payload.strip()):
        match = pattern.match(payload.strip(), position)
        if not match:
            return None
        matches.append(match)
        position = match.end()
    if not 2 <= len(matches) <= 500:
        return None
    labels = [match[1].strip() for match in matches]
    if len({label.casefold() for label in labels}) != len(labels):
        return SuppliedChart("Duplicate category labels make the total ambiguous.", None, "calculation", "Please give each category a unique label.")
    if _mixed_currencies(payload):
        return SuppliedChart("These amounts use different currencies; a combined total requires conversion.", None, "calculation", "Which output currency and conversion rate should I use?")
    unit = _currency(payload)
    symbols = {"GBP": "£", "EUR": "€", "USD": "$", "INR": "₹"}
    prefix = symbols.get(unit, unit + " " if unit else "")
    missing = [match[1].strip() for match in matches if re.fullmatch(missing_value, match[2], re.I)]
    total = sum((_number(match[2]) for match in matches if not re.fullmatch(missing_value, match[2], re.I)), Decimal(0))
    if missing:
        known = len(matches) - len(missing)
        subtotal = f"Known-values subtotal: {prefix}{_format(total, money=bool(unit))}. " if known else ""
        return SuppliedChart(
            subtotal + f"The complete total cannot be calculated because {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing.",
            None, "calculation", f"Please provide the missing values for {', '.join(missing)}.",
        )
    return SuppliedChart(
        f"Total {title.strip().lower()}: {prefix}{_format(total, money=bool(unit))}.",
        None, "calculation",
    )


def build_supplied_chart(query: str, history=()) -> SuppliedChart | None:
    total = _supplied_total(query)
    if total is not None:
        return total
    if not allows_automatic_chart(query):
        return None
    direct = _from_query(query)
    if direct is not None or not _FOLLOWUP.fullmatch(query):
        return direct
    kind = re.search(r"\b(bar|line|area|pie|scatter|radar|heatmap|waterfall)\b",query,re.I)[1].lower()
    for message in reversed(history):
        if "exceeds the conversation context limit" in message.content:
            return SuppliedChart("The previous dataset is too large to reuse completely from conversation context.", None, "chart_explanation", "Please supply the dataset again so all observations can be preserved.")
        # Only the immediately preceding dataset is considered, avoiding stale
        # matches from unrelated turns. Accept validated chart fences first.
        fences = re.findall(r"```chart\s*\n(.*?)```", message.content, re.S)
        prior = None
        if fences:
            try:
                candidate = json.loads(fences[-1])
                build_chart_fence(json.dumps(candidate, allow_nan=False))
                if candidate.get("type") in {"bar", "line", "area"} and any(
                    len(series["data"]) != len(candidate["categories"])
                    for series in candidate["series"]
                ):
                    return None
                prior = SuppliedChart("", candidate)
            except (ValueError, ChartToolError):
                return None
        elif message.role == "assistant":
            prior = _table_chart(message.content)
        elif message.role == "user":
            prior = _from_query(message.content)
        if prior and prior.chart:
            chart = prior.chart
            if kind == "pie" and chart["type"] in {"bar", "line", "area"}:
                series = chart.get("series", [])
                labels = chart.get("categories", [])
                if _mixed_currencies(" ".join(labels)):
                    return SuppliedChart("These amounts use different currencies and cannot form a meaningful pie chart. Use a labelled table instead.", None, "chart_explanation")
                if len(series) != 1 or any(v < 0 for v in series[0]["data"]) or sum(series[0]["data"]) <= 0:
                    return None
                return _validated("The pie chart reuses the supplied categories and values.", dict(type="pie",title=chart["title"],data=[dict(name=n,value=v) for n,v in zip(labels,series[0]["data"],strict=True)]))
            if kind not in {"bar","line","area"} or chart["type"] not in {"bar","line","area"}:
                return None
            return _validated("The chart reuses all observations from the preceding dataset.", {**chart,"type":kind})
        if message.role == "user" and not _FOLLOWUP.fullmatch(message.content):
            return None
    return None

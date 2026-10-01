"""
User-supplied data for the chart types that need more than one number per
label: Pareto, funnel, streamgraph, bubble, Sankey, calendar heatmap and
parallel coordinates.

Each is asked for by name with its figures in the question — the same rule
as extraction.py's other user-supplied data, nothing comes from the model:

    pareto     "...as a pareto chart: Payroll 180000, Rent 55000, IT 25000"
    funnel     "...as a funnel chart: Leads 500, Qualified 200, Won 30"
    stream     "...as a streamgraph: Payroll: 2024 10, 2025 12; Rent: 2024 5, 2025 6"
    bubble     "...as a bubble chart: Product A: revenue 100, margin 20, volume 50;
                Product B: revenue 80, margin 35, volume 20"
    parallel   "...as parallel coordinates: Acme: margin 12, growth 8, debt 30;
                Beta: margin 9, growth 15, debt 45"
    sankey     "...as a sankey chart: Revenue -> Operating Cash: 900;
                Operating Cash -> Payroll: 400"
    calendar   "...as a calendar heatmap: 2026-01-05 12, 2026-01-06 30"

The figures travel as ordinary observations (one per table cell: the row
label as `dimension`, the column as `measure`) because those are the fields
the service already carries from supplied to visualization evidence. The
CHART_TABLE marker in `dimensions` tells data_shape.py what they are, and
build_chart_table_spec() turns them back into a TABLE spec — exact figures
the frontend draws as the named chart, and shows as-is if it cannot.

Pareto, funnel and the others are recognised by response_planner.py's chart
names; sunburst and bullet charts need no parser here, being the existing
composition and actual-versus-target data drawn another way.
"""
from __future__ import annotations

import re
from datetime import date

from app.orchestration.data_shape import CHART_TABLE
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.response_planner import detect_requested_chart_variant
from app.orchestration.visualization.spec import VisualizationSpec

PARETO, FUNNEL, STREAM, BUBBLE, PARALLEL, SANKEY, CALENDAR = (
    "pareto", "funnel", "stream", "bubble", "parallel", "sankey", "calendar",
)

# requested chart variant (response_planner.py) -> table kind
_KINDS = {
    "PARETO_CHART": PARETO,
    "FUNNEL_CHART": FUNNEL,
    "STREAMGRAPH": STREAM,
    "BUBBLE_CHART": BUBBLE,
    "PARALLEL_COORDINATES": PARALLEL,
    "SANKEY_CHART": SANKEY,
    "CALENDAR_HEATMAP": CALENDAR,
}

_MAX_ROWS = 60
_MAX_METRICS = 10
_MAX_CALENDAR_DAYS = 366

_LABEL = r"[A-Za-z][\w &/().'-]{0,59}?"
_METRIC = r"[A-Za-z][\w ]{0,29}?"
_PERIOD = r"[A-Za-z0-9][\w .'/-]{0,19}?"
_NUMBER = r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
_AMOUNT = rf"[$£€₹]?\s*({_NUMBER})\s*(k|thousand|mn|m|million|bn|billion)?\b"
_LABEL_VALUE = re.compile(rf"\s*({_LABEL})\s*[:=]?\s*{_AMOUNT}\s*", re.I)
_METRIC_VALUE = re.compile(rf"\s*({_METRIC})\s*[:=]?\s*{_AMOUNT}\s*", re.I)
_PERIOD_VALUE = re.compile(rf"\s*({_PERIOD})\s*[:=]?\s+{_AMOUNT}\s*", re.I)
_NAMED_LIST = re.compile(rf"^\s*({_LABEL})\s*:\s*(.+?)\s*$")
_FLOW = re.compile(rf"^\s*({_LABEL})\s*(?:-->|->|→)\s*({_LABEL})\s*:\s*{_AMOUNT}\s*$", re.I)
_DAY_VALUE = re.compile(rf"\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*[:=]?\s*{_AMOUNT}\s*", re.I)
_STATEMENT_SPLIT = re.compile(r"\s*(?:;|\n)\s*")
_FLOW_ARROW = " → "

_SUBJECT_NOISE = re.compile(
    r"\b(create|make|show|showing|display|draw|plot|give|compare|me|a|an|the|as|of|for|in|using|"
    r"pareto|funnel|streamgraph|stream|graph|bubble|parallel|coordinates|sankey|calendar|"
    r"heat\s*map|heatmap|chart|diagram|plot)\b",
    re.I,
)


def _amount(number: str, scale: str | None) -> float:
    return float(number.replace(",", "")) * _SCALE.get((scale or "").lower(), 1.0)


def _items(text: str, pattern: re.Pattern[str]) -> list[re.Match[str]] | None:
    """Every comma-separated item in `text` must match `pattern` — thousand
    separators are kept inside their number, and anything left over means the
    list was not what it looked like, so nothing is returned."""
    matches: list[re.Match[str]] = []
    position = 0
    while position < len(text):
        match = pattern.match(text, position)
        if not match:
            return None
        matches.append(match)
        position = match.end()
        if position < len(text):
            if text[position] not in ",;":
                return None
            position += 1
    return matches or None


def _subject(prefix: str) -> str:
    subject = re.sub(r"\s+", " ", _SUBJECT_NOISE.sub(" ", prefix)).strip(" -.,:")
    return (subject[:1].upper() + subject[1:]) if subject else "Supplied figures"


def _evidence(kind: str, subject: str, cells: list[tuple[str, str, float]], key: str) -> EvidenceModel:
    measures = list(dict.fromkeys(measure for _row, measure, _value in cells))
    return EvidenceModel(
        subject=subject,
        observations=[Observation(dimension=row, value=value, measure=measure) for row, measure, value in cells],
        user_supplied=True,
        dimensions=[CHART_TABLE, kind, key],
        measures=measures,
    )


def _labelled(payload: str) -> list[tuple[str, float]] | None:
    matches = _items(payload, _LABEL_VALUE)
    if not matches:
        return None
    pairs = [(m.group(1).strip(), _amount(m.group(2), m.group(3))) for m in matches]
    labels = [label.casefold() for label, _ in pairs]
    if not 2 <= len(pairs) <= _MAX_ROWS or len(set(labels)) != len(labels) or any(v < 0 for _, v in pairs):
        return None
    return pairs


def _named_lists(payload: str, pattern: re.Pattern[str]) -> list[tuple[str, list[tuple[str, float]]]] | None:
    """"Name: key value, key value; Name: ..." with the same keys, in the same
    order, for every name — a ragged table cannot be drawn honestly."""
    rows = []
    for statement in (s for s in _STATEMENT_SPLIT.split(payload) if s):
        named = _NAMED_LIST.match(statement)
        items = _items(named.group(2), pattern) if named else None
        if not items:
            return None
        rows.append((named.group(1).strip(), [(m.group(1).strip(), _amount(m.group(2), m.group(3))) for m in items]))
    names = [name.casefold() for name, _ in rows]
    if not 2 <= len(rows) <= _MAX_ROWS or len(set(names)) != len(names):
        return None
    keys = [key for key, _ in rows[0][1]]
    if not 2 <= len(keys) <= _MAX_METRICS or len(set(k.casefold() for k in keys)) != len(keys):
        return None
    if any([key for key, _ in values] != keys for _name, values in rows):
        return None
    return rows


def _flows(payload: str) -> list[tuple[str, str, float]] | None:
    flows = []
    for statement in (s for s in _STATEMENT_SPLIT.split(payload) if s):
        match = _FLOW.match(statement)
        if not match:
            return None
        source, target = match.group(1).strip(), match.group(2).strip()
        amount = _amount(match.group(3), match.group(4))
        if source.casefold() == target.casefold() or amount <= 0:
            return None
        flows.append((source, target, amount))
    if not 2 <= len(flows) <= _MAX_ROWS or len({(s, t) for s, t, _ in flows}) != len(flows):
        return None
    # A Sankey diagram cannot draw a cycle; refuse one rather than drop a flow.
    outgoing: dict[str, set[str]] = {}
    for source, target, _ in flows:
        outgoing.setdefault(source, set()).add(target)

    def reaches(start: str, goal: str, seen: set[str]) -> bool:
        return any(nxt == goal or (nxt not in seen and reaches(nxt, goal, seen | {nxt})) for nxt in outgoing.get(start, ()))

    if any(reaches(target, source, {target}) for source, target, _ in flows):
        return None
    return flows


def _days(payload: str) -> list[tuple[date, float]] | None:
    matches = _items(payload, _DAY_VALUE)
    if not matches:
        return None
    days = []
    for match in matches:
        try:
            days.append((date.fromisoformat(match.group(1)), _amount(match.group(2), match.group(3))))
        except ValueError:
            return None
    dates = [d for d, _ in days]
    if not 2 <= len(days) <= _MAX_CALENDAR_DAYS or len(set(dates)) != len(dates):
        return None
    if (max(dates) - min(dates)).days >= _MAX_CALENDAR_DAYS:
        return None
    return sorted(days)


def extract_chart_table(query: str) -> EvidenceModel | None:
    """Evidence for a named multi-value chart whose whole payload parses, or
    None — a partial read would silently drop figures the user typed."""
    kind = _KINDS.get(detect_requested_chart_variant(query) or "")
    if kind is None:
        return None
    prefix, separator, payload = (query or "").partition(":")
    payload = payload.strip().rstrip(".!?")
    if not separator or not payload:
        return None
    subject = _subject(prefix)

    if kind in (PARETO, FUNNEL):
        pairs = _labelled(payload)
        if not pairs:
            return None
        key = "Category" if kind == PARETO else "Stage"
        return _evidence(kind, subject, [(label, "Value", value) for label, value in pairs], key)
    if kind == STREAM:
        rows = _named_lists(payload, _PERIOD_VALUE)
        if not rows:
            return None
        cells = [(period, series, value) for series, values in rows for period, value in values]
        return _evidence(kind, subject, cells, "Period")
    if kind in (BUBBLE, PARALLEL):
        rows = _named_lists(payload, _METRIC_VALUE)
        if not rows or (kind == BUBBLE and len(rows[0][1]) != 3):
            return None
        cells = [(item, metric, value) for item, values in rows for metric, value in values]
        return _evidence(kind, subject, cells, "Item")
    if kind == SANKEY:
        flows = _flows(payload)
        if not flows:
            return None
        return _evidence(kind, subject, [(f"{s}{_FLOW_ARROW}{t}", "Amount", v) for s, t, v in flows], "Flow")
    days = _days(payload)
    if not days:
        return None
    return _evidence(kind, subject, [(d.isoformat(), "Value", v) for d, v in days], "Date")


def is_chart_table(evidence: EvidenceModel) -> bool:
    return evidence.dimensions[:1] == [CHART_TABLE] and len(evidence.dimensions) >= 3


def _cell(value: float) -> str:
    return f"{value:.10g}"


_CAPTIONS = {
    PARETO: "Categories sorted largest first; the cumulative share is arithmetic on the supplied figures.",
    FUNNEL: "Stages in the order supplied.",
    STREAM: "Each series over the supplied periods.",
    BUBBLE: "Position from the first two figures, bubble size from the third.",
    PARALLEL: "Each item across every supplied measure.",
    SANKEY: "Flow widths are the supplied amounts.",
    CALENDAR: "Each supplied day, coloured by its value.",
}


def build_chart_table_spec(evidence: EvidenceModel, spec_id: str) -> VisualizationSpec:
    """The supplied figures as a TABLE spec: one row per label, one column per
    measure, every value exactly as typed."""
    kind, key = evidence.dimensions[1], evidence.dimensions[2]
    measures = evidence.measures
    rows_by_label: dict[str, dict[str, str]] = {}
    for observation in evidence.observations:
        row = rows_by_label.setdefault(observation.dimension, {key: observation.dimension})
        row[observation.measure] = _cell(observation.value)
    rows = list(rows_by_label.values())
    columns = [key, *measures]

    if kind == SANKEY:
        columns = ["From", "To", "Amount"]
        rows = [
            {"From": flow.split(_FLOW_ARROW)[0], "To": flow.split(_FLOW_ARROW)[1], "Amount": row["Amount"]}
            for flow, row in rows_by_label.items()
        ]
    elif kind == PARETO:
        ordered = sorted(evidence.observations, key=lambda o: o.value, reverse=True)
        total = sum(o.value for o in ordered) or 1.0
        running = 0.0
        rows = []
        for observation in ordered:
            running += observation.value
            rows.append({key: observation.dimension, "Value": _cell(observation.value),
                         "Cumulative %": f"{running / total * 100:.1f}"})
        columns = [key, "Value", "Cumulative %"]

    return VisualizationSpec(
        id=spec_id,
        type="TABLE",
        family="STATISTICAL",
        renderer="TABLE_ADAPTER",
        title=evidence.subject,
        summary=f"Figures supplied directly by the user. {_CAPTIONS[kind]}",
        columns=columns,
        rows=rows,
        sources=evidence.sources,
    )

"""Say so when the chart drawn is not the type the user asked for.

"Compare the last 10 days of AAPL and Microsoft stock prices in a pie chart"
was drawn as a line chart: a pie shows parts of one whole, and ten days of
two prices are a trend, so the substitution was right — but the answer did
not say it, and the reader saw their request ignored.
"""
from __future__ import annotations

import json
import re

from app.orchestration.response_planner import detect_requested_chart_variant

# Requested variant -> chart fence types that satisfy it.
_FAMILY = {
    "PIE_CHART": {"pie", "donut", "doughnut"}, "DONUT_CHART": {"pie", "donut", "doughnut"},
    "BAR_CHART": {"bar", "grouped_bar", "stacked_bar"}, "GROUPED_BAR_CHART": {"bar", "grouped_bar"},
    "STACKED_BAR_CHART": {"bar", "stacked_bar"},
    "AREA_CHART": {"area", "line"}, "STEP_LINE_CHART": {"line"}, "SPLINE_LINE_CHART": {"line"},
    "STANDARD_LINE": {"line", "area"}, "LINE_CHART": {"line", "area"},
    "WATERFALL_CHART": {"waterfall"}, "TREEMAP_CHART": {"treemap"}, "RADAR_CHART": {"radar"},
}
_LABEL = {"pie": "pie", "donut": "donut", "doughnut": "donut", "bar": "bar", "line": "line", "area": "area",
          "scatter": "scatter", "waterfall": "waterfall", "heatmap": "heatmap", "treemap": "treemap", "radar": "radar"}
_FENCE = re.compile(r"```chart\s*\n(.*?)```", re.S)
_ASKED_LINE = re.compile(r"\bline\s+(?:chart|graph)\b", re.I)


def drawn_chart_types(*texts: str) -> list[str]:
    types: list[str] = []
    for text in texts:
        for body in _FENCE.findall(text or ""):
            try:
                kind = str(json.loads(body).get("type", "")).lower()
            except (ValueError, AttributeError):
                continue
            if kind and kind not in types:
                types.append(kind)
    return types


def substitution_note(query: str, *texts: str) -> str:
    """A note naming the requested and the drawn chart type, or ""."""
    requested = detect_requested_chart_variant(query or "")
    if _ASKED_LINE.search(query or "") and requested is None:
        requested, wanted = "LINE_CHART", {"line", "area"}
    else:
        wanted = _FAMILY.get(requested or "")
    drawn = drawn_chart_types(*texts)
    if not wanted or not drawn or set(drawn) & wanted:
        return ""
    asked = {"STANDARD_LINE": "line"}.get(requested, requested.replace("_CHART", "").replace("_", " ").lower())
    shown = _LABEL.get(drawn[0], drawn[0])
    if asked in {"pie", "donut"} and shown in {"line", "area", "bar"}:
        reason = ("a pie chart shows the parts of one whole, and this data is a comparison over time, "
                  "so the shares would not mean anything")
    else:
        reason = "the requested type does not fit this data"
    return f"You asked for a {asked} chart; a {shown} chart is shown instead because {reason}."

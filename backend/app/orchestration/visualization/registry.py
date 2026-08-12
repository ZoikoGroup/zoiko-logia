"""
Central renderer registry (spec §17) — the one place a visualization type
maps to the renderer that draws it. Nothing else in the codebase should
hard-code that mapping.

Only entries this pipeline can actually produce are listed. Add a row here
the same day you add the orchestrator rule + validator checks that can
produce/verify it — an entry with no producer is a renderer no one can reach.
"""
from __future__ import annotations

VISUALIZATION_REGISTRY: dict[str, dict[str, str]] = {
    "LINE": {"renderer": "ECHARTS"},
    "BAR": {"renderer": "ECHARTS"},
    "HISTOGRAM": {"renderer": "ECHARTS"},
    "BOX": {"renderer": "ECHARTS"},
    "SCATTER": {"renderer": "ECHARTS"},
    "KPI": {"renderer": "KPI_TILE"},
    "EVIDENCE_GRAPH": {"renderer": "GRAPH_ADAPTER"},
    "HEATMAP": {"renderer": "ECHARTS"},
    "PROCESS_FLOW": {"renderer": "FLOW_ADAPTER"},
    "TABLE": {"renderer": "TABLE_ADAPTER"},
    "DONUT": {"renderer": "ECHARTS"},
}

RENDERER_CAPABILITIES: dict[str, frozenset[str]] = {
    "ECHARTS": frozenset({"LINE", "BAR", "HISTOGRAM", "HEATMAP", "BOX", "SCATTER", "DONUT"}),
    "KPI_TILE": frozenset({"KPI"}),
    "GRAPH_ADAPTER": frozenset({"EVIDENCE_GRAPH"}),
    "FLOW_ADAPTER": frozenset({"PROCESS_FLOW"}),
    "TABLE_ADAPTER": frozenset({"TABLE"}),
}

FALLBACKS: dict[str, list[str]] = {
    "LINE": ["BAR", "TABLE", "TEXT"],
    "BAR": ["TABLE", "TEXT"],
    "HISTOGRAM": ["TABLE", "TEXT"],
    "BOX": ["HISTOGRAM", "TABLE", "TEXT"],
    "SCATTER": ["TABLE", "TEXT"],
    "HEATMAP": ["TABLE", "TEXT"],
    "EVIDENCE_GRAPH": ["TABLE", "TEXT"],
    "PROCESS_FLOW": ["TEXT"],
    "KPI": ["TEXT"],
    "TABLE": ["TEXT"],
    "DONUT": ["TABLE", "TEXT"],
}


def renderer_for(visualization_type: str) -> str | None:
    entry = VISUALIZATION_REGISTRY.get(visualization_type)
    return entry["renderer"] if entry else None


def renderer_supports(renderer: str, visualization_type: str) -> bool:
    return visualization_type in RENDERER_CAPABILITIES.get(renderer, frozenset())


def fallbacks_for(visualization_type: str) -> list[str]:
    return list(FALLBACKS.get(visualization_type, ["TEXT"]))

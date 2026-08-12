"""
VisualizationValidator (spec §18) — checked before a VisualizationSpec is
ever attached to a response. A spec that fails validation is dropped (never
sent), never raises into the caller — see orchestrator.py's fallback
behaviour and spec §19 (fallback layer) / §29 DoD #15-16.

Named VisualizationValidationResult (not schemas.ValidationResult) — that
existing type is answer-text validation (Massarius™ Checkpoint C) with a
`degraded_route` field that has no meaning here; reusing it would conflate
two different validation concerns.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.orchestration.visualization.spec import VisualizationSpec
from app.orchestration.visualization.registry import renderer_supports

_MIN_LINE_POINTS = 3


class VisualizationValidationResult(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)


class VisualizationValidator:
    def validate(self, spec: VisualizationSpec) -> VisualizationValidationResult:
        failures: list[str] = []
        failures.extend(self._common(spec))

        if spec.type == "LINE":
            failures.extend(self._line(spec))
        elif spec.type == "BAR":
            failures.extend(self._bar(spec))
        elif spec.type == "HISTOGRAM":
            failures.extend(self._histogram(spec))
        elif spec.type == "BOX":
            failures.extend(self._box(spec))
        elif spec.type == "SCATTER":
            failures.extend(self._scatter(spec))
        elif spec.type == "TABLE":
            failures.extend(self._table(spec))
        elif spec.type == "KPI":
            failures.extend(self._kpi(spec))
        elif spec.type == "EVIDENCE_GRAPH":
            failures.extend(self._graph(spec))
        elif spec.type == "HEATMAP":
            failures.extend(self._heatmap(spec))
        elif spec.type == "PROCESS_FLOW":
            failures.extend(self._flow(spec))
        elif spec.type == "DONUT":
            failures.extend(self._donut(spec))
        else:
            failures.append(f"unknown visualization type: {spec.type!r}")

        return VisualizationValidationResult(passed=not failures, failures=failures)

    def _common(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if not spec.id:
            failures.append("missing id")
        if not spec.type:
            failures.append("missing type")
        if not spec.renderer:
            failures.append("missing renderer")
        elif spec.type and not renderer_supports(spec.renderer, spec.type):
            failures.append(f"renderer {spec.renderer!r} does not support {spec.type!r}")
        return failures

    def _line(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if spec.encoding is None:
            failures.append("LINE requires an encoding")
        if len(spec.data) < _MIN_LINE_POINTS:
            failures.append(f"LINE requires at least {_MIN_LINE_POINTS} observations, got {len(spec.data)}")
        if any(not isinstance(p.y, (int, float)) for p in spec.data):
            failures.append("LINE requires all y values to be numeric")
        # Ordered dimension: DBnomics returns points in period order already,
        # but verify rather than assume — an unordered series renders as a
        # meaningless zig-zag.
        xs = [p.x for p in spec.data]
        if xs != sorted(xs):
            failures.append("LINE requires the x dimension to be ordered")
        return failures

    def _bar(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if spec.encoding is None:
            failures.append("BAR requires an encoding")
        if len(spec.data) < 2:
            failures.append(f"BAR requires at least 2 observations, got {len(spec.data)}")
        if any(not isinstance(p.y, (int, float)) for p in spec.data):
            failures.append("BAR requires all y values to be numeric")
        return failures

    def _histogram(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if len(spec.data) < 1:
            failures.append("HISTOGRAM requires at least one bin")
        if any(p.y < 0 for p in spec.data):
            failures.append("HISTOGRAM bin counts must be non-negative")
        if sum(p.y for p in spec.data) <= 0:
            failures.append("HISTOGRAM requires at least one value across all bins")
        return failures

    def _box(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if spec.box is None:
            failures.append("BOX requires a box summary")
            return failures
        b = spec.box
        if not (b.minimum <= b.q1 <= b.median <= b.q3 <= b.maximum):
            failures.append("BOX quartiles must satisfy min <= q1 <= median <= q3 <= max")
        return failures

    def _scatter(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if len(spec.scatter) < 2:
            failures.append(f"SCATTER requires at least 2 paired observations, got {len(spec.scatter)}")
        if any(not isinstance(p.x, (int, float)) or not isinstance(p.y, (int, float)) for p in spec.scatter):
            failures.append("SCATTER requires all x/y values to be numeric")
        if spec.correlation_coefficient is not None and not (-1.0 <= spec.correlation_coefficient <= 1.0):
            failures.append("SCATTER correlation_coefficient must be within [-1, 1]")
        return failures

    def _table(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if not spec.columns:
            failures.append("TABLE requires at least one column")
        if not spec.rows:
            failures.append("TABLE requires at least one row")
        col_set = set(spec.columns)
        for i, row in enumerate(spec.rows):
            missing = col_set - set(row.keys())
            if missing:
                failures.append(f"TABLE row {i} is missing column(s): {sorted(missing)}")
        return failures

    def _kpi(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if spec.value is None:
            failures.append("KPI requires a value")
        elif not isinstance(spec.value, (int, float)):
            failures.append("KPI value must be numeric")
        return failures

    def _graph(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if len(spec.nodes) < 1:
            failures.append("EVIDENCE_GRAPH requires at least one node")
        node_ids = [n.id for n in spec.nodes]
        if len(node_ids) != len(set(node_ids)):
            failures.append("EVIDENCE_GRAPH requires unique node IDs")
        node_id_set = set(node_ids)
        for e in spec.edges:
            if not e.source or not e.target:
                failures.append("EVIDENCE_GRAPH has a malformed edge with an empty source/target")
                continue
            if e.source not in node_id_set:
                failures.append(f"EVIDENCE_GRAPH edge source {e.source!r} has no matching node")
            if e.target not in node_id_set:
                failures.append(f"EVIDENCE_GRAPH edge target {e.target!r} has no matching node")
        return failures

    def _heatmap(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if len(spec.cells) < 1:
            failures.append("HEATMAP requires at least one cell")
        if any(c.value < 0 for c in spec.cells):
            failures.append("HEATMAP cell values must be non-negative")
        return failures

    def _donut(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if len(spec.donut) < 2:
            failures.append(f"DONUT requires at least 2 slices, got {len(spec.donut)}")
        if any(s.value < 0 for s in spec.donut):
            failures.append("DONUT slice values must be non-negative")
        # 0.5 tolerance absorbs float rounding from band-midpoint arithmetic
        # (e.g. three 33.33...% slices) — not a loosening of the "parts can't
        # exceed the whole" rule itself.
        total = sum(s.value for s in spec.donut)
        if total > 100.5:
            failures.append(f"DONUT slice values must not exceed 100% of the whole, got {total:.1f}%")
        return failures

    def _flow(self, spec: VisualizationSpec) -> list[str]:
        failures: list[str] = []
        if len(spec.nodes) < 2:
            failures.append("PROCESS_FLOW requires at least two stages")
        node_id_set = {n.id for n in spec.nodes}
        targets = set()
        sources = set()
        for e in spec.edges:
            if e.source not in node_id_set:
                failures.append(f"PROCESS_FLOW edge source {e.source!r} has no matching stage")
            if e.target not in node_id_set:
                failures.append(f"PROCESS_FLOW edge target {e.target!r} has no matching stage")
            sources.add(e.source)
            targets.add(e.target)
        # A start stage must exist — one that's never a destination — or the
        # flow has no clear entry point to begin rendering from.
        if node_id_set and not (node_id_set - targets):
            failures.append("PROCESS_FLOW has no identifiable start stage (every stage is a destination)")
        return failures

import type { VisualizationSpec } from "@/lib/api";

/**
 * Defensive re-check of a spec's own SHAPE before rendering — not a re-run
 * of the backend's full validator.py, just the two states this frontend
 * needs to distinguish (spec: "can happen when re-rendering an old saved
 * payload against evolved rules"). This is directly relevant here, not
 * hypothetical: conversations persist to localStorage (ask-kriton-storage.ts)
 * across page loads, and this VisualizationSpec shape has changed more than
 * once this project — a persisted BOX turn from before the `box` field
 * existed would have `box: undefined` when re-rendered today.
 */
export type ChartValidity = "EMPTY" | "STRUCTURALLY_INVALID" | "OK";

/** Fill collection fields that older persisted/API payloads may omit. */
export function normalizeVisualizationSpec(viz: VisualizationSpec): VisualizationSpec {
  return {
    ...viz,
    fallback_order: Array.isArray(viz.fallback_order) ? viz.fallback_order : [],
    data: Array.isArray(viz.data) ? viz.data : [],
    nodes: Array.isArray(viz.nodes) ? viz.nodes : [],
    edges: Array.isArray(viz.edges) ? viz.edges : [],
    cells: Array.isArray(viz.cells) ? viz.cells : [],
    scatter: Array.isArray(viz.scatter) ? viz.scatter : [],
    donut: Array.isArray(viz.donut) ? viz.donut : [],
    candlestick: Array.isArray(viz.candlestick) ? viz.candlestick : [],
    series: Array.isArray(viz.series) ? viz.series : [],
    columns: Array.isArray(viz.columns) ? viz.columns : [],
    rows: Array.isArray(viz.rows) ? viz.rows : [],
    sources: Array.isArray(viz.sources) ? viz.sources : [],
  };
}

export function checkChartValidity(viz: VisualizationSpec): ChartValidity {
  switch (viz.type) {
    case "LINE": {
      const series = Array.isArray(viz.series) ? viz.series : [];
      if (series.length > 0) {
        if (series.length < 2 || series.some((s) => !Array.isArray(s.data) || s.data.length < 2)) return "STRUCTURALLY_INVALID";
        return "OK";
      }
      const data = Array.isArray(viz.data) ? viz.data : [];
      if (data.length === 0) return "EMPTY";
      if (data.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    }
    case "BAR": {
      const data = Array.isArray(viz.data) ? viz.data : [];
      if (data.length === 0) return "EMPTY";
      if (data.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    }
    case "HISTOGRAM":
      if (!Array.isArray(viz.data) || viz.data.length === 0) return "EMPTY";
      return "OK";
    case "BOX":
      if (!viz.box) return "EMPTY";
      if (!(viz.box.minimum <= viz.box.q1 && viz.box.q1 <= viz.box.median && viz.box.median <= viz.box.q3 && viz.box.q3 <= viz.box.maximum)) {
        return "STRUCTURALLY_INVALID";
      }
      return "OK";
    case "SCATTER":
      if (!Array.isArray(viz.scatter) || viz.scatter.length === 0) return "EMPTY";
      if (viz.scatter.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "HEATMAP":
      if (!Array.isArray(viz.cells) || viz.cells.length === 0) return "EMPTY";
      return "OK";
    case "DONUT":
      if (!Array.isArray(viz.donut) || viz.donut.length === 0) return "EMPTY";
      if (viz.donut.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "CANDLESTICK":
      if (!Array.isArray(viz.candlestick) || viz.candlestick.length === 0) return "EMPTY";
      if (viz.candlestick.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "GROUPED_BAR": {
      const series = Array.isArray(viz.series) ? viz.series : [];
      if (series.length === 0) return "EMPTY";
      if (series.length < 2 || series.some((s) => !Array.isArray(s.data) || s.data.length < 2)) return "STRUCTURALLY_INVALID";
      return "OK";
    }
    case "KPI":
      if (viz.value == null) return "EMPTY";
      if (typeof viz.value !== "number") return "STRUCTURALLY_INVALID";
      return "OK";
    case "TABLE": {
      const columns = Array.isArray(viz.columns) ? viz.columns : [];
      const rows = Array.isArray(viz.rows) ? viz.rows : [];
      if (columns.length === 0 || rows.length === 0) return "EMPTY";
      if (rows.some((row) => !row || columns.some((col) => !(col in row)))) return "STRUCTURALLY_INVALID";
      return "OK";
    }
    case "EVIDENCE_GRAPH": {
      const nodes = Array.isArray(viz.nodes) ? viz.nodes : [];
      const edges = Array.isArray(viz.edges) ? viz.edges : [];
      if (nodes.length === 0) return "EMPTY";
      const ids = nodes.map((n) => n.id);
      if (new Set(ids).size !== ids.length) return "STRUCTURALLY_INVALID";
      const idSet = new Set(ids);
      if (edges.some((e) => !idSet.has(e.source) || !idSet.has(e.target))) return "STRUCTURALLY_INVALID";
      return "OK";
    }
    case "PROCESS_FLOW": {
      const nodes = Array.isArray(viz.nodes) ? viz.nodes : [];
      const edges = Array.isArray(viz.edges) ? viz.edges : [];
      if (nodes.length < 2) return "EMPTY";
      const idSet = new Set(nodes.map((n) => n.id));
      const targets = new Set(edges.map((e) => e.target));
      if (edges.some((e) => !idSet.has(e.source) || !idSet.has(e.target))) return "STRUCTURALLY_INVALID";
      if (![...idSet].some((id) => !targets.has(id))) return "STRUCTURALLY_INVALID";
      return "OK";
    }
  }
}

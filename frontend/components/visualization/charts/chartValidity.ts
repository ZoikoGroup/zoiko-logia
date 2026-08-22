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

export function checkChartValidity(viz: VisualizationSpec): ChartValidity {
  switch (viz.type) {
    case "LINE":
      if (viz.series.length > 0) {
        if (viz.series.length < 2 || viz.series.some((s) => s.data.length < 2)) return "STRUCTURALLY_INVALID";
        return "OK";
      }
    case "BAR":
      if (viz.data.length === 0) return "EMPTY";
      if (viz.data.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "HISTOGRAM":
      if (viz.data.length === 0) return "EMPTY";
      return "OK";
    case "BOX":
      if (!viz.box) return "EMPTY";
      if (!(viz.box.minimum <= viz.box.q1 && viz.box.q1 <= viz.box.median && viz.box.median <= viz.box.q3 && viz.box.q3 <= viz.box.maximum)) {
        return "STRUCTURALLY_INVALID";
      }
      return "OK";
    case "SCATTER":
      if (viz.scatter.length === 0) return "EMPTY";
      if (viz.scatter.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "HEATMAP":
      if (viz.cells.length === 0) return "EMPTY";
      return "OK";
    case "DONUT":
      if (viz.donut.length === 0) return "EMPTY";
      if (viz.donut.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "CANDLESTICK":
      if (viz.candlestick.length === 0) return "EMPTY";
      if (viz.candlestick.length < 2) return "STRUCTURALLY_INVALID";
      return "OK";
    case "GROUPED_BAR":
      if (viz.series.length === 0) return "EMPTY";
      if (viz.series.length < 2 || viz.series.some((s) => s.data.length < 2)) return "STRUCTURALLY_INVALID";
      return "OK";
    case "KPI":
      if (viz.value == null) return "EMPTY";
      if (typeof viz.value !== "number") return "STRUCTURALLY_INVALID";
      return "OK";
    case "TABLE":
      if (viz.columns.length === 0 || viz.rows.length === 0) return "EMPTY";
      if (viz.rows.some((row) => viz.columns.some((col) => !(col in row)))) return "STRUCTURALLY_INVALID";
      return "OK";
    case "EVIDENCE_GRAPH": {
      if (viz.nodes.length === 0) return "EMPTY";
      const ids = viz.nodes.map((n) => n.id);
      if (new Set(ids).size !== ids.length) return "STRUCTURALLY_INVALID";
      const idSet = new Set(ids);
      if (viz.edges.some((e) => !idSet.has(e.source) || !idSet.has(e.target))) return "STRUCTURALLY_INVALID";
      return "OK";
    }
    case "PROCESS_FLOW": {
      if (viz.nodes.length < 2) return "EMPTY";
      const idSet = new Set(viz.nodes.map((n) => n.id));
      const targets = new Set(viz.edges.map((e) => e.target));
      if (viz.edges.some((e) => !idSet.has(e.source) || !idSet.has(e.target))) return "STRUCTURALLY_INVALID";
      if (![...idSet].some((id) => !targets.has(id))) return "STRUCTURALLY_INVALID";
      return "OK";
    }
  }
}

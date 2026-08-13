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
    default:
      return "OK";
  }
}

/**
 * Which top-level component family owns a given VisualizationSpec type.
 * Single source of truth for "chart vs. kpi vs. table vs. graph vs. flow" —
 * replaces the manual `||`-chain that used to live inline in
 * AnswerRenderer.tsx's VisualizationRenderer. Typed as an exhaustive Record
 * so TypeScript itself fails to compile if a type is ever added to
 * VisualizationSpec["type"] without a corresponding entry here.
 *
 * This is deliberately scoped ABOVE engineRouting.ts, not a replacement for
 * it: engineFor() answers a separate, finer-grained question (which of the
 * two chart engines renders the 9 "chart" types) that stays inside the
 * chart family. Graph/flow's own engine selection (GraphRendererAdapter's
 * node-count threshold, FlowRendererAdapter's `interactive` flag) is a
 * different kind of decision again and isn't absorbed here either.
 */
import type { VisualizationSpec } from "@/lib/api";

export type VisualFamily = "chart" | "kpi" | "table" | "graph" | "flow";

type VisualTypeConfig = {
  family: VisualFamily;
  // Mirrors backend registry.py's renderer string 1:1, for cross-referencing
  // backend telemetry/logs against frontend behavior — a coarser grouping
  // than the chart family's per-component rendering implementation.
  backendRenderer: VisualizationSpec["renderer"];
};

export const VISUALIZATION_TYPE_REGISTRY: Record<VisualizationSpec["type"], VisualTypeConfig> = {
  LINE: { family: "chart", backendRenderer: "RECHARTS" },
  BAR: { family: "chart", backendRenderer: "RECHARTS" },
  HISTOGRAM: { family: "chart", backendRenderer: "RECHARTS" },
  GROUPED_BAR: { family: "chart", backendRenderer: "RECHARTS" },
  HEATMAP: { family: "chart", backendRenderer: "ECHARTS" },
  BOX: { family: "chart", backendRenderer: "ECHARTS" },
  SCATTER: { family: "chart", backendRenderer: "ECHARTS" },
  DONUT: { family: "chart", backendRenderer: "ECHARTS" },
  CANDLESTICK: { family: "chart", backendRenderer: "ECHARTS" },
  KPI: { family: "kpi", backendRenderer: "KPI_TILE" },
  TABLE: { family: "table", backendRenderer: "TABLE_ADAPTER" },
  EVIDENCE_GRAPH: { family: "graph", backendRenderer: "GRAPH_ADAPTER" },
  PROCESS_FLOW: { family: "flow", backendRenderer: "FLOW_ADAPTER" },
};

export function familyFor(type: VisualizationSpec["type"]): VisualFamily {
  return VISUALIZATION_TYPE_REGISTRY[type].family;
}

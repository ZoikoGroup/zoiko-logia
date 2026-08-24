"use client";

import { useRef, useState } from "react";
import { Download, Table2 } from "lucide-react";
import type { VisualizationSpec } from "@/lib/api";
import { engineFor, SAME_SHAPE_VIEW_ALTERNATIVES } from "./engineRouting";
import { RechartsChart } from "./RechartsAdapter";
import { EChartsChart, type EChartsInstanceLike } from "./EChartsAdapter";
import { ChartErrorBoundary } from "./ChartErrorBoundary";
import { DataTableView } from "./DataTableView";
import { checkChartValidity, normalizeVisualizationSpec } from "./chartValidity";
import { usePreferTable, useDefaultView } from "./useChartPreferences";
import { ChartViewMenu } from "./ChartViewMenu";
import { SummaryMetricCards, shouldShowSummaryMetrics } from "./SummaryMetricCards";
import { exportEChartsPng, exportSvgAsPng, exportChartCsv } from "./exportChart";
import { trackVisualizationInteraction } from "@/lib/telemetry";

/**
 * Top-level entry point for every chart-family VisualizationSpec (LINE/BAR/
 * HISTOGRAM/HEATMAP/BOX/SCATTER) — resolves the 4 states in order (empty,
 * structurally invalid, prefer-table, normal), routes the normal state to
 * whichever engine the type needs, and wraps the interactivity shell
 * (view menu, table toggle, PNG/CSV export, metric cards, error boundary,
 * telemetry) around it. Never re-derives or invents data — every branch
 * reads straight from the spec the backend already validated.
 */
export function ChartRenderer({ viz: rawViz }: { viz: VisualizationSpec }) {
  const originalViz = normalizeVisualizationSpec(rawViz);
  const containerRef = useRef<HTMLDivElement>(null);
  const echartsInstanceRef = useRef<EChartsInstanceLike | null>(null);

  const alternatives = SAME_SHAPE_VIEW_ALTERNATIVES[originalViz.type] ?? [];
  const [defaultView] = useDefaultView(originalViz.type);
  const initialType =
    defaultView && alternatives.includes(defaultView as VisualizationSpec["type"])
      ? (defaultView as VisualizationSpec["type"])
      : originalViz.type;

  const [activeType, setActiveType] = useState<VisualizationSpec["type"]>(initialType);
  const [tableOpen, setTableOpen] = useState(false);
  const [renderFailed, setRenderFailed] = useState(false);
  const [preferTable, setPreferTable] = usePreferTable(originalViz.type);
  const [, setDefaultView] = useDefaultView(originalViz.type);

  const validity = checkChartValidity(originalViz);

  // State 1: empty.
  if (validity === "EMPTY") {
    return <p className="my-4 text-xs text-muted">No data available for this visualization.</p>;
  }

  // State 2: structurally invalid for the current type (e.g. a re-rendered
  // old saved payload against evolved rules) — explanatory caption + table.
  if (validity === "STRUCTURALLY_INVALID") {
    return (
      <div className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        <div className="p-3 sm:p-4">
        <p className="mb-2 text-xs leading-5 text-muted">
          This visualization&apos;s saved data no longer matches what a {originalViz.type.toLowerCase()} chart
          needs. Showing the underlying data instead.
        </p>
        <DataTableView viz={originalViz} />
        </div>
      </div>
    );
  }

  // Shadow the original payload with a derived object for a switched view —
  // never mutate what the backend actually sent.
  const viz: VisualizationSpec = activeType === originalViz.type ? originalViz : { ...originalViz, type: activeType };
  const engine = engineFor(viz.type);
  const ariaLabel = viz.summary ?? viz.title ?? `${viz.type} chart`;
  const otherViews = [originalViz.type, ...alternatives].filter((t) => t !== viz.type);

  function handleViewSelect(type: VisualizationSpec["type"]) {
    setActiveType(type);
    trackVisualizationInteraction("view_selected", "chart", {
      visualizationId: originalViz.id, visualizationType: originalViz.type,
      renderer: engineFor(type) ?? undefined, detail: { from: activeType, to: type },
    });
  }

  function handleSetDefault() {
    setDefaultView(viz.type);
    trackVisualizationInteraction("preference_set", "chart", {
      visualizationId: originalViz.id, visualizationType: originalViz.type, detail: { defaultView: viz.type },
    });
  }

  function handleExportPng() {
    if (engine === "ECHARTS") exportEChartsPng(echartsInstanceRef.current, viz);
    else if (containerRef.current) exportSvgAsPng(containerRef.current, viz);
    trackVisualizationInteraction("exported_png", "chart", { visualizationId: viz.id, visualizationType: viz.type, renderer: engine ?? undefined });
  }

  function handleExportCsv() {
    exportChartCsv(viz);
    trackVisualizationInteraction("exported_csv", "chart", { visualizationId: viz.id, visualizationType: viz.type });
  }

  function toggleTable() {
    const next = !tableOpen;
    setTableOpen(next);
    if (next) trackVisualizationInteraction("table_view_opened", "chart", { visualizationId: viz.id, visualizationType: viz.type });
  }

  // State 3: a saved preference says "prefer table over chart" for this shape.
  if (preferTable) {
    return (
      <div className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        <div className="p-3 sm:p-4">
        {viz.title && <h4 className="text-sm font-semibold text-ink">{viz.title}</h4>}
        <div className="mt-3">
          <DataTableView viz={viz} />
        </div>
        <button
          type="button"
          className="mt-3 text-xs font-medium text-brand underline"
          onClick={() => setPreferTable(false)}
        >
          Reveal chart
        </button>
        </div>
      </div>
    );
  }

  // State 4: normal.
  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex min-w-0 items-start justify-between gap-2 p-3 sm:p-4">
        <div className="min-w-0">
          {viz.title && <h4 className="text-sm font-semibold text-ink">{viz.title}</h4>}
          <span className="mt-1 inline-flex rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">{viz.domain_context?.domain ?? "Data"}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {otherViews.length > 0 && (
            <>
              <ChartViewMenu currentType={viz.type} alternatives={otherViews} onSelect={handleViewSelect} />
              {activeType !== originalViz.type || alternatives.length > 0 ? (
                <button
                  type="button"
                  title="Use this view as my default"
                  onClick={handleSetDefault}
                  className="rounded-lg border border-line px-2 py-1 text-[11px] font-medium text-muted hover:text-ink"
                >
                  Set default
                </button>
              ) : null}
            </>
          )}
        </div>
      </header>

      {shouldShowSummaryMetrics(viz.type) && (
        <div className="border-t border-line p-3 sm:p-4">
          <SummaryMetricCards viz={viz} />
        </div>
      )}

      <div ref={containerRef} className={`${renderFailed ? "" : "h-[300px]"} min-w-0 w-full border-t border-line p-3 sm:p-4`} role="img" aria-label={ariaLabel}>
        <ChartErrorBoundary viz={viz} renderer={engine ?? "UNKNOWN"} onError={() => setRenderFailed(true)}>
          {engine === "RECHARTS" && <RechartsChart viz={viz} />}
          {engine === "ECHARTS" && (
            <EChartsChart viz={viz} onInstance={(instance) => { echartsInstanceRef.current = instance; }} />
          )}
        </ChartErrorBoundary>
      </div>

      {viz.summary && <p className="truncate border-t border-line px-3 py-2 text-[11px] text-muted sm:px-4">{viz.summary}</p>}
      <div className="border-t border-line">
        <button type="button" aria-expanded={tableOpen} className="flex w-full items-center justify-between px-3 py-2 text-left text-[11px] font-medium text-muted hover:text-ink sm:px-4" onClick={toggleTable}>
          <span>View as table</span><span>{tableOpen ? "Hide" : "Show"}</span>
        </button>
      </div>
      {tableOpen && <div className="min-w-0 overflow-x-auto border-t border-line p-3 sm:p-4"><DataTableView viz={viz} /></div>}
      <div className="flex items-center justify-end gap-2 border-t border-line px-3 py-2 sm:px-4">
        <button type="button" title="Export PNG" onClick={handleExportPng} className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-[11px] font-medium text-muted hover:text-ink"><Download size={12} />Export PNG</button>
        <button type="button" className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-[11px] font-medium text-muted hover:text-ink" onClick={handleExportCsv}><Table2 size={12} />Export CSV</button>
      </div>
    </section>
  );
}

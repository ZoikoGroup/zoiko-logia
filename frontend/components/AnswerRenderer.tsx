"use client";

import { type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { VisualizationSpec } from "@/lib/api";
import { GraphRendererAdapter } from "@/components/visualization/GraphRendererAdapter";
import { FlowRendererAdapter } from "@/components/visualization/FlowRendererAdapter";
import { GraphErrorBoundary, RelationshipTableFallback } from "@/components/visualization/GraphErrorBoundary";
import { ChartRenderer } from "@/components/visualization/charts/ChartRenderer";
import { ANSWER_MATH_OPTIONS, hasDisplayMath, sanitizeAnswerMarkdown } from "@/lib/answer-markdown";
import { ChartErrorBoundary } from "@/components/visualization/charts/ChartErrorBoundary";
import { checkChartValidity } from "@/components/visualization/charts/chartValidity";
import { familyFor } from "@/components/visualization/registry";

/**
 * Renders a Kriton answer. Text is rendered as Markdown (so tables, bullet
 * lists, bold, and headings display properly, like ChatGPT). Charts/diagrams
 * are no longer LLM-authored fenced blocks — see visualizationSpecToChartSpec
 * below — this only renders the typed, server-decided `visualization` field.
 * Citations, risk badge and everything else are unchanged.
 */

/**
 * Safety net: strip any inline citation markers the model still slips into the
 * answer text (e.g. "[REF-1]", "[REF-2, REF-5]", "[1]"). Sources are shown in
 * the separate Sources panel, so the answer body should read cleanly. Also
 * strips any stray ```mermaid/```chart fenced blocks a stale prompt/cached
 * response might still contain, rather than dumping raw JSON/mermaid syntax
 * as text — this renderer no longer knows how to draw them (see
 * websearch.py's _FORMATTING_INSTRUCTIONS docstring for why). Also tidies up
 * the leftover spaces/punctuation the removals leave behind.
 */
// ── Data charts ──────────────────────────────────────────────────────────
// LINE/BAR/HISTOGRAM/HEATMAP/BOX/SCATTER/DONUT now render through
// components/visualization/charts/ChartRenderer.tsx — the dual-engine
// (Recharts + ECharts) rendering layer with its full interactivity shell
// (states, view switching, table fallback, PNG/CSV export, metric cards,
// error boundary, telemetry). See VisualizationRenderer below.

function KpiTile({ viz }: { viz: VisualizationSpec }) {
  if (viz.value == null) return null;
  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{viz.label ?? "Metric"}</p>
        <span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">KPI</span>
      </header>
      <div className="border-t border-line p-3 sm:p-4">
      <p className="mt-1 text-2xl font-bold text-ink">
        {viz.value.toLocaleString()}
        {viz.unit && <span className="ml-1 text-base font-semibold text-muted">{viz.unit}</span>}
      </p>
      {viz.summary && <p className="mt-2 text-xs leading-5 text-muted">{viz.summary}</p>}
      </div>
    </section>
  );
}

// TABLE_ADAPTER — a plain HTML table, no chart engine involved. Real rows
// straight from EvidenceModel.observations (orchestrator.py's
// _build_table_spec), never LLM-authored markdown.
function TableViz({ viz }: { viz: VisualizationSpec }) {
  if (!viz.columns.length || !viz.rows.length) return null;
  return (
    <section className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
      <header className="flex items-center justify-between p-3 sm:p-4"><h4 className="text-sm font-semibold text-ink">Data table</h4><span className="rounded-full bg-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Table</span></header>
      <div className="min-w-0 overflow-x-auto border-t border-line p-3 sm:p-4"><table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr>
            {viz.columns.map((col) => (
              <th key={col} className="border border-line px-3 py-2 font-semibold text-ink">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {viz.rows.map((row, i) => (
            <tr key={i}>
              {viz.columns.map((col) => (
                <td key={col} className="border border-line px-3 py-2 align-top text-ink">
                  {row[col] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table></div>
      {viz.summary && <p className="truncate border-t border-line px-3 py-2 text-[11px] text-muted sm:px-4">{viz.summary}</p>}
    </section>
  );
}

function VisualizationRenderer({ viz }: { viz: VisualizationSpec }) {
  // Defensive re-check before any family-specific rendering: catches specs
  // whose shape has drifted from what this frontend build expects (e.g. an
  // old payload persisted to localStorage before a field existed). Only
  // ChartRenderer used to consult this — KPI/TABLE/EVIDENCE_GRAPH/
  // PROCESS_FLOW had no equivalent gate.
  const validity = checkChartValidity(viz);
  if (validity === "EMPTY") {
    return <p className="my-4 text-xs text-muted">No data available for this visualization.</p>;
  }
  if (validity === "STRUCTURALLY_INVALID") {
    const isGraphLike = viz.type === "EVIDENCE_GRAPH" || viz.type === "PROCESS_FLOW";
    return (
      <div className="my-4 min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
        <div className="p-3 sm:p-4">
          <p className="mb-2 text-xs leading-5 text-muted">
            This visualization&apos;s saved data no longer matches what a {viz.type.toLowerCase().replace(/_/g, " ")} needs.
          </p>
          {isGraphLike && <RelationshipTableFallback nodes={viz.nodes} edges={viz.edges} />}
        </div>
      </div>
    );
  }

  switch (familyFor(viz.type)) {
    case "table":
      return (
        <ChartErrorBoundary viz={viz} renderer="TABLE_ADAPTER">
          <TableViz viz={viz} />
        </ChartErrorBoundary>
      );
    case "kpi":
      return (
        <ChartErrorBoundary viz={viz} renderer="KPI_TILE">
          <KpiTile viz={viz} />
        </ChartErrorBoundary>
      );
    case "chart":
      return <ChartRenderer viz={viz} />;
    case "graph":
      return (
        <div className="min-w-0">
          <GraphRendererAdapter nodes={viz.nodes} edges={viz.edges} preferredEngine={viz.graph_engine} />
          {viz.summary && <p className="mt-1 px-1 text-xs leading-5 text-muted">{viz.summary}</p>}
        </div>
      );
    case "flow":
      return (
        <div className="min-w-0">
          <GraphErrorBoundary
            category="flow"
            failedRenderer="flow"
            fallbackRenderer="table"
            fallback={<RelationshipTableFallback nodes={viz.nodes} edges={viz.edges} />}
          >
            <FlowRendererAdapter
              nodes={viz.nodes}
              edges={viz.edges}
              interactive={viz.interactive}
              preferredEngine={viz.flow_engine}
            />
          </GraphErrorBoundary>
          {viz.summary && <p className="mt-1 px-1 text-xs leading-5 text-muted">{viz.summary}</p>}
        </div>
      );
  }
}

// Markdown element styling — theme-tokenized so it stays legible in dark mode
// (the container it sits in, e.g. Ask Kriton's response card, is theme-aware
// and goes dark — hardcoded dark-mode-unaware text here used to render
// dark-on-dark).
const mdComponents = {
  p: (props: ComponentPropsWithoutRef<"p">) => <p className="mb-3 last:mb-0" {...props} />,
  ul: (props: ComponentPropsWithoutRef<"ul">) => <ul className="mb-3 list-disc space-y-1 pl-5" {...props} />,
  ol: (props: ComponentPropsWithoutRef<"ol">) => <ol className="mb-3 list-decimal space-y-1 pl-5" {...props} />,
  strong: (props: ComponentPropsWithoutRef<"strong">) => <strong className="font-semibold text-ink" {...props} />,
  a: (props: ComponentPropsWithoutRef<"a">) => (
    <a className="text-brand underline" target="_blank" rel="noreferrer" {...props} />
  ),
  table: (props: ComponentPropsWithoutRef<"table">) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs" {...props} />
    </div>
  ),
  thead: (props: ComponentPropsWithoutRef<"thead">) => <thead className="bg-soft" {...props} />,
  th: (props: ComponentPropsWithoutRef<"th">) => (
    <th className="border border-line px-3 py-2 font-semibold text-ink" {...props} />
  ),
  td: (props: ComponentPropsWithoutRef<"td">) => (
    <td className="border border-line px-3 py-2 align-top text-ink" {...props} />
  ),
  code: (props: ComponentPropsWithoutRef<"code">) => (
    <code className="rounded bg-soft px-1 py-0.5 text-[12px] text-ink" {...props} />
  ),
  h1: (props: ComponentPropsWithoutRef<"h1">) => <h3 className="mb-2 mt-3 text-base font-bold text-ink" {...props} />,
  h2: (props: ComponentPropsWithoutRef<"h2">) => <h3 className="mb-2 mt-3 text-sm font-bold text-ink" {...props} />,
  h3: (props: ComponentPropsWithoutRef<"h3">) => <h4 className="mb-1 mt-2 text-sm font-semibold text-ink" {...props} />,
};

export function AnswerRenderer({
  text,
  visualization,
  secondaryVisualizations,
  className,
}: {
  text: string;
  /** Deterministic, evidence-backed visual from the response's top-level
   * `visualization` field. */
  visualization?: VisualizationSpec | null;
  /** Complementary visuals (spec §17) — a different lens on the SAME
   * evidence as `visualization`, rendered after it. */
  secondaryVisualizations?: VisualizationSpec[] | null;
  className?: string;
}) {
  const sanitizedText = sanitizeAnswerMarkdown(text);
  const renderMath = hasDisplayMath(sanitizedText);

  return (
    <div className={`w-full min-w-0 text-sm leading-7 text-ink ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={renderMath ? [remarkGfm, [remarkMath, ANSWER_MATH_OPTIONS]] : [remarkGfm]}
        rehypePlugins={renderMath ? [rehypeKatex] : []}
        components={mdComponents}
      >
        {sanitizedText}
      </ReactMarkdown>
      {visualization && <VisualizationRenderer viz={visualization} />}
      {secondaryVisualizations?.map((viz) => <VisualizationRenderer key={viz.id} viz={viz} />)}
    </div>
  );
}

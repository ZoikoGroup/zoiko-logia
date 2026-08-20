"use client";

import { type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { VisualizationSpec } from "@/lib/api";
import { GraphRendererAdapter } from "@/components/visualization/GraphRendererAdapter";
import { FlowRendererAdapter } from "@/components/visualization/FlowRendererAdapter";
import { ChartRenderer } from "@/components/visualization/charts/ChartRenderer";

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
function stripInlineRefs(text: string): string {
  return text
    // KaTeX has no metrics for U+202F (narrow no-break space), which commonly
    // appears in copied/model-generated numbers and units.
    .replace(/\u202F/g, " ")
    .replace(/```(mermaid|chart)\s*[\s\S]*?```/g, "")
    // Hide disclaimer boilerplate from legacy turns persisted before the
    // backend stopped emitting it. The generated block is always terminal.
    .replace(/\n*\s*---\s*\n\s*⚠️\s*(?:\*\*)?Kriton™ Disclaimer(?:\*\*)?:[\s\S]*?latest effective standards\.\s*/gi, "")
    .replace(/\n*This response is for educational purposes only\. Consult a qualified professional\.\s*/gi, "")
    // Provider models occasionally expose their internal domain-routing
    // preamble. It is not part of the user-facing answer, so remove both
    // Markdown-bold and plain variants from new and locally persisted turns.
    .replace(/^\s*(?:\*\*|__)?CLASSIF(?:ICATION|IED)(?:\*\*|__)?\s*:\s*[^\n]*\n?/gim, "")
    .replace(/^\s*(?:\*\*|__)?ANSWER(?:\*\*|__)?\s*:\s*/gim, "")
    .replace(/\*\*/g, "")
    .replace(/\s*\[\s*(?:REF-)?\d+(?:\s*,\s*(?:REF-)?\d+)*\s*\]/gi, "")
    .replace(/[ \t]+([.,;:])/g, "$1")
    .replace(/[ \t]{2,}/g, " ");
}

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
  if (viz.type === "TABLE") return <TableViz viz={viz} />;
  if (viz.type === "KPI") return <KpiTile viz={viz} />;
  if (viz.type === "LINE" || viz.type === "BAR" || viz.type === "HISTOGRAM" || viz.type === "HEATMAP" || viz.type === "BOX" || viz.type === "SCATTER" || viz.type === "DONUT") {
    return <ChartRenderer viz={viz} />;
  }
  if (viz.type === "EVIDENCE_GRAPH") {
    return (
      <div className="min-w-0">
        <GraphRendererAdapter nodes={viz.nodes} edges={viz.edges} />
        {viz.summary && <p className="mt-1 px-1 text-xs leading-5 text-muted">{viz.summary}</p>}
      </div>
    );
  }
  if (viz.type === "PROCESS_FLOW") {
    return (
      <div className="min-w-0">
        <FlowRendererAdapter nodes={viz.nodes} edges={viz.edges} interactive={viz.interactive} />
        {viz.summary && <p className="mt-1 px-1 text-xs leading-5 text-muted">{viz.summary}</p>}
      </div>
    );
  }
  return null;
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
  return (
    <div className={`w-full min-w-0 text-sm leading-7 text-ink ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={mdComponents}
      >
        {stripInlineRefs(text)}
      </ReactMarkdown>
      {visualization && <VisualizationRenderer viz={visualization} />}
      {secondaryVisualizations?.map((viz) => <VisualizationRenderer key={viz.id} viz={viz} />)}
    </div>
  );
}

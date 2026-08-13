"use client";

import { useEffect, useRef, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { CheckCircle2, Copy, Download, Table2 } from "lucide-react";
import type { VisualizationSpec } from "@/lib/api";
import { GraphRendererAdapter } from "@/components/visualization/GraphRendererAdapter";
import { FlowRendererAdapter } from "@/components/visualization/FlowRendererAdapter";
import { ChartRenderer } from "@/components/visualization/charts/ChartRenderer";
import {
  downloadBlob,
  safeDownloadName,
  svgElementToPngBlob,
  tableElementToRows,
  tableRowsToTsv,
  writeImageToClipboard,
  writeTextToClipboard,
} from "@/lib/presentation";

/**
 * Renders a Kriton answer. Text is rendered as Markdown (so tables, bullet
 * lists, bold, and headings display properly, like ChatGPT).
 *
 * Data charts come from the typed, server-decided `visualization` field — never
 * from LLM-authored ```chart JSON, which is stripped below: the deterministic
 * pipeline builds charts from evidence, and a model free-writing its own
 * figures alongside it could disagree with them.
 *
 * ```mermaid blocks ARE still rendered. There is no server-side equivalent for
 * a diagram the model reasons out in prose (PROCESS_FLOW covers only
 * evidence-backed flows), so stripping them silently deleted content instead of
 * degrading it.
 */

/**
 * Safety net: strip any inline citation markers the model still slips into the
 * answer text (e.g. "[REF-1]", "[REF-2, REF-5]", "[1]"). Sources are shown in
 * the separate Sources panel, so the answer body should read cleanly. Also
 * strips stray ```chart fenced blocks a stale prompt/cached response might
 * still contain, rather than dumping raw JSON as text — charts are the
 * deterministic pipeline's job now (see websearch.py's
 * _FORMATTING_INSTRUCTIONS docstring for why). ```mermaid is deliberately NOT
 * stripped here: parseSegments below pulls those out and draws them. Also
 * tidies up the leftover spaces/punctuation the removals leave behind.
 */
function stripInlineRefs(text: string): string {
  return text
    .replace(/```chart\s*[\s\S]*?```/g, "")
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

// ── Figure toolbar ───────────────────────────────────────────────────────────
// Diagrams and prose tables share one small action row, so a user learns one
// control surface rather than two. Each button owns a short-lived status: an
// export that silently succeeds reads as one that did nothing, and
// clipboard/rasterization failures are real (permissions, browser support) and
// must be visible rather than swallowed.

type FigureAction = {
  key: string;
  label: string;
  doneLabel: string;
  icon: typeof Copy;
  onClick: () => void | Promise<void>;
};

function FigureToolbar({ actions, children }: { actions: FigureAction[]; children?: ReactNode }) {
  const [status, setStatus] = useState<Record<string, "idle" | "busy" | "done" | "error">>({});

  function flash(key: string, value: "done" | "error") {
    setStatus((prev) => ({ ...prev, [key]: value }));
    window.setTimeout(() => setStatus((prev) => ({ ...prev, [key]: "idle" })), 1800);
  }

  async function run(action: FigureAction) {
    setStatus((prev) => ({ ...prev, [action.key]: "busy" }));
    try {
      await action.onClick();
      flash(action.key, "done");
    } catch {
      flash(action.key, "error");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {actions.map((action) => {
        const state = status[action.key] ?? "idle";
        const Icon = action.icon;
        return (
          <button
            key={action.key}
            type="button"
            onClick={() => void run(action)}
            disabled={state === "busy"}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-semibold transition disabled:opacity-50 ${
              state === "error"
                ? "border-bad/40 text-bad"
                : state === "done"
                  ? "border-ok/40 text-ok"
                  : "border-line text-muted hover:border-brand/40 hover:text-brand"
            }`}
          >
            {state === "done" ? <CheckCircle2 size={11} /> : <Icon size={11} />}
            {state === "done" ? action.doneLabel : state === "error" ? "Failed" : action.label}
          </button>
        );
      })}
      {children}
    </div>
  );
}

// ── Mermaid diagrams from the answer text ────────────────────────────────────
// The one visual still authored by the model rather than by the deterministic
// pipeline: a flowchart/org-chart/mind-map it reasons out in prose has no
// evidence rows behind it, so there is nothing for orchestrator.py to build a
// spec from. Rendering is contained — an invalid diagram falls back to showing
// its own source rather than blanking or throwing.

type Segment = { type: "text"; content: string } | { type: "mermaid"; content: string };

function parseSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  const regex = /```mermaid\s*([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }
    segments.push({ type: "mermaid", content: match[1].trim() });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", content: text.slice(lastIndex) });
  }
  return segments;
}

/**
 * Repair the most common Mermaid mistakes LLMs make, so a small slip doesn't
 * blow up the whole diagram into a syntax error.
 */
function sanitizeMermaid(raw: string): string {
  let c = raw.trim();
  // Strip a stray leading "mermaid" language tag if the model added one.
  c = c.replace(/^mermaid\s+/i, "");
  // Most common error: an edge label written as `-->|Yes|>` (extra `>`) or
  // `-->|Yes|-->` instead of the valid `-->|Yes|`.
  c = c.replace(/\|\s*>/g, "|");
  // Curly/smart quotes inside labels break the parser — normalise them.
  c = c.replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
  return c;
}

function MermaidDiagram({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Dynamic import so mermaid (which touches the DOM) never runs on the server.
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "strict",
          // Don't let mermaid inject its own "bomb" error graphic into the page
          // when a diagram is malformed — we handle failures ourselves below.
          suppressErrorRendering: true,
        });
        const id = `kriton-mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, sanitizeMermaid(code));
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    // If the model produced invalid Mermaid, fall back to showing the raw code
    // rather than a blank space.
    return (
      <pre className="my-4 overflow-x-auto rounded-xl border border-line bg-soft p-4 text-xs leading-5 text-ink">
        {code}
      </pre>
    );
  }

  // Rasterized from the live SVG rather than re-rendered, so the exported image
  // is exactly the diagram on screen.
  async function diagramPng(): Promise<Blob> {
    const svg = ref.current?.querySelector("svg");
    if (!svg) throw new Error("Diagram is not ready yet");
    return await svgElementToPngBlob(svg as SVGSVGElement);
  }

  return (
    <figure className="my-4 min-w-0">
      <div ref={ref} className="flex justify-center overflow-x-auto" />
      <figcaption className="mt-2 flex justify-end">
        <FigureToolbar
          actions={[
            {
              key: "copy-image",
              label: "Copy image",
              doneLabel: "Copied",
              icon: Copy,
              onClick: async () => writeImageToClipboard(await diagramPng()),
            },
            {
              key: "download",
              label: "Download",
              doneLabel: "Downloaded",
              icon: Download,
              onClick: async () =>
                downloadBlob(await diagramPng(), safeDownloadName("kriton-diagram", "png")),
            },
          ]}
        />
      </figcaption>
    </figure>
  );
}

/** A table inside the answer prose — the rate/comparison tables Kriton writes
 * into its narrative, which are the ones a user most often wants in a
 * spreadsheet. Distinct from a chart's own table view, which reads the typed
 * spec; here the rendered DOM IS the source, so every column comes across
 * exactly as displayed. */
function MarkdownTable(props: ComponentPropsWithoutRef<"table">) {
  const ref = useRef<HTMLTableElement>(null);

  return (
    <div className="my-3 min-w-0">
      <div className="overflow-x-auto">
        <table ref={ref} className="w-full border-collapse text-left text-xs" {...props} />
      </div>
      <div className="mt-1.5 flex justify-end">
        <FigureToolbar
          actions={[
            {
              key: "copy-table",
              label: "Copy table",
              doneLabel: "Copied",
              icon: Table2,
              // TSV, not CSV: spreadsheets split TSV into cells straight off the
              // clipboard with no import dialog.
              onClick: async () => {
                if (!ref.current) throw new Error("Table is not ready yet");
                await writeTextToClipboard(tableRowsToTsv(tableElementToRows(ref.current)));
              },
            },
          ]}
        />
      </div>
    </div>
  );
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
  table: (props: ComponentPropsWithoutRef<"table">) => <MarkdownTable {...props} />,
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
  // Text is split so a ```mermaid block becomes a real diagram instead of a
  // code dump, while the prose around it still goes through Markdown. The
  // server-decided visualizations render after all of it, unaffected.
  //
  // One exception: when the pipeline DID build a structural visual from real
  // evidence, that one wins and any model-authored mermaid is dropped. Both can
  // occur together — the prompt asks for a mermaid diagram (websearch.py) before
  // the visualization decision is made, so the model cannot know a validated
  // diagram is already coming. Showing two diagrams of the same thing invites
  // the reader to spot the differences and trust the wrong one.
  const structuralViz = [visualization, ...(secondaryVisualizations ?? [])].some(
    (viz) => viz?.type === "PROCESS_FLOW" || viz?.type === "EVIDENCE_GRAPH",
  );
  const segments = parseSegments(text).filter(
    (seg) => !(structuralViz && seg.type === "mermaid"),
  );

  return (
    <div className={`w-full min-w-0 text-sm leading-7 text-ink ${className ?? ""}`}>
      {segments.map((seg, i) =>
        seg.type === "mermaid" ? (
          <MermaidDiagram key={i} code={seg.content} />
        ) : (
          <ReactMarkdown
            key={i}
            // singleDollarTextMath: false — "$94.8 billion ($94,827,000,000)" was
            // being parsed as inline math between the first and second $, rendering
            // the figure as stacked italic letters. Currency is far more common than
            // inline formulas in an accounting answer, so the dollar sign belongs to
            // money here. Display math ($$…$$) is unaffected; see
            // _FORMATTING_INSTRUCTIONS for the prompt side.
            remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
            rehypePlugins={[rehypeKatex]}
            components={mdComponents}
          >
            {stripInlineRefs(seg.content)}
          </ReactMarkdown>
        ),
      )}
      {visualization && <VisualizationRenderer viz={visualization} />}
      {secondaryVisualizations?.map((viz) => <VisualizationRenderer key={viz.id} viz={viz} />)}
    </div>
  );
}

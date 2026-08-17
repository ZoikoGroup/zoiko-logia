"use client";

import { useEffect, useRef, useState, type ComponentPropsWithoutRef, type ReactNode } from "react";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { CheckCircle2, Copy, Download, Table2 } from "lucide-react";
import { cssVar } from "@/lib/css-var";
import {
  canvasElementToPngBlob,
  downloadBlob,
  safeDownloadName,
  svgElementToPngBlob,
  tableElementToRows,
  tableRowsToTsv,
  writeImageToClipboard,
  writeTextToClipboard,
} from "@/lib/presentation";

// echarts-for-react touches the DOM (canvas), so load it client-only.
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

/**
 * Renders a Kriton answer. Text is rendered as Markdown (so tables, bullet
 * lists, bold, and headings display properly, like ChatGPT). A fenced
 * ```mermaid block becomes a diagram (flowchart, org chart, mind map, …), and
 * a fenced ```chart block (JSON) becomes a real data chart (bar / line / pie /
 * sankey) via Apache ECharts. Citations, risk badge and everything else are
 * unchanged.
 */

type Segment =
  | { type: "text"; content: string }
  | { type: "mermaid"; content: string }
  | { type: "chart"; content: string };

/**
 * Safety net: strip any inline citation markers the model still slips into the
 * answer text (e.g. "[REF-1]", "[REF-2, REF-5]", "[1]"). Sources are shown in
 * the separate Sources panel, so the answer body should read cleanly. Also
 * tidies up the leftover spaces/punctuation the removal leaves behind.
 */
function stripInlineRefs(text: string): string {
  return text
    .replace(/\s*\[\s*(?:REF-)?\d+(?:\s*,\s*(?:REF-)?\d+)*\s*\]/gi, "")
    .replace(/[ \t]+([.,;:])/g, "$1")
    .replace(/[ \t]{2,}/g, " ");
}

// ── Figure toolbar ───────────────────────────────────────────────────────────
// Charts, diagrams and tables all get the same small action row, so a user
// learns one control surface rather than three. Each button owns a short-lived
// status: an export that silently succeeds reads as one that did nothing, and
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

function parseSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  // Capture both ```mermaid (diagrams) and ```chart (data charts) blocks.
  const regex = /```(mermaid|chart)\s*([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }
    const kind = match[1] === "chart" ? "chart" : "mermaid";
    segments.push({ type: kind, content: match[2].trim() });
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
    <figure className="my-4">
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
              onClick: async () => downloadBlob(await diagramPng(), safeDownloadName("kriton-diagram", "png")),
            },
          ]}
        />
      </figcaption>
    </figure>
  );
}

// ── Data charts (Apache ECharts) ────────────────────────────────────────────
// The model emits a ```chart block containing a SIMPLE JSON spec (just data),
// not raw ECharts options — that keeps the model's job easy and reliable. This
// component maps the spec deterministically onto an ECharts option, so the
// chart always renders correctly from whatever data was provided.
type ChartSpec = {
  type?: "bar" | "line" | "pie" | "sankey";
  title?: string;
  categories?: string[];
  series?: { name?: string; data: number[] }[];
  data?: { name: string; value: number }[];
  nodes?: { name: string }[];
  links?: { source: string; target: string; value: number }[];
};

// Theme-tinted palette so charts sit consistently in the answer card in both
// light and dark mode — read live via cssVar() since ECharts can't consume
// var(--x) directly.
function chartPalette(): string[] {
  return [
    cssVar("--brand", "#16799a"),
    cssVar("--gold", "#f3c437"),
    cssVar("--ok", "#31a06a"),
    cssVar("--bad", "#e2725b"),
    cssVar("--info", "#0ea5b7"),
    cssVar("--brand-2", "#7b61ff"),
    cssVar("--warn", "#e18b2b"),
  ];
}

function buildChartOption(spec: ChartSpec): Record<string, unknown> {
  const ink = cssVar("--ink", "#17211f");
  const muted = cssVar("--muted", "#667673");
  const line = cssVar("--line", "#eef3f2");
  const title = spec.title
    ? { text: spec.title, left: "center", textStyle: { fontSize: 14, fontWeight: 600, color: ink } }
    : undefined;
  const color = chartPalette();

  if (spec.type === "pie") {
    return {
      color,
      title,
      tooltip: { trigger: "item" },
      legend: { bottom: 0, textStyle: { color: muted } },
      series: [
        {
          type: "pie",
          radius: ["35%", "62%"],
          center: ["50%", "46%"],
          data: spec.data ?? [],
          label: { color: ink },
        },
      ],
    };
  }

  if (spec.type === "sankey") {
    return {
      color,
      title,
      tooltip: { trigger: "item", triggerOn: "mousemove" },
      series: [
        {
          type: "sankey",
          data: spec.nodes ?? [],
          links: spec.links ?? [],
          emphasis: { focus: "adjacency" },
          label: { color: ink },
        },
      ],
    };
  }

  // bar / line (default)
  const isLine = spec.type === "line";
  const categoryCount = spec.categories?.length ?? 0;
  return {
    color,
    title,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, textStyle: { color: muted } },
    // containLabel keeps rotated axis labels and the y-axis inside the box.
    grid: { left: 8, right: 24, top: title ? 48 : 24, bottom: 48, containLabel: true },
    xAxis: {
      type: "category",
      data: spec.categories ?? [],
      axisLabel: {
        color: muted,
        interval: 0, // show every label, don't silently drop crowded ones
        // Rotate labels when there are several categories (e.g. many states)
        // so long names stay readable instead of overlapping.
        rotate: categoryCount > 4 ? 35 : 0,
        hideOverlap: false,
      },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: line } },
    },
    series: (spec.series ?? []).map((s) => ({
      name: s.name,
      type: isLine ? "line" : "bar",
      data: s.data,
      smooth: isLine,
      barMaxWidth: 54,
      // Print the value on each bar so amounts are readable at a glance.
      label: isLine ? undefined : { show: true, position: "top", color: ink, fontSize: 11 },
      ...(isLine ? { symbolSize: 7, lineStyle: { width: 3 } } : {}),
    })),
  };
}

// A chart block is "empty" when the model emitted the right shape but no actual
// numbers to plot (its data-honesty guardrail: it won't invent figures). Rather
// than render a blank ECharts frame — which just looks broken — we detect that
// and show a short, clear note instead.
function isChartEmpty(spec: ChartSpec): boolean {
  if (spec.type === "pie") return !(spec.data && spec.data.length > 0);
  if (spec.type === "sankey") return !(spec.links && spec.links.length > 0);
  const hasCategories = !!(spec.categories && spec.categories.length > 0);
  const hasSeriesData = !!(spec.series && spec.series.some((s) => s.data && s.data.length > 0));
  return !(hasCategories && hasSeriesData);
}

/** The chart's own numbers as table rows (header first) — the data behind
 * "View as table" and "Copy table". Derived from the same spec the chart is
 * drawn from, so the table can never disagree with the picture. */
function chartSpecToRows(spec: ChartSpec): string[][] {
  const num = (v: number) => (Number.isFinite(v) ? String(v) : "");

  if (spec.type === "pie") {
    return [["Name", "Value"], ...(spec.data ?? []).map((d) => [d.name, num(d.value)])];
  }
  if (spec.type === "sankey") {
    return [
      ["Source", "Target", "Value"],
      ...(spec.links ?? []).map((l) => [l.source, l.target, num(l.value)]),
    ];
  }
  const series = spec.series ?? [];
  const categories = spec.categories ?? [];
  return [
    ["Category", ...series.map((s, i) => s.name || `Series ${i + 1}`)],
    ...categories.map((c, row) => [c, ...series.map((s) => num(s.data?.[row]))]),
  ];
}

function ChartRenderer({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);

  let spec: ChartSpec | null = null;
  try {
    spec = JSON.parse(code) as ChartSpec;
  } catch {
    spec = null;
  }

  // Invalid JSON or missing type → show the raw block rather than a blank space.
  if (!spec || !spec.type) {
    return (
      <pre className="my-4 overflow-x-auto rounded-xl border border-line bg-soft p-4 text-xs leading-5 text-ink">
        {code}
      </pre>
    );
  }

  // Right shape but no numbers to plot → a clear note beats a blank chart frame.
  if (isChartEmpty(spec)) {
    return (
      <div className="my-4 rounded-xl border border-dashed border-line bg-soft p-4 text-xs leading-5 text-muted">
        No numeric data was available to plot this chart. Provide the figures
        (e.g. “State A 120, State B 90, State C 60”) and it will render as a chart.
      </div>
    );
  }

  const rows = chartSpecToRows(spec);
  const title = spec.title || "kriton-chart";

  // Rasterized from the canvas ECharts actually drew, so the export is exactly
  // what is on screen. next/dynamic does not forward refs, so the instance is
  // reached through the DOM rather than through a component ref.
  async function chartPng(): Promise<Blob> {
    const canvas = containerRef.current?.querySelector("canvas");
    if (!canvas) throw new Error("Chart is not ready yet");
    return await canvasElementToPngBlob(canvas as HTMLCanvasElement, cssVar("--panel", "#ffffff"));
  }

  return (
    <figure className="my-4 rounded-xl border border-line bg-panel p-3">
      <div ref={containerRef}>
        <ReactECharts option={buildChartOption(spec)} style={{ height: 380, width: "100%" }} notMerge />
      </div>

      {showTable && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-left text-xs">
            <thead className="bg-soft">
              <tr>
                {rows[0].map((cell, i) => (
                  <th key={i} className="border-b border-line px-3 py-2 font-semibold text-ink">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(1).map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border-b border-line px-3 py-2 align-top text-ink last:border-b-0">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <figcaption className="mt-2 flex justify-end">
        <FigureToolbar
          actions={[
            {
              key: "copy-image",
              label: "Copy image",
              doneLabel: "Copied",
              icon: Copy,
              onClick: async () => writeImageToClipboard(await chartPng()),
            },
            {
              key: "download",
              label: "Download",
              doneLabel: "Downloaded",
              icon: Download,
              onClick: async () => downloadBlob(await chartPng(), safeDownloadName(title, "png")),
            },
            {
              key: "copy-table",
              label: "Copy table",
              doneLabel: "Copied",
              icon: Table2,
              // TSV, not CSV: spreadsheets split TSV into cells straight off the
              // clipboard with no import dialog.
              onClick: async () => writeTextToClipboard(tableRowsToTsv(rows)),
            },
          ]}
        >
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-expanded={showTable}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2 py-1 text-[11px] font-semibold text-muted transition hover:border-brand/40 hover:text-brand"
          >
            <Table2 size={11} />
            {showTable ? "Hide table" : "View as table"}
          </button>
        </FigureToolbar>
      </figcaption>
    </figure>
  );
}

/** A table inside the answer prose — the rate/comparison tables Kriton writes
 * into its narrative, which are the ones a user most often wants in a
 * spreadsheet. Distinct from a chart's "Copy table", which reads the chart
 * spec; here the rendered DOM IS the source, so every column comes across
 * exactly as displayed. */
function MarkdownTable(props: ComponentPropsWithoutRef<"table">) {
  const ref = useRef<HTMLTableElement>(null);

  return (
    <div className="my-3">
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

export function AnswerRenderer({ text, className }: { text: string; className?: string }) {
  const segments = parseSegments(text);
  return (
    <div className={`min-w-0 text-sm leading-7 text-ink ${className ?? ""}`}>
      {segments.map((seg, i) =>
        seg.type === "mermaid" ? (
          <MermaidDiagram key={i} code={seg.content} />
        ) : seg.type === "chart" ? (
          <ChartRenderer key={i} code={seg.content} />
        ) : (
          <ReactMarkdown
            key={i}
            // singleDollarTextMath: false — "$94.8 billion ($94,827,000,000)"
            // was being parsed as inline math between the first and second $,
            // rendering the figure as stacked italic letters. Currency is far
            // more common than inline formulas in an accounting answer, so the
            // dollar sign belongs to money here. Display math ($$…$$) is
            // unaffected; see _FORMATTING_INSTRUCTIONS for the prompt side.
            remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
            rehypePlugins={[rehypeKatex]}
            components={mdComponents}
          >
            {stripInlineRefs(seg.content)}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}

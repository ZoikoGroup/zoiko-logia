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

/** A pipe-delimited table row: `| a | b |`, with optional leading spaces. */
const TABLE_ROW = /^ {0,3}\|.*\|\s*$/;
/** The `|---|:--:|` line that turns pipe rows into a real table. */
const TABLE_RULE = /^ {0,3}\|[\s:|-]+\|\s*$/;

/**
 * Make GFM tables render as tables.
 *
 * GitHub-flavoured Markdown only recognises a table when it STARTS A BLOCK, so
 * a table written immediately under its heading —
 *
 *     5. Quick-look sample of the Reconciliation table
 *     | Metric | Calculated | Reported |
 *     |--------|------------|----------|
 *
 * — is absorbed into the preceding paragraph and shown to the reader as rows of
 * literal pipe characters. The model does this often, and the answer looks
 * broken even though the content is right.
 *
 * A blank line is inserted before the table (and after it, so a following
 * paragraph is not swallowed). Rows indented four or more spaces are also
 * de-indented: at that depth Markdown treats them as a code block, and a code
 * block of pipes is never what was meant.
 */
function normaliseMarkdownTables(text: string): string {
  const lines = text.split("\n");
  const out: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const deindented = line.replace(/^\s+(?=\|)/, "");
    const isRow = TABLE_ROW.test(deindented);

    // A table proper needs a rule line directly under its header row, so only
    // treat this as the start of one when the next line is that rule.
    const startsTable =
      isRow && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1].replace(/^\s+(?=\|)/, ""));

    if (startsTable) {
      const previous = out[out.length - 1];
      if (previous !== undefined && previous.trim() !== "") out.push("");
    }

    if (isRow) {
      out.push(deindented);
      // Close the block when the next line is neither a row nor already blank.
      const next = lines[i + 1];
      const nextIsRow = next !== undefined && TABLE_ROW.test(next.replace(/^\s+(?=\|)/, ""));
      if (next !== undefined && !nextIsRow && next.trim() !== "") out.push("");
      continue;
    }

    out.push(line);
  }

  return out.join("\n");
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

/**
 * Mermaid diagram types, by the keyword that opens the block. Used to recognise
 * a diagram whose fence carries no language tag.
 *
 * The model is asked for ```mermaid and usually complies, but not always — the
 * same question can come back with a bare ``` fence, and then a perfectly good
 * diagram renders as a wall of monospace text. Sniffing the first keyword makes
 * the diagram appear either way, which matters more than the model's fence
 * discipline: the alternative is a feature that works intermittently for
 * reasons the reader cannot see.
 */
const MERMAID_OPENERS =
  /^\s*(?:%%\{[\s\S]*?\}%%\s*)?(flowchart|graph\s+(?:TB|TD|BT|RL|LR)|sequenceDiagram|classDiagram(?:-v2)?|stateDiagram(?:-v2)?|erDiagram|journey|gantt|pie(?:\s|$)|mindmap|timeline|quadrantChart|gitGraph|sankey-beta|xychart-beta|block-beta|requirementDiagram|C4Context)\b/i;

/** Language tags that mean "the model did not label this", as opposed to a
 *  genuine code block someone wants to read as code. */
const UNLABELLED_FENCE = /^(|text|txt|plaintext|plain|markdown|md|mmd)$/i;

function classifyFence(language: string, body: string): "mermaid" | "chart" | null {
  const lang = language.trim().toLowerCase();
  if (lang === "chart") return "chart";
  if (lang === "mermaid" || lang === "mmd") return "mermaid";
  // An unlabelled block that opens with a Mermaid keyword is a diagram the
  // model forgot to tag. A ```python or ```sql block is left alone.
  if (UNLABELLED_FENCE.test(lang) && MERMAID_OPENERS.test(body)) return "mermaid";
  return null;
}

function parseSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  // Every fenced block is examined; only diagram/chart blocks are extracted,
  // and anything else is left inside the surrounding markdown so real code
  // blocks still render as code.
  const regex = /```([A-Za-z0-9_+-]*)[ \t]*\r?\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const kind = classifyFence(match[1], match[2]);
    if (!kind) continue;                       // ordinary code block — leave it in the text
    if (match.index > lastIndex) {
      segments.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }
    segments.push({ type: kind, content: match[2].trim() });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", content: text.slice(lastIndex) });
  }
  return segments;
}

/**
 * Characters that make Mermaid reject an UNQUOTED node label.
 *
 * `(` and `&` are the ones that actually bite in this product: real accounting
 * labels are full of them — "Profit & Loss Account (Page 1)",
 * "Corporation Tax (25 %)" — and each one turns the whole diagram into a parse
 * error, which the renderer then shows as raw code. Quoting the label fixes it.
 *
 * `<` and `>` are deliberately absent: `<br/>` inside a label is a legitimate
 * line break that already works, and quoting is not needed for it.
 */
const LABEL_NEEDS_QUOTING = /[()&:;,%#=|]/;

/** Node shapes, longest delimiter first so `((x))` is not mistaken for `(x)`. */
const NODE_SHAPES: Array<[RegExp, string, string]> = [
  [/([A-Za-z0-9_-]+)\(\(([^()\n]*)\)\)/g, "((", "))"],
  [/([A-Za-z0-9_-]+)\[\[([^[\]\n]*)\]\]/g, "[[", "]]"],
  [/([A-Za-z0-9_-]+)\[\(([^[\]\n]*)\)\]/g, "[(", ")]"],
  [/([A-Za-z0-9_-]+)\[([^[\]\n]*)\]/g, "[", "]"],
  [/([A-Za-z0-9_-]+)\{([^{}\n]*)\}/g, "{", "}"],
];

function quoteNodeLabels(src: string): string {
  let out = src;
  for (const [pattern, open, close] of NODE_SHAPES) {
    out = out.replace(pattern, (whole, id: string, label: string) => {
      const trimmed = label.trim();
      // Already quoted, or nothing that needs it — leave exactly as written.
      if (!trimmed || /^".*"$/.test(trimmed) || !LABEL_NEEDS_QUOTING.test(trimmed)) {
        return whole;
      }
      // A double quote inside the label would close the quoting early; a single
      // quote reads the same to a human and parses.
      return `${id}${open}"${trimmed.replace(/"/g, "'")}"${close}`;
    });
  }
  return out;
}

/**
 * Repair the most common Mermaid mistakes LLMs make, so a small slip doesn't
 * blow up the whole diagram into a syntax error shown as raw code.
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
  // Non-breaking and narrow spaces come back from the model inside figures
  // ("25 %", "1 605 000") and are not valid label characters.
  c = c.replace(/[\u00a0\u202f\u2007\u2009]/g, " ");
  // Quote labels containing brackets, ampersands and the like. Only applied to
  // node/edge syntax, so `flowchart TD` and arrows are untouched.
  c = quoteNodeLabels(c);
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
  type?: "bar" | "line" | "pie" | "sankey" | "scatter" | "radar" | "heatmap" | "candlestick";
  title?: string;
  categories?: string[];
  /** Bar charts only: stacks the series when they are parts of one total. */
  stacked?: boolean;
  // `data` carries the y-values for bar/line/radar; `points` carries the
  // [x, y] pairs for scatter. A series uses one or the other, never both.
  series?: { name?: string; data?: number[]; points?: [number, number][] }[];
  data?: { name: string; value: number }[];
  nodes?: { name: string }[];
  links?: { source: string; target: string; value: number }[];
  // Scatter axis captions — the two measures being correlated.
  xName?: string;
  yName?: string;
  /** Radar spokes. `max` bounds each axis so profiles stay comparable. */
  indicators?: { name: string; max?: number }[];
  // Heatmap: `categories` is the x axis, `yCategories` the y axis, and each
  // cell is [xIndex, yIndex, value] — indices into those two arrays.
  yCategories?: string[];
  cells?: [number, number, number][];
  /** Candlestick rows, aligned to `categories`: [open, close, low, high]. */
  ohlc?: [number, number, number, number][];
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

  if (spec.type === "scatter") {
    return {
      color,
      title,
      tooltip: { trigger: "item" },
      legend: { bottom: 0, textStyle: { color: muted } },
      grid: { left: 8, right: 24, top: title ? 48 : 24, bottom: 56, containLabel: true },
      // Both axes are numeric here — a scatter plots one measure against
      // another, so neither side is a category list.
      xAxis: {
        type: "value",
        name: spec.xName,
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { color: muted },
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: line } },
      },
      yAxis: {
        type: "value",
        name: spec.yName,
        nameTextStyle: { color: muted },
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: line } },
      },
      series: (spec.series ?? []).map((s) => ({
        name: s.name,
        type: "scatter",
        data: s.points ?? [],
        symbolSize: 12,
      })),
    };
  }

  if (spec.type === "radar") {
    return {
      color,
      title,
      tooltip: { trigger: "item" },
      legend: { bottom: 0, textStyle: { color: muted } },
      radar: {
        indicator: (spec.indicators ?? []).map((i) => ({ name: i.name, max: i.max })),
        axisName: { color: muted },
        axisLine: { lineStyle: { color: line } },
        splitLine: { lineStyle: { color: line } },
        // The default alternating grey bands fight the answer card's own
        // background, so the web is drawn on the card instead.
        splitArea: { show: false },
      },
      series: [
        {
          type: "radar",
          data: (spec.series ?? []).map((s) => ({ name: s.name, value: s.data ?? [] })),
          areaStyle: { opacity: 0.15 },
        },
      ],
    };
  }

  if (spec.type === "heatmap") {
    const values = (spec.cells ?? []).map((c) => c[2]);
    return {
      title,
      tooltip: { position: "top" },
      grid: { left: 8, right: 24, top: title ? 56 : 32, bottom: 76, containLabel: true },
      xAxis: { type: "category", data: spec.categories ?? [], axisLabel: { color: muted } },
      yAxis: { type: "category", data: spec.yCategories ?? [], axisLabel: { color: muted } },
      visualMap: {
        min: values.length ? Math.min(...values) : 0,
        max: values.length ? Math.max(...values) : 1,
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        textStyle: { color: muted },
        // Ramp from the card's own background to the brand colour, so the
        // scale reads as part of the answer rather than a stock rainbow.
        inRange: { color: [cssVar("--panel", "#ffffff"), cssVar("--brand", "#16799a")] },
      },
      series: [{ type: "heatmap", data: spec.cells ?? [] }],
    };
  }

  if (spec.type === "candlestick") {
    return {
      title,
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      grid: { left: 8, right: 24, top: title ? 48 : 24, bottom: 48, containLabel: true },
      xAxis: { type: "category", data: spec.categories ?? [], axisLabel: { color: muted } },
      yAxis: {
        type: "value",
        // Price series rarely start near zero — let the axis frame the range
        // actually traded rather than squashing every candle at the top.
        scale: true,
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: line } },
      },
      series: [
        {
          type: "candlestick",
          data: spec.ohlc ?? [],
          itemStyle: {
            color: cssVar("--ok", "#31a06a"),
            color0: cssVar("--bad", "#e2725b"),
            borderColor: cssVar("--ok", "#31a06a"),
            borderColor0: cssVar("--bad", "#e2725b"),
          },
        },
      ],
    };
  }

  // bar / line (default)
  const isLine = spec.type === "line";
  const isStacked = !isLine && !!spec.stacked;
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
      data: s.data ?? [],
      smooth: isLine,
      barMaxWidth: 54,
      ...(isStacked ? { stack: "total" } : {}),
      // Print the value on each bar so amounts are readable at a glance.
      // Stacked bars are the exception: a top label would sit on the segment
      // above it, and an inside one is unreadable on the lighter palette
      // entries — the tooltip carries the numbers there instead.
      label:
        isLine || isStacked
          ? undefined
          : { show: true, position: "top", color: ink, fontSize: 11 },
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
  if (spec.type === "scatter") {
    return !spec.series?.some((s) => s.points && s.points.length > 0);
  }
  if (spec.type === "radar") {
    // A radar needs both the spokes and at least one profile plotted on them.
    const hasSpokes = !!spec.indicators?.length;
    return !(hasSpokes && spec.series?.some((s) => s.data && s.data.length > 0));
  }
  if (spec.type === "heatmap") return !(spec.cells && spec.cells.length > 0);
  if (spec.type === "candlestick") return !(spec.ohlc && spec.ohlc.length > 0);
  const hasCategories = !!(spec.categories && spec.categories.length > 0);
  const hasSeriesData = !!(spec.series && spec.series.some((s) => s.data && s.data.length > 0));
  return !(hasCategories && hasSeriesData);
}

/** The chart's own numbers as table rows (header first) — the data behind
 * "View as table" and "Copy table". Derived from the same spec the chart is
 * drawn from, so the table can never disagree with the picture. */
function chartSpecToRows(spec: ChartSpec): string[][] {
  // Accepts undefined so a ragged series (fewer points than categories)
  // exports as a blank cell rather than "undefined".
  const num = (v?: number) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");

  if (spec.type === "pie") {
    return [["Name", "Value"], ...(spec.data ?? []).map((d) => [d.name, num(d.value)])];
  }
  if (spec.type === "sankey") {
    return [
      ["Source", "Target", "Value"],
      ...(spec.links ?? []).map((l) => [l.source, l.target, num(l.value)]),
    ];
  }
  if (spec.type === "scatter") {
    // One row per point, tagged with its series, so a multi-series scatter
    // still pastes into a spreadsheet as a single flat table.
    return [
      [spec.xName || "X", spec.yName || "Y", "Series"],
      ...(spec.series ?? []).flatMap((s, i) =>
        (s.points ?? []).map((p) => [num(p[0]), num(p[1]), s.name || `Series ${i + 1}`]),
      ),
    ];
  }
  if (spec.type === "radar") {
    const spokes = spec.indicators ?? [];
    const profiles = spec.series ?? [];
    return [
      ["Indicator", ...profiles.map((s, i) => s.name || `Series ${i + 1}`)],
      ...spokes.map((spoke, row) => [spoke.name, ...profiles.map((s) => num(s.data?.[row]))]),
    ];
  }
  if (spec.type === "heatmap") {
    const xs = spec.categories ?? [];
    const ys = spec.yCategories ?? [];
    // Re-grid the sparse [x, y, value] cells into the matrix the chart shows;
    // any cell the model omitted exports blank rather than zero.
    const byIndex = new Map((spec.cells ?? []).map((c) => [`${c[0]}:${c[1]}`, c[2]]));
    return [
      ["", ...xs],
      ...ys.map((y, yi) => [y, ...xs.map((_, xi) => num(byIndex.get(`${xi}:${yi}`)))]),
    ];
  }
  if (spec.type === "candlestick") {
    return [
      ["Period", "Open", "Close", "Low", "High"],
      ...(spec.categories ?? []).map((c, i) => {
        const row = spec.ohlc?.[i];
        return [c, num(row?.[0]), num(row?.[1]), num(row?.[2]), num(row?.[3])];
      }),
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
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={mdComponents}
          >
            {normaliseMarkdownTables(stripInlineRefs(seg.content))}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}

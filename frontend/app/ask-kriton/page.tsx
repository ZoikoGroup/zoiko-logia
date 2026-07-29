"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CalculationWidget } from "@/components/CalculationWidget";
import { AnswerVisualizations } from "@/components/AnswerVisualizations";
import {
  AlertTriangle,
  ArrowUp,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  ExternalLink,
  FileText,
  FolderKanban,
  Globe,
  History,
  LayoutDashboard,
  Lightbulb,
  Link2,
  Loader2,
  MessageSquare,
  Mic,
  MoreVertical,
  Pencil,
  PenLine,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  askKriton,
  getAuthToken,
  ApiError,
  uploadDocument,
  listConversations,
  getConversation,
  renameConversation,
  deleteConversation,
  openSourceUrl,
  type AskKritonResponse,
  type ConversationSummary,
  type ChatMessage,
} from "@/lib/api";
import { useTypewriter } from "@/hooks/useTypewriter";
import { seriesColor } from "@/lib/chartColors";

// Web Speech API — not part of TypeScript's default DOM lib.
interface SpeechRecognitionResultLike {
  [index: number]: { [index: number]: { transcript: string } };
}
interface SpeechRecognitionEventLike {
  results: SpeechRecognitionResultLike;
}
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

type RiskLevel = "ZERO" | "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

type RecentEntry = {
  id: string;
  text: string;
  pinned: boolean;
  updatedAt: number;
  turns: ConversationTurn[];
};

const LEGACY_RECENTS_STORAGE_KEY = "kriton_recent_queries";
const RECENTS_STORAGE_KEY = "kriton_conversations_v2";
const ACTIVE_CONVERSATION_KEY = "kriton_active_conversation_v2";
const MAX_RECENTS = 12;

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];

const QUICK_MODES = [
  { label: "Source check", icon: BookOpen, prompt: "Review this question with eligible source grounding: " },
  { label: "Learn", icon: Lightbulb, prompt: "Explain this as a learning note without giving regulated advice: " },
  { label: "Write", icon: PenLine, prompt: "Draft a professional, source-aware explanation for: " },
  { label: "Workflow", icon: BriefcaseBusiness, prompt: "Turn this into a practical accounting workflow: " },
  { label: "Kriton's choice", icon: Sparkles, prompt: "" },
];

const RISK_STYLES: Record<
  RiskLevel,
  { bg: string; border: string; text: string; icon: typeof ShieldCheck; label: string }
> = {
  ZERO: { bg: "bg-soft", border: "border-line", text: "text-muted", icon: ShieldCheck, label: "No risk - casual" },
  LOW: { bg: "bg-ok/10", border: "border-ok/30", text: "text-ok", icon: ShieldCheck, label: "Low risk - verified" },
  MEDIUM: { bg: "bg-info/10", border: "border-info/30", text: "text-info", icon: ShieldCheck, label: "Medium risk - educational" },
  HIGH: { bg: "bg-warn/10", border: "border-warn/30", text: "text-warn", icon: ShieldAlert, label: "High risk - boundary applied" },
  RESTRICTED: { bg: "bg-bad/10", border: "border-bad/30", text: "text-bad", icon: ShieldOff, label: "Restricted - blocked" },
};

const RESPONSE_STAGES = [
  "Validating your request",
  "Screening safety controls",
  "Checking eligible sources",
  "Preparing a governed response",
];

const OUTCOME_PRESENTATION: Record<
  string,
  { label: string; tone: string }
> = {
  answered: { label: "Answer ready", tone: "text-ok" },
  clarification_required: { label: "One detail needed", tone: "text-info" },
  escalated: { label: "Human review", tone: "text-warn" },
  limited_response: { label: "Limited answer", tone: "text-warn" },
  refused: { label: "Unable to answer", tone: "text-bad" },
  rejected: { label: "Request blocked", tone: "text-bad" },
};

function readableState(value: string) {
  return value.replaceAll("_", " ");
}

function cleanDisplayText(value: string) {
  return value.replace(/\*\*(.*?)\*\*/g, "$1").replace(/\*\*/g, "").trim();
}

// Calling mermaid.initialize() at module scope (as this originally did)
// runs it during Next.js's server-side render pass too, before a real
// window/document exists — confirmed live this session: that leaves
// Mermaid's internal DOMPurify instance broken ("DOMPurify.addHook is not
// a function"), and every diagram then fails to render in the browser
// even though the Mermaid syntax itself was valid. Guarding this to run
// exactly once, only from inside a mounted client component (so a real
// DOM is guaranteed to exist), is the fix.
let mermaidInitialized = false;
function ensureMermaidInitialized() {
  if (mermaidInitialized) return;
  mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict" });
  mermaidInitialized = true;
}

// The typewriter effect feeds react-markdown a GROWING, partial string every
// tick. Headings/bold/lists degrade gracefully mid-reveal (literal '#'/'**'
// characters for one tick, then resolve) — but a fenced ```mermaid/
// ```kriton-chart block doesn't have that tolerance: a code fence whose
// language tag has been revealed but whose content hasn't yet (children
// still undefined) makes `String(children)` produce the literal 9-character
// string "undefined", which then gets handed to mermaid.render() or
// JSON.parse() and fails loudly and confusingly ("No diagram type detected
// ... for text: undefined"). Confirmed live this session. The fix: don't
// attempt to render these blocks at all until the reveal is finished —
// this context carries that signal down from TypedAnswerText, which
// already knows when revealed === the final text.
const RevealCompleteContext = createContext(true);

// Deterministic safety net for a known, recurring model mistake: a labeled
// edge written as '-->|Label|>' (a stray, invalid '>' right after the
// label's closing pipe) instead of the correct '-->|Label|'. The composition
// prompt already tells the model not to do this (see format_intent.py's
// _MERMAID_SYNTAX_RULE) — that instruction measurably reduces how often it
// happens but doesn't eliminate it (confirmed live: the identical mistake
// recurred on a later, unrelated query after the prompt fix shipped), since
// prompt instructions are a probabilistic nudge, not a hard guarantee. This
// closes the gap deterministically: there is no valid Mermaid construct
// where a label's closing '|' is legitimately followed by '>', so this
// rewrite can never break a well-formed diagram, only repair this one
// specific, already-documented malformed shape.
function sanitizeMermaidCode(code: string): string {
  return code.replace(/\|([^|\n]+)\|>/g, "|$1|");
}

// Renders a ```mermaid fenced block as an actual diagram. mermaid.render()
// is async and returns an SVG string — can't do this as a plain
// synchronous component the way the other Markdown overrides are, hence
// the effect + ref instead of returning JSX directly.
function MermaidDiagram({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const isRevealComplete = useContext(RevealCompleteContext);
  // One id per rendered instance — mermaid.render() writes to a DOM node
  // it creates internally keyed by this id; reusing one across multiple
  // diagrams on the same page would collide.
  const idRef = useRef(`mermaid-${Math.random().toString(36).slice(2, 10)}`);

  useEffect(() => {
    // Don't even attempt a render against a still-revealing (necessarily
    // partial/invalid) or empty code string — wait for the real thing.
    if (!isRevealComplete || !code.trim()) return;
    let cancelled = false;
    setError(null); // clear any stale failure from an earlier, unrelated attempt
    ensureMermaidInitialized();
    mermaid
      .render(idRef.current, sanitizeMermaidCode(code))
      .then(({ svg }) => {
        if (!cancelled && containerRef.current) containerRef.current.innerHTML = svg;
      })
      .catch((err) => {
        // Logged, not swallowed silently — a genuine Mermaid syntax error
        // from the model and an environment/init failure (like the
        // DOMPurify issue above) look identical to the user otherwise,
        // and only the console message tells them apart during debugging.
        console.error("Mermaid render failed:", err);
        // Malformed diagram syntax from the model — degrade to showing
        // nothing rendered rather than a broken half-drawn diagram; the
        // raw fenced block staying out of view is preferable to a JS
        // exception taking down the rest of the answer.
        if (!cancelled) setError("Diagram could not be rendered.");
      });
    return () => {
      cancelled = true;
    };
  }, [code, isRevealComplete]);

  if (!isRevealComplete) return null;
  if (error) return <p className="text-xs italic text-muted">{error}</p>;
  return <div ref={containerRef} className="my-3 flex justify-center overflow-x-auto" />;
}

type KritonChartSpec = {
  type: "line" | "bar";
  labels: string[];
  series: { name: string; values: number[] }[];
};


// Custom tooltip: values lead (Strong, primary ink), series name follows
// (secondary/muted) — the legend's hierarchy inverted, since here the
// reader already has the series and wants the number. A short line-key
// swatch carries identity instead of a filled box (tooltip-density ink).
function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name?: string; value?: number; color?: string }[]; label?: string }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-muted">{label}</p>
      <div className="space-y-1">
        {payload.map((entry, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="inline-block h-0.5 w-3 shrink-0" style={{ backgroundColor: entry.color }} aria-hidden="true" />
            <span className="text-muted">{entry.name}:</span>
            <span className="font-semibold text-ink">{entry.value?.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Legend text stays in a text token, never the series color (marks carry
// color; labels never do) — Recharts' default legend colors the text
// itself, so this overrides it with a small swatch + muted text instead.
function ChartLegend({ payload }: { payload?: { value?: string; color?: string }[] }) {
  if (!payload || payload.length < 2) return null; // single series needs no legend box
  return (
    <div className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1">
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-1.5 text-[11px]">
          <span className="inline-block h-0.5 w-3 shrink-0" style={{ backgroundColor: entry.color }} aria-hidden="true" />
          <span className="text-muted">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

// Renders a ```kriton-chart fenced block (JSON, see the format_intent
// instruction built server-side in orchestration/format_intent.py) as an
// actual chart instead of raw JSON text.
function KritonChart({ code }: { code: string }) {
  // Same reveal-race issue as MermaidDiagram above — a still-typing JSON
  // block is by definition invalid JSON on every tick but the last one;
  // don't show a "could not be parsed" flicker for what's just incomplete.
  const isRevealComplete = useContext(RevealCompleteContext);
  const [showTable, setShowTable] = useState(false);
  if (!isRevealComplete) return null;

  let spec: KritonChartSpec | null = null;
  try {
    spec = JSON.parse(code);
  } catch {
    return <p className="text-xs italic text-muted">Chart data could not be parsed.</p>;
  }
  if (!spec || !Array.isArray(spec.labels) || !Array.isArray(spec.series)) {
    return <p className="text-xs italic text-muted">Chart data was incomplete.</p>;
  }

  const data = spec.labels.map((label, i) => {
    const row: Record<string, string | number> = { label };
    for (const s of spec!.series) row[s.name] = s.values[i];
    return row;
  });
  const isBar = spec.type === "bar";
  const ChartComponent = isBar ? BarChart : LineChart;
  // "Label selectively — never a number on every point": direct bar labels
  // only when there's one series and few enough categories to stay legible;
  // otherwise every value is still fully reachable via the tooltip (and the
  // table-view toggle below) without cluttering the chart itself.
  const canDirectLabelBars = isBar && spec.series.length === 1 && spec.labels.length <= 8;

  return (
    <div className="my-3 w-full">
      <div className="mb-1.5 flex justify-end">
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          className="text-[11px] font-medium text-muted underline decoration-line hover:text-brand"
        >
          {showTable ? "View as chart" : "View as table"}
        </button>
      </div>

      {showTable ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-[13px]">
            <thead className="border-b border-line/70 bg-soft">
              <tr>
                <th className="px-3 py-1.5 text-left font-semibold text-ink">Label</th>
                {spec.series.map((s) => (
                  <th key={s.name} className="px-3 py-1.5 text-right font-semibold text-ink">{s.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i}>
                  <td className="border-t border-line/40 px-3 py-1.5 text-ink">{row.label}</td>
                  {spec!.series.map((s) => (
                    <td key={s.name} className="border-t border-line/40 px-3 py-1.5 text-right tabular-nums text-ink">
                      {(row[s.name] as number)?.toLocaleString()}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ChartComponent data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "var(--muted)" }}
                axisLine={{ stroke: "var(--line)" }}
                tickLine={{ stroke: "var(--line)" }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "var(--muted)" }}
                axisLine={{ stroke: "var(--line)" }}
                tickLine={{ stroke: "var(--line)" }}
                width={40}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--soft)" }} />
              {spec.series.length > 1 && <Legend content={<ChartLegend />} />}
              {spec.series.map((s, i) => {
                const color = seriesColor(i, spec!.series.length);
                if (isBar) {
                  return (
                    <Bar key={s.name} dataKey={s.name} fill={color} radius={[4, 4, 0, 0]} maxBarSize={24}>
                      {canDirectLabelBars && (
                        <LabelList dataKey={s.name} position="top" style={{ fill: "var(--ink)", fontSize: 11 }} />
                      )}
                    </Bar>
                  );
                }
                return (
                  <Line
                    key={s.name}
                    dataKey={s.name}
                    stroke={color}
                    strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, stroke: "var(--panel)", fill: color }}
                    activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--panel)" }}
                    label={(
                      // Recharts' own label-prop type (Props<RenderableText,...>)
                      // is broader than any hand-written shape matches (it keeps
                      // including more of its own internal union on each pass) —
                      // accepted as `any` at this one boundary and validated at
                      // runtime below instead, rather than chasing the type.
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      props: any
                    ) => {
                      // Endpoint-only label — the "value at the end" spec for
                      // lines, never one per point (that reads as chaos).
                      if (props.index !== data.length - 1) return <></>;
                      const x = Number(props.x ?? 0) + 6;
                      const y = Number(props.y ?? 0);
                      return (
                        <text x={x} y={y} dy={4} fontSize={11} fill="var(--ink)" fontWeight={600}>
                          {typeof props.value === "number" ? props.value.toLocaleString() : String(props.value ?? "")}
                        </text>
                      );
                    }}
                  />
                );
              })}
            </ChartComponent>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// Maps the model's Markdown output (see the formatting instruction in
// orchestration/service.py's grounded_input) to the page's existing type
// scale/colors instead of react-markdown's unstyled defaults.
const answerMarkdownComponents: Components = {
  h1: ({ ...props }) => <h1 className="mb-3 mt-1 text-xl font-bold leading-8 text-ink" {...props} />,
  h2: ({ ...props }) => <h2 className="mb-2 mt-5 text-base font-bold leading-7 text-ink first:mt-0" {...props} />,
  h3: ({ ...props }) => <h3 className="mb-2 mt-5 text-base font-bold leading-7 text-ink first:mt-0" {...props} />,
  p: ({ ...props }) => <p className="mb-3 text-[15px] leading-7 text-ink last:mb-0" {...props} />,
  ul: ({ ...props }) => <ul className="mb-3 ml-5 list-disc space-y-1.5 text-[15px] leading-7 text-ink" {...props} />,
  ol: ({ ...props }) => <ol className="mb-3 ml-5 list-decimal space-y-1.5 text-[15px] leading-7 text-ink" {...props} />,
  li: ({ ...props }) => <li className="pl-1" {...props} />,
  strong: ({ ...props }) => <strong className="font-semibold text-ink" {...props} />,
  em: ({ ...props }) => <em className="italic" {...props} />,
  a: ({ ...props }) => <a className="text-brand underline hover:no-underline" target="_blank" rel="noopener noreferrer" {...props} />,
  blockquote: ({ ...props }) => <blockquote className="mb-3 border-l-2 border-line pl-3 italic text-muted" {...props} />,
  hr: () => <hr className="my-4 border-line" />,
  table: ({ ...props }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13px]" {...props} />
    </div>
  ),
  thead: ({ ...props }) => <thead className="border-b border-line/70" {...props} />,
  th: ({ ...props }) => <th className="px-3 py-1.5 text-left font-semibold text-ink" {...props} />,
  td: ({ ...props }) => <td className="border-t border-line/40 px-3 py-1.5 text-ink" {...props} />,
  // react-markdown always wraps a fenced code block in <pre><code>...
  // — special-cased languages (mermaid/kriton-chart) render as a diagram/
  // chart instead, so `pre` has to skip its own box styling for those
  // rather than wrapping a rendered SVG/chart in a code-block frame.
  pre: ({ children, ...props }) => {
    const child = children as { props?: { className?: string } };
    const className = child?.props?.className ?? "";
    if (className.includes("language-mermaid") || className.includes("language-kriton-chart")) {
      return <>{children}</>;
    }
    return (
      <pre className="my-3 overflow-x-auto rounded-lg bg-soft p-3 text-[13px] leading-6 text-ink" {...props}>
        {children}
      </pre>
    );
  },
  code: ({ className, children, ...props }) => {
    const raw = String(children).replace(/\n$/, "");
    if (className?.includes("language-mermaid")) return <MermaidDiagram code={raw} />;
    if (className?.includes("language-kriton-chart")) return <KritonChart code={raw} />;
    return (
      <code className={`${className ?? ""} rounded bg-soft px-1 py-0.5 font-mono text-[13px]`} {...props}>
        {children}
      </code>
    );
  },
};

// Display-only — [REF-N] markers stay in turn.result.answer.text for
// Checkpoint C's grounding validation (massarius/answer_validator.py scans
// for exactly this pattern against source_bundle) and are never stripped
// there; this only affects what's rendered on screen. Sources are already
// shown separately via the citations list below the answer, so the inline
// marker is pure noise for the reader once it's on screen.
function stripCitationMarkers(value: string) {
  return value.replace(/\s?\[REF-\d+\]/g, "");
}

// Extracted to its own component (rather than calling useTypewriter directly
// inside the turns.map() callback below) because Hooks can't be called from
// inside a loop/callback — this is the one turn's answer text, revealed
// progressively. The backend already returned the complete, Checkpoint-C-
// validated text in one response; this is purely a client-side reveal
// animation, not real streaming of partial/unvalidated model output.
// react-markdown tolerates the mid-reveal, not-yet-closed '**'/'#' tokens
// useTypewriter hands it word by word — they render as literal characters
// for one tick, then resolve once the closing token arrives. A [REF-N]
// token straddling a reveal tick just shows its raw characters for one
// tick and vanishes once the closing ']' arrives — same graceful
// degradation already accepted for '**'/'#' tokens.
function TypedAnswerText({ text }: { text: string }) {
  const revealed = useTypewriter(text);
  const isRevealComplete = revealed.length >= text.length;
  return (
    <RevealCompleteContext.Provider value={isRevealComplete}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={answerMarkdownComponents}>
        {stripCitationMarkers(revealed)}
      </ReactMarkdown>
    </RevealCompleteContext.Provider>
  );
}

function sourcePreview(sourceId: string, url: string | null) {
  if (sourceId === "src-kriton-user-provided-data") {
    return { label: "Current request data", detail: "Values supplied in this conversation and used for validated calculations." };
  }
  if (url?.startsWith("http")) {
    try {
      return { label: new URL(url).hostname.replace(/^www\./, ""), detail: "Governed external publication used to support this answer." };
    } catch {
      // Keep the governed-source fallback below for malformed legacy URLs.
    }
  }
  return { label: "Kriton knowledge source", detail: "Reviewed source content used to support and validate this answer." };
}

function conversationTitle(query: string) {
  const value = query.replace(/[“”"']/g, "").trim();
  if (/quarterly.*profit|profit.*quarter/i.test(value)) return "Quarterly profit visualization";
  if (/budget.*actual|actual.*budget/i.test(value)) return "Budget vs actual analysis";
  if (/bank.*reconcil|reconcil.*bank/i.test(value)) return "Bank reconciliation process";
  if (/trial balance/i.test(value)) return "Trial balance preparation";
  if (/month.?end.*clos|financial closing/i.test(value)) return "Month-end close process";
  if (/cash.*receivable.*inventory/i.test(value)) return "Account balance comparison";
  const compact = value
    .replace(/^(?:can you|could you|please|show|give me|explain|compare|visuali[sz]e)\s+/i, "")
    .replace(/\s+/g, " ");
  return compact.length > 44 ? `${compact.slice(0, 41).trimEnd()}…` : compact || "New conversation";
}

function extractReviewCase(value: string) {
  const match = value.match(/\s*\(Review Case ([^)]+)\)/i);
  if (!match) return { message: cleanDisplayText(value), caseId: null };

  return {
    message: cleanDisplayText(value.replace(match[0], "")),
    caseId: match[1],
  };
}

function ZoikoGlyph({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <div className={`${className} relative shrink-0 overflow-hidden rounded-xl bg-brand shadow-[0_18px_44px_rgba(0,0,0,0.28)]`}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_18%,rgba(255,255,255,0.32),transparent_34%)]" />
      <div className="absolute left-[25%] top-[26%] h-[48%] w-[50%] rounded-sm border-[3px] border-white" />
      <div className="absolute bottom-[31%] left-[36%] h-[26%] w-[8%] bg-gold" />
      <div className="absolute bottom-[31%] left-[48%] h-[26%] w-[8%] bg-gold" />
      <div className="absolute bottom-[31%] left-[60%] h-[26%] w-[8%] bg-gold" />
    </div>
  );
}

function KritonThinking() {
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActiveStage((current) => Math.min(current + 1, RESPONSE_STAGES.length - 1));
    }, 900);

    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="kriton-message-in flex items-center gap-3 py-2" role="status" aria-live="polite">
      <Sparkles size={15} className="kriton-stage-icon shrink-0 text-brand" />
      <div className="min-w-0">
        <p className="text-xs font-bold uppercase tracking-[0.14em] text-ink">Kriton</p>
        <p key={activeStage} className="kriton-status-change mt-0.5 text-sm text-muted">
          {RESPONSE_STAGES[activeStage]}
        </p>
      </div>
      <span className="ml-1 flex items-center gap-1" aria-hidden="true">
        {RESPONSE_STAGES.map((stage, index) => (
          <span
            key={stage}
            className={`h-1.5 rounded-full transition-all duration-500 ${
              index === activeStage ? "w-4 bg-brand" : index < activeStage ? "w-1.5 bg-ok" : "w-1.5 bg-line"
            }`}
          />
        ))}
      </span>
    </div>
  );
}

function SidebarItem({
  icon: Icon,
  label,
  href,
  onClick,
}: {
  icon: typeof MessageSquare;
  label: string;
  href?: string;
  onClick?: () => void;
}) {
  const content = (
    <span className="flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink transition hover:bg-soft hover:text-ink">
      <Icon size={17} className="text-muted" />
      <span className="truncate">{label}</span>
    </span>
  );

  if (href) return <Link href={href}>{content}</Link>;
  return (
    <button type="button" onClick={onClick} className="w-full text-left">
      {content}
    </button>
  );
}

type ConversationTurn = {
  id: string;
  query: string;
  submittedQuery: string;
  loading: boolean;
  error: string;
  result: AskKritonResponse | null;
};

export default function AskKritonPage() {
  const [query, setQuery] = useState("");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [jurisdiction, setJurisdiction] = useState("");
  const [formError, setFormError] = useState("");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "uploading" | "ingested" | "error">("idle");
  const [uploadMsg, setUploadMsg] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [recents, setRecents] = useState<RecentEntry[]>([]);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const [activeConversationIdValue, setActiveConversationIdValue] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recentConversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function refreshConversations() {
    const token = getAuthToken();
    if (!token) return;
    try {
      setConversations(await listConversations(token));
      const stored = window.localStorage.getItem(RECENTS_STORAGE_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (!Array.isArray(parsed)) return;
      const normalized: RecentEntry[] = parsed
        .filter((item) => item && typeof item === "object" && Array.isArray(item.turns))
        .map((item, i) => ({
          ...item,
          text: String(item.text || "").length > 44
            ? conversationTitle(item.turns[0]?.query || item.text)
            : item.text || conversationTitle(item.turns[0]?.query || ""),
          updatedAt: item.updatedAt ?? Date.now() - i,
          turns: item.turns.map((turn: ConversationTurn) => turn.loading ? {
            ...turn,
            loading: false,
            error: turn.error || "The previous request was interrupted. Please send it again.",
          } : turn),
        }));
      setRecents(normalized);
      // A browser refresh starts on a clean composer, matching ChatGPT and
      // Claude's explicit New Chat behavior for this workspace. Conversations
      // remain in Recents and are restored only when the user selects one.
      window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
      // Remove the obsolete one-query-per-row format so it cannot continue
      // appearing beside the new conversation-session history.
      window.localStorage.removeItem(LEGACY_RECENTS_STORAGE_KEY);
    } catch {
      // Sidebar list is best-effort — a failed refresh just leaves the
      // previous list showing, never blocks the chat itself.
    }
  }

  useEffect(() => {
    refreshConversations();
  }, []);

  /** Rebuild a synthetic AskKritonResponse from a stored ChatMessage — the
   * DB only keeps role/content/route/risk_level (see chat_history.models),
   * not the full live-response shape (citations, source_bundle detail),
   * so a reopened conversation renders text + risk badge faithfully but
   * without re-fetching citations. */
  function responseFromMessage(msg: ChatMessage, conversationId: string): AskKritonResponse {
    const route = (msg.route ?? "LLM") as AskKritonResponse["route"];
    const outcome: AskKritonResponse["outcome"] =
      route === "REFUSAL" ? "refused"
      : route === "CLARIFICATION" ? "clarification_required"
      : route === "HUMAN_REVIEW" || route === "SECURITY_INCIDENT" ? "escalated"
      : route === "REJECTED" ? "rejected"
      : "answered";
    const answered = outcome === "answered";
    return {
      query_id: msg.id,
      correlation_id: "",
      outcome,
      route,
      safety: { risk_level: (msg.risk_level ?? "LOW") as AskKritonResponse["safety"]["risk_level"], policy_state: "allowed", disclaimer_required: false },
      confidence_state: "sufficient",
      source_bundle: null,
      answer: answered ? { text: msg.content, citations: msg.citations ?? [], limitations: [] } : null,
      next_action: answered ? null : { type: "history", message: msg.content },
      audit_reference: { audit_chain_id: "" },
      conversation_id: conversationId,
    };
  }

  async function openConversation(id: string) {
    const token = getAuthToken();
    if (!token) return;
    setOpenMenuId(null);
    try {
      const detail = await getConversation(token, id);
      const paired: ConversationTurn[] = [];
      for (const msg of detail.messages) {
        if (msg.role === "user") {
          paired.push({ id: msg.id, query: msg.content, submittedQuery: msg.content, loading: false, error: "", result: null });
        } else if (paired.length > 0) {
          paired[paired.length - 1].result = responseFromMessage(msg, id);
        }
      }
      setTurns(paired);
      setActiveConversationId(id);
      setQuery("");
      setFormError("");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not load that conversation.");
    }
  }

  function persistRecents(next: RecentEntry[]) {
    try {
      window.localStorage.setItem(RECENTS_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore write failures
    }
  }

  function saveConversation(q: string, conversationTurns: ConversationTurn[]) {
    const id = recentConversationIdRef.current ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    recentConversationIdRef.current = id;
    setActiveConversationIdValue(id);
    window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, id);
    setRecents((prev) => {
      const existing = prev.find((entry) => entry.id === id);
      const entry: RecentEntry = {
        id,
        text: existing?.text || conversationTitle(q),
        pinned: existing?.pinned ?? false,
        updatedAt: Date.now(),
        turns: conversationTurns,
      };
      const withoutCurrent = prev.filter((recent) => recent.id !== id);
      const next = [entry, ...withoutCurrent]
        .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updatedAt - a.updatedAt)
        .slice(0, MAX_RECENTS);
      persistRecents(next);
      return next;
    });
  }

  function togglePin(id: string) {
    setRecents((prev) => {
      const toggled = prev.map((r) => (r.id === id ? { ...r, pinned: !r.pinned } : r));
      const next = [...toggled.filter((r) => r.pinned), ...toggled.filter((r) => !r.pinned)];
      persistRecents(next);
      return next;
    });
    setOpenMenuId(null);
  }

  function deleteRecent(id: string) {
    setRecents((prev) => {
      const next = prev.filter((r) => r.id !== id);
      persistRecents(next);
      return next;
    });
    if (recentConversationIdRef.current === id) {
      recentConversationIdRef.current = null;
      setActiveConversationIdValue(null);
      window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
      setTurns([]);
    }
    setOpenMenuId(null);
  }

  function startRename(entry: RecentEntry) {
    setEditingId(entry.id);
    setEditText(entry.text);
    setOpenMenuId(null);
  }

  async function renameConversationEntry(id: string) {
    const token = getAuthToken();
    const trimmed = editText.trim();
    setEditingId(null);
    if (!token || !trimmed) return;
    try {
      const updated = await renameConversation(token, id, trimmed);
      setConversations((prev) => prev.map((c) => (c.id === id ? updated : c)));
    } catch {
      // best-effort — sidebar just keeps the old title on failure
    }
  }

  async function deleteConversationEntry(id: string) {
    setOpenMenuId(null);
    const token = getAuthToken();
    if (!token) return;
    try {
      await deleteConversation(token, id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConversationId === id) startNewChat();
    } catch {
      // best-effort — entry just stays in the sidebar on failure
    }
  }

  function startNewChat() {
    recentConversationIdRef.current = null;
    setActiveConversationIdValue(null);
    window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
    setTurns([]);
    setQuery("");
    setFormError("");
    setActiveConversationId(null);
  }

  function openEvidenceView(citation: NonNullable<AskKritonResponse["answer"]>["citations"][number], turn: ConversationTurn) {
    const key = `evidence-${turn.result?.correlation_id ?? turn.id}-${citation.source_id}`;
    const payload = {
      title: citation.title,
      sourceId: citation.source_id,
      sourceUrl: citation.url,
      excerpt: citation.evidence_preview || "No additional excerpt is available for this source.",
      query: turn.query,
      correlationId: turn.result?.correlation_id,
      savedAt: Date.now(),
    };
    window.localStorage.setItem(key, JSON.stringify(payload));
    window.open(
      `/source-preview?key=${encodeURIComponent(key)}`,
      `kriton-evidence-${citation.source_id}`,
      "popup=yes,width=720,height=720,resizable=yes,scrollbars=yes,noopener,noreferrer",
    );
  }

  function toggleVoiceInput() {
    const SpeechRecognitionCtor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) {
      setFormError("Voice input isn't supported in this browser — try Chrome or Edge.");
      return;
    }
    if (isListening) {
      recognitionRef.current?.stop();
      return;
    }
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? "";
      if (transcript) setQuery((prev) => (prev ? `${prev} ${transcript}` : transcript));
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);
    recognitionRef.current = recognition;
    setIsListening(true);
    recognition.start();
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadedFile(file);
    setUploadStatus("uploading");
    setUploadMsg("");
    try {
      const token = getAuthToken();
      if (!token) {
        setUploadStatus("error");
        setUploadMsg("Please sign in before uploading documents.");
        return;
      }
      const res = await uploadDocument(token, file);
      setUploadStatus("ingested");
      setUploadMsg(`${res.chunks_stored} chunks indexed - ${res.title}`);
    } catch (err) {
      setUploadStatus("error");
      setUploadMsg(err instanceof ApiError ? err.message : "Upload failed. Please try again.");
    }
  }

  function clearUpload() {
    setUploadedFile(null);
    setUploadStatus("idle");
    setUploadMsg("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    const token = getAuthToken();
    if (!token) {
      setFormError("Please sign in before asking Kriton.");
      return;
    }
    setFormError("");
    setQuery("");

    const turnId = `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    // Every submitted composer message is an independent query. Automatic
    // clarification concatenation contaminated later standalone prompts with
    // prior topics and presentation words (timeline/checklist/chart).
    const submittedQuery = trimmed;
    const pendingTurn: ConversationTurn = {
      id: turnId,
      query: trimmed,
      submittedQuery,
      loading: true,
      error: "",
      result: null,
    };
    const pendingConversation = [...turns, pendingTurn];
    setTurns(pendingConversation);
    saveConversation(trimmed, pendingConversation);

    try {
      const idempotencyKey = `idem-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      // Prior turns' queries only, never the composed answers — capped to
      // the last few since the backend only ever needs the most recent one
      // to resolve an elliptical follow-up, not the full conversation.
      const history = turns.map((t) => t.query).slice(-3);
      const response = await askKriton(
        token,
        {
          query: submittedQuery,
          jurisdiction,
          mode: "Workflow",
          history,
          conversation_id: activeConversationId,
          clarification_cycle: 0,
        },
        idempotencyKey,
      );
      const completedConversation = pendingConversation.map((t) =>
        t.id === turnId ? { ...t, loading: false, result: response } : t
      );
      setTurns(completedConversation);
      saveConversation(trimmed, completedConversation);
      if (response.conversation_id) {
        const isNewConversation = response.conversation_id !== activeConversationId;
        setActiveConversationId(response.conversation_id);
        if (isNewConversation) refreshConversations();
        else setConversations((prev) => {
          const bumped = prev.find((c) => c.id === response.conversation_id);
          if (!bumped) return prev;
          return [{ ...bumped, updated_at: new Date().toISOString() }, ...prev.filter((c) => c.id !== response.conversation_id)];
        });
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not reach the orchestration service.";
      const failedConversation = pendingConversation.map((t) =>
        t.id === turnId ? { ...t, loading: false, error: message } : t
      );
      setTurns(failedConversation);
      saveConversation(trimmed, failedConversation);
    }
  }

  const hasConversation = turns.length > 0;
  const isLoading = turns.some((t) => t.loading);

  return (
    <main className="relative h-screen w-full min-w-0 overflow-hidden bg-soft text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,var(--panel)_0%,var(--soft)_46%,var(--bg)_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-soft" />
      <div className="relative z-10 grid h-screen w-full min-w-0 grid-cols-1 md:grid-cols-[252px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 border-r border-line bg-soft md:flex md:flex-col">
          <div className="flex items-center justify-between px-5 py-5">
            <div className="flex items-center gap-3">
              <ZoikoGlyph className="h-9 w-9 rounded-lg" />
              <div>
                <div className="text-lg font-bold tracking-normal text-ink">Kriton</div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">ZoikoLogia</div>
              </div>
            </div>
            <div className="text-muted">
              <Search size={17} />
            </div>
          </div>

          <nav className="space-y-1 px-3">
            <SidebarItem icon={Plus} label="New chat" onClick={startNewChat} />
            <SidebarItem icon={FolderKanban} label="Projects" href="/my-workspace" />
            <SidebarItem icon={BookOpen} label="Sources" href="/source-licensing" />
          </nav>

          {conversations.length > 0 ? (
            <div className="mt-6 flex min-h-0 flex-1 flex-col px-5">
              <p className="mb-2 text-xs font-bold text-muted">Chats</p>
              <div className="min-h-0 space-y-0.5 overflow-y-auto pr-1">
                {conversations.map((entry) => (
                  <div
                    key={entry.id}
                    className={`group relative flex items-center rounded-lg hover:bg-soft ${
                      activeConversationId === entry.id ? "bg-soft" : ""
                    }`}
                  >
                    {editingId === entry.id ? (
                      <input
                        autoFocus
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onBlur={() => renameConversationEntry(entry.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") renameConversationEntry(entry.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        className="h-9 w-full rounded-lg border border-brand/40 bg-panel px-2 text-sm text-ink outline-none"
                      />
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => openConversation(entry.id)}
                          className="flex h-9 min-w-0 flex-1 items-center gap-1.5 truncate rounded-lg px-2 text-left text-sm font-medium text-muted hover:text-ink"
                        >
                          <span className="truncate">{entry.title}</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setOpenMenuId(openMenuId === entry.id ? null : entry.id)}
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted opacity-0 transition group-hover:opacity-100 hover:bg-line/50"
                          aria-label="More options"
                        >
                          <MoreVertical size={14} />
                        </button>
                      </>
                    )}

                    {openMenuId === entry.id && (
                      <div className="absolute right-0 top-9 z-20 w-40 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-lg">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingId(entry.id);
                            setEditText(entry.title);
                            setOpenMenuId(null);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-ink hover:bg-soft"
                        >
                          <Pencil size={13} /> Rename
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteConversationEntry(entry.id)}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-bad hover:bg-bad/10"
                        >
                          <Trash2 size={13} /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                    ))}
              </div>
            </div>
          ) : (
            <p className="rounded-lg px-2 py-3 text-xs leading-5 text-muted">Your conversation sessions will appear here after you send a question.</p>
          )}

          {openMenuId && <div className="fixed inset-0 z-10" onClick={() => setOpenMenuId(null)} />}

          <div className="border-t border-line px-3 py-3">
            <SidebarItem icon={LayoutDashboard} label="Back to Dashboard" href="/" />
          </div>
        </aside>

        <section className="relative flex min-h-0 min-w-0 flex-col">
          <header className="relative z-10 flex h-14 items-center justify-between border-b border-line bg-panel/80 px-4 md:hidden">
            <div className="flex items-center gap-2">
              <ZoikoGlyph className="h-8 w-8 rounded-lg" />
              <span className="font-bold">Kriton</span>
            </div>
            <button type="button" onClick={() => setMobileHistoryOpen(true)} className="rounded-lg p-2 text-muted hover:bg-soft hover:text-ink" aria-label="Open recent chats">
              <History size={18} />
            </button>
          </header>

          {mobileHistoryOpen && (
            <div className="fixed inset-0 z-50 md:hidden">
              <button type="button" className="absolute inset-0 bg-black/35" onClick={() => setMobileHistoryOpen(false)} aria-label="Close recent chats" />
              <aside className="absolute inset-y-0 left-0 w-[86%] max-w-sm overflow-y-auto border-r border-line bg-panel p-4 shadow-2xl">
                <div className="flex items-center justify-between">
                  <h2 className="font-bold">Recent chats</h2>
                  <button type="button" onClick={() => setMobileHistoryOpen(false)} className="rounded-lg p-2 text-muted hover:bg-soft" aria-label="Close"><X size={18} /></button>
                </div>
                <button type="button" onClick={() => { startNewChat(); setMobileHistoryOpen(false); }} className="mt-4 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold hover:bg-soft">
                  <Plus size={15} /> New chat
                </button>
                {recents.length ? (
                  <div className="mt-5 space-y-0.5">
                        {recents.map((entry) => (
                          <button key={entry.id} type="button" onClick={() => {
                            recentConversationIdRef.current = entry.id;
                            setActiveConversationIdValue(entry.id);
                            window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, entry.id);
                            setTurns(entry.turns);
                            setQuery("");
                            setMobileHistoryOpen(false);
                          }} className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2.5 text-left text-sm font-semibold ${activeConversationIdValue === entry.id ? "bg-soft text-ink" : "text-muted hover:bg-soft hover:text-ink"}`}>
                            <MessageSquare size={13} className="shrink-0" /><span className="truncate">{entry.text}</span>
                          </button>
                        ))}
                  </div>
                ) : (
                  <p className="mt-5 rounded-lg bg-soft p-3 text-xs leading-5 text-muted">Your conversation sessions will appear here after you send a question.</p>
                )}
              </aside>
            </div>
          )}

          <div className="relative z-10 flex-1 overflow-y-auto px-4">
            <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col items-center justify-center pb-16 pt-6 md:pb-24 md:pt-8">
              {!hasConversation ? (
                <div className="flex w-full max-w-3xl flex-col items-center text-center">
                  <div className="w-full">
                    <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-brand shadow-sm">
                      <Sparkles size={14} />
                      Ask Kriton
                    </div>
                    <h1 className="text-balance text-4xl font-bold tracking-normal text-ink md:text-5xl">
                      Get a governed answer from your sources.
                    </h1>
                    <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-muted">
                      Ask accounting, audit, and policy questions with source checks, risk routing, and audit history kept in the flow.
                    </p>
                  </div>

                  <form onSubmit={handleSubmit} className="mt-8 w-full">
                    <div className="rounded-[1.75rem] border border-line bg-panel p-4 shadow-[0_18px_48px_rgba(18,34,32,0.08)]">
                      <textarea
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Ask Kriton..."
                        rows={2}
                        className="min-h-20 w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-base font-medium leading-7 text-ink !shadow-none outline-none placeholder:text-muted"
                      />

                      {uploadedFile && (
                        <div className={`mb-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-[11px] font-semibold ${
                          uploadStatus === "ingested"
                            ? "border-ok/30 bg-ok/10 text-ok"
                            : uploadStatus === "error"
                              ? "border-bad/30 bg-bad/10 text-bad"
                              : "border-info/30 bg-info/10 text-info"
                        }`}>
                          {uploadStatus === "ingested" ? <CheckCircle2 size={12} /> : uploadStatus === "error" ? <X size={12} /> : <FileText size={12} />}
                          <span className="flex-1 truncate">
                            {uploadStatus === "uploading" ? `Processing ${uploadedFile.name}...` : uploadMsg || uploadedFile.name}
                          </span>
                          <button type="button" onClick={clearUpload} className="rounded p-1 hover:bg-white/10" aria-label="Clear uploaded file">
                            <X size={11} />
                          </button>
                        </div>
                      )}

                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.xlsx,.pptx" className="hidden" onChange={handleFileChange} />
                          <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={uploadStatus === "uploading"}
                            className="flex h-10 w-10 items-center justify-center rounded-full text-ink transition hover:bg-soft disabled:opacity-40"
                            aria-label="Upload document"
                          >
                            {uploadStatus === "uploading" ? <Loader2 size={18} className="animate-spin" /> : <Plus size={23} />}
                          </button>
                        </div>

                        <div className="flex min-w-0 items-center justify-end gap-2">
                          <select
                            value={jurisdiction}
                            onChange={(e) => setJurisdiction(e.target.value)}
                            className="hidden h-9 rounded-full !border-transparent !bg-soft px-3 text-xs font-semibold text-ink !shadow-none outline-none hover:bg-soft sm:block"
                          >
                            {JURISDICTIONS.map((j) => (
                              <option key={j} value={j} className="bg-panel text-ink">{j || "Any"}</option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={toggleVoiceInput}
                            className={`hidden h-9 w-9 items-center justify-center rounded-full transition hover:bg-soft lg:flex ${isListening ? "text-bad" : "text-muted"}`}
                            aria-label={isListening ? "Stop voice input" : "Voice input"}
                            title={isListening ? "Stop voice input" : "Voice input"}
                          >
                            <Mic size={19} className={isListening ? "animate-pulse" : ""} />
                          </button>
                          <button
                            type="submit"
                            disabled={isLoading || !query.trim()}
                            className="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-white transition hover:bg-brand-2 disabled:opacity-40"
                            aria-label="Ask Kriton"
                          >
                            {isLoading ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
                          </button>
                        </div>
                      </div>
                    </div>

                    {formError && (
                      <p className="mt-3 rounded-xl border border-bad/30 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                        {formError}
                      </p>
                    )}
                  </form>

                  <div className="mt-5 grid w-full grid-cols-2 gap-2 md:grid-cols-5">
                    {QUICK_MODES.map(({ label, icon: ModeIcon, prompt }) => (
                      <button
                        key={label}
                        type="button"
                        onClick={() => setQuery((current) => `${prompt}${current}`.trim())}
                        className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-line bg-panel px-2 text-xs font-bold text-ink shadow-sm transition hover:border-brand/30 hover:bg-soft"
                      >
                        <ModeIcon size={16} />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="mx-auto w-full max-w-3xl space-y-8 md:translate-x-8 lg:translate-x-12">
                  {turns.map((turn) => {
                    const safety = turn.result?.safety ?? null;
                    const riskLevel = (safety?.risk_level ?? "LOW") as RiskLevel;
                    const style = safety ? RISK_STYLES[riskLevel] : null;
                    const outcome = turn.result?.outcome ?? null;
                    const outcomePresentation = OUTCOME_PRESENTATION[outcome ?? ""] ?? {
                      label: "Response complete",
                      tone: style?.text ?? "text-brand",
                    };
                    const action = turn.result?.next_action
                      ? extractReviewCase(turn.result.next_action.message)
                      : null;

                    return (
                      <div key={turn.id} className="space-y-4 border-b border-line/60 pb-8 last:border-b-0">
                        <div className="kriton-user-message-in flex justify-end pr-5 sm:pr-8 lg:pr-10">
                          <div className="max-w-[76%] rounded-2xl rounded-tr-md border border-brand/20 bg-brand/10 px-4 py-2.5 text-sm font-medium leading-6 text-ink">
                            {turn.query}
                          </div>
                        </div>

                        {turn.loading && <KritonThinking />}

                        {!turn.loading && turn.error && (
                          <div className="kriton-message-in flex items-start gap-3 py-2">
                            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-bad" />
                            <div>
                              <p className="text-sm font-semibold text-bad">Kriton could not respond</p>
                              <p className="mt-1 text-xs leading-5 text-muted">{turn.error}</p>
                            </div>
                          </div>
                        )}

                        {turn.result && safety && (
                          <article className="kriton-response-in min-w-0 py-2">
                              <header className="flex flex-wrap items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-bold text-ink">Kriton</span>
                                  <span className={`h-1.5 w-1.5 rounded-full ${outcomePresentation.tone.replace("text-", "bg-")}`} aria-hidden="true" />
                                  <span className={`text-xs font-medium ${outcomePresentation.tone}`}>
                                    {outcomePresentation.label}
                                  </span>
                                </div>
                                  <Link
                                    href={`/audit-replay?correlation_id=${encodeURIComponent(turn.result.correlation_id)}`}
                                    className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-muted transition hover:text-brand"
                                    aria-label="View audit"
                                  >
                                    <History size={12} />
                                    View audit
                                  </Link>
                              </header>

                              <section className="mt-3 min-w-0">
                              {turn.result.answer ? (
                                <>
                                  <div className="kriton-answer-reveal min-w-0 text-[15px] leading-7 text-ink">
                                    <TypedAnswerText text={turn.result.answer.text} />
                                  </div>
                                    {turn.result.answer.presentation && (
                                      <AnswerVisualizations
                                        presentation={turn.result.answer.presentation}
                                        onFollowUp={(question) => setQuery(`${question} Context: ${turn.query}`)}
                                      />
                                    )}
                                    {turn.result.answer.calculation_widget && (
                                      <CalculationWidget data={turn.result.answer.calculation_widget} />
                                    )}
                                    {turn.result.answer.citations.length > 0 && (
                                      <div className="mt-5 border-t border-line/70 pt-3">
                                        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Sources</p>
                                        <ul className="mt-2 space-y-1.5">
                                          {turn.result.answer.citations.map((c) => {
                                            const preview = sourcePreview(c.source_id, c.url);
                                            // source_url is the legacy, live-data-only field; url is the
                                            // general one (external link for a live source, or a
                                            // `/sources/{id}/file` internal link for a document) — prefer
                                            // url, fall back to source_url only if url is unset.
                                            const resolvedUrl = c.url || c.source_url || null;
                                            return (
                                              <li key={c.ref_id} className="flex max-w-full items-center gap-1">
                                                <button
                                                  type="button"
                                                  onClick={() => openEvidenceView(c, turn)}
                                                  title={preview.detail}
                                                  className="group inline-flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium text-brand hover:text-brand-2 hover:underline hover:underline-offset-2"
                                                >
                                                  {c.source_id === "src-kriton-user-provided-data" ? <MessageSquare size={14} className="shrink-0" />
                                                    : c.source_type === "live_api" ? <Globe size={14} className="shrink-0" />
                                                    : <FileText size={14} className="shrink-0" />}
                                                  <span className="truncate">{c.title}</span>
                                                  <span className="shrink-0 text-[10px] font-normal text-muted">· {preview.label}</span>
                                                  <ExternalLink size={11} className="shrink-0 opacity-60" />
                                                </button>
                                                {resolvedUrl && (
                                                  <button
                                                    type="button"
                                                    onClick={() => {
                                                      const token = getAuthToken();
                                                      if (token) openSourceUrl(token, resolvedUrl);
                                                    }}
                                                    title={`Open source directly: ${resolvedUrl}`}
                                                    className="shrink-0 rounded-md p-1 text-muted hover:bg-soft hover:text-brand"
                                                  >
                                                    <Link2 size={13} />
                                                  </button>
                                                )}
                                              </li>
                                            );
                                          })}
                                        </ul>
                                      </div>
                                    )}
                                  </>
                              ) : action ? (
                                <div>
                                  <p className="text-[15px] font-medium leading-7 text-ink">{action.message}</p>
                                  {action.caseId && (
                                    <span
                                      title={`Review Case ${action.caseId}`}
                                      className="mt-3 inline-flex items-center gap-1.5 border-b border-warn/40 pb-0.5 font-mono text-[10px] font-semibold text-warn"
                                    >
                                      Review case / {action.caseId.slice(0, 8)}
                                    </span>
                                  )}
                                </div>
                              ) : (
                                <p className="text-sm italic leading-6 text-muted">
                                    {outcome === "escalated"
                                      ? "This query has been escalated for human review. No AI-generated response is returned until a qualified reviewer clears it."
                                      : outcome === "clarification_required"
                                        ? "Kriton needs more context to route this query correctly. Please respond to the clarification above."
                                        : outcome === "rejected"
                                          ? "This request was blocked before processing."
                                          : "This query was refused by the policy engine. No response was composed."}
                                  </p>
                                )}

                              {turn.result.answer && action && (
                                <div className="mt-4 border-l-2 border-info pl-3 text-sm leading-6 text-ink">
                                  <span className="block text-[10px] font-bold uppercase tracking-[0.14em] text-info">Next step</span>
                                  {action.message}
                                </div>
                                )}

                              {turn.result.answer?.limitations && turn.result.answer.limitations.length > 0 && (
                                  <div className="mt-4 space-y-1.5 text-xs leading-5 text-muted">
                                    {turn.result.answer.limitations.map((l, i) => (
                                      <div key={i} className="flex items-start gap-2">
                                        <AlertTriangle size={12} className="mt-1 shrink-0 text-warn" />
                                        {l}
                                      </div>
                                    ))}
                                  </div>
                              )}

                              <div className="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line/60 pt-3 text-[11px] text-muted">
                                {turn.result.source_bundle && (
                                  <span>
                                    {turn.result.source_bundle.eligible_source_count} eligible
                                    {turn.result.source_bundle.excluded_source_count > 0 && `, ${turn.result.source_bundle.excluded_source_count} excluded`}
                                  </span>
                                )}
                                <span aria-hidden="true">·</span>
                                <span className="capitalize">{readableState(turn.result.confidence_state)} confidence</span>
                                <span aria-hidden="true">·</span>
                                <span>{turn.result.source_bundle?.jurisdiction || "Any jurisdiction"}</span>
                                <span aria-hidden="true">·</span>
                                <span className={`capitalize ${outcomePresentation.tone}`}>{riskLevel.toLowerCase()} risk</span>
                              </div>
                              </section>
                          </article>
                        )}
                      </div>
                    );
                  })}

                  <div ref={bottomRef} />

                  <form onSubmit={handleSubmit} className="sticky bottom-5 mx-auto max-w-2xl">
                    <div className="rounded-[1.5rem] border border-line bg-panel p-3 shadow-[0_18px_48px_rgba(18,34,32,0.08)]">
                      <textarea
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Ask a follow-up..."
                        rows={2}
                        className="min-h-14 w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-sm font-medium leading-6 text-ink !shadow-none outline-none placeholder:text-muted"
                      />

                      {uploadedFile && (
                        <div className={`mb-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-[11px] font-semibold ${
                          uploadStatus === "ingested"
                            ? "border-ok/30 bg-ok/10 text-ok"
                            : uploadStatus === "error"
                              ? "border-bad/30 bg-bad/10 text-bad"
                              : "border-info/30 bg-info/10 text-info"
                        }`}>
                          {uploadStatus === "ingested" ? <CheckCircle2 size={12} /> : uploadStatus === "error" ? <X size={12} /> : <FileText size={12} />}
                          <span className="flex-1 truncate">
                            {uploadStatus === "uploading" ? `Processing ${uploadedFile.name}...` : uploadMsg || uploadedFile.name}
                          </span>
                          <button type="button" onClick={clearUpload} className="rounded p-1 hover:bg-white/10" aria-label="Clear uploaded file">
                            <X size={11} />
                          </button>
                        </div>
                      )}

                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.xlsx,.pptx" className="hidden" onChange={handleFileChange} />
                          <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={uploadStatus === "uploading"}
                            className="flex h-9 w-9 items-center justify-center rounded-full text-ink transition hover:bg-soft disabled:opacity-40"
                            aria-label="Upload document"
                          >
                            {uploadStatus === "uploading" ? <Loader2 size={16} className="animate-spin" /> : <Plus size={21} />}
                          </button>
                        </div>

                        <div className="flex min-w-0 items-center justify-end gap-2">
                          <select
                            value={jurisdiction}
                            onChange={(e) => setJurisdiction(e.target.value)}
                            className="hidden h-9 rounded-full !border-transparent !bg-soft px-3 text-xs font-semibold text-ink !shadow-none outline-none hover:bg-soft sm:block"
                          >
                            {JURISDICTIONS.map((j) => (
                              <option key={j} value={j} className="bg-panel text-ink">{j || "Any"}</option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={toggleVoiceInput}
                            className={`hidden h-9 w-9 items-center justify-center rounded-full transition hover:bg-soft lg:flex ${isListening ? "text-bad" : "text-muted"}`}
                            aria-label={isListening ? "Stop voice input" : "Voice input"}
                            title={isListening ? "Stop voice input" : "Voice input"}
                          >
                            <Mic size={18} className={isListening ? "animate-pulse" : ""} />
                          </button>
                          <button
                            type="submit"
                            disabled={isLoading || !query.trim()}
                            className="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-white transition hover:bg-brand-2 disabled:opacity-40"
                            aria-label="Ask follow-up"
                          >
                            {isLoading ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
                          </button>
                        </div>
                      </div>
                    </div>

                    {formError && (
                      <p className="mt-3 rounded-xl border border-bad/30 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                        {formError}
                      </p>
                    )}
                  </form>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

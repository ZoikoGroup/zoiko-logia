"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUp,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  FolderKanban,
  History,
  Lightbulb,
  Loader2,
  MessageSquare,
  Mic,
  PenLine,
  Plus,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { ADVISOR } from "@/lib/advisor";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import { askKriton, getAuthToken, ApiError, type AskKritonResponse } from "@/lib/api";

type RiskLevel = "ZERO" | "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];

const CONVERSATIONS_KEY = "kriton_conversations";
const MAX_CONVERSATIONS = 30;

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
  ZERO: { bg: "bg-slate-50", border: "border-slate-200", text: "text-slate-600", icon: ShieldCheck, label: "Zero risk" },
  LOW: { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", icon: ShieldCheck, label: "Low risk" },
  MEDIUM: { bg: "bg-sky-50", border: "border-sky-200", text: "text-sky-700", icon: ShieldCheck, label: "Medium risk" },
  HIGH: { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", icon: ShieldAlert, label: "High risk" },
  RESTRICTED: { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", icon: ShieldOff, label: "Restricted - blocked" },
};

const ROUTE_LABELS: Record<string, string> = {
  // LLM is deliberately absent — "source grounded" is only true when sources
  // were actually retrieved, and retrieval fails soft (a dead SearXNG yields
  // zero citations silently). routeLabel() below reads the real count instead
  // of asserting provenance the answer may not have.
  REFUSAL: "Refused - policy blocked",
  CLARIFICATION: "Clarification required",
  HUMAN_REVIEW: "Escalated for human review",
  SECURITY_INCIDENT: "Security incident - blocked",
  REJECTED: "Rejected - invalid request",
};

function ZoikoGlyph({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <div className={`${className} relative shrink-0 overflow-hidden rounded-xl bg-[#16799A] shadow-[0_18px_44px_rgba(0,0,0,0.28)]`}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_18%,rgba(255,255,255,0.32),transparent_34%)]" />
      <div className="absolute left-[25%] top-[26%] h-[48%] w-[50%] rounded-sm border-[3px] border-white" />
      <div className="absolute bottom-[31%] left-[36%] h-[26%] w-[8%] bg-[#F3C437]" />
      <div className="absolute bottom-[31%] left-[48%] h-[26%] w-[8%] bg-[#F3C437]" />
      <div className="absolute bottom-[31%] left-[60%] h-[26%] w-[8%] bg-[#F3C437]" />
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
    <span className="flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-[#31413e] transition hover:bg-white hover:text-[#122220]">
      <Icon size={17} className="text-[#667673]" />
      <span className="truncate">{label}</span>
    </span>
  );

  return href ? (
    <Link href={href}>{content}</Link>
  ) : (
    <button type="button" onClick={onClick} className="w-full text-left">
      {content}
    </button>
  );
}

// One question + its answer. `result` is null while loading or on error.
type Turn = {
  id: string;
  question: string;
  result: AskKritonResponse | null;
  error: string | null;
  loading: boolean;
};

// A full chat thread — a sequence of turns, saved together under one title.
type Conversation = {
  id: string;
  title: string;
  turns: Turn[];
  createdAt: number;
};

function readableState(value: string) {
  return value.replaceAll("_", " ");
}

/** Outcome caption under "Kriton response". For an answered turn this reports
 * the citations the answer actually carries, rather than claiming it is source
 * grounded on the strength of the route alone — retrieval fails soft, so an
 * unreachable SearXNG produces a confident-looking answer with no provenance
 * behind it at all. */
function routeLabel(route: string | null, citationCount: number) {
  if (route !== "LLM") return ROUTE_LABELS[route ?? ""] ?? route;
  if (citationCount === 0) return "Answered - model knowledge, no sources retrieved";
  return `Answered - grounded in ${citationCount} source${citationCount === 1 ? "" : "s"}`;
}

// Citation markers stay in the API response for validation and audit replay;
// the chat surface presents provenance as the Sources list instead, so they
// are stripped from anything the user copies or downloads.
function answerDisplayText(value: string) {
  return value.replace(/\s*\[REF-\d+\]/gi, "").replace(/[ \t]+\n/g, "\n").trim();
}

// The answer as a self-contained markdown document — used by both Copy and
// Download so the clipboard and the .md file can never disagree. The same
// references are restated as a Sources list, so an exported answer stays
// attributable once it leaves the app.
function answerAsMarkdown(question: string, result: AskKritonResponse) {
  const answer = result.answer;
  if (!answer) return "";
  const parts = [`# ${question.trim()}`, "", answerDisplayText(answer.text)];

  if (answer.limitations?.length) {
    parts.push("", "## Limitations", "", ...answer.limitations.map((l) => `- ${l}`));
  }
  if (answer.citations.length) {
    parts.push("", "## Sources", "");
    parts.push(
      ...answer.citations.map((c) => `- ${c.ref_id}: ${c.title}${c.url ? ` — ${c.url}` : ""}`),
    );
  }
  parts.push(
    "",
    "---",
    `Risk: ${result.safety.risk_level} · Route: ${result.route} · ` +
      `Confidence: ${readableState(result.confidence_state)} · ` +
      `Jurisdiction: ${result.source_bundle?.jurisdiction || "Any"}`,
  );
  return parts.join("\n");
}

function safeDownloadName(value: string, extension: string) {
  const stem =
    value
      .normalize("NFKD")
      .replace(/[^a-zA-Z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase()
      .slice(0, 80) || "kriton-answer";
  return `${stem}.${extension}`;
}

async function writeTextToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  // navigator.clipboard is undefined outside secure contexts (plain http on a
  // LAN IP, for instance), so fall back to the legacy selection-based copy.
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("Clipboard copy was rejected");
}

function downloadTextFile(contents: string, filename: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// Copy / Download / Reuse for one composed answer. Each button owns a
// short-lived status so the result is visible without a toast system: an
// action that silently succeeds reads as an action that did nothing.
function ResponseActions({
  question,
  result,
  onReuse,
}: {
  question: string;
  result: AskKritonResponse;
  onReuse: () => void;
}) {
  const [status, setStatus] = useState<Record<string, "idle" | "done" | "error">>({});

  function flash(key: string, value: "done" | "error") {
    setStatus((prev) => ({ ...prev, [key]: value }));
    window.setTimeout(() => setStatus((prev) => ({ ...prev, [key]: "idle" })), 1800);
  }

  async function copyAnswer() {
    try {
      await writeTextToClipboard(answerAsMarkdown(question, result));
      flash("copy", "done");
    } catch {
      flash("copy", "error");
    }
  }

  function downloadAnswer() {
    try {
      downloadTextFile(answerAsMarkdown(question, result), safeDownloadName(question, "md"));
      flash("download", "done");
    } catch {
      flash("download", "error");
    }
  }

  const actions = [
    { key: "copy", label: "Copy", doneLabel: "Copied", icon: Copy, onClick: copyAnswer },
    { key: "download", label: "Download .md", doneLabel: "Downloaded", icon: Download, onClick: downloadAnswer },
    { key: "reuse", label: "Reuse prompt", doneLabel: "Reuse prompt", icon: RotateCcw, onClick: onReuse },
  ];

  return (
    <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-[#edf2ef] pt-3">
      {actions.map(({ key, label, doneLabel, icon: Icon, onClick }) => {
        const state = status[key] ?? "idle";
        return (
          <button
            key={key}
            type="button"
            onClick={onClick}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition ${
              state === "error"
                ? "border-rose-200 text-rose-600"
                : state === "done"
                  ? "border-emerald-200 text-emerald-700"
                  : "border-[#dfe8e5] text-[#667673] hover:border-[#16799a]/40 hover:text-[#16799a]"
            }`}
          >
            {state === "done" ? <CheckCircle2 size={12} /> : <Icon size={12} />}
            {state === "done" ? doneLabel : label}
          </button>
        );
      })}
    </div>
  );
}

// Renders a single turn: the user's question bubble followed by Kriton's
// response (loading / error / answer). Risk styling is computed per-turn so
// each answer in the thread shows its own badge.
function ConversationTurn({ turn, onReuse }: { turn: Turn; onReuse: (question: string) => void }) {
  const { question, result, error, loading } = turn;
  const safety = result?.safety ?? null;
  const riskLevel = (safety?.risk_level ?? "LOW") as RiskLevel;
  const style = safety ? RISK_STYLES[riskLevel] : null;
  const StatusIcon = style?.icon ?? ShieldCheck;
  const route = result?.route ?? null;
  const outcome = result?.outcome ?? null;

  return (
    <>
      <div className="flex justify-end">
        <div className="max-w-[82%] rounded-2xl rounded-tr-md bg-[#16799a] px-5 py-3 text-sm font-medium leading-6 text-white shadow-sm">
          {question}
        </div>
      </div>

      {loading && (
        <div className="flex items-start gap-3">
          <ZoikoGlyph className="h-9 w-9 rounded-xl" />
          <div className="rounded-2xl rounded-tl-md border border-[#dfe8e5] bg-white px-5 py-4 shadow-sm">
            <p className="text-sm font-semibold text-[#17211f]">{ADVISOR.loadingState}</p>
            <div className="mt-2 flex items-center gap-2 text-xs text-[#667673]">
              <Loader2 size={13} className="animate-spin" />
              Checking sources, safety route, and composition rules.
            </div>
          </div>
        </div>
      )}

      {!loading && error && (
        <div className="flex items-start gap-3">
          <ZoikoGlyph className="h-9 w-9 rounded-xl" />
          <div className="rounded-2xl rounded-tl-md border border-rose-200 bg-rose-50 px-5 py-4 shadow-sm">
            <p className="text-sm font-semibold text-rose-700">Kriton could not respond</p>
            <p className="mt-1 text-xs text-rose-600">{error}</p>
          </div>
        </div>
      )}

      {result && safety && (
        <div className="flex items-start gap-3">
          <ZoikoGlyph className="h-9 w-9 rounded-xl" />
          <article className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-[#dfe8e5] bg-white p-5 shadow-sm">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className={`flex h-9 w-9 items-center justify-center rounded-xl border ${style?.border ?? "border-[#dfe8e5]"} ${style?.bg ?? "bg-[#f7faf8]"}`}>
                  <StatusIcon size={17} className={style?.text ?? "text-[#16799a]"} />
                </span>
                <div>
                  <p className="text-sm font-bold text-[#17211f]">Kriton response</p>
                  <p className="text-xs text-[#667673]">
                    {routeLabel(route, result.answer?.citations.length ?? 0)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {style && (
                  <span
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-bold ${style.border} ${style.bg} ${style.text}`}
                    title="Assessed risk level for this question"
                  >
                    <StatusIcon size={13} />
                    {style.label}
                  </span>
                )}
                <Link
                  href={`/audit-replay?correlation_id=${encodeURIComponent(result.correlation_id)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#dfe8e5] bg-[#f7faf8] px-3 text-xs font-semibold text-[#31413e] hover:bg-[#eef5f3]"
                >
                  <History size={13} />
                  Audit
                </Link>
              </div>
            </div>

            {result.answer ? (
              <>
                <AnswerRenderer text={result.answer.text} />
                {result.answer.citations.length > 0 && (
                  <details className="group/sources mt-5 border-t border-[#edf2ef] pt-4">
                    {/* Collapsed by default — the list only opens on click, so a
                        long answer is not pushed down by its own provenance.
                        Named group: the citation links below carry their own
                        bare `group`, and an unnamed group here would fire their
                        hover styles from anywhere in the panel. */}
                    <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-bold uppercase text-[#788884] transition hover:text-[#17211f]">
                      <ChevronDown size={13} className="shrink-0 transition-transform group-open/sources:rotate-180" />
                      Sources
                      <span className="rounded-full bg-[#f7faf8] px-1.5 py-0.5 text-[10px] font-semibold normal-case text-[#667673]">
                        {result.answer.citations.length}
                      </span>
                    </summary>
                    <div className="mt-2 space-y-2">
                      {result.answer.citations.map((c) =>
                        c.url ? (
                          <a
                            key={c.ref_id}
                            href={c.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="group flex items-start gap-2 text-xs leading-5 text-[#667673] hover:text-[#16799a]"
                          >
                            <BookOpen size={13} className="mt-0.5 shrink-0 text-[#16799a]" />
                            <span className="font-mono text-[#16799a]">[{c.ref_id}]</span>
                            <span className="flex-1 truncate underline decoration-transparent group-hover:decoration-[#16799a]">
                              {c.title}
                            </span>
                            <ExternalLink size={12} className="mt-0.5 shrink-0 opacity-0 group-hover:opacity-100" />
                          </a>
                        ) : (
                          <div key={c.ref_id} className="flex items-start gap-2 text-xs leading-5 text-[#667673]">
                            <BookOpen size={13} className="mt-0.5 shrink-0 text-[#16799a]" />
                            <span className="font-mono text-[#16799a]">[{c.ref_id}]</span>
                            <span>{c.title}</span>
                          </div>
                        ),
                      )}
                    </div>
                  </details>
                )}

                <ResponseActions
                  question={question}
                  result={result}
                  onReuse={() => onReuse(question)}
                />
              </>
            ) : (
              <p className="rounded-xl border border-[#dfe8e5] bg-[#f7faf8] p-4 text-sm italic leading-6 text-[#667673]">
                {outcome === "escalated"
                  ? "This query has been escalated for human review. No AI-generated response is returned until a qualified reviewer clears it."
                  : outcome === "clarification_required"
                    ? "Kriton needs more context to route this query correctly. Please respond to the clarification above."
                    : outcome === "rejected"
                      ? "This request was blocked before processing."
                      : "This query was refused by the policy engine. No response was composed."}
              </p>
            )}

            {result.next_action && (
              <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm leading-6 text-[#31413e]">
                <span className="block text-[11px] font-bold uppercase text-sky-700">{result.next_action.type}</span>
                {result.next_action.message}
              </div>
            )}

            {result.answer?.limitations && result.answer.limitations.length > 0 && (
              <div className="mt-4 space-y-2 border-t border-[#edf2ef] pt-4">
                {result.answer.limitations.map((l, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs leading-5 text-[#667673]">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-600" />
                    {l}
                  </div>
                ))}
              </div>
            )}

            {/* Provenance strip — the governance metadata behind this answer,
                including the jurisdiction the SourceBundle was scoped to. */}
            <div className="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[#edf2ef] pt-3 text-[11px] text-[#667673]">
              {result.source_bundle && (
                <>
                  <span>
                    {result.source_bundle.eligible_source_count} eligible
                    {result.source_bundle.excluded_source_count > 0 &&
                      `, ${result.source_bundle.excluded_source_count} excluded`}
                  </span>
                  <span aria-hidden="true">·</span>
                </>
              )}
              <span className="capitalize">{readableState(result.confidence_state)} confidence</span>
              <span aria-hidden="true">·</span>
              <span>{result.source_bundle?.jurisdiction || "Any jurisdiction"}</span>
              <span aria-hidden="true">·</span>
              <span className="capitalize">{result.source_bundle?.freshness_state || "unknown"} sources</span>
              <span aria-hidden="true">·</span>
              <span className="capitalize">{riskLevel.toLowerCase()} risk</span>
            </div>
          </article>
        </div>
      )}
    </>
  );
}

export default function AskKritonPage() {
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // All chat threads, newest first, persisted in localStorage so they survive
  // refreshes. `activeId` is the thread currently open — null means a fresh
  // "New chat" with nothing asked yet (shows the welcome screen).
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(CONVERSATIONS_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) setConversations(parsed);
      }
    } catch {
      /* ignore malformed storage */
    }
  }, []);

  function persist(next: Conversation[]) {
    try {
      localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(next));
    } catch {
      /* ignore storage write failures (e.g. private mode / quota) */
    }
  }

  function patchTurn(convId: string, turnId: string, patch: Partial<Turn>) {
    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id !== convId
          ? c
          : { ...c, turns: c.turns.map((t) => (t.id !== turnId ? t : { ...t, ...patch })) },
      );
      persist(next);
      return next;
    });
  }

  function startNewChat() {
    setActiveId(null);
    setQuery("");
  }

  async function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || submitting) return;
    const token = getAuthToken();
    if (!token) {
      alert("Please sign in before asking Kriton.");
      return;
    }

    const turnId = `turn-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const newTurn: Turn = { id: turnId, question: trimmed, result: null, error: null, loading: true };

    // Append the turn to the open conversation, or start a new one if none.
    const isNew = activeId === null;
    const convId = activeId ?? `conv-${Date.now()}`;
    setConversations((prev) => {
      const next = isNew
        ? [{ id: convId, title: trimmed.slice(0, 80), turns: [newTurn], createdAt: Date.now() }, ...prev].slice(0, MAX_CONVERSATIONS)
        : prev.map((c) => (c.id === convId ? { ...c, turns: [...c.turns, newTurn] } : c));
      persist(next);
      return next;
    });
    if (isNew) setActiveId(convId);

    setQuery("");
    setSubmitting(true);
    try {
      const idempotencyKey = `idem-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const response = await askKriton(token, { query: trimmed, jurisdiction, mode: "Workflow" }, idempotencyKey);
      patchTurn(convId, turnId, { result: response, loading: false });
    } catch (err) {
      patchTurn(convId, turnId, {
        error: err instanceof ApiError ? err.message : "Could not reach the orchestration service.",
        loading: false,
      });
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;
  const hasConversation = activeConversation !== null && activeConversation.turns.length > 0;

  return (
    <main className="relative min-h-screen w-full min-w-0 overflow-hidden bg-[#f5f7f4] text-[#17211f]">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#ffffff_0%,#f5f7f4_46%,#edf3f1_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[#d9e5e1]" />
      <div className="relative z-10 grid min-h-screen w-full min-w-0 grid-cols-1 md:grid-cols-[252px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 border-r border-[#d9e5e1] bg-[#f5f7f4] md:flex md:flex-col">
          <div className="flex items-center justify-between px-5 py-5">
            <div className="flex items-center gap-3">
              <ZoikoGlyph className="h-9 w-9 rounded-lg" />
              <div>
                <div className="text-lg font-bold tracking-normal text-[#122220]">Kriton</div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#667673]">ZoikoLogia</div>
              </div>
            </div>
            <div className="text-[#667673]">
              <Search size={17} />
            </div>
          </div>

          <nav className="space-y-1 px-3">
            <SidebarItem icon={Plus} label="New chat" onClick={startNewChat} />
            <SidebarItem icon={MessageSquare} label="Chats" />
            <SidebarItem icon={FolderKanban} label="Projects" href="/my-workspace" />
            <SidebarItem icon={BookOpen} label="Sources" href="/source-licensing" />
          </nav>

          <div className="mt-6 flex min-h-0 flex-1 flex-col px-5">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-bold text-[#788884]">Recents</p>
              <SlidersHorizontal size={13} className="text-[#8b9996]" />
            </div>
            <div className="min-h-0 space-y-1 overflow-y-auto pr-1">
              {conversations.length === 0 ? (
                <p className="px-2 py-1 text-xs text-[#8b9996]">No chats yet — ask a question to start one.</p>
              ) : (
                conversations.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => {
                      setActiveId(c.id);
                      setQuery("");
                    }}
                    className={`block h-9 w-full truncate rounded-lg px-2 text-left text-sm font-medium hover:bg-white hover:text-[#122220] ${
                      c.id === activeId ? "bg-white text-[#122220]" : "text-[#667673]"
                    }`}
                  >
                    {c.title}
                  </button>
                ))
              )}
            </div>
          </div>
        </aside>

        <section className="relative flex min-h-0 min-w-0 flex-col">
          <header className="relative z-10 flex h-14 items-center justify-between border-b border-[#dfe8e5] bg-white/80 px-4 md:hidden">
            <div className="flex items-center gap-2">
              <ZoikoGlyph className="h-8 w-8 rounded-lg" />
              <span className="font-bold">Kriton</span>
            </div>
            <Search size={18} className="text-[#566865]" />
          </header>

          <div className="relative z-10 flex-1 overflow-y-auto px-4">
            <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col items-center justify-center pb-16 pt-6 md:pb-24 md:pt-8">
              {!hasConversation ? (
                <div className="flex w-full max-w-3xl flex-col items-center text-center">
                  <div className="w-full">
                    <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-[#d7e3df] bg-white px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-[#16799a] shadow-sm">
                      <Sparkles size={14} />
                      Ask Kriton
                    </div>
                    <h1 className="text-balance text-4xl font-bold tracking-normal text-[#122220] md:text-5xl">
                      Get a governed answer from your sources.
                    </h1>
                    <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-[#667673]">
                      Ask accounting, audit, and policy questions with source checks, risk routing, and audit history kept in the flow.
                    </p>
                  </div>

                  <form onSubmit={handleSubmit} className="mt-8 w-full">
                    <div className="rounded-[1.75rem] border border-[#d9e5e1] bg-white p-4 shadow-[0_18px_48px_rgba(18,34,32,0.08)]">
                      <textarea
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Ask Kriton..."
                        rows={2}
                        className="min-h-20 w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-base font-medium leading-7 text-[#17211f] !shadow-none outline-none placeholder:text-[#8b9996]"
                      />

                      <div className="flex items-center justify-end gap-3">
                        <div className="flex min-w-0 items-center justify-end gap-2">
                          <select
                            value={jurisdiction}
                            onChange={(e) => setJurisdiction(e.target.value)}
                            className="hidden h-9 rounded-full !border-transparent !bg-[#f7faf8] px-3 text-xs font-semibold text-[#31413e] !shadow-none outline-none hover:bg-[#eef5f3] sm:block"
                          >
                            {JURISDICTIONS.map((j) => (
                              <option key={j} value={j} className="bg-white text-[#17211f]">{j || "Any"}</option>
                            ))}
                          </select>
                          <button type="button" className="hidden h-9 w-9 items-center justify-center rounded-full text-[#667673] transition hover:bg-[#f1f7f8] lg:flex" aria-label="Voice input">
                            <Mic size={19} />
                          </button>
                          <button
                            type="submit"
                            disabled={submitting || !query.trim()}
                            className="flex h-9 w-9 items-center justify-center rounded-full bg-[#16799a] text-white transition hover:bg-[#126783] disabled:opacity-40"
                            aria-label="Ask Kriton"
                          >
                            {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
                          </button>
                        </div>
                      </div>
                    </div>
                  </form>

                  <div className="mt-5 grid w-full grid-cols-2 gap-2 md:grid-cols-5">
                    {QUICK_MODES.map(({ label, icon: ModeIcon, prompt }) => (
                      <button
                        key={label}
                        type="button"
                        onClick={() => setQuery((current) => `${prompt}${current}`.trim())}
                        className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-[#dfe8e5] bg-white px-2 text-xs font-bold text-[#31413e] shadow-sm transition hover:border-[#16799a]/30 hover:bg-[#f1f7f8]"
                      >
                        <ModeIcon size={16} />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="w-full max-w-4xl space-y-6 self-stretch">
                  {activeConversation?.turns.map((turn) => (
                    <ConversationTurn key={turn.id} turn={turn} onReuse={setQuery} />
                  ))}

                  <form onSubmit={handleSubmit} className="sticky bottom-5 mx-auto max-w-2xl">
                    <div className="rounded-[1.5rem] border border-[#d9e5e1] bg-white p-3 shadow-[0_18px_48px_rgba(18,34,32,0.08)]">
                      <textarea
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Ask a follow-up..."
                        rows={2}
                        className="min-h-14 w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-sm font-medium leading-6 text-[#17211f] !shadow-none outline-none placeholder:text-[#8b9996]"
                      />

                      <div className="flex items-center justify-end gap-3">
                        <div className="flex min-w-0 items-center justify-end gap-2">
                          <select
                            value={jurisdiction}
                            onChange={(e) => setJurisdiction(e.target.value)}
                            className="hidden h-9 rounded-full !border-transparent !bg-[#f7faf8] px-3 text-xs font-semibold text-[#31413e] !shadow-none outline-none hover:bg-[#eef5f3] sm:block"
                          >
                            {JURISDICTIONS.map((j) => (
                              <option key={j} value={j} className="bg-white text-[#17211f]">{j || "Any"}</option>
                            ))}
                          </select>
                          <button type="button" className="hidden h-9 w-9 items-center justify-center rounded-full text-[#667673] transition hover:bg-[#f1f7f8] lg:flex" aria-label="Voice input">
                            <Mic size={18} />
                          </button>
                          <button
                            type="submit"
                            disabled={submitting || !query.trim()}
                            className="flex h-9 w-9 items-center justify-center rounded-full bg-[#16799a] text-white transition hover:bg-[#126783] disabled:opacity-40"
                            aria-label="Ask follow-up"
                          >
                            {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
                          </button>
                        </div>
                      </div>
                    </div>
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

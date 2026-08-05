"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CalculationWidget } from "@/components/CalculationWidget";
import { AnswerVisualizations } from "@/components/AnswerVisualizations";
import { DynamicAnswerBlocks } from "@/components/DynamicAnswerBlocks";
import {
  AlertTriangle,
  ArrowUp,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  ExternalLink,
  FileText,
  FolderKanban,
  History,
  LayoutDashboard,
  Lightbulb,
  Loader2,
  MessageSquare,
  Mic,
  MoreVertical,
  Pencil,
  PenLine,
  Pin,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { askKriton, getAuthToken, ApiError, uploadDocument, type AskKritonResponse } from "@/lib/api";

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
  ZERO: { bg: "bg-ok/10", border: "border-ok/30", text: "text-ok", icon: ShieldCheck, label: "Zero risk - routine" },
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

function answerDisplayText(value: string) {
  // Citation markers remain in the API response for validation, audit replay,
  // and source assembly. The chat surface presents the provenance as source
  // cards below instead of leaking internal identifiers such as "REF-1".
  return value.replace(/\s*\[REF-\d+\]/gi, "").replace(/[ \t]+\n/g, "\n").trim();
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

// Response-format vision doc (2026-07-22, item 1 "Text"): Kriton's
// composition prompt now asks for real markdown structure (headings,
// bullets, tables) for explanation/comparison answers — this renders it
// with the app's own visual language instead of raw ** and | characters.
// cleanDisplayText's ** stripping predates this and stays for the other,
// non-markdown-rendered text surfaces (action.message, etc.) below.
const markdownComponents: Components = {
  h1: ({ children }) => <h2 className="mb-2 mt-5 text-lg font-bold text-ink first:mt-0">{children}</h2>,
  h2: ({ children }) => <h3 className="mb-2 mt-5 text-base font-bold text-ink first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1.5 mt-4 text-sm font-bold text-ink first:mt-0">{children}</h4>,
  h4: ({ children }) => <h5 className="mb-1.5 mt-4 text-sm font-semibold text-ink first:mt-0">{children}</h5>,
  p: ({ children }) => <p className="mb-3 text-[15px] leading-7 text-ink last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 ml-5 list-disc space-y-1 text-[15px] leading-7 text-ink last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 ml-5 list-decimal space-y-1 text-[15px] leading-7 text-ink last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-brand underline decoration-dotted underline-offset-2 hover:text-brand-2">
      {children}
    </a>
  ),
  code: ({ children }) => <code className="rounded bg-soft px-1 py-0.5 font-mono text-[13px] text-ink">{children}</code>,
  blockquote: ({ children }) => <blockquote className="mb-3 border-l-2 border-line pl-3 italic text-muted">{children}</blockquote>,
  hr: () => <hr className="my-4 border-line" />,
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-soft">{children}</thead>,
  tr: ({ children }) => <tr className="border-t border-line first:border-t-0">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 align-top text-sm text-ink">{children}</td>,
};

function KritonMarkdown({ text }: { text: string }) {
  return (
    <div className="min-w-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  );
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
  const activeConversationId = useRef<string | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    try {
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
      // localStorage unavailable (private browsing, etc.) — recents just won't persist.
    }
  }, []);

  function persistRecents(next: RecentEntry[]) {
    try {
      window.localStorage.setItem(RECENTS_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore write failures
    }
  }

  function saveConversation(q: string, conversationTurns: ConversationTurn[]) {
    const id = activeConversationId.current ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    activeConversationId.current = id;
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
    if (activeConversationId.current === id) {
      activeConversationId.current = null;
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

  function commitRename(id: string) {
    const trimmed = editText.trim();
    setRecents((prev) => {
      const next = prev.map((r) => (r.id === id ? { ...r, text: trimmed || r.text } : r));
      persistRecents(next);
      return next;
    });
    setEditingId(null);
  }

  function startNewChat() {
    activeConversationId.current = null;
    setActiveConversationIdValue(null);
    window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
    setTurns([]);
    setQuery("");
    setFormError("");
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
      const response = await askKriton(
        token,
        {
          query: submittedQuery,
          jurisdiction,
          mode: "Workflow",
          clarification_cycle: 0,
          // Dynamic Visualization Selection v4 — the same locally-generated
          // thread id already used for the recents sidebar (saveConversation
          // above has already assigned one by this point), sent to the
          // backend for the first time so it can scope the chart-repetition
          // penalty and telemetry to this conversation. Never used for
          // authorization — tenant/user scoping still comes from the
          // authenticated token, same as every other field here.
          conversation_id: activeConversationId.current ?? undefined,
        },
        idempotencyKey,
      );
      const completedConversation = pendingConversation.map((t) =>
        t.id === turnId ? { ...t, loading: false, result: response } : t
      );
      setTurns(completedConversation);
      saveConversation(trimmed, completedConversation);
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

          <div className="mt-6 flex min-h-0 flex-1 flex-col px-5">
              <p className="mb-2 px-2 text-xs font-bold text-muted">Recents</p>
              {recents.length > 0 ? (
              <div className="min-h-0 space-y-0.5 overflow-y-auto pr-1">
                    {recents.map((entry) => (
                  <div key={entry.id} className={`group relative flex items-center rounded-lg transition ${activeConversationIdValue === entry.id ? "bg-line/60" : "hover:bg-line/35"}`}>
                    {editingId === entry.id ? (
                      <input
                        autoFocus
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onBlur={() => commitRename(entry.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename(entry.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        className="h-9 w-full rounded-lg border border-brand/40 bg-panel px-2 text-sm text-ink outline-none"
                      />
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            activeConversationId.current = entry.id;
                            setActiveConversationIdValue(entry.id);
                            window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, entry.id);
                            setTurns(entry.turns);
                            setQuery(entry.turns.length ? "" : entry.text);
                            setFormError("");
                          }}
                          className={`flex h-10 min-w-0 flex-1 items-center gap-1.5 truncate rounded-lg px-2.5 text-left text-sm font-semibold ${activeConversationIdValue === entry.id ? "text-ink" : "text-muted hover:text-ink"}`}
                        >
                          {entry.pinned && <Pin size={11} className="shrink-0 text-brand" />}
                          <span className="truncate">{entry.text}</span>
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
                          onClick={() => togglePin(entry.id)}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-ink hover:bg-soft"
                        >
                          <Pin size={13} /> {entry.pinned ? "Unpin" : "Pin"}
                        </button>
                        <button
                          type="button"
                          onClick={() => startRename(entry)}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-ink hover:bg-soft"
                        >
                          <Pencil size={13} /> Rename
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteRecent(entry.id)}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-bad hover:bg-bad/10"
                        >
                          <Trash2 size={13} /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                    ))}
              </div>
              ) : (
                <p className="rounded-lg px-2 py-3 text-xs leading-5 text-muted">Your conversation sessions will appear here after you send a question.</p>
              )}
            </div>

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
                            activeConversationId.current = entry.id;
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
                                  <div className="kriton-answer-reveal">
                                    <DynamicAnswerBlocks
                                      answer={turn.result.answer}
                                      queryId={turn.result.query_id}
                                      conversationId={activeConversationIdValue ?? undefined}
                                      onFollowUp={(question) => setQuery(`${question} Context: ${turn.query}`)}
                                      renderMarkdown={(text) => <KritonMarkdown text={answerDisplayText(text)} />}
                                    />
                                  </div>
                                    {!turn.result.answer.blocks?.length && turn.result.answer.presentation && (
                                      <AnswerVisualizations
                                        presentation={turn.result.answer.presentation}
                                        onFollowUp={(question) => setQuery(`${question} Context: ${turn.query}`)}
                                        queryId={turn.result.query_id}
                                        sourceReferences={turn.result.answer.citations.map((c) => c.ref_id)}
                                        conversationId={activeConversationIdValue ?? undefined}
                                      />
                                    )}
                                    {!turn.result.answer.blocks?.length && turn.result.answer.calculation_widget && (
                                      <CalculationWidget
                                        data={turn.result.answer.calculation_widget}
                                        queryId={turn.result.query_id}
                                        sourceReferences={turn.result.answer.citations.map((c) => c.ref_id)}
                                      />
                                    )}
                                    {turn.result.answer.citations.length > 0 && (
                                      <div className="mt-5 border-t border-line/70 pt-3">
                                        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Sources</p>
                                        <ul className="mt-2 space-y-1.5">
                                          {turn.result.answer.citations.map((c) => {
                                            const preview = sourcePreview(c.source_id, c.url);
                                            return (
                                              <li key={c.ref_id}>
                                                <button
                                                  type="button"
                                                  onClick={() => openEvidenceView(c, turn)}
                                                  title={preview.detail}
                                                  className="group inline-flex max-w-full items-center gap-2 text-left text-sm font-medium text-brand hover:text-brand-2 hover:underline hover:underline-offset-2"
                                                >
                                                  {c.source_id === "src-kriton-user-provided-data" ? <MessageSquare size={14} className="shrink-0" /> : <FileText size={14} className="shrink-0" />}
                                                  <span className="truncate">{c.title}</span>
                                                  <span className="shrink-0 text-[10px] font-normal text-muted">· {preview.label}</span>
                                                  <ExternalLink size={11} className="shrink-0 opacity-60" />
                                                </button>
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
                                <span className="capitalize">
                                  {turn.result.source_bundle?.freshness_state || "unknown"} sources
                                </span>
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

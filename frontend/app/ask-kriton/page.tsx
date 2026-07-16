"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUp,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
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

type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

type RecentEntry = { id: string; text: string; pinned: boolean };

const RECENTS_STORAGE_KEY = "kriton_recent_queries";
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
  refused: { label: "Unable to answer", tone: "text-bad" },
  rejected: { label: "Request blocked", tone: "text-bad" },
};

function readableState(value: string) {
  return value.replaceAll("_", " ");
}

function cleanDisplayText(value: string) {
  return value.replace(/\*\*(.*?)\*\*/g, "$1").replace(/\*\*/g, "").trim();
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(RECENTS_STORAGE_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (!Array.isArray(parsed)) return;
      // Older sessions stored plain strings — upgrade them in place.
      const normalized: RecentEntry[] = parsed.map((item, i) =>
        typeof item === "string" ? { id: `legacy-${i}-${Date.now()}`, text: item, pinned: false } : item
      );
      setRecents(normalized);
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

  function addRecent(q: string) {
    setRecents((prev) => {
      const withoutDup = prev.filter((r) => r.text !== q);
      const entry: RecentEntry = { id: `r-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, text: q, pinned: false };
      const pinned = withoutDup.filter((r) => r.pinned);
      const unpinned = withoutDup.filter((r) => !r.pinned);
      const next = [...pinned, entry, ...unpinned].slice(0, MAX_RECENTS);
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
    setTurns([]);
    setQuery("");
    setFormError("");
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
    addRecent(trimmed);

    const turnId = `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setTurns((prev) => [...prev, { id: turnId, query: trimmed, loading: true, error: "", result: null }]);

    try {
      const idempotencyKey = `idem-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const response = await askKriton(
        token,
        {
          query: trimmed,
          jurisdiction,
          mode: "Workflow",
        },
        idempotencyKey,
      );
      setTurns((prev) => prev.map((t) => (t.id === turnId ? { ...t, loading: false, result: response } : t)));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not reach the orchestration service.";
      setTurns((prev) => prev.map((t) => (t.id === turnId ? { ...t, loading: false, error: message } : t)));
    }
  }

  const hasConversation = turns.length > 0;
  const isLoading = turns.some((t) => t.loading);

  return (
    <main className="relative min-h-screen w-full min-w-0 overflow-hidden bg-soft text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,var(--panel)_0%,var(--soft)_46%,var(--bg)_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-soft" />
      <div className="relative z-10 grid min-h-screen w-full min-w-0 grid-cols-1 md:grid-cols-[252px_minmax(0,1fr)]">
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

          {recents.length > 0 ? (
            <div className="mt-6 flex min-h-0 flex-1 flex-col px-5">
              <p className="mb-2 text-xs font-bold text-muted">Recents</p>
              <div className="min-h-0 space-y-0.5 overflow-y-auto pr-1">
                {recents.map((entry) => (
                  <div key={entry.id} className="group relative flex items-center rounded-lg hover:bg-soft">
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
                          onClick={() => setQuery(entry.text)}
                          className="flex h-9 min-w-0 flex-1 items-center gap-1.5 truncate rounded-lg px-2 text-left text-sm font-medium text-muted hover:text-ink"
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
            </div>
          ) : (
            <div className="flex-1" />
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
            <Search size={18} className="text-muted" />
          </header>

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
                                  <div className="kriton-answer-reveal whitespace-pre-line text-[15px] leading-7 text-ink">
                                    {cleanDisplayText(turn.result.answer.text)}
                                  </div>
                                    {turn.result.answer.citations.length > 0 && (
                                      <div className="mt-5 border-t border-line/70 pt-3">
                                        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">Sources</p>
                                        <ol className="mt-2 space-y-1.5">
                                          {turn.result.answer.citations.map((c, index) => (
                                            <li key={c.ref_id} className="flex items-start gap-2 text-xs leading-5 text-muted">
                                              <span className="font-mono font-semibold text-brand">{index + 1}.</span>
                                              <span>{c.title}</span>
                                            </li>
                                          ))}
                                        </ol>
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

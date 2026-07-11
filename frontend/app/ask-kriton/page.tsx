"use client";

import { useRef, useState } from "react";
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
  Lightbulb,
  Loader2,
  MessageSquare,
  Mic,
  PenLine,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { ADVISOR } from "@/lib/advisor";
import { askKriton, getAuthToken, ApiError, uploadDocument, type AskKritonResponse } from "@/lib/api";

type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];

const RECENTS = [
  "Document review and explanation",
  "Revenue recognition context",
  "Mixed supply VAT treatment",
  "Going concern source check",
  "Lease accounting study guide",
  "Academic integrity boundary",
  "IFRS disclosure review",
  "Audit trail walkthrough",
  "Source bundle readiness",
];

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
  LOW: { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", icon: ShieldCheck, label: "Low risk - verified" },
  MEDIUM: { bg: "bg-sky-50", border: "border-sky-200", text: "text-sky-700", icon: ShieldCheck, label: "Medium risk - educational" },
  HIGH: { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", icon: ShieldAlert, label: "High risk - boundary applied" },
  RESTRICTED: { bg: "bg-rose-50", border: "border-rose-200", text: "text-rose-700", icon: ShieldOff, label: "Restricted - blocked" },
};

const ROUTE_LABELS: Record<string, string> = {
  LLM: "Answered - source grounded",
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
}: {
  icon: typeof MessageSquare;
  label: string;
  href?: string;
}) {
  const content = (
    <span className="flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-[#31413e] transition hover:bg-white hover:text-[#122220]">
      <Icon size={17} className="text-[#667673]" />
      <span className="truncate">{label}</span>
    </span>
  );

  return href ? <Link href={href}>{content}</Link> : <button type="button" className="w-full text-left">{content}</button>;
}

export default function AskKritonPage() {
  const [query, setQuery] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskKritonResponse | null>(null);
  const [error, setError] = useState("");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "uploading" | "ingested" | "error">("idle");
  const [uploadMsg, setUploadMsg] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

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
      setError("Please sign in before asking Kriton.");
      return;
    }
    setLoading(true);
    setResult(null);
    setError("");
    setLastQuery(trimmed);
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
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the orchestration service.");
    } finally {
      setLoading(false);
    }
  }

  const safety = result?.safety ?? null;
  const riskLevel = (safety?.risk_level ?? "LOW") as RiskLevel;
  const style = safety ? RISK_STYLES[riskLevel] : null;
  const StatusIcon = style?.icon ?? ShieldCheck;
  const route = result?.route ?? null;
  const outcome = result?.outcome ?? null;
  const hasConversation = Boolean(lastQuery || loading || result);

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
            <SidebarItem icon={Plus} label="New chat" />
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
              {RECENTS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setQuery(item)}
                  className="block h-9 w-full truncate rounded-lg px-2 text-left text-sm font-medium text-[#667673] hover:bg-white hover:text-[#122220]"
                >
                  {item}
                </button>
              ))}
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
                        placeholder="Ask Kriton..."
                        rows={2}
                        className="min-h-20 w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-base font-medium leading-7 text-[#17211f] !shadow-none outline-none placeholder:text-[#8b9996]"
                      />

                      {uploadedFile && (
                        <div className={`mb-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-[11px] font-semibold ${
                          uploadStatus === "ingested"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : uploadStatus === "error"
                              ? "border-rose-200 bg-rose-50 text-rose-700"
                              : "border-sky-200 bg-sky-50 text-sky-700"
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
                            className="flex h-10 w-10 items-center justify-center rounded-full text-[#31413e] transition hover:bg-[#f1f7f8] disabled:opacity-40"
                            aria-label="Upload document"
                          >
                            {uploadStatus === "uploading" ? <Loader2 size={18} className="animate-spin" /> : <Plus size={23} />}
                          </button>
                        </div>

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
                            disabled={loading || !query.trim()}
                            className="flex h-9 w-9 items-center justify-center rounded-full bg-[#16799a] text-white transition hover:bg-[#126783] disabled:opacity-40"
                            aria-label="Ask Kriton"
                          >
                            {loading ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
                          </button>
                        </div>
                      </div>
                    </div>

                    {error && (
                      <p className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">
                        {error}
                      </p>
                    )}
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
                  {lastQuery && (
                    <div className="flex justify-end">
                      <div className="max-w-[82%] rounded-2xl rounded-tr-md bg-[#16799a] px-5 py-3 text-sm font-medium leading-6 text-white shadow-sm">
                        {lastQuery}
                      </div>
                    </div>
                  )}

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
                              <p className="text-xs text-[#667673]">{ROUTE_LABELS[route ?? ""] ?? route}</p>
                            </div>
                          </div>
                          <Link
                            href={`/audit-replay?correlation_id=${encodeURIComponent(result.correlation_id)}`}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#dfe8e5] bg-[#f7faf8] px-3 text-xs font-semibold text-[#31413e] hover:bg-[#eef5f3]"
                          >
                            <History size={13} />
                            Audit
                          </Link>
                        </div>

                        {result.answer ? (
                          <>
                            <p className="whitespace-pre-line text-sm leading-7 text-[#31413e]">{result.answer.text}</p>
                            {result.answer.citations.length > 0 && (
                              <div className="mt-5 border-t border-[#edf2ef] pt-4">
                                <p className="text-xs font-bold uppercase text-[#788884]">Sources</p>
                                <div className="mt-2 space-y-2">
                                  {result.answer.citations.map((c) => (
                                    <div key={c.ref_id} className="flex items-start gap-2 text-xs leading-5 text-[#667673]">
                                      <BookOpen size={13} className="mt-0.5 shrink-0 text-[#16799a]" />
                                      <span className="font-mono text-[#16799a]">[{c.ref_id}]</span>
                                      <span>{c.title}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
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
                      </article>
                    </div>
                  )}

                  <form onSubmit={handleSubmit} className="sticky bottom-5 mx-auto max-w-2xl">
                    <div className="rounded-[1.5rem] border border-[#d9e5e1] bg-white p-3 shadow-[0_18px_48px_rgba(18,34,32,0.08)]">
                      <textarea
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Ask a follow-up..."
                        rows={2}
                        className="min-h-14 w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-sm font-medium leading-6 text-[#17211f] !shadow-none outline-none placeholder:text-[#8b9996]"
                      />

                      {uploadedFile && (
                        <div className={`mb-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-[11px] font-semibold ${
                          uploadStatus === "ingested"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : uploadStatus === "error"
                              ? "border-rose-200 bg-rose-50 text-rose-700"
                              : "border-sky-200 bg-sky-50 text-sky-700"
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
                            className="flex h-9 w-9 items-center justify-center rounded-full text-[#31413e] transition hover:bg-[#f1f7f8] disabled:opacity-40"
                            aria-label="Upload document"
                          >
                            {uploadStatus === "uploading" ? <Loader2 size={16} className="animate-spin" /> : <Plus size={21} />}
                          </button>
                        </div>

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
                            disabled={loading || !query.trim()}
                            className="flex h-9 w-9 items-center justify-center rounded-full bg-[#16799a] text-white transition hover:bg-[#126783] disabled:opacity-40"
                            aria-label="Ask follow-up"
                          >
                            {loading ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
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

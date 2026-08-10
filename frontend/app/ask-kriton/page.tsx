"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  BookOpen,
  BriefcaseBusiness,
  ExternalLink,
  History,
  Lightbulb,
  PenLine,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Sparkles,
} from "lucide-react";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import { askKriton, getAuthToken, ApiError, type SourceCitation } from "@/lib/api";
import { openSourcePopup } from "@/lib/source-popup";
import { getFollowUpSuggestions } from "@/lib/follow-up-suggestions";
import { ThinkingIndicator } from "@/components/ask-kriton/ThinkingIndicator";
import { DesktopSidebar, MobileDrawer } from "@/components/ask-kriton/Sidebar";
import { Composer } from "@/components/ask-kriton/Composer";
import { ExploreFurther } from "@/components/ask-kriton/ExploreFurther";
import {
  loadActiveConversationId,
  loadConversations,
  persistActiveConversationId,
  persistConversations,
  sortConversations,
  type Conversation,
  type Turn,
} from "@/lib/ask-kriton-storage";

type RiskLevel = "ZERO" | "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

const QUICK_MODES = [
  { label: "Source check", icon: BookOpen, prompt: "Review this question with eligible source grounding: " },
  { label: "Learn", icon: Lightbulb, prompt: "Explain this as a learning note without giving regulated advice: " },
  { label: "Write", icon: PenLine, prompt: "Draft a professional, source-aware explanation for: " },
  { label: "Workflow", icon: BriefcaseBusiness, prompt: "Turn this into a practical accounting workflow: " },
  { label: "Kriton's choice", icon: Sparkles, prompt: "" },
];

const RISK_STYLES: Record<RiskLevel, { badge: string; icon: typeof ShieldCheck; label: string }> = {
  ZERO: { badge: "border-line bg-soft text-muted", icon: ShieldCheck, label: "Zero risk" },
  LOW: { badge: "border-ok/30 bg-ok/10 text-ok", icon: ShieldCheck, label: "Low risk" },
  MEDIUM: { badge: "border-info/30 bg-info/10 text-info", icon: ShieldCheck, label: "Medium risk" },
  HIGH: { badge: "border-warn/30 bg-warn/10 text-warn", icon: ShieldAlert, label: "High risk" },
  RESTRICTED: { badge: "border-bad/30 bg-bad/10 text-bad", icon: ShieldOff, label: "Restricted — blocked" },
};

const ROUTE_LABELS: Record<string, string> = {
  LLM: "Answered — source grounded",
  REFUSAL: "Refused — policy blocked",
  CLARIFICATION: "Clarification required",
  HUMAN_REVIEW: "Escalated for human review",
  SECURITY_INCIDENT: "Security incident — blocked",
  REJECTED: "Rejected — invalid request",
};

function genId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function timestamp(): number {
  return Date.now();
}

/** Trailing consecutive clarification_required turns — resets to 0 the moment
 * a turn actually gets answered, so the count reflects one live back-and-forth. */
function clarificationCycleFor(conversation: Conversation | null): number {
  if (!conversation) return 0;
  let cycle = 0;
  for (let i = conversation.turns.length - 1; i >= 0; i--) {
    if (conversation.turns[i].result?.outcome === "clarification_required") cycle++;
    else break;
  }
  return cycle;
}

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

function SourceButton({ citation }: { citation: SourceCitation }) {
  const label = citation.url ? new URL(citation.url).hostname.replace(/^www\./, "") : citation.title;
  return (
    <button
      type="button"
      onClick={() => openSourcePopup(citation)}
      className="group flex w-full items-start gap-2 rounded-lg px-1 py-1 text-left text-xs leading-5 text-muted hover:bg-soft hover:text-brand"
    >
      <BookOpen size={13} className="mt-0.5 shrink-0 text-brand" />
      <span className="font-mono text-brand">[{citation.ref_id}]</span>
      <span className="flex-1 truncate">{citation.title || label}</span>
      <ExternalLink size={12} className="mt-0.5 shrink-0 opacity-0 group-hover:opacity-100" />
    </button>
  );
}

function ConversationTurn({ turn, onFollowUp }: { turn: Turn; onFollowUp?: (question: string, originalQuery: string) => void }) {
  const { submittedQuery, result, error, loading } = turn;
  const followUps = useMemo(() => getFollowUpSuggestions(result, submittedQuery), [result, submittedQuery]);
  const safety = result?.safety ?? null;
  const riskLevel = (safety?.risk_level ?? "LOW") as RiskLevel;
  const style = safety ? RISK_STYLES[riskLevel] : null;
  const route = result?.route ?? null;
  const outcome = result?.outcome ?? null;
  const bundle = result?.source_bundle ?? null;

  return (
    <>
      <div className="flex justify-end">
        <div className="kriton-animate-msg-user kriton-user-query max-w-[82%] rounded-2xl rounded-tr-md border px-5 py-3 text-sm font-medium leading-6 text-ink shadow-sm">
          {submittedQuery}
        </div>
      </div>

      {loading && <ThinkingIndicator />}

      {!loading && error && (
        <div className="kriton-animate-msg-response">
          <div className="rounded-2xl rounded-tl-md border border-bad/30 bg-bad/5 px-5 py-4 shadow-sm">
            <p className="text-sm font-semibold text-bad">Kriton could not respond</p>
            <p className="mt-1 text-xs text-bad/80">{error}</p>
          </div>
        </div>
      )}

      {result && safety && (
        <div className="kriton-animate-msg-response">
          <article className="min-w-0 flex-1 py-1 text-ink">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-bold text-ink">Kriton response</p>
                <p className="text-xs text-muted">{ROUTE_LABELS[route ?? ""] ?? route}</p>
              </div>
              <div className="flex items-center gap-2">
                <Link
                  href={`/audit-replay?correlation_id=${encodeURIComponent(result.correlation_id)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-soft px-3 text-xs font-semibold text-ink hover:bg-line/40"
                >
                  <History size={13} />
                  View audit
                </Link>
              </div>
            </div>

            <div className="kriton-animate-answer-reveal">
              {result.answer ? (
                <>
                  <AnswerRenderer text={result.answer.text} />
                  {result.answer.citations.length > 0 && (
                    <div className="mt-5 border-t border-line pt-4">
                      <p className="text-xs font-bold uppercase text-muted">
                        Sources ({result.answer.citations.length}) — the answer is drawn from these
                      </p>
                      <div className="mt-2 space-y-1">
                        {result.answer.citations.map((c) => <SourceButton key={c.ref_id} citation={c} />)}
                      </div>
                    </div>
                  )}
                  {result.answer.limitations.length > 0 && (
                    <div className="mt-4 space-y-2 border-t border-line pt-4">
                      {result.answer.limitations.map((l, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs leading-5 text-muted">
                          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" />
                          {l}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p className="rounded-xl border border-line bg-soft p-4 text-sm italic leading-6 text-muted">
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
                <div className="mt-4 rounded-xl border border-info/30 bg-info/5 p-3 text-sm leading-6 text-ink">
                  <span className="block text-[11px] font-bold uppercase text-info">{result.next_action.type}</span>
                  {result.next_action.message}
                </div>
              )}

              <ExploreFurther
                questions={followUps}
                onFollowUp={onFollowUp ? (question) => onFollowUp(question, submittedQuery) : undefined}
              />
            </div>

            {bundle && (
              <p className="mt-4 border-t border-line pt-3 text-[11px] text-muted">
                {bundle.eligible_source_count} eligible
                {bundle.excluded_source_count > 0 ? ` · ${bundle.excluded_source_count} excluded` : ""} · {result.confidence_state.replaceAll("_", " ")} confidence
                {bundle.jurisdiction ? ` · ${bundle.jurisdiction}` : " · Any jurisdiction"} · {bundle.freshness_state} sources · {style?.label ?? "Unknown risk"}
              </p>
            )}
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
  const [conversations, setConversations] = useState<Conversation[]>(() =>
    typeof window === "undefined" ? [] : loadConversations(),
  );
  const [activeId, setActiveId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const saved = loadActiveConversationId();
    return saved && conversations.some((c) => c.id === saved) ? saved : null;
  });
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  function persist(next: Conversation[]) {
    setConversations(next);
    persistConversations(next);
  }

  function patchTurn(convId: string, turnId: string, patch: Partial<Turn>) {
    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id !== convId ? c : { ...c, updatedAt: Date.now(), turns: c.turns.map((t) => (t.id !== turnId ? t : { ...t, ...patch })) },
      );
      persistConversations(next);
      return next;
    });
  }

  function startNewChat() {
    setActiveId(null);
    persistActiveConversationId(null);
    setQuery("");
  }

  /** Seeds the composer with the suggestion + the just-answered turn's own
   * question as context — never auto-submits, the user stays in control. */
  function handleFollowUp(question: string, originalTurnQuery: string) {
    setQuery(`${question} Context: ${originalTurnQuery}`);
  }

  function selectConversation(id: string) {
    setActiveId(id);
    persistActiveConversationId(id);
    setQuery("");
  }

  function pinConversation(id: string) {
    persist(conversations.map((c) => (c.id === id ? { ...c, pinned: !c.pinned } : c)));
  }

  function renameConversation(id: string, title: string) {
    persist(conversations.map((c) => (c.id === id ? { ...c, title } : c)));
  }

  function deleteConversation(id: string) {
    persist(conversations.filter((c) => c.id !== id));
    if (activeId === id) {
      setActiveId(null);
      persistActiveConversationId(null);
    }
  }

  async function handleSubmit() {
    const trimmed = query.trim();
    if (!trimmed || submitting) return;
    const token = getAuthToken();
    if (!token) {
      setSubmitError("Please sign in before asking Kriton.");
      return;
    }

    const turnId = genId("turn");
    const newTurn: Turn = { id: turnId, query: trimmed, submittedQuery: trimmed, result: null, error: null, loading: true };

    const isNew = activeId === null;
    const convId = activeId ?? genId("conv");
    const now = timestamp();
    const priorConversation = conversations.find((c) => c.id === convId) ?? null;
    const cycle = clarificationCycleFor(priorConversation);
    setConversations((prev) => {
      const next = isNew
        ? [{ id: convId, title: trimmed.slice(0, 80), turns: [newTurn], createdAt: now, updatedAt: now, pinned: false }, ...prev]
        : prev.map((c) => (c.id === convId ? { ...c, updatedAt: now, turns: [...c.turns, newTurn] } : c));
      persistConversations(next);
      return next;
    });
    if (isNew) {
      setActiveId(convId);
      persistActiveConversationId(convId);
    }

    setQuery("");
    setSubmitError(null);
    setSubmitting(true);
    try {
      const idempotencyKey = genId("idem");
      const response = await askKriton(
        token,
        { query: trimmed, jurisdiction, mode: "Workflow", clarification_cycle: cycle, conversation_id: convId },
        idempotencyKey,
      );
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

  const [submitError, setSubmitError] = useState<string | null>(null);

  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;
  const hasConversation = activeConversation !== null && activeConversation.turns.length > 0;
  const sorted = useMemo(() => sortConversations(conversations), [conversations]);
  const lastTurnLoading = activeConversation?.turns.at(-1)?.loading;
  const turnCount = activeConversation?.turns.length;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turnCount, lastTurnLoading]);

  const sidebarProps = {
    conversations: sorted,
    activeId,
    onSelect: selectConversation,
    onPin: pinConversation,
    onRename: renameConversation,
    onDelete: deleteConversation,
    onNewChat: startNewChat,
  };

  return (
    <main className="kriton-page-background relative min-h-screen w-full min-w-0 overflow-hidden text-ink">
      <div className="kriton-page-ambient pointer-events-none absolute inset-0" />
      <div className="relative z-10 grid h-screen w-full min-w-0 grid-cols-1 md:grid-cols-[252px_minmax(0,1fr)]">
        <DesktopSidebar {...sidebarProps} showMenu />
        <MobileDrawer {...sidebarProps} showMenu open={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />

        <section className="relative flex min-h-0 min-w-0 flex-col">
          <header className="relative z-10 flex h-14 items-center justify-between border-b border-line bg-panel/80 px-4 md:hidden">
            <div className="flex items-center gap-2">
              <ZoikoGlyph className="h-8 w-8 rounded-lg" />
              <span className="font-bold text-ink">Kriton</span>
            </div>
            <button onClick={() => setMobileMenuOpen(true)} aria-label="Open recent chats" className="text-muted">
              <History size={19} />
            </button>
          </header>

          <div ref={scrollRef} className="relative z-10 flex-1 overflow-y-auto px-4">
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

                  <div className="mt-8 w-full">
                    <Composer
                      variant="hero"
                      query={query}
                      onQueryChange={setQuery}
                      jurisdiction={jurisdiction}
                      onJurisdictionChange={setJurisdiction}
                      onSubmit={handleSubmit}
                      submitting={submitting}
                      error={submitError}
                    />
                  </div>

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
                <div className="w-full max-w-4xl space-y-6 self-stretch">
                  {activeConversation?.turns.map((turn) => (
                    <ConversationTurn key={turn.id} turn={turn} onFollowUp={handleFollowUp} />
                  ))}

                  <Composer
                    variant="sticky"
                    query={query}
                    onQueryChange={setQuery}
                    jurisdiction={jurisdiction}
                    onJurisdictionChange={setJurisdiction}
                    onSubmit={handleSubmit}
                    submitting={submitting}
                    error={submitError}
                  />
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

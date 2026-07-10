"use client";

import { useState } from "react";
import Link from "next/link";
import { Pill } from "@/components/governance/Pill";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  AlertTriangle,
  Info,
  Loader2,
  BookOpen,
  History,
  Send,
  Sparkles,
  Bot,
  FileText,
  SlidersHorizontal,
  Bookmark,
  CheckCircle2,
  Scale,
  Landmark,
  GraduationCap,
  LockKeyhole,
} from "lucide-react";
import { ADVISOR } from "@/lib/advisor";
import type { RiskLevel } from "@/lib/safety-api";
import { askKriton, createSavedAnswer, getAuthToken, ApiError, type AskKritonResponse } from "@/lib/api";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];

const EXAMPLE_QUERIES = [
  {
    q: "Summarise the accrual basis of accounting with source-backed teaching points.",
    j: "",
    note: "Learn",
    icon: GraduationCap,
  },
  {
    q: "For the UK, what should I consider when reviewing mixed supply VAT treatment?",
    j: "UK",
    note: "Tax",
    icon: Landmark,
  },
  {
    q: "What information do you need before explaining revenue recognition for a contract?",
    j: "IFRS",
    note: "Scope",
    icon: Scale,
  },
  {
    q: "Check whether this request crosses an academic integrity boundary.",
    j: "",
    note: "Safety",
    icon: LockKeyhole,
  },
];

const RISK_STYLES: Record<
  RiskLevel,
  { bg: string; border: string; text: string; icon: typeof ShieldCheck; label: string }
> = {
  LOW: { bg: "bg-ok/10", border: "border-ok/30", text: "text-ok", icon: ShieldCheck, label: "Low Risk - Verified" },
  MEDIUM: { bg: "bg-info/10", border: "border-info/30", text: "text-info", icon: Info, label: "Medium Risk - Educational" },
  HIGH: { bg: "bg-warn/10", border: "border-warn/30", text: "text-warn", icon: ShieldAlert, label: "High Risk - Limitations Apply" },
  RESTRICTED: { bg: "bg-bad/10", border: "border-bad/30", text: "text-bad", icon: ShieldOff, label: "Restricted - Blocked" },
};

const CONFIDENCE_TONE: Record<string, "ok" | "warn" | "bad"> = {
  HIGH_CONFIDENCE: "ok",
  LOW_CONFIDENCE: "warn",
  NO_ELIGIBLE_SOURCE: "bad",
};

export default function AskKritonPage() {
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskKritonResponse | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    setError("");
    setSaved(false);
    try {
      // The backend owns source confidence and safety classification. Keeping
      // those controls off the page prevents a cosmetic setting from hiding a
      // real "no eligible source" result.
      const response = await askKriton(getAuthToken(), {
        query,
        jurisdiction,
        mode: "Workflow",
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the orchestration service.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveAnswer() {
    if (!result?.answer || !decision) return;
    setSaving(true);
    try {
      await createSavedAnswer(getAuthToken(), {
        query_id: result.query_id,
        query_text: query,
        answer_text: result.answer.output_text,
        risk_level: decision.risk_level,
      });
      setSaved(true);
    } catch {
      setError("Could not save this answer.");
    } finally {
      setSaving(false);
    }
  }

  const decision = result?.safety ?? null;
  const style = decision ? RISK_STYLES[decision.risk_level as RiskLevel] : null;
  const Icon = style?.icon ?? ShieldCheck;
  const confidenceTone = result?.source_bundle
    ? CONFIDENCE_TONE[result.source_bundle.confidence_state] ?? "neutral"
    : "neutral";

  const noAnswerText =
    result?.outcome === "HUMAN_REVIEW"
      ? "This query was routed to human review instead of generation. No response is composed until a reviewer clears it."
      : result?.outcome === "CLARIFICATION"
        ? "The safety classifier could not confidently route this query, so Kriton is asking for clarification instead of generating a response."
        : result?.outcome === "COMPOSE_UNAVAILABLE"
          ? "No approved prompt template is available for this mode, so no response could be composed."
          : result?.outcome === "REJECTED"
            ? "This request could not be processed because the question text was empty or malformed."
            : "This query was refused before reaching generation.";

  return (
    <main className="flex-1 overflow-y-auto bg-bg">
      <div className="grid min-h-[calc(100vh-72px)] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="flex min-h-0 flex-col border-line lg:border-r">
          <header className="flex items-center justify-between gap-3 border-b border-line bg-panel/90 px-4 py-3 backdrop-blur sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ink text-panel">
                <Bot size={20} />
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-base font-bold text-ink">{ADVISOR.navLabel}</h1>
                <p className="truncate text-xs text-muted">Accounting intelligence with source checks, safety routing, and audit evidence.</p>
              </div>
            </div>
            <div className="hidden items-center gap-2 sm:flex">
              <Pill tone={decision ? "ok" : "neutral"}>{decision ? "Routed" : "Ready"}</Pill>
              <Pill tone={result?.source_bundle ? confidenceTone : "neutral"}>{result?.source_bundle?.confidence_state ?? "Sources pending"}</Pill>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
            <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
              {!result && !loading && (
                <div className="flex min-h-[52vh] flex-col justify-center">
                  <div className="mx-auto max-w-2xl text-center">
                    <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-lg border border-line bg-panel shadow-[0_16px_40px_rgba(11,95,122,0.10)]">
                      <Sparkles size={24} className="text-brand" />
                    </div>
                    <h2 className="text-3xl font-bold tracking-normal text-ink sm:text-4xl">
                      What should Kriton verify today?
                    </h2>
                    <p className="mt-3 text-sm leading-6 text-muted">
                      Ask for guidance, request source-backed reasoning, or test whether a question crosses a professional boundary.
                    </p>
                  </div>

                  <div className="mt-8 grid grid-cols-1 gap-3 md:grid-cols-2">
                    {EXAMPLE_QUERIES.map(({ q, j, note, icon: ExampleIcon }) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => {
                          setQuery(q);
                          setJurisdiction(j);
                          setResult(null);
                        }}
                        className="group min-h-28 rounded-lg border border-line bg-panel p-4 text-left shadow-[0_10px_30px_rgba(11,95,122,0.06)] transition hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-[0_16px_36px_rgba(11,95,122,0.12)]"
                      >
                        <div className="flex items-start gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-soft text-brand">
                            <ExampleIcon size={17} />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-xs font-bold uppercase text-muted">{note}</span>
                            <span className="mt-1 block text-sm leading-5 text-ink">{q}</span>
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {(query.trim() || loading || result) && (
                <div className="space-y-5">
                  {query.trim() && (
                    <div className="flex justify-end">
                      <div className="max-w-[82%] rounded-lg bg-ink px-4 py-3 text-sm leading-6 text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)]">
                        {query}
                      </div>
                    </div>
                  )}

                  {loading && (
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-panel text-brand shadow-sm">
                        <Loader2 size={17} className="animate-spin" />
                      </div>
                      <div className="rounded-lg border border-line bg-panel px-4 py-3 shadow-[0_10px_30px_rgba(11,95,122,0.06)]">
                        <p className="text-sm font-semibold text-ink">{ADVISOR.loadingState}</p>
                        <p className="mt-1 text-xs text-muted">Retrieval, safety routing, and answer composition are running.</p>
                      </div>
                    </div>
                  )}

                  {result && decision && (
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand text-white shadow-sm">
                        <Bot size={17} />
                      </div>
                      <article className="min-w-0 flex-1 rounded-lg border border-line bg-panel p-5 shadow-[0_14px_36px_rgba(11,95,122,0.08)]">
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            {style && (
                              <span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg ${style.bg}`}>
                                <Icon size={16} className={style.text} />
                              </span>
                            )}
                            <div>
                              <p className="text-sm font-bold text-ink">Kriton response</p>
                              <p className="text-xs text-muted">{style?.label ?? result.outcome}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            {result.answer && (
                              <button
                                onClick={handleSaveAnswer}
                                disabled={saving || saved}
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-panel px-3 text-xs font-semibold text-ink hover:bg-soft disabled:opacity-60"
                              >
                                <Bookmark size={13} />
                                {saved ? "Saved" : saving ? "Saving..." : "Save"}
                              </button>
                            )}
                            <Link
                              href={`/audit-replay?correlation_id=${encodeURIComponent(result.query_id)}`}
                              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-panel px-3 text-xs font-semibold text-brand hover:bg-soft"
                            >
                              <History size={13} />
                              Audit
                            </Link>
                          </div>
                        </div>

                        {result.answer ? (
                          <>
                            <p className="whitespace-pre-line text-sm leading-7 text-ink">{result.answer.output_text}</p>
                            <p className="mt-4 border-t border-line pt-3 text-[11px] text-muted">
                              Composed via {result.answer.prompt_name} ({result.answer.prompt_id})
                            </p>
                          </>
                        ) : (
                          <p className="rounded-lg border border-line bg-soft p-4 text-sm italic leading-6 text-muted">
                            {noAnswerText}
                          </p>
                        )}

                        {decision.refusal_text && (
                          <p className="mt-4 whitespace-pre-line rounded-lg border border-bad/20 bg-bad/10 p-3 text-sm leading-6 text-ink">
                            {decision.refusal_text}
                          </p>
                        )}

                        {decision.safe_alternative && (
                          <p className="mt-3 rounded-lg border border-ok/20 bg-ok/10 p-3 text-sm leading-6 text-ink">
                            <span className="font-semibold text-ok">Safe alternative: </span>
                            {decision.safe_alternative}
                          </p>
                        )}

                        {decision.requires_professional_boundary && (
                          <p className="mt-3 rounded-lg border border-info/20 bg-info/10 p-3 text-xs leading-5 text-muted">
                            Kriton provides source-governed guidance to support your professional judgment. It does not act as a licensed accountant,
                            auditor, tax advisor, or legal counsel.
                          </p>
                        )}
                      </article>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-line bg-bg/95 px-4 py-4 backdrop-blur sm:px-6">
            <form onSubmit={handleSubmit} className="mx-auto max-w-4xl">
              <div className="rounded-lg border border-line bg-panel p-3 shadow-[0_18px_46px_rgba(11,95,122,0.12)]">
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={ADVISOR.chatPlaceholder}
                  rows={3}
                  className="min-h-20 w-full resize-none bg-transparent text-sm leading-6 text-ink placeholder:text-muted outline-none"
                />
                <div className="mt-3 flex flex-col gap-3 border-t border-line pt-3 sm:flex-row sm:items-center">
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
                      <SlidersHorizontal size={14} />
                      Jurisdiction
                    </span>
                    <select
                      value={jurisdiction}
                      onChange={(e) => setJurisdiction(e.target.value)}
                      className="h-9 rounded-lg border border-line bg-panel px-3 text-xs font-medium text-ink outline-none"
                    >
                      {JURISDICTIONS.map((j) => (
                        <option key={j} value={j}>{j || "Any"}</option>
                      ))}
                    </select>
                    <span className="rounded-full border border-line bg-chip px-2.5 py-1 text-[11px] font-semibold text-muted">
                      Workflow mode
                    </span>
                  </div>

                  <button
                    type="submit"
                    disabled={loading || !query.trim()}
                    aria-label="Ask Kriton"
                    className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(11,95,122,0.18)] transition-colors hover:bg-brand-2 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
                  >
                    {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                    Ask
                  </button>
                </div>
              </div>
              {error && (
                <p className="mt-3 rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                  {error}
                </p>
              )}
            </form>
          </div>
        </section>

        <aside className="hidden min-h-0 overflow-y-auto bg-panel lg:block">
          <div className="sticky top-0 border-b border-line bg-panel px-5 py-4">
            <h2 className="text-sm font-bold text-ink">Answer context</h2>
            <p className="mt-1 text-xs leading-5 text-muted">Risk, sources, and required controls update after each question.</p>
          </div>

          <div className="space-y-4 p-5">
            <section className={`rounded-lg border p-4 ${style ? `${style.border} ${style.bg}` : "border-line bg-soft/60"}`}>
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-panel">
                  <Icon size={18} className={style?.text ?? "text-muted"} />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-bold uppercase text-muted">Safety route</p>
                  <h3 className={`mt-1 text-sm font-bold ${style?.text ?? "text-ink"}`}>{style?.label ?? "Awaiting query"}</h3>
                  {decision && (
                    <p className="mt-1 text-xs leading-5 text-muted">
                      Confidence {(decision.confidence * 100).toFixed(0)}% | Route {decision.route} | Outcome {result?.outcome}
                    </p>
                  )}
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-line bg-bg p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-bold text-ink">Retrieved sources</h3>
                {result?.source_bundle ? <Pill tone={confidenceTone}>{result.source_bundle.confidence_state}</Pill> : <Pill>Pending</Pill>}
              </div>
              {!result?.source_bundle || result.source_bundle.sources.length === 0 ? (
                <p className="flex items-start gap-2 text-sm leading-6 text-muted">
                  <BookOpen size={15} className="mt-1 shrink-0" />
                  No eligible sources shown yet.
                </p>
              ) : (
                <ul className="space-y-3">
                  {result.source_bundle.sources.map((s) => (
                    <li key={s.id} className="rounded-lg border border-line bg-panel p-3">
                      <div className="flex items-start gap-2">
                        <FileText size={15} className="mt-0.5 shrink-0 text-brand" />
                        <div className="min-w-0">
                          <p className="text-sm font-semibold leading-5 text-ink">{s.title}</p>
                          <p className="mt-1 text-xs leading-5 text-muted">
                            {s.version_label} | {s.jurisdiction_scope} | {s.category}
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-lg border border-line bg-bg p-4">
              <h3 className="text-sm font-bold text-ink">Controls</h3>
              {decision ? (
                <>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {decision.requires_sources && <Pill tone="info">Source grounding</Pill>}
                    {decision.requires_citation && <Pill tone="info">Inline citations</Pill>}
                    {decision.requires_professional_boundary && <Pill tone="warn">Boundary notice</Pill>}
                    {decision.requires_human_review && <Pill tone="bad">Human review</Pill>}
                    {!decision.requires_sources && !decision.requires_citation && !decision.requires_professional_boundary && !decision.requires_human_review && (
                      <Pill tone="ok">No extra requirements</Pill>
                    )}
                  </div>
                  {decision.limitations.length > 0 && (
                    <ul className="mt-4 space-y-2">
                      {decision.limitations.map((l, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs leading-5 text-muted">
                          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" />
                          {l}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="mt-4 border-t border-line pt-4">
                    <p className="text-xs font-bold uppercase text-muted">Rules applied</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {decision.rules_applied.map((r) => (
                        <Pill key={r}>{r}</Pill>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <p className="mt-2 flex items-start gap-2 text-sm leading-6 text-muted">
                  <CheckCircle2 size={15} className="mt-1 shrink-0 text-ok" />
                  Submit a question to see the required control set.
                </p>
              )}
            </section>
          </div>
        </aside>
      </div>
    </main>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { Pill } from "@/components/governance/Pill";
import { LoadError, errorMessage, formatCount, formatWhen } from "@/components/governance/LiveStatus";
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Loader2,
  Send,
  ListChecks,
  Info,
  Activity,
  Gavel,
} from "lucide-react";
import {
  checkBoundary,
  getBoundaryView,
  type BoundaryCheckResult,
  type BoundaryView,
} from "@/lib/safety-api";

// ─── Spec-defined Sufficient-Context Checklist (ZL-T0-11 §7.2) ───────────────

const CONTEXT_CHECKLIST = [
  {
    id: "CTX-1",
    condition: "Jurisdiction identified",
    detail: "At least one jurisdiction is present (UK, US, IFRS, UAE, India, EU…). Without it, treat as RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT.",
    required: true,
  },
  {
    id: "CTX-2",
    condition: "Entity type known",
    detail: "Query scope includes entity type (sole trader, partnership, listed company, etc.) for entity-specific standards.",
    required: true,
  },
  {
    id: "CTX-3",
    condition: "Applicable framework confirmed",
    detail: "Accounting or regulatory framework is specified or inferable (IFRS, UK GAAP, US GAAP, local tax code).",
    required: true,
  },
  {
    id: "CTX-4",
    condition: "Source bundle available",
    detail: "At least one non-expired, licensed source exists for the topic. Without a source, refuse with source-limitation notice.",
    required: true,
  },
];

// ─── Sample Queries for Demo ──────────────────────────────────────────────────

const SAMPLE_DRAFTS = [
  {
    label: "Safe: Educational explanation",
    text: "IFRS 16 requires lessees to recognise a right-of-use asset and a corresponding lease liability at the commencement date of the lease. This applies to most leases with a term of more than 12 months. For specific application to your situation, please consult a qualified accountant.",
  },
  {
    label: "Violation: Direct tax advice",
    text: "You must file your tax return under the self-assessment scheme. Since your income is above £100,000 your personal allowance is withdrawn and you will owe additional tax. I recommend filing immediately to avoid penalties.",
  },
  {
    label: "Violation: Audit opinion wording",
    text: "Based on the ratios you've provided, there is no going concern risk and the auditors will likely issue an unqualified opinion for the annual report.",
  },
  {
    label: "Violation: Academic answer",
    text: "Here is the complete answer to exam question 3: The correct journal entry is Dr. Lease Liability £50,000 Cr. Cash £50,000.",
  },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

const PANEL = `${PANEL_CLASS} space-y-4`;

const SOURCE_STRENGTH = [
  { value: "sufficient", label: "Strong sources" },
  { value: "limited", label: "Limited sources" },
  { value: "conflicting_sources", label: "Conflicting sources" },
  { value: "stale_sources", label: "Stale sources" },
];

const OUTCOME_COPY: Record<BoundaryCheckResult["outcome"], { title: string; detail: string; tone: "ok" | "bad" | "warn" }> = {
  released: { title: "Passes the boundary checks — would be released", detail: "None of the live wording checks fired for these settings.", tone: "ok" },
  refused: { title: "Prohibited claim — Kriton would refuse this answer", detail: "The answer is withheld and a boundary-safe refusal is returned instead.", tone: "bad" },
  human_review: { title: "Would be sent to human review", detail: "The wording claims more certainty than the sources allow.", tone: "warn" },
};

function friendlyFailure(failure: string): string {
  const match = failure.match(/^([^:]+):[^']*'([^']+)'/);
  return match ? `${match[1]} — pattern ${match[2]}` : failure;
}

export function ProfessionalBoundariesPanel() {
  const [view, setView] = useState<BoundaryView | null>(null);
  const [loadingView, setLoadingView] = useState(true);
  const [viewError, setViewError] = useState("");

  const [draftText, setDraftText] = useState("");
  const [userSpecific, setUserSpecific] = useState(false);
  const [sourceStrength, setSourceStrength] = useState("sufficient");
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState("");
  const [result, setResult] = useState<BoundaryCheckResult | null>(null);

  const load = useCallback(async () => {
    setLoadingView(true);
    try {
      setView(await getBoundaryView());
      setViewError("");
    } catch (err) {
      setViewError(errorMessage(err, "boundary activity"));
    } finally {
      setLoadingView(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  function resetResult() {
    setResult(null);
    setCheckError("");
  }

  async function handleValidate() {
    if (!draftText.trim()) return;
    setChecking(true);
    resetResult();
    try {
      setResult(await checkBoundary({
        text: draftText,
        user_specific: userSpecific,
        confidence_state: sourceStrength,
        authority_level: "secondary",
      }));
    } catch (err) {
      setCheckError(err instanceof Error ? err.message : "The validator did not respond.");
    } finally {
      setChecking(false);
    }
  }

  const counts = view?.counts;
  const checked = (counts?.answers_returned ?? 0) + (counts?.answers_rejected ?? 0);

  return (
    <>

      <LiveSourceStatus loading={loadingView} error={viewError} signedOut={false} reload={load} />

      <div className="space-y-6">

      {/* ── Live counts from the audit ledger ─────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          { label: "Answers checked", value: checked, tone: "text-ink" },
          { label: "Released", value: counts?.answers_returned, tone: "text-ok" },
          { label: "Rejected by validator", value: counts?.answers_rejected, tone: "text-warn" },
          { label: "Prohibited-claim refusals", value: counts?.prohibited_claim_refusals, tone: "text-bad" },
          { label: "Certification refusals", value: counts?.certification_refusals, tone: "text-bad" },
        ].map((tile) => (
          <div key={tile.label} className="rounded-xl border border-line bg-panel/80 p-4">
            <div className="text-[10px] font-bold uppercase tracking-wider text-muted">{tile.label}</div>
            <div className={`mt-2 text-xl font-extrabold ${tile.tone}`}>{view ? formatCount(tile.value) : "—"}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start max-w-7xl">
        <div className="lg:col-span-8 space-y-6">
          {/* Live validator console */}
          <div className={`${PANEL} space-y-5`}>
            <PanelHeader icon={Shield} tone="brand" title="Output Boundary Validator" subtitle="Runs a draft through the same wording checks Ask Kriton applies to every answer." />

            <div className="space-y-1">
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Load Sample Draft</label>
              <div className="flex flex-wrap gap-2">
                {SAMPLE_DRAFTS.map((sample) => (
                  <button
                    key={sample.label}
                    type="button"
                    onClick={() => { setDraftText(sample.text); resetResult(); }}
                    className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[10px] font-semibold text-muted hover:bg-soft hover:text-ink transition-colors cursor-pointer"
                  >
                    {sample.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <label htmlFor="boundary-draft-input" className="text-[10px] font-bold text-muted uppercase tracking-wider">Draft Output Text</label>
              <textarea
                id="boundary-draft-input"
                value={draftText}
                onChange={(e) => { setDraftText(e.target.value); resetResult(); }}
                rows={6}
                className="w-full rounded-xl border border-line bg-soft/40 px-4 py-3 text-xs text-ink leading-relaxed focus:outline-none focus:ring-2 focus:ring-brand/40 transition-all resize-none"
                placeholder="Paste a draft answer to check it against the professional boundary rules…"
              />
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex items-start gap-2 rounded-xl border border-line bg-soft/30 p-3 text-xs text-ink">
                <input
                  type="checkbox"
                  checked={userSpecific}
                  onChange={(e) => { setUserSpecific(e.target.checked); resetResult(); }}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-semibold">Question is about the asker&apos;s own matter</span>
                  <span className="block text-[10px] text-muted">HIGH risk. Directive wording (&ldquo;you must file…&rdquo;) is only checked then.</span>
                </span>
              </label>
              <label className="space-y-1 rounded-xl border border-line bg-soft/30 p-3 text-xs text-ink">
                <span className="font-semibold">Source strength behind the answer</span>
                <select
                  value={sourceStrength}
                  onChange={(e) => { setSourceStrength(e.target.value); resetResult(); }}
                  className="w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-xs"
                >
                  {SOURCE_STRENGTH.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <button
              id="validate-boundary-btn"
              type="button"
              onClick={handleValidate}
              disabled={checking || !draftText.trim()}
              className="flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-xs font-bold text-white shadow-lg shadow-brand/20 hover:bg-brand/90 active:scale-95 transition-all disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {checking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              {checking ? "Validating…" : "Validate Against Boundary Rules"}
            </button>

            {checkError && <LoadError message={`Validation did not run: ${checkError}`} />}
          </div>

          {result && (
            <div className={`${PANEL} space-y-4`}>
              {(() => {
                const copy = OUTCOME_COPY[result.outcome];
                const toneClass = copy.tone === "ok" ? "bg-ok/10 border-ok/30 text-ok" : copy.tone === "bad" ? "bg-bad/10 border-bad/30 text-bad" : "bg-warn/10 border-warn/30 text-warn";
                return (
                  <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${toneClass}`}>
                    {result.passed ? <ShieldCheck size={20} /> : <ShieldAlert size={20} />}
                    <div>
                      <div className="text-sm font-extrabold">{copy.title}</div>
                      <div className="text-[10px] text-muted">{copy.detail}</div>
                    </div>
                  </div>
                );
              })()}
              {result.failures.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-bold text-ink">Checks that fired</h4>
                  {result.failures.map((failure) => (
                    <div key={failure} className="rounded-xl border border-bad/20 bg-bad/5 p-3 text-[11px] text-ink break-words">
                      {friendlyFailure(failure)}
                    </div>
                  ))}
                </div>
              )}
              {result.certification_request && (
                <p className="rounded-xl border border-warn/30 bg-warn/5 p-3 text-[11px] text-warn">
                  As a question, this text asks for a professional sign-off — Kriton would refuse it before answering.
                </p>
              )}
            </div>
          )}

          {/* Recent rejections */}
          <div className={PANEL}>
            <PanelHeader icon={Activity} tone="warn" title="Recent rejected answers" subtitle="Answers the validator stopped before they reached the user" />
            {!view ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : view.recent_rejections.length === 0 ? (
              <p className="py-6 text-center text-xs text-muted">No answers have been rejected for this tenant.</p>
            ) : (
              <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                {view.recent_rejections.map((item) => (
                  <div key={`${item.query_id}-${item.time}`} className="rounded-xl border border-line/60 bg-soft/30 p-3.5 space-y-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-[10px] text-muted">{item.query_id}</span>
                      <span className="text-[10px] text-muted">{formatWhen(item.time)}</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {item.categories.map((category) => <Pill key={category} tone="warn">{category}</Pill>)}
                      {item.route && <Pill tone={item.route === "REFUSAL" ? "bad" : "info"}>{item.route.replace(/_/g, " ")}</Pill>}
                    </div>
                    {item.failures[0] && <p className="text-[11px] leading-relaxed text-muted line-clamp-2">{friendlyFailure(item.failures[0])}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-4 space-y-6">
          {/* Why answers were rejected */}
          <div className={PANEL}>
            <PanelHeader icon={Gavel} tone="bad" title="Rejections by check" />
            {!view ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : view.rejections_by_check.length === 0 ? (
              <p className="text-xs text-muted">No rejections recorded.</p>
            ) : (
              <div className="space-y-2.5">
                {view.rejections_by_check.map((entry) => {
                  const top = view.rejections_by_check[0].count || 1;
                  return (
                    <div key={entry.key} className="space-y-1">
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="text-ink">{entry.label}</span>
                        <span className="font-mono text-muted">{formatCount(entry.count)}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-soft">
                        <div className="h-1.5 rounded-full bg-warn" style={{ width: `${(entry.count / top) * 100}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Sufficient Context Checklist */}
          <div className={PANEL}>
            <PanelHeader icon={ListChecks} tone="ok" title="Sufficient Context (ZL-T0-11 §7.2)" />
            <p className="text-[11px] text-muted">All 4 conditions must be met before Kriton™ can answer a regulated query. Missing conditions route to RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT.</p>
            <div className="space-y-3">
              {CONTEXT_CHECKLIST.map((item) => (
                <div key={item.id} className="rounded-xl border border-ok/20 bg-ok/5 p-3.5 space-y-1">
                  <span className="text-xs font-bold text-ink">{item.condition}</span>
                  <p className="text-[10px] text-muted leading-relaxed">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className={PANEL}>
            <PanelHeader icon={Info} tone="info" title="How It Works" />
            <div className="space-y-2 text-[11px] text-muted leading-relaxed">
              <p>Every Ask Kriton answer passes the <strong className="text-ink">Checkpoint C validator</strong> before it is returned.</p>
              <p><strong className="text-bad">Prohibited claims</strong> (sign-offs, &ldquo;as your accountant&rdquo;, claiming to give tax advice) are refused, unless the cited source itself uses the phrase.</p>
              <p><strong className="text-warn">Directive wording</strong> on a question about the asker&apos;s own matter is restated once as general guidance before anything is refused.</p>
              <p><strong className="text-warn">Over-authoritative or unhedged wording</strong> that the sources cannot back sends the answer to human review.</p>
              <p>Each rejection is written to the audit ledger with the query ID; the counts above come from there.</p>
            </div>
          </div>
        </div>
      </div>

      {/* ── Live rules ───────────────────────────────────────────────────── */}
      <div className={`${PANEL} max-w-7xl`}>
        <PanelHeader icon={Shield} tone="brand" title="Rules the validator enforces" subtitle="Read from the running validator — the exact patterns checked (implements ZL-T0-11 §7.1)." />
        {!view ? (
          <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                  <th className="font-bold pb-2.5 pr-4">Check</th>
                  <th className="font-bold pb-2.5 pr-4">Pattern</th>
                  <th className="font-bold pb-2.5 pr-4">Applies to</th>
                  <th className="font-bold pb-2.5">Outcome</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/40">
                {view.rules.map((rule) => (
                  <tr key={`${rule.check}-${rule.pattern}`}>
                    <td className="py-2.5 pr-4 font-semibold text-ink">{rule.check}</td>
                    <td className="py-2.5 pr-4"><code className="break-all font-mono text-[10px] text-muted">{rule.pattern}</code></td>
                    <td className="py-2.5 pr-4 text-muted">{rule.applies}</td>
                    <td className="py-2.5 text-muted">{rule.outcome}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      </div>
    </>
  );
}

"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, ClipboardList, RefreshCw, ShieldAlert } from "lucide-react";
import { ApiError, getAuthToken, getGovernanceDashboard } from "@/lib/api";
import type {
  AlertSeverity,
  DomainState,
  GateState,
  GovernanceDashboardViewModel,
} from "@/lib/governance-dashboard-types";

const STATE_LABEL: Record<DomainState, string> = {
  critical: "Critical",
  attention: "Needs attention",
  effective: "Effective",
  not_assessed: "Not assessed",
};

const STATE_STYLE: Record<DomainState, string> = {
  critical: "bg-bad/10 text-bad",
  attention: "bg-warn/10 text-warn",
  effective: "bg-ok/10 text-ok",
  not_assessed: "bg-soft text-muted",
};

const SEVERITY_STYLE: Record<AlertSeverity, string> = {
  critical: "bg-bad text-white",
  high: "bg-bad/10 text-bad",
  medium: "bg-warn/10 text-warn",
  low: "bg-soft text-muted",
};

const GATE_STYLE: Record<GateState, { label: string; className: string }> = {
  passed: { label: "Passed", className: "text-ok" },
  blocked: { label: "Blocked", className: "text-bad" },
  partial: { label: "Partial evidence", className: "text-warn" },
  not_assessed: { label: "Not assessed", className: "text-muted" },
};

function when(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function StatePill({ state }: { state: DomainState }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${STATE_STYLE[state]}`}>
      {STATE_LABEL[state]}
    </span>
  );
}

/** Governance Dashboard (Admin Governance Console spec §4): health cards,
 * alerts with owners, the viewer's work queue and release blockers — all from
 * the tenant's live governance records. Nothing here is sample data: domains
 * the platform cannot measure yet say "Not assessed" and why. */
export function GovernanceDashboard() {
  const [model, setModel] = useState<GovernanceDashboardViewModel | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // State is only set in the request's callbacks, so the initial load can run
  // straight from the effect; Refresh resets the loading/error state first.
  const fetchModel = useCallback((signal?: AbortSignal) => {
    return getGovernanceDashboard(getAuthToken(), { environment: "PRODUCTION", windowDays: 30 }, signal)
      .then((next) => {
        setModel(next);
        setError("");
      })
      .catch((err) => {
        if (signal?.aborted) return;
        setError(
          err instanceof ApiError && err.status === 403
            ? "The Governance Dashboard isn't available for your role."
            : "Could not load the governance assessment. Please try again.",
        );
      })
      .finally(() => {
        if (!signal?.aborted) setLoading(false);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchModel(controller.signal);
    return () => controller.abort();
  }, [fetchModel]);

  function load() {
    setLoading(true);
    setError("");
    return fetchModel();
  }

  const summary = model?.governanceSummary;

  return (
    <main className="flex-1 overflow-y-auto bg-canvas p-4 lg:p-6">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">Governance Dashboard</h1>
            <p className="mt-1 text-muted">
              Live oversight of sources, risk policy, escalations, incidents, the audit ledger and release readiness.
            </p>
            {model && (
              <p className="mt-2 text-sm text-muted">
                {model.governanceScope.workspaceName} · {model.governanceScope.environment} · Assessed{" "}
                {when(model.governanceSummary.lastEvaluatedAt)}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex min-h-11 items-center gap-2 self-start rounded-xl border border-line bg-panel px-4 text-sm font-semibold text-ink hover:bg-soft disabled:opacity-60"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
            {loading ? "Assessing…" : "Refresh"}
          </button>
        </header>

        {error && (
          <div role="alert" className="rounded-xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm text-bad">
            {error}
          </div>
        )}

        {!model && loading && (
          <div aria-busy="true" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-36 animate-pulse rounded-2xl border border-line bg-panel" />
            ))}
          </div>
        )}

        {model && summary && (
          <>
            <section className="rounded-2xl border border-line bg-panel p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-semibold text-ink">Overall</span>
                <StatePill state={summary.overallState} />
                <span className="text-sm text-ink">
                  {summary.criticalExceptionCount} critical · {summary.highExceptionCount} high ·{" "}
                  {summary.pendingDecisionCount} decision{summary.pendingDecisionCount === 1 ? "" : "s"} for you ·{" "}
                  {summary.blockedGateCount} release gate{summary.blockedGateCount === 1 ? "" : "s"} blocked
                </span>
              </div>
              {summary.notAssessedDomains.length > 0 && (
                <p className="mt-2 text-xs text-muted">
                  Not assessed yet: {summary.notAssessedDomains.join(", ")}. These show no figures until there is
                  real data behind them.
                </p>
              )}
            </section>

            <section aria-labelledby="health-title">
              <h2 id="health-title" className="mb-3 text-xs font-bold uppercase tracking-wide text-muted">
                Governance health
              </h2>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                {model.domainStates.map((domain) => (
                  <article key={domain.key} className="flex flex-col rounded-2xl border border-line bg-panel p-4">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-sm font-semibold text-ink">{domain.label}</h3>
                      <StatePill state={domain.state} />
                    </div>
                    <p className="mt-2 text-sm text-ink">{domain.headline}</p>
                    {domain.metrics.length > 0 && (
                      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                        {domain.metrics.map((metric) => (
                          <div key={metric.label} className="contents">
                            <dt className="text-muted">{metric.label}</dt>
                            <dd className="text-right font-semibold text-ink">{metric.value ?? "—"}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                    {domain.reason && <p className="mt-3 text-xs text-muted">{domain.reason}</p>}
                    <Link
                      href={domain.drilldownTarget}
                      className="mt-auto inline-flex items-center gap-1 pt-3 text-xs font-semibold text-brand hover:underline"
                    >
                      Open <ArrowRight size={12} />
                    </Link>
                  </article>
                ))}
              </div>
            </section>

            <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
              <section className="overflow-hidden rounded-2xl border border-line bg-panel" aria-labelledby="alerts-title">
                <div className="flex items-center gap-2 border-b border-line px-5 py-4">
                  <ShieldAlert size={16} className="text-bad" />
                  <h2 id="alerts-title" className="text-sm font-bold text-ink">Alerts</h2>
                  <span className="text-xs text-muted">({model.exceptions.length})</span>
                </div>
                {model.exceptions.length === 0 ? (
                  <p className="flex items-center gap-2 p-5 text-sm text-muted">
                    <CheckCircle2 size={16} className="text-ok" /> No active alerts.
                  </p>
                ) : (
                  <ul className="divide-y divide-line">
                    {model.exceptions.map((alert) => (
                      <li key={alert.id} className="flex flex-wrap items-start gap-3 p-4">
                        <span className={`rounded-md px-2 py-0.5 text-[11px] font-bold uppercase ${SEVERITY_STYLE[alert.severity]}`}>
                          {alert.severity}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold text-ink">{alert.title}</p>
                          <p className="mt-0.5 text-xs text-muted">
                            {alert.domain} · Owner: {alert.ownerRole}
                            {alert.dueAt && ` · Due ${when(alert.dueAt)}`}
                            {!alert.dueAt && alert.openedAt && ` · Opened ${when(alert.openedAt)}`}
                          </p>
                        </div>
                        <Link
                          href={alert.drilldownTarget}
                          title={alert.resolvedBy}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline"
                        >
                          Resolve <ArrowRight size={12} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <div className="space-y-5">
                <section className="overflow-hidden rounded-2xl border border-line bg-panel" aria-labelledby="queue-title">
                  <div className="flex items-center gap-2 border-b border-line px-5 py-4">
                    <ClipboardList size={16} className="text-brand" />
                    <h2 id="queue-title" className="text-sm font-bold text-ink">Your work queue</h2>
                    <span className="text-xs text-muted">({model.decisions.length})</span>
                  </div>
                  {model.decisions.length === 0 ? (
                    <p className="p-5 text-sm text-muted">Nothing waiting for your decision.</p>
                  ) : (
                    <ul className="divide-y divide-line">
                      {model.decisions.map((item) => (
                        <li key={item.id} className="p-4">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-muted">{item.type}</p>
                          <Link href={item.drilldownTarget} className="mt-0.5 block text-sm font-semibold text-ink hover:text-brand">
                            {item.title}
                          </Link>
                          <p className="mt-0.5 text-xs text-muted">Submitted {when(item.submittedAt)}</p>
                          {item.blockedReason && <p className="mt-1 text-xs text-warn">{item.blockedReason}</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="overflow-hidden rounded-2xl border border-line bg-panel" aria-labelledby="release-title">
                  <div className="flex items-center gap-2 border-b border-line px-5 py-4">
                    <AlertTriangle size={16} className="text-warn" />
                    <h2 id="release-title" className="text-sm font-bold text-ink">Release readiness</h2>
                  </div>
                  <ul className="divide-y divide-line">
                    {model.releaseReadiness.map((gate) => (
                      <li key={gate.gate} className="flex items-start gap-3 p-4">
                        {gate.state === "not_assessed" ? (
                          <CircleDashed size={16} className="mt-0.5 shrink-0 text-muted" />
                        ) : (
                          <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${gate.state === "passed" ? "bg-ok" : gate.state === "blocked" ? "bg-bad" : "bg-warn"}`} />
                        )}
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-ink">
                            {gate.gate}{" "}
                            <span className={`text-xs font-semibold ${GATE_STYLE[gate.state].className}`}>
                              · {GATE_STYLE[gate.state].label}
                            </span>
                          </p>
                          <p className="mt-0.5 text-xs text-muted">{gate.reason}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}

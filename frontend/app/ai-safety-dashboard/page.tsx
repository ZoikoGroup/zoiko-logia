"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { StatTile } from "@/components/governance/StatTile";
import { Pill } from "@/components/governance/Pill";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { errorMessage, formatCount, formatWhen } from "@/components/governance/LiveStatus";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  Activity,
  AlertTriangle,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Zap,
  BarChart3,
  MessageSquare,
} from "lucide-react";
import { getSafetyEvents, getSafetySummary, type SafetyEvent, type SafetySummary } from "@/lib/safety-api";

type Tone = Exclude<PanelTone, "brand">;

const EVENT_ICONS: Record<string, typeof ShieldCheck> = {
  risk_classification_applied: ShieldCheck,
  risk_classification_uncertain: AlertTriangle,
  restricted_topic_blocked: ShieldOff,
  human_review_case_created: Clock,
  human_review_decision_recorded: CheckCircle2,
  security_incident_created: XCircle,
  safety_refusal_returned: ShieldAlert,
};

const EVENT_TONES: Record<string, Tone> = {
  risk_classification_applied: "ok",
  risk_classification_uncertain: "warn",
  restricted_topic_blocked: "bad",
  human_review_case_created: "info",
  human_review_decision_recorded: "ok",
  security_incident_created: "bad",
  safety_refusal_returned: "warn",
};

// Tailwind only ships classes it can see in the source, so tone classes must
// be written out in full rather than built as `bg-${tone}`.
const EVENT_TONE_CLASSES: Record<Tone, { dot: string; icon: string }> = {
  ok: { dot: "bg-ok", icon: "bg-ok/10 border-ok/20 text-ok" },
  warn: { dot: "bg-warn", icon: "bg-warn/10 border-warn/20 text-warn" },
  bad: { dot: "bg-bad", icon: "bg-bad/10 border-bad/20 text-bad" },
  info: { dot: "bg-info", icon: "bg-info/10 border-info/20 text-info" },
};

const OUTCOME_TEXT: Record<Tone, string> = { ok: "text-ok", warn: "text-warn", bad: "text-bad", info: "text-info" };

const RISK_ORDER = ["ZERO", "LOW", "MEDIUM", "HIGH", "RESTRICTED"];
const RISK_BAR: Record<string, string> = {
  ZERO: "bg-muted/50", LOW: "bg-ok", MEDIUM: "bg-info", HIGH: "bg-warn", RESTRICTED: "bg-bad",
};

function Loading() {
  return <div className="flex items-center justify-center py-10 text-muted"><Loader2 className="animate-spin" size={18} /></div>;
}

export default function AiSafetyDashboardPage() {
  const [summary, setSummary] = useState<SafetySummary | null>(null);
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextEvents] = await Promise.all([getSafetySummary(), getSafetyEvents()]);
      setSummary(nextSummary);
      setEvents(nextEvents);
      setError("");
    } catch (err) {
      setError(errorMessage(err, "the safety ledger"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  const totals = summary?.totals;
  const week = summary?.last_7_days;
  const escalations = summary?.escalations;
  const show = (value: number | undefined) => (summary ? formatCount(value) : "—");

  const outcomes = summary?.answer_outcomes;
  const outcomes7d = summary?.answer_outcomes_7d;
  const outcomeRows: { label: string; key: keyof NonNullable<typeof outcomes>; tone: Tone }[] = [
    { label: "Answered", key: "answered", tone: "ok" },
    { label: "Clarification asked", key: "clarified", tone: "info" },
    { label: "Refused", key: "refused", tone: "warn" },
    { label: "Sent to human review", key: "sent_to_review", tone: "info" },
  ];

  const trend = summary?.trend ?? [];
  const trendMax = Math.max(1, ...trend.map((p) => p.classified + p.blocked + p.review + p.other));
  const riskTotal = RISK_ORDER.reduce((sum, level) => sum + (summary?.risk_levels[level] ?? 0), 0);

  return (
    <PageShell
      title="AI Safety Dashboard"
      subtitle="Real-time view of risk classifications, refusals, escalations, and human review activity."
      showMetrics={false}
    >
      <LiveSourceStatus loading={loading} error={error} signedOut={false} reload={load} />

      <div className="space-y-6">
        {/* Whole-ledger totals for this tenant */}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <StatTile label="Classifications" value={show(totals?.classified)} tone="ok" icon={ShieldCheck} hint={summary ? `${formatCount(week?.classified)} in last 7 days` : undefined} />
          <StatTile label="Blocked / Refused" value={show(totals?.blocked)} tone="bad" icon={ShieldOff} hint={summary ? `${formatCount(week?.blocked)} in last 7 days` : undefined} />
          <StatTile label="Uncertain" value={show(totals?.uncertain)} tone="warn" icon={AlertTriangle} hint={summary ? "Took the conservative path" : undefined} />
          <StatTile label="Security Incidents" value={show(totals?.incidents)} tone="bad" icon={XCircle} hint={summary ? `${formatCount(week?.incidents)} in last 7 days` : undefined} />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
          <div className={`xl:col-span-8 ${PANEL_CLASS}`}>
            <PanelHeader icon={BarChart3} tone="info" title="Safety activity — last 14 days" subtitle="Events per day from the safety ledger" />
            {!summary ? <Loading /> : (
              <div className="space-y-3">
                <div className="flex h-40 items-end gap-1.5" role="img" aria-label="Safety events per day for the last 14 days">
                  {trend.map((point) => {
                    const total = point.classified + point.blocked + point.review + point.other;
                    return (
                      <div key={point.date} className="flex h-full flex-1 flex-col justify-end" title={`${point.date}: ${total} events (${point.classified} classified, ${point.blocked} blocked, ${point.review} review)`}>
                        <div className="flex flex-col-reverse overflow-hidden rounded-t-md" style={{ height: `${(total / trendMax) * 100}%`, minHeight: total ? 2 : 0 }}>
                          <div className="bg-ok/70" style={{ flexGrow: point.classified }} />
                          <div className="bg-info/70" style={{ flexGrow: point.review + point.other }} />
                          <div className="bg-bad/80" style={{ flexGrow: point.blocked }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex gap-1.5 text-[9px] text-muted">
                  {trend.map((point, index) => (
                    <span key={point.date} className="flex-1 text-center">
                      {index % 2 === 0 ? new Date(`${point.date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : ""}
                    </span>
                  ))}
                </div>
                <div className="flex flex-wrap gap-3 text-[11px] text-muted">
                  <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-ok/70" />Classified</span>
                  <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-info/70" />Review &amp; other</span>
                  <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-bad/80" />Blocked</span>
                </div>
              </div>
            )}
          </div>

          <div className={`xl:col-span-4 ${PANEL_CLASS}`}>
            <PanelHeader icon={ShieldAlert} tone="warn" title="Risk level mix" subtitle="All classified queries for this tenant" />
            {!summary ? <Loading /> : riskTotal === 0 ? (
              <p className="py-8 text-center text-xs text-muted">No classified queries yet.</p>
            ) : (
              <div className="space-y-3">
                {RISK_ORDER.map((level) => {
                  const count = summary.risk_levels[level] ?? 0;
                  const share = (count / riskTotal) * 100;
                  return (
                    <div key={level} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-ink">{level}</span>
                        <span className="font-mono text-muted">{formatCount(count)} · {share.toFixed(1)}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-soft">
                        <div className={`h-2 rounded-full ${RISK_BAR[level]}`} style={{ width: `${share}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className={PANEL_CLASS}>
          <PanelHeader icon={MessageSquare} tone="ok" title="Ask Kriton outcomes" subtitle="From the audit ledger — every request this tenant sent. Validator rejections are on Professional Boundaries." />
          {!outcomes ? <Loading /> : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {outcomeRows.map((row) => (
                <div key={row.key} className="rounded-lg border border-line/60 bg-soft/30 p-4">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-muted">{row.label}</div>
                  <div className={`mt-2 text-xl font-extrabold ${OUTCOME_TEXT[row.tone]}`}>{formatCount(outcomes[row.key])}</div>
                  <div className="mt-1 text-[10px] text-muted">{formatCount(outcomes7d?.[row.key])} in last 7 days</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
          <div className={`xl:col-span-8 ${PANEL_CLASS}`}>
            <PanelHeader icon={Activity} tone="info" title="Live Safety Event Log" subtitle="Latest 30 events — audit trail per ZL-T0-04 Section 15" />
            {loading && events.length === 0 ? <Loading /> : events.length === 0 ? (
              <div className="text-center py-16 space-y-3">
                <Activity size={32} className="mx-auto text-muted/40" />
                <p className="text-xs text-muted max-w-sm mx-auto leading-relaxed">
                  No safety events yet. They appear here as questions are asked in <span className="font-semibold text-brand">Ask Kriton™</span>.
                </p>
              </div>
            ) : (
              <div className="relative pl-6 space-y-5 border-l-2 border-line/60 ml-3 max-h-[500px] overflow-y-auto pr-2">
                {events.map((evt) => {
                  const Icon = EVENT_ICONS[evt.event_type] ?? Activity;
                  const tone = EVENT_TONE_CLASSES[EVENT_TONES[evt.event_type] ?? "info"];
                  const payload = evt.payload as Record<string, unknown>;
                  const confidence = payload.confidence ?? payload.classifier_confidence;
                  return (
                    <div key={evt.id} className="relative flex items-start gap-4 p-4 rounded-lg border border-line/50 bg-soft/20 hover:bg-panel hover:shadow-md hover:border-line transition-all duration-200">
                      <span className={`absolute -left-[31px] top-[22px] flex h-3 w-3 rounded-full border-2 border-panel shadow-sm ${tone.dot}`} />
                      <div className={`shrink-0 p-2 rounded-md border ${tone.icon}`}>
                        <Icon size={16} />
                      </div>
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-xs font-bold text-ink uppercase tracking-wide">{evt.event_type.replace(/_/g, " ")}</span>
                          {evt.timestamp && (
                            <span className="text-[10px] text-muted font-mono bg-soft px-1.5 py-0.5 rounded border border-line/30">{formatWhen(evt.timestamp)}</span>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          <span className="text-[10px] text-muted font-mono pr-2">ID: {evt.id}</span>
                          {payload.risk_level != null && (
                            <Pill tone={String(payload.risk_level) === "HIGH" ? "warn" : String(payload.risk_level) === "RESTRICTED" ? "bad" : "ok"}>
                              {String(payload.risk_level)}
                            </Pill>
                          )}
                          {confidence != null && !Number.isNaN(Number(confidence)) && (
                            <Pill>{"Conf: " + (Number(confidence) * 100).toFixed(0) + "%"}</Pill>
                          )}
                          {payload.route != null && <Pill tone="info">{String(payload.route)}</Pill>}
                          {payload.restricted_sub_class != null && <Pill tone="bad">{String(payload.restricted_sub_class).replace("RESTRICTED_", "")}</Pill>}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Counts only — the case list lives in the Escalation Queue. */}
          <div className={`xl:col-span-4 ${PANEL_CLASS}`}>
            <PanelHeader
              icon={Zap}
              tone="warn"
              title="Escalations"
              action={<Link href="/escalation-queue" className="text-[11px] font-semibold text-brand hover:underline">Open queue →</Link>}
            />
            {!escalations ? <Loading /> : (
              <dl className="space-y-2.5 text-xs">
                {[
                  ["Total cases", escalations.total, "text-ink"],
                  ["Pending", escalations.pending, "text-warn"],
                  ["Under review", escalations.under_review, "text-info"],
                  ["Over SLA", escalations.over_sla, "text-bad"],
                  ["Resolved", escalations.resolved, "text-ok"],
                  ["Refused", escalations.refused, "text-muted"],
                  ["Active safety overrides", summary?.active_overrides ?? 0, "text-warn"],
                ].map(([label, value, tone]) => (
                  <div key={label as string} className="flex items-center justify-between border-b border-line/40 pb-2 last:border-b-0">
                    <dt className="text-muted">{label}</dt>
                    <dd className={`font-mono font-bold ${tone}`}>{formatCount(value as number)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  );
}

"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
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
  RefreshCw,
} from "lucide-react";
import { getSafetyEvents, getEscalations, type SafetyEvent, type Escalation } from "@/lib/safety-api";

const EVENT_ICONS: Record<string, typeof ShieldCheck> = {
  risk_classification_applied: ShieldCheck,
  risk_classification_uncertain: AlertTriangle,
  restricted_topic_blocked: ShieldOff,
  human_review_case_created: Clock,
  human_review_decision_recorded: CheckCircle2,
  security_incident_created: XCircle,
  safety_refusal_returned: ShieldAlert,
};

const EVENT_TONES: Record<string, "ok" | "warn" | "bad" | "info"> = {
  risk_classification_applied: "ok",
  risk_classification_uncertain: "warn",
  restricted_topic_blocked: "bad",
  human_review_case_created: "info",
  human_review_decision_recorded: "ok",
  security_incident_created: "bad",
  safety_refusal_returned: "warn",
};

/* ── Simulated stats (would come from aggregation queries in production) ── */
function computeStats(events: SafetyEvent[], escalations: Escalation[]) {
  const classified = events.filter((e) => e.event_type === "risk_classification_applied").length;
  const blocked = events.filter((e) => e.event_type === "restricted_topic_blocked").length;
  const uncertain = events.filter((e) => e.event_type === "risk_classification_uncertain").length;
  const incidents = events.filter((e) => e.event_type === "security_incident_created").length;
  const pendingReview = escalations.filter(
    (e) => e.status === "PENDING" || e.status === "UNDER_REVIEW"
  ).length;
  const overSla = escalations.filter((e) => {
    if (!e.sla_deadline) return false;
    return new Date(e.sla_deadline).getTime() < Date.now() && e.status !== "RESOLVED";
  }).length;

  return { classified, blocked, uncertain, incidents, pendingReview, overSla };
}

export default function AiSafetyDashboardPage() {
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const [evts, escs] = await Promise.all([getSafetyEvents(), getEscalations()]);
    setEvents(evts);
    setEscalations(escs);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  const stats = computeStats(events, escalations);

  return (
    <main className="flex-1 overflow-y-auto p-4 pt-0">
      <PageHeader
        title="AI Safety Dashboard"
        subtitle="Real-time view of risk classifications, refusals, escalations, and human review activity."
      />

      {/* ── Summary Metrics ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
        {[
          { label: "Classifications", value: stats.classified, tone: "ok" as const, icon: ShieldCheck },
          { label: "Blocked", value: stats.blocked, tone: "bad" as const, icon: ShieldOff },
          { label: "Uncertain", value: stats.uncertain, tone: "warn" as const, icon: AlertTriangle },
          { label: "Security Incidents", value: stats.incidents, tone: "bad" as const, icon: XCircle },
          { label: "Pending Review", value: stats.pendingReview, tone: "warn" as const, icon: Clock },
          { label: "Over SLA", value: stats.overSla, tone: "bad" as const, icon: AlertTriangle },
        ].map((m) => {
          const Icon = m.icon;
          return (
            <Card key={m.label} className="!p-4">
              <div className="flex items-center gap-2 mb-1">
                <Icon size={14} className={`text-${m.tone}`} />
                <span className="text-[11px] text-muted">{m.label}</span>
              </div>
              <div className={`text-2xl font-extrabold text-${m.tone}`}>{m.value}</div>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_1fr] gap-6">
        {/* ── Safety Event Feed ─────────────────────────────────────── */}
        <Card
          title="Safety Event Feed"
          action={
            <button
              onClick={load}
              className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-soft"
            >
              <RefreshCw size={12} /> Refresh
            </button>
          }
        >
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted">
              <Loader2 className="animate-spin mr-2" size={16} /> Loading events…
            </div>
          ) : events.length === 0 ? (
            <div className="text-center py-12 space-y-2">
              <Activity size={28} className="mx-auto text-muted" />
              <p className="text-sm text-muted">
                No safety events yet. Submit a query on the{" "}
                <span className="font-semibold text-brand">Ask Kriton™</span> page to generate events.
              </p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {events.map((evt) => {
                const Icon = EVENT_ICONS[evt.event_type] ?? Activity;
                const tone = EVENT_TONES[evt.event_type] ?? "info";
                const payload = evt.payload as Record<string, unknown>;
                return (
                  <div
                    key={evt.id}
                    className="flex items-start gap-3 rounded-xl border border-line bg-soft p-3"
                  >
                    <div className={`shrink-0 mt-0.5 p-1.5 rounded-lg bg-${tone}/10 border border-${tone}/20`}>
                      <Icon size={14} className={`text-${tone}`} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-bold text-ink truncate">
                          {evt.event_type.replace(/_/g, " ")}
                        </span>
                        {evt.timestamp && (
                          <span className="text-[10px] text-muted shrink-0">
                            {new Date(evt.timestamp).toLocaleTimeString()}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {payload.risk_level != null && (
                          <Pill tone={String(payload.risk_level) === "HIGH" ? "warn" : String(payload.risk_level) === "RESTRICTED" ? "bad" : "ok"}>
                            {String(payload.risk_level)}
                          </Pill>
                        )}
                        {payload.confidence != null && (
                          <Pill>
                            {"Conf: " + (Number(payload.confidence) * 100).toFixed(0) + "%"}
                          </Pill>
                        )}
                        {payload.route != null && <Pill tone="info">{String(payload.route)}</Pill>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* ── Active Escalation Summary ─────────────────────────────── */}
        <Card title="Active Escalations">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted">
              <Loader2 className="animate-spin mr-2" size={16} /> Loading…
            </div>
          ) : escalations.length === 0 ? (
            <p className="text-sm text-muted py-8 text-center">No active escalations.</p>
          ) : (
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {escalations
                .filter((e) => e.status !== "RESOLVED" && e.status !== "REFUSED")
                .map((esc) => {
                  const overdue = esc.sla_deadline && new Date(esc.sla_deadline).getTime() < Date.now();
                  return (
                    <div
                      key={esc.id}
                      className={`rounded-xl border p-3 ${
                        overdue ? "border-bad/30 bg-bad/5" : "border-line bg-soft"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-bold text-ink">{esc.id}</span>
                        <Pill tone={esc.risk_level === "RESTRICTED" ? "bad" : "warn"}>
                          {esc.risk_level}
                        </Pill>
                      </div>
                      <p className="text-xs text-ink truncate">{esc.topic}</p>
                      <div className="flex items-center gap-2 mt-1.5">
                        <Pill>{esc.jurisdiction}</Pill>
                        <Pill tone={overdue ? "bad" : "info"}>
                          {overdue ? "SLA Overdue" : esc.status}
                        </Pill>
                      </div>
                    </div>
                  );
                })}
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}

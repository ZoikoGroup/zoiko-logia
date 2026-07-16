"use client";

import { useEffect, useState } from "react";
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
  Zap,
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
    <main className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* ── Summary Metrics Grid (Section 15 audit counts) ───────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        {[
          {
            label: "Classifications",
            value: stats.classified,
            textColor: "text-ok",
            bg: "bg-ok/5 border-ok/20 hover:shadow-ok/5 hover:border-ok/40",
            iconBg: "bg-ok/10 text-ok border-ok/20",
            icon: ShieldCheck
          },
          {
            label: "Blocked Requests",
            value: stats.blocked,
            textColor: "text-bad",
            bg: "bg-bad/5 border-bad/20 hover:shadow-bad/5 hover:border-bad/40",
            iconBg: "bg-bad/10 text-bad border-bad/20",
            icon: ShieldOff
          },
          {
            label: "Uncertain Queries",
            value: stats.uncertain,
            textColor: "text-warn",
            bg: "bg-warn/5 border-warn/20 hover:shadow-warn/5 hover:border-warn/40",
            iconBg: "bg-warn/10 text-warn border-warn/20",
            icon: AlertTriangle
          },
          {
            label: "Security Incidents",
            value: stats.incidents,
            textColor: "text-bad",
            bg: "bg-bad/5 border-bad/20 hover:shadow-bad/5 hover:border-bad/40",
            iconBg: "bg-bad/10 text-bad border-bad/20",
            icon: XCircle
          },
          {
            label: "Pending Review",
            value: stats.pendingReview,
            textColor: "text-info",
            bg: "bg-info/5 border-info/20 hover:shadow-info/5 hover:border-info/40",
            iconBg: "bg-info/10 text-info border-info/20",
            icon: Clock
          },
          {
            label: "SLA Overdue",
            value: stats.overSla,
            textColor: "text-bad",
            bg: "bg-bad/5 border-bad/20 hover:shadow-bad/5 hover:border-bad/40",
            iconBg: "bg-bad/10 text-bad border-bad/20",
            icon: AlertTriangle
          },
        ].map((m) => {
          const Icon = m.icon;
          return (
            <div
              key={m.label}
              className={`rounded-2xl border bg-panel/85 p-5 flex flex-col justify-between shadow-[0_4px_12px_rgba(0,0,0,0.01)] transition-all duration-300 ${m.bg} hover:-translate-y-0.5 hover:shadow-lg`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] text-muted font-bold uppercase tracking-wider">{m.label}</span>
                <div className={`p-1.5 rounded-lg border ${m.iconBg}`}>
                  <Icon size={13} />
                </div>
              </div>
              <div className={`text-2xl font-extrabold tracking-tight mt-3 ${m.textColor}`}>{m.value}</div>
            </div>
          );
        })}
      </div>

      {/* ── Content Columns ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        {/* ── Safety Event Feed (Timeline format) ────────────────────── */}
        <div className="xl:col-span-8">
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center justify-between border-b border-line/50 pb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                  <Activity size={14} className="text-brand animate-pulse" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-ink">Live Safety Event Log</h3>
                  <p className="text-[11px] text-muted">Audit trail complying with ZL-T0-04 Section 15</p>
                </div>
              </div>
              <button
                onClick={load}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft transition-all duration-200 cursor-pointer shadow-sm"
              >
                <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
                Sync Log
              </button>
            </div>

            {loading ? (
              <div className="flex flex-col items-center justify-center py-20 text-muted">
                <Loader2 className="animate-spin mb-2" size={24} />
                <span className="text-xs">Fetching audit events...</span>
              </div>
            ) : events.length === 0 ? (
              <div className="text-center py-20 space-y-3">
                <Activity size={32} className="mx-auto text-muted/40" />
                <p className="text-xs text-muted max-w-sm mx-auto leading-relaxed">
                  Audit feed currently empty. Submit dynamic queries on the <span className="font-semibold text-brand">Ask Kriton™</span> console to seed events.
                </p>
              </div>
            ) : (
              <div className="relative pl-6 space-y-5 border-l-2 border-line/60 ml-3 max-h-[500px] overflow-y-auto pr-2">
                {events.map((evt) => {
                  const Icon = EVENT_ICONS[evt.event_type] ?? Activity;
                  const tone = EVENT_TONES[evt.event_type] ?? "info";
                  const payload = evt.payload as Record<string, unknown>;

                  return (
                    <div
                      key={evt.id}
                      className="group relative flex items-start gap-4 p-4 rounded-xl border border-line/50 bg-soft/20 hover:bg-panel hover:shadow-md hover:border-line transition-all duration-200"
                    >
                      {/* Pulsing Timeline Anchor */}
                      <span className={`absolute -left-[31px] top-[22px] flex h-3 w-3 items-center justify-center rounded-full bg-${tone} border-2 border-panel shadow-sm group-hover:scale-125 transition-transform duration-200`} />

                      <div className={`shrink-0 p-2 rounded-xl bg-${tone}/10 border border-${tone}/20 text-${tone}`}>
                        <Icon size={16} />
                      </div>

                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-xs font-bold text-ink uppercase tracking-wide">
                            {evt.event_type.replace(/_/g, " ")}
                          </span>
                          {evt.timestamp && (
                            <span className="text-[10px] text-muted font-mono bg-soft px-1.5 py-0.5 rounded border border-line/30">
                              {new Date(evt.timestamp).toLocaleTimeString()}
                            </span>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          <span className="text-[10px] text-muted font-mono pr-2">ID: {evt.id}</span>
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
          </div>
        </div>

        {/* ── Active Escalation Summary ─────────────────────────────── */}
        <div className="xl:col-span-4">
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-warn/10 border border-warn/20">
                <Zap size={14} className="text-warn" />
              </div>
              <h3 className="text-sm font-bold text-ink">Actionable Escalations</h3>
            </div>

            {loading ? (
              <div className="flex flex-col items-center justify-center py-10 text-muted">
                <Loader2 className="animate-spin mb-2" size={16} />
                <span className="text-xs">Fetching active cases...</span>
              </div>
            ) : escalations.length === 0 ? (
              <div className="text-center py-10 text-muted">
                <span className="text-xs">No active escalations.</span>
              </div>
            ) : (
              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                {escalations
                  .filter((e) => e.status !== "RESOLVED" && e.status !== "REFUSED")
                  .map((esc) => {
                    const overdue = esc.sla_deadline && new Date(esc.sla_deadline).getTime() < Date.now();
                    return (
                      <div
                        key={esc.id}
                        className={`rounded-xl border p-4 space-y-2.5 transition-all duration-200 hover:shadow-md ${overdue
                            ? "border-bad/30 bg-bad/5 hover:border-bad"
                            : "border-line/60 bg-soft/30 hover:bg-panel hover:border-line"
                          }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono font-bold text-ink">{esc.id}</span>
                          <Pill tone={esc.risk_level === "RESTRICTED" ? "bad" : "warn"}>
                            {esc.risk_level}
                          </Pill>
                        </div>
                        <p className="text-xs text-ink font-semibold line-clamp-2 leading-relaxed">{esc.topic}</p>
                        <div className="flex items-center gap-1.5 pt-1">
                          <Pill>{esc.jurisdiction}</Pill>
                          <Pill tone={overdue ? "bad" : "info"}>
                            {overdue ? "SLA Breach" : esc.status}
                          </Pill>
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

"use client";

import { useEffect, useState, Fragment } from "react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { MetricsRow } from "@/components/governance/MetricsRow";
import {
  AlertTriangle,
  Clock,
  CheckCircle2,
  XCircle,
  ArrowUpCircle,
  MessageSquare,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { getEscalations, type Escalation } from "@/lib/safety-api";

function slaStatus(deadline: string | null): { label: string; tone: "ok" | "warn" | "bad" } {
  if (!deadline) return { label: "No SLA", tone: "warn" };
  const remaining = new Date(deadline).getTime() - Date.now();
  if (remaining < 0) return { label: "Overdue", tone: "bad" };
  const mins = Math.floor(remaining / 60000);
  if (mins < 60) return { label: `${mins}m remaining`, tone: mins < 15 ? "bad" : "warn" };
  const hrs = Math.floor(mins / 60);
  return { label: `${hrs}h ${mins % 60}m remaining`, tone: "ok" };
}

const STATUS_ICONS: Record<string, typeof CheckCircle2> = {
  PENDING: Clock,
  UNDER_REVIEW: MessageSquare,
  RESOLVED: CheckCircle2,
  REFUSED: XCircle,
  ESCALATED: ArrowUpCircle,
};

export default function EscalationQueuePage() {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    const data = await getEscalations();
    setEscalations(data);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  const pending = escalations.filter((e) => e.status === "PENDING" || e.status === "UNDER_REVIEW");
  const overdue = escalations.filter((e) => {
    if (!e.sla_deadline) return false;
    return new Date(e.sla_deadline).getTime() < Date.now() && e.status !== "RESOLVED" && e.status !== "REFUSED";
  });

  return (
    <main className="flex-1 overflow-y-auto p-4 pt-0">
      <PageHeader
        title="Escalation Queue"
        subtitle="Route high-risk and restricted items by SLA, jurisdiction, owner, and evidence completeness."
      />

      {/* ── Summary Metrics ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-ink">{escalations.length}</div>
          <div className="text-xs text-muted mt-0.5">Total Cases</div>
        </Card>
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-warn">{pending.length}</div>
          <div className="text-xs text-muted mt-0.5">Pending Review</div>
        </Card>
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-bad">{overdue.length}</div>
          <div className="text-xs text-muted mt-0.5">Over SLA</div>
        </Card>
        <Card className="!p-4">
          <div className="text-2xl font-extrabold text-ok">
            {escalations.filter((e) => e.status === "RESOLVED").length}
          </div>
          <div className="text-xs text-muted mt-0.5">Resolved</div>
        </Card>
      </div>

      {/* ── Escalation Table ──────────────────────────────────────────── */}
      <Card
        title="Active Escalations"
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
            <Loader2 className="animate-spin mr-2" size={16} /> Loading escalations…
          </div>
        ) : escalations.length === 0 ? (
          <p className="text-sm text-muted py-8 text-center">No escalation cases found.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="font-medium pb-2">Case</th>
                <th className="font-medium pb-2">Topic</th>
                <th className="font-medium pb-2">Risk</th>
                <th className="font-medium pb-2">Jurisdiction</th>
                <th className="font-medium pb-2">SLA</th>
                <th className="font-medium pb-2">Status</th>
                <th className="font-medium pb-2" />
              </tr>
            </thead>
            <tbody>
              {escalations.map((esc) => {
                const isOpen = openId === esc.id;
                const sla = slaStatus(esc.sla_deadline);
                const StatusIcon = STATUS_ICONS[esc.status] ?? Clock;

                return (
                  <Fragment key={esc.id}>
                    <tr className="border-t border-line align-top">
                      <td className="py-2.5 font-semibold text-ink">{esc.id}</td>
                      <td className="py-2.5 text-ink max-w-[220px]">
                        <div className="truncate">{esc.topic}</div>
                        {esc.restricted_sub_class && (
                          <Pill tone="bad">{esc.restricted_sub_class.replace("RESTRICTED_", "")}</Pill>
                        )}
                      </td>
                      <td className="py-2.5">
                        <Pill tone={esc.risk_level === "RESTRICTED" ? "bad" : esc.risk_level === "HIGH" ? "warn" : "info"}>
                          {esc.risk_level}
                        </Pill>
                      </td>
                      <td className="py-2.5 text-ink">{esc.jurisdiction}</td>
                      <td className="py-2.5">
                        <Pill tone={sla.tone}>{sla.label}</Pill>
                      </td>
                      <td className="py-2.5">
                        <span className="flex items-center gap-1 text-xs text-muted">
                          <StatusIcon size={13} /> {esc.status}
                        </span>
                      </td>
                      <td className="py-2.5 text-right">
                        <button
                          onClick={() => setOpenId(isOpen ? null : esc.id)}
                          className="rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-medium text-ink hover:bg-soft"
                        >
                          {isOpen ? "Close" : "Review"}
                        </button>
                      </td>
                    </tr>

                    {isOpen && (
                      <tr>
                        <td colSpan={7} className="pb-4">
                          <div className="rounded-xl border border-line bg-soft p-4 space-y-3">
                            {/* Query */}
                            <div>
                              <span className="text-[11px] font-bold text-muted uppercase tracking-wider">
                                Original Query
                              </span>
                              <p className="text-sm text-ink mt-1 bg-panel rounded-lg border border-line p-2.5">
                                &ldquo;{esc.query_text}&rdquo;
                              </p>
                            </div>

                            {/* Decision workspace */}
                            <div>
                              <span className="text-[11px] font-bold text-muted uppercase tracking-wider">
                                Decision Workspace
                              </span>
                              <p className="text-sm text-ink mt-1 leading-relaxed">{esc.detail}</p>
                            </div>

                            {/* Evidence & metadata tags */}
                            <div className="flex flex-wrap gap-1.5">
                              <Pill>Query ID: {esc.query_id}</Pill>
                              {esc.reviewer_role && <Pill tone="info">Reviewer: {esc.reviewer_role}</Pill>}
                              <Pill>Source bundle</Pill>
                              <Pill>Risk decision</Pill>
                              <Pill>Audit log</Pill>
                              <Pill tone="warn">Maker-checker required</Pill>
                            </div>

                            {/* Reviewer actions */}
                            {(esc.status === "PENDING" || esc.status === "UNDER_REVIEW") && (
                              <div className="flex gap-2 pt-2 border-t border-line">
                                <button className="flex items-center gap-1.5 rounded-lg bg-ok/10 border border-ok/30 px-3 py-1.5 text-xs font-semibold text-ok hover:bg-ok/20">
                                  <CheckCircle2 size={13} /> Approve
                                </button>
                                <button className="flex items-center gap-1.5 rounded-lg bg-bad/10 border border-bad/30 px-3 py-1.5 text-xs font-semibold text-bad hover:bg-bad/20">
                                  <XCircle size={13} /> Refuse
                                </button>
                                <button className="flex items-center gap-1.5 rounded-lg bg-warn/10 border border-warn/30 px-3 py-1.5 text-xs font-semibold text-warn hover:bg-warn/20">
                                  <ArrowUpCircle size={13} /> Escalate
                                </button>
                                <button className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
                                  <MessageSquare size={13} /> Request Info
                                </button>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Pill } from "@/components/governance/Pill";
import {
  AlertTriangle,
  Clock,
  CheckCircle2,
  XCircle,
  ArrowUpCircle,
  MessageSquare,
  Loader2,
  RefreshCw,
  Zap,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { 
  getEscalations, 
  actOnEscalation,
  getEscalationStats,
  getSafetyOverrides,
  createSafetyOverride,
  type Escalation,
  type EscalationStats,
  type SafetyOverride
} from "@/lib/safety-api";

function slaStatus(deadline: string | null): { 
  label: string; 
  tone: "ok" | "warn" | "bad"; 
  percent: number; 
  breached: boolean 
} {
  if (!deadline) return { label: "No SLA", tone: "warn", percent: 100, breached: false };
  const deadlineTime = new Date(deadline).getTime();
  const now = Date.now();
  const remaining = deadlineTime - now;

  if (remaining < 0) {
    return { label: "SLA Breached", tone: "bad", percent: 100, breached: true };
  }

  const mins = Math.floor(remaining / 60000);
  if (mins < 60) {
    const pct = Math.max(0, Math.min(100, (mins / 60) * 100));
    return { label: `${mins}m remaining`, tone: mins < 15 ? "bad" : "warn", percent: pct, breached: false };
  }

  const hrs = Math.floor(mins / 60);
  const pct = Math.max(0, Math.min(100, (remaining / (24 * 3600 * 1000)) * 100));
  return { label: `${hrs}h ${mins % 60}m left`, tone: "ok", percent: pct, breached: false };
}

const STATUS_ICONS: Record<string, typeof CheckCircle2> = {
  PENDING: Clock,
  UNDER_REVIEW: MessageSquare,
  RESOLVED: CheckCircle2,
  REFUSED: XCircle,
  ESCALATED: ArrowUpCircle,
};

const STATUS_TONES: Record<string, "ok" | "warn" | "bad" | "info"> = {
  PENDING: "info",
  UNDER_REVIEW: "warn",
  RESOLVED: "ok",
  REFUSED: "bad",
  ESCALATED: "warn",
};

export default function EscalationQueuePage() {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [stats, setStats] = useState<EscalationStats | null>(null);
  const [overrides, setOverrides] = useState<SafetyOverride[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [reviewerId, setReviewerId] = useState("user_admin");
  const [actionReason, setActionReason] = useState("");
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  // Override form state
  const [showOverrideForm, setShowOverrideForm] = useState(false);
  const [overrideForm, setOverrideForm] = useState({
    scope: "",
    original_route: "HUMAN_REVIEW",
    new_route: "REFUSAL",
    reason: "",
    duration_hours: 24
  });

  async function load() {
    setLoading(true);
    try {
      const [escData, statsData, overrideData] = await Promise.all([
        getEscalations(),
        getEscalationStats(),
        getSafetyOverrides()
      ]);
      setEscalations(escData);
      setStats(statsData || null);
      setOverrides(overrideData);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function handleAction(caseId: string, action: "approve" | "refuse" | "escalate" | "request_info") {
    setErrorMsg(null);
    setSubmittingId(caseId);
    try {
      await actOnEscalation(caseId, action, reviewerId, actionReason);
      setActionReason("");
      await load();
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to resolve case. Maker-checker constraint violation.");
    } finally {
      setSubmittingId(null);
    }
  }

  async function handleCreateOverride(e: React.FormEvent) {
    e.preventDefault();
    try {
      await createSafetyOverride({
        actor_id: reviewerId,
        authority_role: "Security Lead",
        ...overrideForm
      });
      setShowOverrideForm(false);
      await load();
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to create safety override.");
    }
  }

  return (
    <main className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* ── Summary Metrics Grid ─────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Total Cases", value: stats?.total ?? 0, tone: "info" as const },
          { label: "Pending Review", value: (stats?.pending ?? 0) + (stats?.under_review ?? 0), tone: "warn" as const },
          { label: "Over SLA", value: stats?.over_sla ?? 0, tone: "bad" as const },
          { label: "Resolved", value: stats?.resolved ?? 0, tone: "ok" as const },
        ].map((m) => (
          <div 
            key={m.label}
            className={`rounded-2xl border bg-panel p-5 flex flex-col justify-between shadow-[0_4px_12px_rgba(0,0,0,0.01)] hover:shadow-md transition-all duration-300 ${
              m.tone === "info" 
                ? "border-line/60 bg-soft/10" 
                : m.tone === "warn" 
                  ? "border-warn/20 bg-warn/5 text-warn" 
                  : m.tone === "bad" 
                    ? "border-bad/20 bg-bad/5 text-bad" 
                    : "border-ok/20 bg-ok/5 text-ok"
            }`}
          >
            <span className="text-[10px] text-muted font-bold uppercase tracking-wider">{m.label}</span>
            <div className="text-2xl font-extrabold tracking-tight mt-2">{m.value}</div>
          </div>
        ))}
      </div>

      {/* ── Error Toast Notice ────────────────────────────────────────── */}
      {errorMsg && (
        <div className="rounded-xl border-2 border-bad/30 bg-bad/5 p-4 text-xs text-bad leading-relaxed flex items-start gap-2 animate-shake shadow-lg">
          <AlertTriangle size={16} className="shrink-0" />
          <div>
            <span className="font-bold uppercase tracking-wider">Error:</span> {errorMsg}
          </div>
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-6">
        {/* ── Escalation Workspace (Left) ─────────────────────────────── */}
        <div className="flex-1 rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
          <div className="flex items-center justify-between border-b border-line/50 pb-4">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                <Zap size={14} className="text-brand" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-ink">Incident Review Queue</h3>
                <p className="text-[11px] text-muted">Maker-checker evaluation workspace</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 bg-soft px-3 py-1.5 rounded-lg border border-line/60">
                <span className="text-[10px] font-bold text-muted uppercase">Actor:</span>
                <input 
                  type="text" 
                  value={reviewerId} 
                  onChange={(e) => setReviewerId(e.target.value)} 
                  className="text-xs text-ink bg-transparent border-none outline-none font-bold w-[90px]"
                />
              </div>
              <button
                onClick={load}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-semibold text-ink hover:bg-soft transition-all duration-200 cursor-pointer shadow-sm"
              >
                <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
              </button>
            </div>
          </div>

          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 text-muted">
              <Loader2 className="animate-spin mb-2" size={24} />
              <span className="text-xs">Fetching escalations...</span>
            </div>
          ) : escalations.length === 0 ? (
            <p className="text-sm text-muted py-20 text-center">No active escalation cases found.</p>
          ) : (
            <div className="space-y-4">
              {escalations.map((esc) => {
                const isOpen = openId === esc.id;
                const sla = slaStatus(esc.sla_deadline);
                const StatusIcon = STATUS_ICONS[esc.status] ?? Clock;
                const tone = STATUS_TONES[esc.status] ?? "info";

                return (
                  <div 
                    key={esc.id} 
                    className={`rounded-xl border transition-all duration-300 ${
                      isOpen 
                        ? "border-brand shadow-lg bg-panel" 
                        : esc.status === "RESOLVED" || esc.status === "REFUSED"
                          ? "border-line/40 bg-soft/20 opacity-80"
                          : sla.breached
                            ? "border-bad/30 bg-bad/5 hover:border-bad"
                            : "border-line/60 bg-panel hover:shadow-md hover:border-line"
                    }`}
                  >
                    <div 
                      onClick={() => setOpenId(isOpen ? null : esc.id)}
                      className="p-4 flex flex-wrap items-center justify-between gap-4 cursor-pointer select-none"
                    >
                      <div className="flex items-center gap-3">
                        <div className={`p-1.5 rounded-lg border bg-${tone}/10 text-${tone} border-${tone}/20`}>
                          <StatusIcon size={14} />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-extrabold text-ink">{esc.id}</span>
                            <Pill tone={esc.risk_level === "RESTRICTED" ? "bad" : esc.risk_level === "HIGH" ? "warn" : "info"}>
                              {esc.risk_level}
                            </Pill>
                            <Pill>{esc.jurisdiction}</Pill>
                          </div>
                          <p className="text-xs font-semibold text-ink mt-0.5 max-w-lg truncate">{esc.topic}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 ml-auto">
                        <div className="hidden sm:flex flex-col items-end gap-1 min-w-[120px]">
                          <div className="flex items-center justify-between w-full text-[10px] font-bold">
                            <span className={`text-${sla.tone}`}>{sla.label}</span>
                            <span className="text-muted font-mono">{sla.percent.toFixed(0)}%</span>
                          </div>
                          <div className="w-full bg-soft h-1.5 rounded-full overflow-hidden border border-line/30">
                            <div 
                              className={`h-full rounded-full transition-all duration-300 bg-${sla.tone}`} 
                              style={{ width: `${sla.percent}%` }}
                            />
                          </div>
                        </div>
                        <Pill tone={tone}>{esc.status}</Pill>
                        {isOpen ? <ChevronUp size={16} className="text-muted" /> : <ChevronDown size={16} className="text-muted" />}
                      </div>
                    </div>

                    {isOpen && (
                      <div className="border-t border-line/50 p-5 bg-soft/10 space-y-4 rounded-b-xl animate-fadeIn">
                        <div className="space-y-1.5">
                          <span className="text-[10px] font-bold text-muted uppercase tracking-wider">User Query Prompt</span>
                          <div className="rounded-xl border border-line/60 bg-panel p-4 text-xs font-medium text-ink shadow-inner leading-relaxed">
                            &ldquo;{esc.query_text}&rdquo;
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <span className="text-[10px] font-bold text-muted uppercase tracking-wider">Evaluation Details</span>
                          <p className="text-xs text-muted leading-relaxed pl-1">{esc.detail}</p>
                        </div>

                        <div className="flex flex-wrap gap-1.5 border-t border-line/40 pt-4">
                          <Pill>Query ID: {esc.query_id}</Pill>
                          {esc.reviewer_role && <Pill tone="info">Required Role: {esc.reviewer_role}</Pill>}
                          {esc.reviewer_id && <Pill tone="ok">Reviewer ID: {esc.reviewer_id}</Pill>}
                          {esc.reviewer_decision && <Pill tone="ok">Decision: {esc.reviewer_decision}</Pill>}
                          {esc.restricted_sub_class && <Pill tone="bad">Sub-Class: {esc.restricted_sub_class}</Pill>}
                        </div>

                        {(esc.status === "PENDING" || esc.status === "UNDER_REVIEW") && (
                          <div className="space-y-3 border-t border-line/50 pt-4">
                            <div className="space-y-1.5">
                              <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Resolution Reason / Notes</label>
                              <textarea
                                value={actionReason}
                                onChange={(e) => setActionReason(e.target.value)}
                                placeholder="Describe your review reasoning, boundary exclusions, or additional context required..."
                                className="w-full text-xs text-ink placeholder:text-muted/60 p-3 bg-panel rounded-xl border border-line/80 outline-none focus:border-brand h-[70px] resize-none"
                              />
                            </div>

                            <div className="flex flex-wrap gap-2">
                              <button 
                                onClick={() => handleAction(esc.id, "approve")}
                                disabled={submittingId != null}
                                className="flex items-center gap-1.5 rounded-xl bg-ok/10 border border-ok/30 px-4 py-2 text-xs font-bold text-ok hover:bg-ok/20 cursor-pointer disabled:opacity-50"
                              >
                                <CheckCircle2 size={13} /> Approve
                              </button>
                              <button 
                                onClick={() => handleAction(esc.id, "refuse")}
                                disabled={submittingId != null}
                                className="flex items-center gap-1.5 rounded-xl bg-bad/10 border border-bad/30 px-4 py-2 text-xs font-bold text-bad hover:bg-bad/20 cursor-pointer disabled:opacity-50"
                              >
                                <XCircle size={13} /> Refuse
                              </button>
                              <button 
                                onClick={() => handleAction(esc.id, "escalate")}
                                disabled={submittingId != null}
                                className="flex items-center gap-1.5 rounded-xl bg-warn/10 border border-warn/30 px-4 py-2 text-xs font-bold text-warn hover:bg-warn/20 cursor-pointer disabled:opacity-50"
                              >
                                <ArrowUpCircle size={13} /> Escalate
                              </button>
                              <button 
                                onClick={() => handleAction(esc.id, "request_info")}
                                disabled={submittingId != null}
                                className="flex items-center gap-1.5 rounded-xl border border-line bg-panel px-4 py-2 text-xs font-bold text-ink hover:bg-soft cursor-pointer disabled:opacity-50"
                              >
                                <MessageSquare size={13} /> Request Info
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Overrides Panel (Right) ─────────────────────────────────── */}
        <div className="w-full lg:w-[320px] shrink-0 space-y-6">
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center justify-between border-b border-line/50 pb-4">
              <h3 className="text-sm font-bold text-ink">Active Overrides</h3>
              <button
                onClick={() => setShowOverrideForm(!showOverrideForm)}
                className="text-xs bg-brand text-white px-3 py-1.5 rounded hover:bg-brand/90 transition"
              >
                + Create
              </button>
            </div>
            
            {showOverrideForm && (
              <form onSubmit={handleCreateOverride} className="bg-soft/10 border border-line/60 rounded p-4 space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-muted">New Safety Override</h4>
                <div className="space-y-1">
                  <label className="text-[10px] uppercase text-muted font-bold">Scope Pattern</label>
                  <input required className="w-full text-xs p-2 border border-line rounded" value={overrideForm.scope} onChange={e => setOverrideForm({...overrideForm, scope: e.target.value})} placeholder="e.g., test-dataset-*" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] uppercase text-muted font-bold">Reason</label>
                  <input required className="w-full text-xs p-2 border border-line rounded" value={overrideForm.reason} onChange={e => setOverrideForm({...overrideForm, reason: e.target.value})} placeholder="Why is this needed?" />
                </div>
                <div className="flex gap-2">
                  <div className="flex-1 space-y-1">
                    <label className="text-[10px] uppercase text-muted font-bold">Duration (hrs)</label>
                    <input type="number" max="72" required className="w-full text-xs p-2 border border-line rounded" value={overrideForm.duration_hours} onChange={e => setOverrideForm({...overrideForm, duration_hours: parseInt(e.target.value)})} />
                  </div>
                </div>
                <button type="submit" className="w-full mt-2 text-xs bg-ink text-white py-2 rounded hover:opacity-90">Apply Override</button>
              </form>
            )}

            <div className="space-y-3">
              {overrides.length === 0 ? (
                <p className="text-xs text-muted">No active overrides.</p>
              ) : (
                overrides.map(ovr => (
                  <div key={ovr.id} className="text-xs border border-line p-3 rounded bg-panel">
                    <div className="font-mono text-[10px] text-muted">{ovr.id}</div>
                    <div className="font-medium mt-1">Scope: {ovr.scope}</div>
                    <div className="text-muted mt-0.5">{ovr.reason}</div>
                    <div className="mt-2 flex justify-between items-center text-[10px]">
                      <span className="text-warn font-bold">Expires: {new Date(ovr.expires_at).toLocaleString()}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

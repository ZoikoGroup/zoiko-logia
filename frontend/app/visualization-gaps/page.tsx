"use client";
import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { ApiError, createVisualizationGapReport, transitionVisualizationGapReport, getAuthToken, getVisualizationGapSummary, getEvidenceMonitoringStatus, runEvidenceMonitoring, type VisualizationGapReport, type VisualizationGapRow, type VisualizationGapFilters, type EvidenceMonitoringStatus, type MonitoringRunSummary } from "@/lib/api";

const environments = ["production","staging","development","test"];
const monitoringStatusLabel: Record<EvidenceMonitoringStatus["monitoring_status"], string> = {
  collecting_evidence: "Collecting evidence", directional_signal: "Directional signal", ready_for_review: "Ready for review",
  awaiting_approval: "Awaiting maker-checker approval", approved_findings_available: "Approved findings available",
};

function RunSummaryLine({ label, run }: { label: string; run: MonitoringRunSummary | null }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <p className="text-xs text-muted">{label}</p>
      {run ? <>
        <p className="mt-1 text-sm"><strong>{run.status}</strong> · {new Date(run.started_at).toLocaleString()}</p>
        <p className="mt-1 text-xs text-muted">Draft created: {run.draft_created ? "yes" : "no"} · Reviewer notification created: {run.alert_created ? "yes" : "no"}</p>
      </> : <p className="mt-1 text-sm text-muted">Never run yet</p>}
    </div>
  );
}

function EvidenceMonitoringSection() {
  const [status, setStatus] = useState<EvidenceMonitoringStatus | null>(null);
  const [error, setError] = useState(""); const [running, setRunning] = useState(false);
  async function load() { try { setError(""); setStatus(await getEvidenceMonitoringStatus(getAuthToken())); } catch { setError("Could not load evidence monitoring status — Admin access is required."); } }
  useEffect(() => { load(); }, []);
  const runActive = running || status?.current_run?.status === "running";
  const evidenceVersion = status?.current_run?.evidence_version || status?.last_report?.evidence_version;
  async function run() {
    setRunning(true);
    try { await runEvidenceMonitoring(getAuthToken()); await load(); }
    catch (err) { await load(); setError(err instanceof ApiError ? err.message : "Could not run evidence monitoring"); }
    finally { setRunning(false); }
  }
  return (
    <section className="mt-5 rounded-2xl border border-line bg-panel p-4" aria-labelledby="evidence-monitoring-heading">
      <div className="flex items-center justify-between gap-3">
        <div><h2 id="evidence-monitoring-heading" className="font-bold">Evidence Monitoring</h2><p className="mt-1 text-xs text-muted">Aggregated production evidence only — no raw events, identifiers, queries, values, labels, or errors are ever shown here.</p></div>
        <button type="button" onClick={run} disabled={runActive} aria-disabled={runActive} aria-busy={runActive} className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs font-bold disabled:opacity-50"><RefreshCw size={13} aria-hidden="true" />{runActive ? "Running…" : "Run evidence monitoring"}</button>
      </div>
      {error && <p className="mt-3 text-sm text-bad" role="alert">{error}</p>}
      {status && <>
        <p className="mt-4 text-sm" aria-live="polite"><span aria-hidden="true">●</span> Status: <strong>{monitoringStatusLabel[status.monitoring_status]}</strong>{evidenceVersion && <> · Evidence {evidenceVersion}</>}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Production gap events", status.valid_event_count],
            ["Distinct conversations", status.distinct_conversation_count],
            ["Aggregated actor count", status.distinct_actor_count],
            ["Overall evidence status", status.overall_evidence_status.replaceAll("_"," ")],
          ].map(([label, value]) => <div key={label as string} className="rounded-xl border border-line bg-panel p-4"><p className="text-xs text-muted">{label}</p><p className="mt-1 text-2xl font-bold">{value}</p></div>)}
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-line bg-panel p-4">
            <p className="text-xs text-muted">Progress toward next evidence threshold</p>
            <p className="mt-1 text-sm">{status.diversity_gate_blocking_next ? "Blocked — needs more than one conversation and actor" : status.events_to_next_threshold !== null ? `${status.events_to_next_threshold} more valid event(s) needed` : status.next_eligible_finding ? "No further threshold — awaiting review" : "No findings in progress"}</p>
          </div>
          <div className="rounded-xl border border-line bg-panel p-4">
            <p className="text-xs text-muted">Next scheduled run</p>
            <p className="mt-1 text-sm">{status.next_scheduled_run_at ? new Date(status.next_scheduled_run_at).toLocaleString() : "Not scheduled"}</p>
          </div>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <RunSummaryLine label="Last scheduled run" run={status.last_scheduled_run} />
          <RunSummaryLine label="Last manual run" run={status.last_manual_run} />
          <RunSummaryLine label="Current run" run={status.current_run} />
        </div>
        <p className="mt-3 text-xs text-muted">Draft report availability: {status.last_report ? <strong>{status.last_report.status.replaceAll("_"," ")}</strong> : "none yet"}</p>
      </>}
    </section>
  );
}

export default function VisualizationGapsPage() {
  const [filters,setFilters]=useState<VisualizationGapFilters>({environment:"production"}); const [rows,setRows]=useState<VisualizationGapRow[]>([]);
  const [totals,setTotals]=useState({requests:0,fallbacks:0,rate:0}); const [error,setError]=useState("");
  const [report,setReport]=useState<VisualizationGapReport|null>(null); const [findings,setFindings]=useState("");
  async function load(){try{setError("");const data=await getVisualizationGapSummary(getAuthToken(),filters);setRows(data.rows);setTotals({requests:data.total_visualization_requests,fallbacks:data.total_fallback_events,rate:data.gap_rate});}catch{setError("Could not load visualization gap evidence — Admin access is required.");}}
  useEffect(()=>{load();},[]); // eslint-disable-line react-hooks/exhaustive-deps
  const field=(key:keyof VisualizationGapFilters,label:string)=><label className="text-xs text-muted">{label}<input value={filters[key]??""} onChange={e=>setFilters(v=>({...v,[key]:e.target.value||undefined}))} className="mt-1 block w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-ink" /></label>;
  return <PageShell title="Visualization Gap Report" subtitle="Aggregated, privacy-safe evidence only. Production is the default; development and test events are excluded." showMetrics={false}>
    <section className="rounded-2xl border border-line bg-panel p-4"><div className="grid gap-3 md:grid-cols-4">
      {field("dateFrom","From")}{field("dateTo","To")}
      <label className="text-xs text-muted">Environment<select value={filters.environment} onChange={e=>setFilters(v=>({...v,environment:e.target.value}))} className="mt-1 block w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-ink">{environments.map(x=><option key={x}>{x}</option>)}</select></label>
      {field("analyticalIntent","Analytical intent")}{field("requestedChartType","Requested chart")}{field("requestedVisualizationFamily","Visualization family")}{field("dataShapeClass","Data shape")}{field("evidenceStatus","Evidence status")}
    </div><button type="button" onClick={load} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-brand px-3 py-2 text-xs font-bold text-white"><RefreshCw size={13}/>Apply filters</button></section>
    {error&&<p className="mt-4 text-sm text-bad">{error}</p>}
    <EvidenceMonitoringSection />
    <div className="mt-5 grid gap-3 sm:grid-cols-3">{[["Total visualization requests",totals.requests],["Total fallback events",totals.fallbacks],["Gap rate",`${(totals.rate*100).toFixed(1)}%`]].map(([label,value])=><div key={label} className="rounded-xl border border-line bg-panel p-4"><p className="text-xs text-muted">{label}</p><p className="mt-1 text-2xl font-bold">{value}</p></div>)}</div>
    <section className="mt-5 overflow-x-auto rounded-2xl border border-line bg-panel"><table className="w-full text-left text-xs"><thead><tr className="border-b border-line text-muted">{["Requested chart/family","Validated data shape","Current fallback","Sample","Conversations","Evidence","Issue classification","Recommended action"].map(x=><th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={`${row.requested_capability}-${row.validated_data_shape}-${i}`} className="border-b border-line/60"><td className="p-3 font-semibold">{row.requested_capability}<br/><span className="font-normal text-muted">{row.requested_visualization_family}</span></td><td className="p-3">{row.validated_data_shape}</td><td className="p-3">{row.current_fallback}</td><td className="p-3">{row.sample_size}</td><td className="p-3">{row.distinct_conversations}</td><td className="p-3">{row.evidence_status.replaceAll("_"," ")}</td><td className="p-3"><span className="inline-flex items-center gap-1"><AlertTriangle size={12}/>{row.recommended_issue_classification.replaceAll("_"," ")}</span></td><td className="p-3">{row.recommended_action.replaceAll("_"," ")}</td></tr>)}</tbody></table>{!rows.length&&<p className="p-8 text-center text-sm text-muted">No valid production gap evidence in this range.</p>}</section>
    <section className="mt-5 rounded-2xl border border-line bg-panel p-4"><h2 className="font-bold">Report approval workflow</h2><p className="mt-1 text-xs text-muted">Findings are explicit and capped at three. Approval records the period and evidence version but never changes chart selection.</p>
      {!report?<><textarea aria-label="Approved findings" value={findings} onChange={e=>setFindings(e.target.value)} placeholder="One proposed V9 chart type per line (maximum three)" className="mt-3 min-h-24 w-full rounded-lg border border-line bg-panel p-2 text-sm"/><button type="button" onClick={async()=>setReport(await createVisualizationGapReport(getAuthToken(),filters.dateFrom||new Date().toISOString().slice(0,10),filters.dateTo||new Date().toISOString().slice(0,10),findings.split("\n").map(x=>x.trim()).filter(Boolean)))} className="mt-2 rounded-lg bg-brand px-3 py-2 text-xs font-bold text-white">Create draft</button></>:<div className="mt-3"><p className="text-sm">Status: <strong>{report.status.replaceAll("_"," ")}</strong> · Evidence {report.evidence_version}</p><div className="mt-2 flex gap-2">{report.status==="draft"&&<button onClick={async()=>setReport(await transitionVisualizationGapReport(getAuthToken(),report.id,"under_review"))} className="rounded-lg border border-line px-3 py-2 text-xs font-bold">Submit for review</button>}{report.status==="under_review"&&<><button onClick={async()=>setReport(await transitionVisualizationGapReport(getAuthToken(),report.id,"approved"))} className="rounded-lg bg-brand px-3 py-2 text-xs font-bold text-white">Approve</button><button onClick={async()=>setReport(await transitionVisualizationGapReport(getAuthToken(),report.id,"rejected"))} className="rounded-lg border border-line px-3 py-2 text-xs font-bold">Reject</button></>}</div></div>}
    </section>
  </PageShell>;
}

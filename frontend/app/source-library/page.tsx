"use client";
import Link from "next/link";
import { Suspense } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { GovernedRegister, type RegisterRecord } from "@/components/governance/GovernedRegister";
import { ContextStrip } from "@/components/overview/OverviewUI";
import { useLiveData } from "@/components/overview/useLiveData";
import { useTabParam } from "@/components/shell/useTabParam";
import { SourceLicensingPanel } from "@/components/source-knowledge/SourceLicensingPanel";
import { listSources } from "@/lib/api";

export default function SourceLibraryPage() { return <Suspense fallback={null}><SourceLibrary /></Suspense>; }
function SourceLibrary() {
  const [tab, setTab] = useTabParam("all", ["all", "standards", "tax", "audit", "payroll-compliance", "internal-policies", "education-content", "licensing"]);
  const { data, loading, error, signedOut, reload } = useLiveData(`source-library:${tab}`, (token, signal) => listSources(token, tab === "all" || tab === "licensing" ? undefined : tab, signal), 20_000);
  const sources = data ?? [];
  const records: RegisterRecord[] = sources.map(s => ({ id: s.id, title: s.title, category: s.category, state: s.latest_version.status, scope: s.jurisdiction_scope, version: s.latest_version.version_label, owner: s.latest_version.submitted_by, updated: s.latest_version.created_at?.slice(0, 10), facts: { "Source class": s.source_class, "Framework": s.framework_scope, "Jurisdiction": s.jurisdiction_scope, "Display restriction": s.latest_version.display_restriction, "Effective from": s.latest_version.effective_from || "Not recorded", "Effective until": s.latest_version.effective_to || "Not recorded", "Approved by": s.latest_version.approved_by || "Not recorded", "Quality state": s.latest_version.quality_state || "Not recorded" }, evidence: [s.latest_version.note, s.latest_version.source_url ? `Source URL: ${s.latest_version.source_url}` : s.latest_version.file_path ? "Document attached to the source record." : "Metadata only; no document attached."].filter(Boolean), history: [`Version ${s.latest_version.version_label} · created ${s.latest_version.created_at}`, `Approval actor: ${s.latest_version.approved_by || "Not recorded"}`], actions: <Link href="/source-library?tab=licensing" className="rounded-lg bg-[#f28a18] px-3 py-2 text-xs font-bold text-white">Open licensing & approval →</Link> }));
  const count = (states: string[]) => sources.filter(s => states.includes(s.latest_version.status)).length;
  return <PageShell title="Source Library" subtitle="Govern authoritative accounting knowledge, licensing rights, temporal applicability, and retrieval eligibility.">
    <ContextStrip jurisdiction="All loaded jurisdictions" framework="All loaded frameworks" period="Effective dates per record" />
    <LiveSourceStatus {...{ loading, error, signedOut, reload }} />
    <div className="flex gap-2 text-xs"><button className="rounded-md border border-line px-3 py-2 text-brand" onClick={() => setTab("all")}>Source register</button><button className="rounded-md border border-line px-3 py-2 text-brand" onClick={() => setTab("licensing")}>Licensing & Approval</button></div>
    {tab === "licensing" ? <SourceLicensingPanel /> : !error && !signedOut && <GovernedRegister title="Governed source register" inspector="Source inspector" records={records} tabs={["Overview", "Authority & rights", "Versions", "Retrieval & audit"]} doctrine="Source eligibility is a multi-gate decision: authority, licence rights, jurisdiction, effective date, integrity, and retrieval approval must all be checked." action={<button onClick={() => setTab("licensing")} className="rounded-md bg-[#f28a18] px-3 py-2 text-xs font-bold text-white">+ Add source</button>} metrics={[
      { label: "Registered source records", value: data ? sources.length : "—", detail: "Loaded catalog scope" }, { label: "Approved / active", value: data ? count(["ACTIVE", "APPROVED"]) : "—", detail: "Status alone does not establish retrieval rights", tone: "green" }, { label: "Awaiting validation", value: data ? count(["PROPOSED", "UNDER_REVIEW"]) : "—", detail: "Editorial or applicability review", tone: "amber" }, { label: "Disputed / blocked", value: data ? count(["DISPUTED", "BLOCKED"]) : "—", detail: "Requires a governance decision", tone: "red" }, { label: "Superseded", value: data ? count(["SUPERSEDED"]) : "—", detail: "Check historical applicability" },
    ]} />}
  </PageShell>;
}

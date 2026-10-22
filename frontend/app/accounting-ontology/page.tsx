"use client";
import { Suspense } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { GovernedRegister } from "@/components/governance/GovernedRegister";
import { ContextStrip } from "@/components/overview/OverviewUI";
import { useLiveData } from "@/components/overview/useLiveData";
import { useTabParam } from "@/components/shell/useTabParam";
import { SyllabusCoveragePanel } from "@/components/source-knowledge/SyllabusCoveragePanel";
import { listTopicMapNodes } from "@/lib/api";
export default function AccountingOntologyPage() { return <Suspense fallback={null}><AccountingOntology /></Suspense>; }
function AccountingOntology() {
  const [tab, setTab] = useTabParam("topics", ["topics", "syllabus"]);
  const { data, error, loading, signedOut, reload } = useLiveData("accounting-ontology", (token, signal) => listTopicMapNodes(token, signal), 20_000);
  const topics = data ?? [];
  return <PageShell title="Accounting Ontology" subtitle="Explore concept identities, prerequisite relationships, standards, and syllabus coverage.">
    <ContextStrip jurisdiction="Topic map scope" framework="Linked standards per concept" period="Saved learning topic map" />
    <LiveSourceStatus showRefresh={false} {...{ loading, error, signedOut, reload }} />
    <div className="flex gap-2">{["topics", "syllabus"].map(t => <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t} className="rounded-md border border-line px-3 py-2 text-xs text-brand">{t === "topics" ? "Concept register" : "Syllabus coverage"}</button>)}</div>
    {tab === "syllabus" ? <SyllabusCoveragePanel /> : !error && !signedOut && <GovernedRegister title="Accounting concept registry" inspector="Ontology inspector" tabs={["Overview", "Relationships", "Framework mappings", "Versions"]} records={topics.map(t => ({ id: t.id, title: t.topic, category: "Learning concept", state: "Recorded", facts: { "Persistent concept ID": t.id, "Standards": t.standards_summary || "Not recorded", "Prerequisites": t.prerequisites || "None recorded", "Release approval": "Not supplied by topic map" }, evidence: t.standards_summary ? [`Linked standards: ${t.standards_summary}`, "A standards summary does not establish a reviewed cross-framework equivalence."] : [], relations: t.prerequisites ? t.prerequisites.split(",").map(p => `Prerequisite: ${p.trim()}`) : [], actions: <button onClick={() => setTab("syllabus")} className="rounded-md bg-[#f28a18] px-3 py-2 text-xs font-bold text-white">Explore syllabus coverage →</button> }))} metrics={[
      { label: "Registered concepts", value: data ? topics.length : "—", detail: "Saved topic map identities" }, { label: "Prerequisite references", value: data ? topics.reduce((n, t) => n + (t.prerequisites ? t.prerequisites.split(",").filter(p => p.trim()).length : 0), 0) : "—", detail: "Recorded prerequisite labels", tone: "green" }, { label: "Linked standards", value: data ? topics.filter(t => t.standards_summary).length : "—", detail: "Concepts with standards summaries" }, { label: "Semantic conflicts", value: "—", detail: "Conflict review feed not available", tone: "red" }, { label: "Impact reviews", value: "—", detail: "Release impact feed not available", tone: "amber" },
    ]} doctrine="Ontology invariant: matching labels do not establish equivalent meaning. Cross-framework assertions require authoritative sources, jurisdiction, effective period, and independent review." footerTitle="Controlled ontology release" />}
  </PageShell>;
}

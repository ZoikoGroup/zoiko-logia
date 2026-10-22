"use client";
import { PageShell } from "@/components/governance/PageShell";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { GovernedRegister } from "@/components/governance/GovernedRegister";
import { ContextStrip, ActionLink } from "@/components/overview/OverviewUI";
import { useLiveData } from "@/components/overview/useLiveData";
import { getJurisdictionSummary } from "@/lib/api";
export default function JurisdictionRolloutPage() {
  const { data, error, loading, signedOut, reload } = useLiveData("jurisdiction-rollout", (token, signal) => getJurisdictionSummary(token, signal), 20_000);
  const summaries = data ?? [];
  return <PageShell title="Jurisdiction Rollout" subtitle="Inspect jurisdiction source coverage and the evidence needed before professional use.">
    <ContextStrip jurisdiction="All registered jurisdictions" framework="Mapped source categories" period="Current source coverage" />
    <LiveSourceStatus showRefresh={false} {...{ loading, error, signedOut, reload }} />
    {!error && !signedOut && <GovernedRegister title="Jurisdiction readiness register" inspector="Jurisdiction inspector" tabs={["Overview", "Sources & rights", "Evaluations", "History & rollback"]} records={summaries.map(s => ({ id: s.jurisdiction_scope, title: s.jurisdiction_scope, category: "Source coverage", state: s.readiness, scope: s.jurisdiction_scope, facts: { "Approved sources": String(s.approved_count), "Pending sources": String(s.pending_count), "Categories": String(s.categories.length), "Readiness": s.readiness, "Independent sign-off": "Not evaluated by this feed", "Production release": "Not established by coverage" }, evidence: ["READY means 5+ approved sources across 2+ categories. PARTIAL means some approved coverage; NOT_STARTED means no approved sources.", "This feed does not evaluate local-expert sign-off, privacy review, or QA release gates.", ...s.categories.map(c => `${c.category}: ${c.approved_count} approved · ${c.pending_count} pending`)], actions: <ActionLink href="/source-library">View source evidence</ActionLink> }))} metrics={[
      { label: "Jurisdiction records", value: data ? summaries.length : "—", detail: "Source coverage scopes" }, { label: "Source coverage ready", value: data ? summaries.filter(s => s.readiness === "READY").length : "—", detail: "Coverage threshold only · not release approval", tone: "green" }, { label: "Partial coverage", value: data ? summaries.filter(s => s.readiness === "PARTIAL").length : "—", detail: "Additional coverage needed", tone: "amber" }, { label: "Not started", value: data ? summaries.filter(s => s.readiness === "NOT_STARTED").length : "—", detail: "No approved sources", tone: "red" }, { label: "Pending sources", value: data ? summaries.reduce((n, s) => n + s.pending_count, 0) : "—", detail: "Across loaded jurisdictions", tone: "amber" },
    ]} doctrine="Release invariant: a jurisdiction in this register does not imply supported professional use. Source coverage does not establish passed evaluations, independent sign-off, or production-release authority." />}
  </PageShell>;
}

"use client";
import { PageShell } from "@/components/governance/PageShell";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { GovernedRegister } from "@/components/governance/GovernedRegister";
import { ContextStrip, ActionLink } from "@/components/overview/OverviewUI";
import { useLiveData } from "@/components/overview/useLiveData";
import { listSourceBundles } from "@/lib/api";

export default function SourceBundlesPage() {
  const { data, loading, error, signedOut, reload } = useLiveData("source-bundles", listSourceBundles, 20_000);
  const bundles = data ?? [];
  return <PageShell title="Source Bundles" subtitle="Inspect saved source packages assembled during governed Kriton retrieval.">
    <ContextStrip jurisdiction="All loaded jurisdictions" framework="Per retrieval context" period="Saved retrieval snapshots" />
    <LiveSourceStatus {...{ loading, error, signedOut, reload }} />
    {!error && !signedOut && <GovernedRegister title="Governed bundle register" inspector="Bundle inspector" tabs={["Overview", "Composition", "Validation gates", "Versions & replay"]} records={bundles.map(b => ({ id: b.id, title: b.sources[0]?.title ? `Research bundle · ${b.sources[0].title}` : `Source bundle ${b.id.slice(0, 8)}`, category: "Retrieval snapshot", state: b.confidence_state, scope: b.jurisdiction || "Unspecified", updated: b.created_at.slice(0, 10), facts: { "Bundle ID": b.id, "Jurisdiction": b.jurisdiction || "Not recorded", "Sources": String(b.sources.length), "Confidence state": b.confidence_state, "Created": b.created_at, "Publication authority": "Not supplied by this feed" }, relations: b.sources.map(s => `${s.title} · ${s.id}`), evidence: ["Saved during governed retrieval; confidence is not a publication approval.", `${b.sources.length} source references retained.`], history: [`Created ${b.created_at}`], actions: <ActionLink href="/source-library">Inspect source library</ActionLink> }))} metrics={[
      { label: "Loaded bundles", value: data ? bundles.length : "—", detail: "Latest 12 saved retrieval bundles" }, { label: "Source references", value: data ? bundles.reduce((n, b) => n + b.sources.length, 0) : "—", detail: "References across loaded snapshots", tone: "green" }, { label: "Empty bundles", value: data ? bundles.filter(b => !b.sources.length).length : "—", detail: "No eligible source references", tone: "amber" }, { label: "Published / approved", value: "—", detail: "Release lifecycle not supplied by this API" }, { label: "Jurisdictions", value: data ? new Set(bundles.map(b => b.jurisdiction).filter(Boolean)).size : "—", detail: "Loaded snapshot coverage" },
    ]} doctrine="Bundle safety invariant: a saved source bundle is not automatically eligible for reuse. Rights, purpose, source version, jurisdiction, time, and approval must be checked for each use." />}
  </PageShell>;
}

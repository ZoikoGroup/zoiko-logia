"use client";

import { Package, BookOpen } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { useLiveData } from "@/components/overview/useLiveData";
import { listSourceBundles } from "@/lib/api";

export default function SourceBundlesPage() {
  const { data, loading, error, signedOut, reload } = useLiveData("source-bundles", listSourceBundles, 20_000);
  return <PageShell title="Source Bundles" subtitle="The latest 12 saved source bundles assembled during governed retrieval." showMetrics={false}>
    <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />
    {!loading && !error && !signedOut && data?.length === 0 && <p className="text-sm text-muted">No saved source bundles yet.</p>}
    <div className="space-y-4">
      {data?.map((bundle) => <div key={bundle.id} className={PANEL_CLASS}>
        <PanelHeader icon={Package} title={bundle.id} action={<Pill>{bundle.confidence_state}</Pill>} />
        <p className="text-xs text-muted mb-3">{bundle.jurisdiction || "Jurisdiction unspecified"} · {new Date(bundle.created_at).toLocaleString()}</p>
        {bundle.sources.length ? <ul className="space-y-1">{bundle.sources.map((source) => <li key={source.id} className="flex items-center gap-2 text-sm"><BookOpen size={13} />{source.title}</li>)}</ul> : <p className="text-sm text-muted">No eligible sources in this bundle.</p>}
      </div>)}
    </div>
  </PageShell>;
}

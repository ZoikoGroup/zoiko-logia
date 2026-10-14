"use client";

import { Suspense } from "react";
import { Loader2, Network } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { Tabs } from "@/components/shell/Tabs";
import { useTabParam } from "@/components/shell/useTabParam";
import { SyllabusCoveragePanel } from "@/components/source-knowledge/SyllabusCoveragePanel";
import { listTopicMapNodes } from "@/lib/api";

const TOPIC_TONES: PanelTone[] = ["brand", "warn", "ok", "info"];

const TABS = [
  { label: "Topic map", slug: "topics" },
  // Was the separate Learning & Syllabus Mapping page.
  { label: "Syllabus coverage", slug: "syllabus" },
];
const TAB_SLUGS = TABS.map((t) => t.slug);

export default function AccountingOntologyPage() {
  return (
    <Suspense fallback={null}>
      <AccountingOntology />
    </Suspense>
  );
}

function AccountingOntology() {
  const [activeTab, setActiveTab] = useTabParam("topics", TAB_SLUGS);
  return (
    <PageShell
      title="Accounting Ontology"
      subtitle="The real topic map behind Kriton's accounting knowledge — concepts, prerequisites, the standards each one links to, and syllabus coverage."
      showMetrics={false}
    >
      <div className="mb-4"><Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} /></div>
      {activeTab === "syllabus" ? <SyllabusCoveragePanel /> : <TopicMap />}
    </PageShell>
  );
}

function TopicMap() {
  const { data, error, loading, signedOut, reload } = useLiveData(`accounting-ontology`, (token, signal) => listTopicMapNodes(token, signal), 20_000);
  const topics = data ?? [];


  return (
    <>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />

      <div className="rounded-xl border border-line bg-soft p-3 mb-4 text-xs text-muted">
        Topics, prerequisites, and linked standards come from the saved learning topic map.
      </div>

      {error || signedOut ? null : loading && !data ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading topic map…
        </div>
      ) : topics.length === 0 ? (
        <Card>
          <p className="text-sm text-muted py-4 text-center">No topics defined yet.</p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {topics.map((topic, idx) => (
            <div key={topic.id} className={PANEL_CLASS}>
              <PanelHeader icon={Network} tone={TOPIC_TONES[idx % TOPIC_TONES.length]} title={topic.topic} />
              <div className="space-y-3">
                <div>
                  <span className="text-[11px] font-bold text-muted uppercase tracking-wider">Prerequisites</span>
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {topic.prerequisites
                      ? topic.prerequisites.split(",").map((p) => <Pill key={p.trim()}>{p.trim()}</Pill>)
                      : <span className="text-xs text-muted">None</span>}
                  </div>
                </div>
                <div>
                  <span className="text-[11px] font-bold text-muted uppercase tracking-wider">Standards</span>
                  <p className="text-sm text-ink mt-1.5">{topic.standards_summary || "—"}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

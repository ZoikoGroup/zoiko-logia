"use client";

import { useEffect, useState } from "react";
import { Loader2, Network } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { getAuthToken, listTopicMapNodes, type TopicMapNode } from "@/lib/api";

const TOPIC_TONES: PanelTone[] = ["brand", "warn", "ok", "info"];

export default function AccountingOntologyPage() {
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    listTopicMapNodes(getAuthToken())
      .then(setTopics)
      .catch(() => setError("Could not load the topic map from the server."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <PageShell
      title="Accounting Ontology"
      subtitle="The real topic map behind Kriton's accounting knowledge — concepts, prerequisites, and the standards each one links to."
      showMetrics={false}
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <div className="rounded-xl border border-line bg-soft p-3 mb-4 text-xs text-muted">
        This shows the real topic/prerequisite/standard data used by Learning &amp; Practice. It is not yet a full
        graph — no cycle detection, no versioned releases, no tenant-policy conflict resolution. That is the
        still-unbuilt <code>ontology</code> domain.
      </div>

      {loading ? (
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
    </PageShell>
  );
}

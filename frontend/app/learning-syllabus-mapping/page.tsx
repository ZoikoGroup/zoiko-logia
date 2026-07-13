"use client";

import { useEffect, useState } from "react";
import { Loader2, CheckCircle2, Circle, BookMarked } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import {
  getAuthToken,
  listSyllabusPathways,
  listTopicMapNodes,
  type SyllabusPathway,
  type TopicMapNode,
} from "@/lib/api";

export default function LearningSyllabusMappingPage() {
  const [pathways, setPathways] = useState<SyllabusPathway[]>([]);
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listSyllabusPathways(token), listTopicMapNodes(token)])
      .then(([p, t]) => {
        setPathways(p);
        setTopics(t);
      })
      .catch(() => setError("Could not load syllabus mapping data from the server."))
      .finally(() => setLoading(false));
  }, []);

  const topicByName = new Map(topics.map((t) => [t.topic.toLowerCase(), t]));
  const mappedCount = pathways.filter((p) => topicByName.has(p.topic.toLowerCase())).length;

  return (
    <PageShell
      title="Learning & Syllabus Mapping"
      subtitle="Real coverage between professional-body syllabus pathways and Kriton's topic map."
      showMetrics={false}
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading syllabus mapping…
        </div>
      ) : pathways.length === 0 ? (
        <Card>
          <p className="text-sm text-muted py-4 text-center">No syllabus pathways defined yet.</p>
        </Card>
      ) : (
        <div className={PANEL_CLASS}>
          <PanelHeader
            icon={BookMarked}
            tone={mappedCount === pathways.length ? "ok" : "warn"}
            title="Syllabus → topic map coverage"
            action={
              <Pill tone={mappedCount === pathways.length ? "ok" : "warn"}>
                {mappedCount} / {pathways.length} mapped
              </Pill>
            }
          />
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="font-medium pb-2">Body / Qualification / Module</th>
                <th className="font-medium pb-2">Topic</th>
                <th className="font-medium pb-2">Learning outcome</th>
                <th className="font-medium pb-2">Topic map</th>
              </tr>
            </thead>
            <tbody>
              {pathways.map((p) => {
                const mapped = topicByName.get(p.topic.toLowerCase());
                return (
                  <tr key={p.id} className="border-t border-line align-top">
                    <td className="py-2.5 text-xs text-muted whitespace-nowrap">
                      {p.body} · {p.qualification} · {p.module}
                    </td>
                    <td className="py-2.5 font-semibold text-ink">{p.topic}</td>
                    <td className="py-2.5 text-xs text-ink max-w-xs">{p.learning_outcome}</td>
                    <td className="py-2.5">
                      {mapped ? (
                        <span className="flex items-center gap-1.5 text-xs text-ok">
                          <CheckCircle2 size={13} /> Mapped
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 text-xs text-muted">
                          <Circle size={13} /> No topic map node
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

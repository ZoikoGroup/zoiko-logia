"use client";

import { Loader2, CheckCircle2, Circle, BookMarked } from "lucide-react";
import { useLiveData } from "@/components/overview/useLiveData";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import {
  listSyllabusPathways,
  listTopicMapNodes,
} from "@/lib/api";

export function SyllabusCoveragePanel() {
  const { data, error, loading, signedOut, reload } = useLiveData(`learning-syllabus-mapping`, (token, signal) => Promise.all([listSyllabusPathways(token, signal), listTopicMapNodes(token, signal)]), 20_000);
  const [pathways, topics] = data ?? [[], []];


  const topicByName = new Map(topics.map((t) => [t.topic.trim().toLowerCase(), t]));
  const mappedCount = pathways.filter((p) => topicByName.has(p.topic.trim().toLowerCase())).length;

  return (
    <>
      <LiveSourceStatus loading={loading} error={error} signedOut={signedOut} reload={reload} />

      {error || signedOut ? null : loading && !data ? (
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
                const mapped = topicByName.get(p.topic.trim().toLowerCase());
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
    </>
  );
}

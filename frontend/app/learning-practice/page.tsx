"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { ADVISOR } from "@/lib/advisor";
import {
  getAuthToken,
  listSyllabusPathways,
  listTopicMapNodes,
  SyllabusPathway,
  TopicMapNode,
} from "@/lib/api";

export default function LearningPracticePage() {
  const [pathways, setPathways] = useState<SyllabusPathway[]>([]);
  const [topics, setTopics] = useState<TopicMapNode[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([listSyllabusPathways(token), listTopicMapNodes(token)])
      .then(([p, t]) => {
        setPathways(p);
        setTopics(t);
      })
      .catch(() => setError("Could not load learning content from the server."));
  }, []);

  return (
    <PageShell
      title="Learning & Practice"
      subtitle="Guided learning content, syllabus pathways, and topic maps for skill development."
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <Card className="mb-4">
        <div className="flex items-center gap-2 text-xs text-muted mb-3">
          <Pill tone="info">Context: Learning</Pill>
          <Pill>Jurisdiction: US</Pill>
          <Pill>Framework: US GAAP</Pill>
        </div>
        <div className="flex items-center gap-2 rounded-xl bg-soft border border-line px-4 py-3">
          <Search size={16} className="text-muted shrink-0" />
          <input
            type="text"
            disabled
            placeholder={ADVISOR.chatPlaceholder}
            className="w-full bg-transparent text-sm text-ink placeholder:text-muted outline-none disabled:cursor-not-allowed"
          />
          <button
            disabled
            className="shrink-0 rounded-lg bg-brand text-white text-xs font-semibold px-3.5 py-2 opacity-60 cursor-not-allowed"
          >
            Ask
          </button>
        </div>
        <p className="mt-2 text-[11px] text-muted">
          {ADVISOR.emptyState} Query submission is not yet wired to a live model — this is the Phase 1 entry point
          only.
        </p>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title="Continue Pathway">
          <ul className="space-y-3">
            {pathways.map((p) => (
              <li key={p.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                <div className="text-sm font-semibold text-ink">{p.topic}</div>
                <div className="text-xs text-muted mt-0.5">
                  {p.body} — {p.qualification} — {p.module}
                </div>
                <div className="text-xs text-ink mt-1">{p.learning_outcome}</div>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Topic Map">
          <ul className="space-y-3">
            {topics.map((t) => (
              <li key={t.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
                <div className="text-sm font-semibold text-ink">{t.topic}</div>
                <div className="text-xs text-muted mt-0.5">Prerequisites: {t.prerequisites}</div>
                <div className="text-xs text-muted">Standards: {t.standards_summary}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </PageShell>
  );
}

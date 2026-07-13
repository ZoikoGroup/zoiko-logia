"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, BookOpen, History, Package } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { getAuthToken, listAuditEvents, listSources, type AuditEvent, type Source } from "@/lib/api";

const CONFIDENCE_TONE: Record<string, "ok" | "warn" | "bad"> = {
  HIGH_CONFIDENCE: "ok",
  LOW_CONFIDENCE: "warn",
  NO_ELIGIBLE_SOURCE: "bad",
};

const CONFIDENCE_PANEL_TONE: Record<string, "ok" | "warn" | "bad" | "brand"> = {
  HIGH_CONFIDENCE: "ok",
  LOW_CONFIDENCE: "warn",
  NO_ELIGIBLE_SOURCE: "bad",
};

type BundlePayload = {
  bundle_id: string;
  retrieval_run_id: string;
  category: string;
  confidence_state: string;
  source_ids: string[];
};

const SOURCES_PREVIEW_COUNT = 4;

export default function RagSourceBundlesPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [sourceTitles, setSourceTitles] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  useEffect(() => {
    const token = getAuthToken();
    Promise.all([
      listAuditEvents(token, { eventName: "source_bundle_created", limit: 12 }),
      listSources(token),
    ])
      .then(([bundleEvents, sources]) => {
        setEvents(bundleEvents);
        const lookup: Record<string, string> = {};
        sources.forEach((s: Source) => {
          lookup[s.id] = s.title;
        });
        setSourceTitles(lookup);
      })
      .catch(() => setError("Could not load source bundles from the server."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <PageShell
      title="RAG Source Bundles"
      subtitle="Source bundles assembled for retrieval-augmented answer generation — one per Ask Kriton query, built by the real orchestration retrieval step."
      showMetrics={false}
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <div className="rounded-xl border border-line bg-soft p-3 mb-4 text-xs text-muted">
        Showing the 12 most recent bundles. Each shows the real sources matched for one query, by category and
        jurisdiction — a proportionate retrieval step (category + jurisdiction match), not semantic ranking yet, so a
        bundle can include sources that turn out not to be relevant to the specific question. Full semantic
        retrieval (embeddings, reranking, citation anchors) is the still-unbuilt <code>rag</code> domain.
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading source bundles…
        </div>
      ) : events.length === 0 ? (
        <Card>
          <p className="text-sm text-muted py-4 text-center">
            No bundles yet — ask Kriton a question and one will be recorded here automatically.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {events.map((event) => {
            const payload = event.payload as unknown as BundlePayload;
            return (
              <div key={event.id} className={PANEL_CLASS}>
                <PanelHeader
                  icon={Package}
                  tone={CONFIDENCE_PANEL_TONE[payload.confidence_state] ?? "brand"}
                  title={payload.bundle_id}
                  action={
                    <Pill tone={CONFIDENCE_TONE[payload.confidence_state] ?? "neutral"}>
                      {payload.confidence_state}
                    </Pill>
                  }
                />
                <div className="flex items-center gap-2 text-xs text-muted mb-2">
                  <Pill>{payload.category}</Pill>
                  <span>{event.event_time ? new Date(event.event_time).toLocaleString() : ""}</span>
                  {event.correlation_id && (
                    <Link
                      href={`/audit-replay?correlation_id=${encodeURIComponent(event.correlation_id)}`}
                      className="flex items-center gap-1 text-brand hover:underline ml-auto"
                    >
                      <History size={11} /> View audit trail
                    </Link>
                  )}
                </div>
                {payload.source_ids.length === 0 ? (
                  <p className="text-sm text-muted">No eligible sources matched this query.</p>
                ) : (
                  <>
                    <ul className="space-y-1">
                      {(expanded.has(event.id)
                        ? payload.source_ids
                        : payload.source_ids.slice(0, SOURCES_PREVIEW_COUNT)
                      ).map((id) => (
                        <li key={id} className="flex items-center gap-2 text-sm text-ink truncate">
                          <BookOpen size={13} className="text-muted shrink-0" />
                          <span className="truncate">{sourceTitles[id] ?? id}</span>
                        </li>
                      ))}
                    </ul>
                    {payload.source_ids.length > SOURCES_PREVIEW_COUNT && (
                      <button
                        onClick={() => toggleExpanded(event.id)}
                        className="mt-1.5 text-xs text-brand hover:underline"
                      >
                        {expanded.has(event.id)
                          ? "Show fewer"
                          : `Show ${payload.source_ids.length - SOURCES_PREVIEW_COUNT} more`}
                      </button>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}

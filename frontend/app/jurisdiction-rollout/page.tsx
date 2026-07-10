"use client";

import { useEffect, useState } from "react";
import { Loader2, Globe } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { getAuthToken, getJurisdictionSummary, type JurisdictionSummary } from "@/lib/api";

const READINESS_TONE: Record<string, "ok" | "warn" | "neutral"> = {
  READY: "ok",
  PARTIAL: "warn",
  NOT_STARTED: "neutral",
};

const READINESS_PANEL_TONE: Record<string, "ok" | "warn" | "brand"> = {
  READY: "ok",
  PARTIAL: "warn",
  NOT_STARTED: "brand",
};

const BAR_COLOR: Record<string, string> = {
  READY: "bg-ok",
  PARTIAL: "bg-warn",
  NOT_STARTED: "bg-line",
};

export default function JurisdictionRolloutPage() {
  const [summaries, setSummaries] = useState<JurisdictionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getJurisdictionSummary(getAuthToken())
      .then(setSummaries)
      .catch(() => setError("Could not load jurisdiction readiness from the server."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <PageShell
      title="Jurisdiction Rollout"
      subtitle="Real source-coverage readiness per jurisdiction, computed from the approved source register — not a fixed checklist."
      showMetrics={false}
    >
      {error && <p className="text-xs text-bad mb-3">{error}</p>}

      <div className="rounded-xl border border-line bg-soft p-3 mb-4 text-xs text-muted">
        Readiness here is derived from real approved-source counts: <Pill tone="ok">READY</Pill> means 5+ approved
        sources across 2+ categories, <Pill tone="warn">PARTIAL</Pill> means some coverage but concentrated in one
        category, <Pill>NOT_STARTED</Pill> means nothing approved yet. It does not yet reflect local-expert sign-off,
        privacy review, or QA gates — those controls aren&rsquo;t built.
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted">
          <Loader2 className="animate-spin mr-2" size={16} /> Computing jurisdiction readiness…
        </div>
      ) : summaries.length === 0 ? (
        <Card>
          <p className="text-sm text-muted py-4 text-center">No sources in the register yet.</p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {summaries.map((s) => {
            const maxCount = Math.max(...summaries.map((x) => x.approved_count), 1);
            const pct = Math.round((s.approved_count / maxCount) * 100);
            return (
              <div key={s.jurisdiction_scope} className={PANEL_CLASS}>
                <PanelHeader
                  icon={Globe}
                  tone={READINESS_PANEL_TONE[s.readiness] ?? "brand"}
                  title={s.jurisdiction_scope}
                  action={<Pill tone={READINESS_TONE[s.readiness]}>{s.readiness}</Pill>}
                />
                <div className="flex items-center justify-between text-sm mb-1.5">
                  <span className="text-ink">{s.approved_count} approved · {s.pending_count} pending</span>
                </div>
                <div className="h-2 rounded-full bg-soft border border-line overflow-hidden mb-3">
                  <div className={`h-full rounded-full ${BAR_COLOR[s.readiness]}`} style={{ width: `${pct}%` }} />
                </div>
                <div className="space-y-1.5">
                  {s.categories.map((c) => (
                    <div key={c.category} className="flex items-center justify-between text-xs">
                      <span className="text-muted">{c.category}</span>
                      <span className="text-ink font-medium">
                        {c.approved_count} approved
                        {c.pending_count > 0 && <span className="text-warn"> · {c.pending_count} pending</span>}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}

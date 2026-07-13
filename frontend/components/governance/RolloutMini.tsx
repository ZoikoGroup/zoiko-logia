"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getAuthToken, getJurisdictionSummary, type JurisdictionSummary } from "@/lib/api";
import { Card } from "./Card";
import { Pill } from "./Pill";

const BAR_COLOR: Record<string, string> = {
  READY: "bg-ok",
  PARTIAL: "bg-warn",
  NOT_STARTED: "bg-line",
};

const TEXT_COLOR: Record<string, string> = {
  READY: "text-ok",
  PARTIAL: "text-warn",
  NOT_STARTED: "text-muted",
};

export function RolloutMini() {
  const [summaries, setSummaries] = useState<JurisdictionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getJurisdictionSummary(getAuthToken())
      .then(setSummaries)
      .finally(() => setLoading(false));
  }, []);

  const maxCount = Math.max(...summaries.map((s) => s.approved_count), 1);

  return (
    <Card title="Jurisdiction rollout readiness" action={<Pill tone="info">Live</Pill>}>
      {loading ? (
        <div className="flex items-center justify-center py-6 text-muted">
          <Loader2 className="animate-spin mr-2" size={14} /> Loading…
        </div>
      ) : summaries.length === 0 ? (
        <p className="text-sm text-muted py-2">No sources in the register yet.</p>
      ) : (
        <div className="space-y-3">
          {summaries.map((s) => {
            const pct = Math.round((s.approved_count / maxCount) * 100);
            return (
              <div key={s.jurisdiction_scope}>
                <div className="flex items-center justify-between text-sm">
                  <span className="font-semibold text-ink">{s.jurisdiction_scope}</span>
                  <span className={`text-xs font-medium ${TEXT_COLOR[s.readiness]}`}>
                    {s.approved_count} approved
                  </span>
                </div>
                <div className="mt-1.5 h-2 rounded-full bg-soft border border-line overflow-hidden">
                  <div className={`h-full rounded-full ${BAR_COLOR[s.readiness]}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

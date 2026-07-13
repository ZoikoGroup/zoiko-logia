"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/governance/Card";
import { getEscalationStats } from "@/lib/safety-api";
import { getAuthToken, listSources } from "@/lib/api";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = ["AI Governance Lead", "Admin"];

export function GovernanceSnapshotModule() {
  const [pendingEscalations, setPendingEscalations] = useState<number | null>(null);
  const [disputedSources, setDisputedSources] = useState<number | null>(null);

  useEffect(() => {
    getEscalationStats().then((stats) => setPendingEscalations(stats?.pending ?? 0));
    listSources(getAuthToken())
      .then((sources) =>
        setDisputedSources(
          sources.filter((s) => ["DISPUTED", "BLOCKED"].includes(s.latest_version.status)).length
        )
      )
      .catch(() => setDisputedSources(0));
  }, []);

  return (
    <Card title="Governance Snapshot">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-2xl font-extrabold text-ink">{pendingEscalations ?? "—"}</div>
          <div className="text-xs text-muted">Pending escalations</div>
        </div>
        <div>
          <div className="text-2xl font-extrabold text-ink">{disputedSources ?? "—"}</div>
          <div className="text-xs text-muted">Disputed / blocked sources</div>
        </div>
      </div>
    </Card>
  );
}

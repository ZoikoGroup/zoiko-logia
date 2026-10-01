"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card } from "@/components/governance/Card";
import { getAuthToken, getCPDSummary, listSyllabusPathways, type CPDSummary, type SyllabusPathway } from "@/lib/api";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = ["Learner", "Admin"];

export function LearningProgressModule() {
  const [summary, setSummary] = useState<CPDSummary | null>(null);
  const [nextPathway, setNextPathway] = useState<SyllabusPathway | null>(null);

  useEffect(() => {
    const token = getAuthToken();
    // Both calls swallow their errors on purpose. This is a background widget
    // on a dashboard: it already renders a "—" placeholder when it has no
    // data, so a failed fetch should degrade to that. Unhandled, a rejection
    // surfaces as a red overlay in dev — and any 401 also triggers the
    // sign-out-and-redirect in lib/api.ts, so an expired token would boot the
    // user out from a widget they were not even looking at.
    getCPDSummary(token)
      .then(setSummary)
      .catch(() => setSummary(null));
    listSyllabusPathways(token)
      .then((rows) => setNextPathway(rows[0] ?? null))
      .catch(() => setNextPathway(null));
  }, []);

  return (
    <Card title="Learning Progress">
      <div className="space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-ink">CPD time logged</span>
          <span className="text-xs text-muted">{summary ? `${summary.total_hours}h` : "—"}</span>
        </div>
        {nextPathway && (
          <div className="text-xs text-muted">
            Next in pathway: {nextPathway.topic} ({nextPathway.body})
          </div>
        )}
        <Link href="/learning-practice" className="inline-block text-xs text-brand hover:underline">
          Go to Learning & Practice
        </Link>
      </div>
    </Card>
  );
}

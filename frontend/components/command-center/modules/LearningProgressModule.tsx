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
    getCPDSummary(token).then(setSummary);
    listSyllabusPathways(token).then((rows) => setNextPathway(rows[0] ?? null));
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

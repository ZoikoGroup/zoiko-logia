"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { Tabs } from "@/components/shell/Tabs";
import { getAuthToken, listSources, Source } from "@/lib/api";

const TABS = [
  { label: "Standards", slug: "standards" },
  { label: "Tax", slug: "tax" },
  { label: "Audit", slug: "audit" },
  { label: "Payroll/Compliance", slug: "payroll-compliance" },
  { label: "Internal Policies", slug: "internal-policies" },
  { label: "Education Content", slug: "education-content" },
];

const DESCRIPTIONS: Record<string, string> = {
  standards: "Authoritative accounting and financial reporting standards (IFRS, GAAP, etc.).",
  tax: "Tax authority guidance, statutes, and rulings by jurisdiction.",
  audit: "Auditing standards, methodology guides, and quality control frameworks.",
  "payroll-compliance": "Payroll, employment, and statutory compliance source material.",
  "internal-policies": "Firm- and tenant-specific internal policy documents.",
  "education-content": "Licensed education and CPD source content.",
};

const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = {
  ACTIVE: "ok",
  APPROVED: "ok",
  PROPOSED: "warn",
  UNDER_REVIEW: "warn",
  DISPUTED: "bad",
  SUPERSEDED: "neutral",
  BLOCKED: "bad",
};

export default function SourceLibraryPage() {
  const [activeTab, setActiveTab] = useState("standards");
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    listSources(getAuthToken(), activeTab)
      .then(setSources)
      .catch(() => setError("Could not load sources from the server."));
  }, [activeTab]);

  return (
    <PageShell
      title="Source Library"
      subtitle="Browse and manage authoritative source material by category before it enters licensing and RAG bundles."
    >
      <Card>
        <Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} />
        <p className="text-xs text-muted mt-3 mb-3">{DESCRIPTIONS[activeTab]}</p>
        {error && <p className="text-xs text-bad mb-3">{error}</p>}

        {sources.length === 0 && !error && (
          <p className="text-sm text-muted py-4">No sources in this category yet.</p>
        )}

        <ul className="space-y-3">
          {sources.map((source) => (
            <li key={source.id} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-ink">{source.title}</div>
                <Pill tone={STATUS_TONE[source.latest_version.status] ?? "neutral"}>
                  {source.latest_version.status}
                </Pill>
              </div>
              <div className="text-xs text-muted mt-0.5">
                {source.source_class} — {source.jurisdiction_scope}
              </div>
              {source.latest_version.note && (
                <div className="text-xs text-ink mt-1">{source.latest_version.note}</div>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </PageShell>
  );
}

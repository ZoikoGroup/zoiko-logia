"use client";

import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Database,
  Landmark,
  ClipboardCheck,
  Users,
  Lock,
  GraduationCap,
  CheckCircle2,
  Clock,
  XCircle,
} from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { StatTile } from "@/components/governance/StatTile";
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

const TAB_ICON: Record<string, LucideIcon> = {
  standards: Database,
  tax: Landmark,
  audit: ClipboardCheck,
  "payroll-compliance": Users,
  "internal-policies": Lock,
  "education-content": GraduationCap,
};

const TAB_TONE: Record<string, PanelTone> = {
  standards: "brand",
  tax: "warn",
  audit: "ok",
  "payroll-compliance": "info",
  "internal-policies": "brand",
  "education-content": "warn",
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

  const approvedCount = sources.filter((s) => ["ACTIVE", "APPROVED"].includes(s.latest_version.status)).length;
  const pendingCount = sources.filter((s) => ["PROPOSED", "UNDER_REVIEW"].includes(s.latest_version.status)).length;
  const disputedCount = sources.filter((s) => ["DISPUTED", "BLOCKED"].includes(s.latest_version.status)).length;

  return (
    <PageShell
      title="Source Library"
      subtitle="Browse and manage authoritative source material by category before it enters licensing and RAG bundles."
      showMetrics={false}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <StatTile label="In this category" value={sources.length} tone={TAB_TONE[activeTab] ?? "brand"} icon={TAB_ICON[activeTab] ?? Database} />
        <StatTile label="Approved / active" value={approvedCount} tone="ok" icon={CheckCircle2} />
        <StatTile label="Awaiting review" value={pendingCount} tone="warn" icon={Clock} />
        <StatTile label="Disputed / blocked" value={disputedCount} tone="bad" icon={XCircle} />
      </div>

      <div className={PANEL_CLASS}>
        <PanelHeader
          icon={TAB_ICON[activeTab] ?? Database}
          tone={TAB_TONE[activeTab] ?? "brand"}
          title={TABS.find((t) => t.slug === activeTab)?.label ?? "Sources"}
          subtitle={DESCRIPTIONS[activeTab]}
        />
        <Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} />
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
      </div>
    </PageShell>
  );
}

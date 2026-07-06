"use client";

import { useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Tabs } from "@/components/shell/Tabs";
import { PlannedModule } from "@/components/shell/PlannedModule";

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

export default function SourceLibraryPage() {
  const [activeTab, setActiveTab] = useState("standards");

  return (
    <PageShell
      title="Source Library"
      subtitle="Browse and manage authoritative source material by category before it enters licensing and RAG bundles."
    >
      <Card>
        <Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} />
        <PlannedModule phase={3} description={DESCRIPTIONS[activeTab]} />
      </Card>
    </PageShell>
  );
}

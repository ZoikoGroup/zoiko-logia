"use client";

import { useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import { Tabs } from "@/components/shell/Tabs";
import { PlannedModule } from "@/components/shell/PlannedModule";
import { MODEL_REGISTRY, PROMPT_REGISTRY } from "@/lib/governance-data";

const MODEL_TONE: Record<string, "ok" | "warn" | "bad"> = {
  Active: "ok",
  Testing: "warn",
  Deprecated: "bad",
};

const PROMPT_TONE: Record<string, "ok" | "warn"> = {
  Approved: "ok",
  "Pending review": "warn",
};

const TABS = [
  { label: "Models", slug: "models" },
  { label: "Prompts", slug: "prompts" },
  { label: "System Instructions", slug: "system-instructions" },
  { label: "Evaluation Status", slug: "evaluation-status" },
  { label: "Change History", slug: "change-history" },
];

export default function ModelPromptRegistryPage() {
  const [activeTab, setActiveTab] = useState("models");

  return (
    <PageShell
      title="Model & Prompt Registry"
      subtitle="Track which models and prompt versions are active in production, staging, or pending approval."
    >
      <Card>
        <Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} />

        {activeTab === "models" && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="font-medium pb-2">Model</th>
                <th className="font-medium pb-2">Environment</th>
                <th className="font-medium pb-2">Version</th>
                <th className="font-medium pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {MODEL_REGISTRY.map(([model, role, environment, version, status]) => (
                <tr key={model} className="border-t border-line align-top">
                  <td className="py-2.5 font-semibold text-ink">
                    {model}
                    <div className="text-[11px] text-muted font-normal">{role}</div>
                  </td>
                  <td className="py-2.5 text-ink">{environment}</td>
                  <td className="py-2.5 text-ink">{version}</td>
                  <td className="py-2.5"><Pill tone={MODEL_TONE[status]}>{status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {activeTab === "prompts" && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="font-medium pb-2">Prompt</th>
                <th className="font-medium pb-2">Version</th>
                <th className="font-medium pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {PROMPT_REGISTRY.map(([prompt, version, status]) => (
                <tr key={prompt} className="border-t border-line">
                  <td className="py-2.5 font-semibold text-ink">{prompt}</td>
                  <td className="py-2.5 text-ink">{version}</td>
                  <td className="py-2.5"><Pill tone={PROMPT_TONE[status]}>{status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {activeTab === "system-instructions" && (
          <PlannedModule phase={3} description="System instruction versioning and per-tenant overrides." />
        )}
        {activeTab === "evaluation-status" && (
          <PlannedModule phase={3} description="Live evaluation gate status per model/prompt version, linked to Evaluation Gates." />
        )}
        {activeTab === "change-history" && (
          <PlannedModule phase={3} description="Full change history and approval trail for models and prompts." />
        )}
      </Card>
    </PageShell>
  );
}

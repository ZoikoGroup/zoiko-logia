"use client";

import { FormEvent, useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Cpu, MessageSquare, FileCode, FlaskConical, History } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { Tabs } from "@/components/shell/Tabs";
import { PlannedModule } from "@/components/shell/PlannedModule";
import {
  ApiError,
  getAuthToken,
  listModels,
  listPrompts,
  approvePrompt,
  runTestPrompt,
  ModelDefinition,
  PromptTemplate,
} from "@/lib/api";

const MODEL_TONE: Record<string, "ok" | "warn" | "bad"> = {
  Active: "ok",
  Testing: "warn",
  Deprecated: "bad",
};

const PROMPT_TONE: Record<string, "ok" | "warn"> = {
  Approved: "ok",
  PendingReview: "warn",
};

const TABS = [
  { label: "Models", slug: "models" },
  { label: "Prompts", slug: "prompts" },
  { label: "System Instructions", slug: "system-instructions" },
  { label: "Evaluation Status", slug: "evaluation-status" },
  { label: "Change History", slug: "change-history" },
];

const TAB_ICON: Record<string, LucideIcon> = {
  models: Cpu,
  prompts: MessageSquare,
  "system-instructions": FileCode,
  "evaluation-status": FlaskConical,
  "change-history": History,
};

const TAB_TONE: Record<string, PanelTone> = {
  models: "brand",
  prompts: "info",
  "system-instructions": "warn",
  "evaluation-status": "ok",
  "change-history": "brand",
};

export default function ModelPromptRegistryPage() {
  const [activeTab, setActiveTab] = useState("models");
  const [models, setModels] = useState<ModelDefinition[]>([]);
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");

  const [testPromptId, setTestPromptId] = useState("");
  const [testInput, setTestInput] = useState("");
  const [testOutput, setTestOutput] = useState("");
  const [testSubmitting, setTestSubmitting] = useState(false);

  function describeLoadError(err: unknown, what: string): string {
    if (err instanceof ApiError) {
      if (err.status === 401) return "Your session has expired. Please log out and log back in.";
      if (err.status === 403) return `Admin role required to view ${what}.`;
    }
    return `Could not load ${what} from the server.`;
  }

  function loadPrompts() {
    listPrompts(getAuthToken())
      .then((p) => {
        setPrompts(p);
        if (p.length > 0 && !testPromptId) setTestPromptId(p[0].id);
      })
      .catch((err) => setError(describeLoadError(err, "prompts")));
  }

  useEffect(() => {
    listModels(getAuthToken())
      .then(setModels)
      .catch((err) => setError(describeLoadError(err, "models")));
    loadPrompts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleApprove(prompt: PromptTemplate) {
    setActionError("");
    try {
      await approvePrompt(getAuthToken(), prompt.id);
      loadPrompts();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not approve prompt.");
    }
  }

  async function handleTestRun(e: FormEvent) {
    e.preventDefault();
    setTestOutput("");
    setTestSubmitting(true);
    try {
      const res = await runTestPrompt(getAuthToken(), testPromptId, testInput);
      setTestOutput(res.output_text);
    } catch (err) {
      setTestOutput(err instanceof ApiError ? `Error: ${err.message}` : "Could not run test prompt.");
    } finally {
      setTestSubmitting(false);
    }
  }

  return (
    <PageShell
      title="Model & Prompt Registry"
      subtitle="Track which models and prompt versions are active in production, staging, or pending approval."
      showMetrics={false}
    >
      <div className={PANEL_CLASS}>
        <PanelHeader
          icon={TAB_ICON[activeTab] ?? Cpu}
          tone={TAB_TONE[activeTab] ?? "brand"}
          title={TABS.find((t) => t.slug === activeTab)?.label ?? "Registry"}
        />
        <Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} />

        {activeTab === "models" && (
          <>
            {error && <p className="text-xs text-bad mt-3">{error}</p>}
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
                {models.map((model) => (
                  <tr key={model.id} className="border-t border-line align-top">
                    <td className="py-2.5 font-semibold text-ink">
                      {model.name}
                      <div className="text-[11px] text-muted font-normal">{model.role}</div>
                    </td>
                    <td className="py-2.5 text-ink">{model.environment}</td>
                    <td className="py-2.5 text-ink">{model.version}</td>
                    <td className="py-2.5">
                      <Pill tone={MODEL_TONE[model.status] ?? "warn"}>{model.status}</Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {activeTab === "prompts" && (
          <>
            {error && <p className="text-xs text-bad mt-3">{error}</p>}
            {actionError && <p className="text-xs text-bad mt-3">{actionError}</p>}
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted">
                  <th className="font-medium pb-2">Prompt</th>
                  <th className="font-medium pb-2">Version</th>
                  <th className="font-medium pb-2">Status</th>
                  <th className="font-medium pb-2" />
                </tr>
              </thead>
              <tbody>
                {prompts.map((prompt) => (
                  <tr key={prompt.id} className="border-t border-line align-top">
                    <td className="py-2.5 font-semibold text-ink">{prompt.name}</td>
                    <td className="py-2.5 text-ink">{prompt.version}</td>
                    <td className="py-2.5">
                      <Pill tone={PROMPT_TONE[prompt.status] ?? "warn"}>{prompt.status}</Pill>
                    </td>
                    <td className="py-2.5 text-right">
                      {prompt.status === "PendingReview" && (
                        <button
                          onClick={() => handleApprove(prompt)}
                          className="text-xs text-brand hover:underline"
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="mt-5 pt-4 border-t border-line">
              <div className="text-sm font-semibold text-ink mb-2">Test run (Model Gateway → mock provider)</div>
              <form onSubmit={handleTestRun} className="flex flex-col sm:flex-row gap-2 items-start sm:items-end">
                <div className="flex-1 w-full">
                  <label className="block text-xs font-medium text-muted mb-1.5">Prompt template</label>
                  <select
                    value={testPromptId}
                    onChange={(e) => setTestPromptId(e.target.value)}
                    className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                  >
                    {prompts.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.version})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex-[2] w-full">
                  <label className="block text-xs font-medium text-muted mb-1.5">Input</label>
                  <input
                    value={testInput}
                    onChange={(e) => setTestInput(e.target.value)}
                    placeholder="e.g. What is deferred revenue?"
                    required
                    className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                  />
                </div>
                <button
                  type="submit"
                  disabled={testSubmitting || !testPromptId}
                  className="rounded-lg bg-brand text-white text-sm font-semibold px-4 py-2 hover:bg-brand-2 disabled:opacity-60 whitespace-nowrap"
                >
                  {testSubmitting ? "Running..." : "Run test"}
                </button>
              </form>
              {testOutput && (
                <div className="mt-3 rounded-lg border border-line bg-soft p-3 text-xs text-ink font-mono">
                  {testOutput}
                </div>
              )}
              <p className="mt-2 text-[11px] text-muted">
                Uses a mock provider adapter — no real model call happens yet; this proves the gateway routing path.
              </p>
            </div>
          </>
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
      </div>
    </PageShell>
  );
}

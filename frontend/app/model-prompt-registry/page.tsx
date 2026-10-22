"use client";

import Link from "next/link";
import { GovernedRegister, type RegisterRecord } from "@/components/governance/GovernedRegister";
import { ContextStrip } from "@/components/overview/OverviewUI";

import { FormEvent, useCallback, useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Cpu, MessageSquare, FileCode, FlaskConical, History, Loader2 } from "lucide-react";
import { PageShell } from "@/components/governance/PageShell";
import { Pill } from "@/components/governance/Pill";
import { PanelHeader, PANEL_CLASS, type PanelTone } from "@/components/governance/PanelHeader";
import { LoadError, formatCount, formatWhen } from "@/components/governance/LiveStatus";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { Tabs } from "@/components/shell/Tabs";
import {
  ApiError,
  getAuthToken,
  getRegistryChangeHistory,
  getRegistryOverview,
  getSystemInstructions,
  listModels,
  listPrompts,
  approvePrompt,
  runTestPrompt,
  type ModelDefinition,
  type PromptTemplate,
  type RegistryChange,
  type RegistryOverview,
  type SystemInstruction,
} from "@/lib/api";
import { listRuns, type RunHistoryEntry } from "@/lib/evaluation-api";

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

function describeLoadError(err: unknown, what: string): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Your session has expired. Please log out and log back in.";
    if (err.status === 403) return `Your role cannot view ${what}.`;
    return `Could not load ${what}: ${err.message}`;
  }
  return `Could not load ${what} — the backend did not respond.`;
}

function Loading() {
  return <div className="flex items-center justify-center py-10 text-muted"><Loader2 className="animate-spin" size={16} /></div>;
}

export default function ModelPromptRegistryPage() {
  const [activeTab, setActiveTab] = useState("models");
  const [models, setModels] = useState<ModelDefinition[] | null>(null);
  const [prompts, setPrompts] = useState<PromptTemplate[] | null>(null);
  const [overview, setOverview] = useState<RegistryOverview | null>(null);
  const [instructions, setInstructions] = useState<SystemInstruction[] | null>(null);
  const [runs, setRuns] = useState<RunHistoryEntry[] | null>(null);
  const [changes, setChanges] = useState<RegistryChange[] | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState("");

  const [testPromptId, setTestPromptId] = useState("");
  const [testInput, setTestInput] = useState("");
  const [testOutput, setTestOutput] = useState("");
  const [testSubmitting, setTestSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const token = getAuthToken();
    const nextErrors: Record<string, string> = {};
    // Each tab loads independently so one failing call does not blank the page.
    await Promise.all([
      listModels(token).then(setModels).catch((err) => { nextErrors.models = describeLoadError(err, "models"); }),
      listPrompts(token).then((p) => {
        setPrompts(p);
        setTestPromptId((current) => current || p[0]?.id || "");
      }).catch((err) => { nextErrors.prompts = describeLoadError(err, "prompts"); }),
      getRegistryOverview(token).then(setOverview).catch((err) => { nextErrors.models ??= describeLoadError(err, "runtime models"); }),
      getSystemInstructions(token).then(setInstructions).catch((err) => { nextErrors["system-instructions"] = describeLoadError(err, "system instructions"); }),
      listRuns(10).then(setRuns).catch((err) => { nextErrors["evaluation-status"] = err instanceof Error ? `Could not load evaluation runs: ${err.message}` : "Could not load evaluation runs."; }),
      getRegistryChangeHistory(token).then(setChanges).catch((err) => { nextErrors["change-history"] = describeLoadError(err, "change history"); }),
    ]);
    setErrors(nextErrors);
    setLoading(false);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  async function handleApprove(prompt: PromptTemplate) {
    setActionError("");
    try {
      await approvePrompt(getAuthToken(), prompt.id);
      await load();
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

  const tabError = errors[activeTab];
  const promptUsage = overview?.usage.by_prompt ?? {};
  const registryRecords: RegisterRecord[] = [
    ...(models ?? []).map(m => ({ id: `model:${m.id}`, title: m.name, category: "Models", state: m.status, scope: m.environment, version: m.version, facts: { "Model ID": m.id, "Provider": m.provider, "Role": m.role, "Environment": m.environment, "Version": m.version, "Runtime matches": overview?.registry_matches[m.id]?.join(", ") || "No running role matched" }, evidence: [`Provider: ${m.provider}`, `Registered status: ${m.status}`, "A model registration alone does not authorize a production configuration."], actions: <button onClick={() => setActiveTab("models")} className="rounded border border-line px-3 py-2 text-xs text-brand">Inspect runtime models below</button> })),
    ...(prompts ?? []).map(p => ({ id: `prompt:${p.id}`, title: p.name, category: "Prompt templates", state: p.status, scope: p.mode, version: p.version, owner: p.submitted_by, facts: { "Prompt ID": p.id, "Mode": p.mode, "Version": p.version, "Submitted by": p.submitted_by, "Approved by": p.approved_by || "Not recorded", "Recorded runs": String(promptUsage[p.id]?.runs ?? 0) }, evidence: [`Approval actor: ${p.approved_by || "Not recorded"}`, `Last run: ${promptUsage[p.id]?.last_run || "Not recorded"}`], actions: <button onClick={() => setActiveTab("prompts")} className="rounded border border-line px-3 py-2 text-xs text-brand">Open prompt testing & approval below</button> })),
  ];


  return (
    <PageShell
      title="Model & Prompt Registry"
      subtitle="Track which models and prompt versions are active in production, staging, or pending approval."
    >
      <LiveSourceStatus showRefresh={false} loading={loading} error="" signedOut={false} reload={load} />
      <ContextStrip jurisdiction="Registered environments" framework="Models, prompts, tools & evaluation evidence" period="Current backend configuration" />
      <div className="overview-navy rounded-xl p-5 text-white"><p className="text-[10px] uppercase tracking-widest text-amber-300">Versioned · tested · human authorized</p><h2 className="mt-2 text-xl font-bold">Trace every Kriton release to its exact configuration.</h2><p className="mt-2 text-xs text-blue-100">Model and prompt records remain distinct from production release authorization.</p></div>
      <GovernedRegister title="Model & prompt register" inspector="Selected registry configuration" records={registryRecords} tabs={["Overview", "Lineage", "Gate evidence", "Audit history"]} doctrine="A release binds model, prompt, tool access, source bundles, policy versions, and evaluation evidence. Registered or active model status alone is not release authorization." metrics={[
        { label: "Model versions", value: models?.length ?? "—", detail: "Registered model catalog" },
        { label: "Prompt versions", value: prompts?.length ?? "—", detail: "Versioned prompt templates", tone: "amber" },
        { label: "Runtime model roles", value: overview?.runtime_models.length ?? "—", detail: "Configured backend responsibilities" },
        { label: "Evaluation runs", value: runs?.length ?? "—", detail: "Loaded release evaluation history", tone: "green" },
        { label: "Pending prompt reviews", value: prompts ? prompts.filter(p => p.status !== "Approved").length : "—", detail: "Prompts without approved status", tone: "red" },
      ]} />
      <div className={PANEL_CLASS}>
        <PanelHeader
          icon={TAB_ICON[activeTab] ?? Cpu}
          tone={TAB_TONE[activeTab] ?? "brand"}
          title={TABS.find((t) => t.slug === activeTab)?.label ?? "Registry"}
        />
        <Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} />
        {tabError && <div className="mt-3"><LoadError message={tabError} onRetry={() => void load()} /></div>}

        {activeTab === "models" && (
          <div className="space-y-6">
            <section className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="text-sm font-semibold text-ink">Running now</h4>
                <span className="text-[11px] text-muted">
                  Read from the backend&apos;s model settings{overview ? ` · answering through ${overview.active_adapter} · approved providers: ${overview.approved_providers.join(", ")}` : ""}
                </span>
              </div>
              {!overview ? (!tabError && <Loading />) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-[11px] text-muted">
                        <th className="font-medium pb-2 pr-3">Role</th>
                        <th className="font-medium pb-2 pr-3">Model</th>
                        <th className="font-medium pb-2 pr-3">Provider</th>
                        <th className="font-medium pb-2 pr-3">Set by</th>
                        <th className="font-medium pb-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.runtime_models.map((model) => (
                        <tr key={model.role} className="border-t border-line align-top">
                          <td className="py-2.5 pr-3 font-semibold text-ink">
                            {model.role}
                            <div className="text-[11px] text-muted font-normal">{model.used_by}</div>
                          </td>
                          <td className="py-2.5 pr-3 font-mono text-xs text-ink">{model.model}</td>
                          <td className="py-2.5 pr-3 text-ink">{model.provider}</td>
                          <td className="py-2.5 pr-3 font-mono text-[11px] text-muted">{model.source === "default" ? "code default" : model.source}</td>
                          <td className="py-2.5">
                            {model.active ? <Pill tone="ok">Active</Pill>
                              : !model.provider_approved ? <Pill tone="bad">Provider not approved</Pill>
                              : <Pill tone="warn">No API key</Pill>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {overview && overview.usage.by_provider.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-sm font-semibold text-ink">Model runs by provider</h4>
                <div className="grid gap-3 sm:grid-cols-3">
                  {overview.usage.by_provider.map((row) => (
                    <div key={row.provider} className="rounded-xl border border-line bg-soft/40 p-3">
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{row.provider}</div>
                      <div className="mt-1 text-xl font-extrabold text-ink">{formatCount(row.runs)}</div>
                      <div className="text-[11px] text-muted">last {formatWhen(row.last_run)}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="text-sm font-semibold text-ink">Registry catalogue</h4>
                {overview && models && overview.unused_registry_models.length > 0 && (
                  <span className="text-[11px] text-warn">
                    {overview.unused_registry_models.length} of {models.length} entries are not used by the running system
                  </span>
                )}
              </div>
              {!models ? (!tabError && <Loading />) : models.length === 0 ? (
                <p className="text-xs text-muted">No models registered.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] text-muted">
                      <th className="font-medium pb-2">Model</th>
                      <th className="font-medium pb-2">Environment</th>
                      <th className="font-medium pb-2">Version</th>
                      <th className="font-medium pb-2">Status</th>
                      <th className="font-medium pb-2">In use</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((model) => {
                      const roles = overview?.registry_matches[model.id] ?? [];
                      return (
                        <tr key={model.id} className="border-t border-line align-top">
                          <td className="py-2.5 font-semibold text-ink">
                            {model.name}
                            <div className="text-[11px] text-muted font-normal">{model.role} · {model.provider}</div>
                          </td>
                          <td className="py-2.5 text-ink">{model.environment}</td>
                          <td className="py-2.5 font-mono text-xs text-ink">{model.version}</td>
                          <td className="py-2.5"><Pill tone={MODEL_TONE[model.status] ?? "warn"}>{model.status}</Pill></td>
                          <td className="py-2.5">
                            {!overview ? "—" : roles.length
                              ? <Pill tone="ok">{roles.join(", ")}</Pill>
                              : <Pill tone="warn">Not used</Pill>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          </div>
        )}

        {activeTab === "prompts" && (
          <>
            {actionError && <p className="text-xs text-bad mt-3">{actionError}</p>}
            {!prompts ? (!tabError && <Loading />) : prompts.length === 0 ? (
              <p className="py-6 text-xs text-muted">No prompt templates registered.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] text-muted">
                    <th className="font-medium pb-2">Prompt</th>
                    <th className="font-medium pb-2">Version</th>
                    <th className="font-medium pb-2">Status</th>
                    <th className="font-medium pb-2">Model runs</th>
                    <th className="font-medium pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {prompts.map((prompt) => {
                    const usage = promptUsage[prompt.id];
                    return (
                      <tr key={prompt.id} className="border-t border-line align-top">
                        <td className="py-2.5 font-semibold text-ink">
                          {prompt.name}
                          <div className="text-[11px] text-muted font-normal">{prompt.mode}</div>
                        </td>
                        <td className="py-2.5 text-ink">{prompt.version}</td>
                        <td className="py-2.5">
                          <Pill tone={PROMPT_TONE[prompt.status] ?? "warn"}>{prompt.status}</Pill>
                        </td>
                        <td className="py-2.5 text-ink">
                          {usage ? (
                            <>
                              {formatCount(usage.runs)}
                              <div className="text-[11px] text-muted">last {formatWhen(usage.last_run)}</div>
                            </>
                          ) : <span className="text-muted">0</span>}
                        </td>
                        <td className="py-2.5 text-right">
                          {prompt.status === "PendingReview" && (
                            <button onClick={() => handleApprove(prompt)} className="text-xs text-brand hover:underline">
                              Approve
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            <div className="mt-5 pt-4 border-t border-line">
              <div className="text-sm font-semibold text-ink mb-2">
                Test run (Model Gateway → {overview?.active_adapter ?? "configured provider"})
              </div>
              <form onSubmit={handleTestRun} className="flex flex-col sm:flex-row gap-2 items-start sm:items-end">
                <div className="flex-1 w-full">
                  <label className="block text-xs font-medium text-muted mb-1.5">Prompt template</label>
                  <select
                    value={testPromptId}
                    onChange={(e) => setTestPromptId(e.target.value)}
                    className="w-full rounded-lg border border-line bg-soft px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                  >
                    {(prompts ?? []).map((p) => (
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
                <div className="mt-3 max-h-80 overflow-y-auto whitespace-pre-wrap rounded-lg border border-line bg-soft p-3 text-xs text-ink font-mono">
                  {testOutput}
                </div>
              )}
              <p className="mt-2 text-[11px] text-muted">
                {overview?.active_adapter === "MockProvider"
                  ? "No provider API key is configured, so this uses the mock adapter."
                  : "Calls the real model provider and records a model_run_completed audit event."}
              </p>
            </div>
          </>
        )}

        {activeTab === "system-instructions" && (
          !instructions ? (!tabError && <Loading />) : (
            <div className="space-y-3">
              <p className="text-[11px] text-muted">
                The system prompts the answer path sends today. The fingerprint changes whenever the text changes.
              </p>
              {instructions.map((item) => (
                <details key={item.name} className="rounded-xl border border-line bg-soft/30 p-4">
                  <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="text-sm font-semibold text-ink">{item.name}</span>
                      <span className="block text-[11px] text-muted">{item.used_by}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <code className="font-mono text-[10px] text-muted" title={item.sha256}>sha256 {item.sha256.slice(0, 12)}</code>
                      <Pill>{formatCount(item.characters)} chars</Pill>
                    </span>
                  </summary>
                  <pre className="mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap rounded-lg border border-line bg-panel p-3 text-[11px] leading-relaxed text-ink">{item.text}</pre>
                </details>
              ))}
            </div>
          )
        )}

        {activeTab === "evaluation-status" && (
          !runs ? (!tabError && <Loading />) : (() => {
            const current = runs.find((run) => run.matches_current_config);
            const passed = current?.result_pack?.promotion_eligible;
            const tone = !current ? "border-warn/30 bg-warn/5 text-warn" : passed ? "border-ok/30 bg-ok/5 text-ok" : "border-bad/30 bg-bad/5 text-bad";
            return (
              <div className={`rounded-lg border p-4 text-sm ${tone}`}>
                <p className="font-semibold">
                  {!current
                    ? runs.length
                      ? "The deployed configuration has not been evaluated yet."
                      : "No evaluation runs yet."
                    : passed
                      ? "The deployed configuration passed evaluation."
                      : "The deployed configuration was evaluated but did not pass every gate."}
                </p>
                {current && (
                  <p className="mt-1 text-xs text-muted">
                    Run <code className="font-mono">{current.id}</code> on {current.dataset_id} · {formatWhen(current.created_at)}
                    {current.promotion ? ` · release ${current.promotion.decision.toLowerCase()}` : " · no release decision yet"}
                  </p>
                )}
                <Link href="/evaluation-gates" className="mt-2 inline-block text-xs font-semibold text-brand hover:underline">
                  Run history and release decisions in Evaluation Gates →
                </Link>
              </div>
            );
          })()
        )}

        {activeTab === "change-history" && (
          !changes ? (!tabError && <Loading />) : changes.length === 0 ? (
            <p className="py-6 text-xs text-muted">No prompt approvals recorded yet. Evaluation runs and release decisions are in <Link href="/evaluation-gates" className="text-brand hover:underline">Evaluation Gates</Link>.</p>
          ) : (
            <ol className="relative ml-2 space-y-4 border-l border-line pl-5">
              {changes.map((change, index) => {
                return (
                  <li key={`${change.time}-${index}`} className="relative">
                    <span className="absolute -left-[25px] top-1.5 h-2 w-2 rounded-full bg-brand" aria-hidden />
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone="ok">Prompt approved</Pill>
                      <span className="text-[11px] text-muted">{formatWhen(change.time)}</span>
                    </div>
                    <p className="mt-1 text-sm text-ink">{change.summary}</p>
                    {change.actor && <p className="text-[11px] text-muted">by {change.actor}</p>}
                  </li>
                );
              })}
            </ol>
          )
        )}
      </div>
    </PageShell>
  );
}

"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { PageShell } from "@/components/governance/PageShell";
import { PanelHeader, PANEL_CLASS } from "@/components/governance/PanelHeader";
import { LiveSourceStatus } from "@/components/governance/LiveSourceStatus";
import { Pill } from "@/components/governance/Pill";
import { errorMessage, formatCount, formatWhen } from "@/components/governance/LiveStatus";
import {
  Scale,
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  Loader2,
  FileText,
  Terminal,
  GitBranch,
  BellRing,
  FlaskConical,
} from "lucide-react";
import { getPolicyView, getTemplates, type PolicyView } from "@/lib/safety-api";
import { Tabs } from "@/components/shell/Tabs";
import { useTabParam } from "@/components/shell/useTabParam";
import { ProfessionalBoundariesPanel } from "@/components/ai-governance/ProfessionalBoundariesPanel";

type Template = { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null };

// Definitions are the ZL-T0-04 §3 policy text; the counts, SLAs and routing
// beside them come from the backend.
const RISK_TAXONOMY = [
  {
    level: "LOW",
    icon: ShieldCheck,
    definition: "Informational, navigational, or learning material with no regulated judgment.",
    examples: "UI help, glossary explanation, general concept overview.",
    bg: "bg-ok/5 border-ok/20 text-ok",
  },
  {
    level: "MEDIUM",
    icon: Scale,
    definition: "Technical context exists but answer is educational, non-client-specific, or workflow-oriented.",
    examples: "Worked learning example, generic journal entry explanation.",
    bg: "bg-info/5 border-info/20 text-info",
  },
  {
    level: "HIGH",
    icon: ShieldAlert,
    definition: "Answer may affect accounting treatment, tax outcome, audit judgment, or business decision.",
    examples: "Revenue recognition, payroll filing deadline, lease classification.",
    bg: "bg-warn/5 border-warn/20 text-warn",
  },
  {
    level: "RESTRICTED",
    icon: ShieldOff,
    definition: "System must not provide a definitive answer without routing through sub-class controls.",
    examples: "Academic integrity, insufficient context advice, prohibited source use, control bypass.",
    bg: "bg-bad/5 border-bad/20 text-bad",
  },
];

const CONFIDENCE_COLUMNS = [
  { key: "HIGH_CONFIDENCE", label: "Strong sources" },
  { key: "LOW_CONFIDENCE", label: "Weak sources" },
  { key: "NO_ELIGIBLE_SOURCE", label: "No source" },
];

const ROUTE_TONE: Record<string, "ok" | "warn" | "bad" | "info"> = {
  LLM: "ok",
  CLARIFICATION: "info",
  HUMAN_REVIEW: "warn",
  REFUSAL: "bad",
  SECURITY_INCIDENT: "bad",
  LICENSE_PATH: "warn",
};

const PANEL = `${PANEL_CLASS} space-y-4`;

function routeLabel(route: string): string {
  return route === "LLM" ? "Answer" : route.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

const TABS = [
  { label: "Classification", slug: "classification" },
  // Was the separate Professional Boundaries page.
  { label: "Professional boundaries", slug: "boundaries" },
];
const TAB_SLUGS = TABS.map((t) => t.slug);

export default function RiskPolicyPage() {
  return (
    <Suspense fallback={null}>
      <RiskPolicy />
    </Suspense>
  );
}

function RiskPolicy() {
  const [activeTab, setActiveTab] = useTabParam("classification", TAB_SLUGS);
  return (
    <PageShell
      title="Risk Policy"
      subtitle="Risk taxonomy and classification on the way in; professional boundaries on every answer on the way out."
      showMetrics={false}
    >
      <div className="mb-4"><Tabs tabs={TABS} activeSlug={activeTab} onChange={setActiveTab} /></div>
      {activeTab === "boundaries" ? <ProfessionalBoundariesPanel /> : <ClassificationPolicy />}
    </PageShell>
  );
}

function ClassificationPolicy() {
  const [view, setView] = useState<PolicyView | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextView, nextTemplates] = await Promise.all([getPolicyView(), getTemplates()]);
      setView(nextView);
      setTemplates(nextTemplates);
      setError("");
    } catch (err) {
      setError(errorMessage(err, "the risk policy"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  const policy = view?.policy;

  return (
    <>

      <LiveSourceStatus loading={loading} error={error} signedOut={false} reload={load} />

      <div className="space-y-6">

      {/* ── Active policy record ─────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[
          { label: "Policy", value: policy ? `${policy.id}` : view ? "None recorded" : "—" },
          { label: "Version", value: policy?.version ?? "—" },
          { label: "Owner", value: policy?.owner ?? "—" },
          { label: "Approver", value: policy?.approver ?? "—" },
          { label: "Effective from", value: formatWhen(policy?.effective_from) },
          { label: "Classifier / matrix", value: view ? `${view.classifier_version} · ${view.routing_matrix_version}` : "—" },
        ].map((item) => (
          <div key={item.label} className="rounded-xl border border-line bg-panel/80 p-4">
            <div className="text-[10px] font-bold uppercase tracking-wider text-muted">{item.label}</div>
            <div className="mt-1.5 break-words text-xs font-semibold text-ink">{item.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-8 space-y-6">
          {/* Taxonomy with live counts */}
          <div className={PANEL}>
            <PanelHeader
              icon={Scale}
              title="Risk Taxonomy (ZL-T0-04 §3)"
              subtitle={view ? `Queries per level in the last ${view.risk_level_window_days} days, open review cases and review SLA` : "Loading live counts…"}
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {RISK_TAXONOMY.map((r) => {
                const Icon = r.icon;
                const count = view?.risk_levels[r.level] ?? 0;
                const open = view?.open_cases_by_risk[r.level] ?? 0;
                const sla = view?.sla_hours[r.level];
                return (
                  <div key={r.level} className={`rounded-xl border p-4 space-y-2.5 ${r.bg}`}>
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Icon size={16} />
                        <span className="text-xs font-extrabold uppercase tracking-wide">{r.level} Risk</span>
                      </div>
                      <span className="text-lg font-extrabold">{view ? formatCount(count) : "—"}</span>
                    </div>
                    <p className="text-xs text-ink leading-relaxed font-semibold">{r.definition}</p>
                    <p className="text-[10px] text-muted leading-relaxed italic"><span className="font-bold not-italic">Examples:</span> {r.examples}</p>
                    <div className="flex flex-wrap gap-1.5 border-t border-line/30 pt-2">
                      <Pill tone={open ? "warn" : "neutral"}>{formatCount(open)} open review cases</Pill>
                      <Pill>{sla ? `Review SLA ${sla}h` : "No review SLA"}</Pill>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Routing matrix — what the classifier does per risk × source strength */}
          <div className={PANEL}>
            <PanelHeader
              icon={GitBranch}
              title="Routing Matrix"
              subtitle={view ? `routing_matrix.py ${view.routing_matrix_version} — decided after retrieval, per risk level and source strength` : undefined}
            />
            {!view ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                      <th className="font-bold pb-2.5 pr-3">Risk level</th>
                      {CONFIDENCE_COLUMNS.map((column) => (
                        <th key={column.key} className="font-bold pb-2.5 pr-3">{column.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {Object.entries(view.routing_matrix).map(([level, row]) => (
                      <tr key={level}>
                        <td className="py-3 pr-3 font-bold text-ink">{level}</td>
                        {CONFIDENCE_COLUMNS.map((column) => {
                          const rule = row[column.key];
                          if (!rule) return <td key={column.key} className="py-3 pr-3 text-muted">—</td>;
                          const needs = [
                            rule.requires_sources && "sources",
                            rule.requires_citation && "citations",
                            rule.requires_professional_boundary && "boundary notice",
                          ].filter(Boolean);
                          return (
                            <td key={column.key} className="py-3 pr-3 align-top">
                              <Pill tone={ROUTE_TONE[rule.route] ?? "neutral"}>{routeLabel(rule.route)}</Pill>
                              {needs.length > 0 && <div className="mt-1 text-[10px] text-muted">Needs {needs.join(", ")}</div>}
                              {rule.limitation && <div className="mt-0.5 text-[10px] italic text-muted">{rule.limitation}</div>}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                    <tr>
                      <td className="py-3 pr-3 font-bold text-ink">RESTRICTED</td>
                      <td colSpan={3} className="py-3 pr-3 text-[11px] text-muted">
                        Never answered directly — routed by sub-class before retrieval (see right).
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Policy rule patterns + escalation rules */}
          <div className={PANEL}>
            <PanelHeader icon={Terminal} title="Classification Rules" subtitle={policy ? `Keyword rules in ${policy.id} ${policy.version}` : undefined} />
            {!view ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : !policy || policy.rules.length === 0 ? (
              <p className="text-xs text-muted">No keyword rules are recorded on the active policy.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                    <th className="font-bold pb-2.5">Pattern</th>
                    <th className="font-bold pb-2.5 w-32">Risk level</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/40">
                  {policy.rules.map((rule) => (
                    <tr key={`${rule.pattern}-${rule.risk}`}>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-ink">{rule.pattern}</td>
                      <td className="py-2.5">
                        <Pill tone={rule.risk === "RESTRICTED" ? "bad" : rule.risk === "HIGH" ? "warn" : "info"}>{rule.risk}</Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line/50 pt-3">
              <p className="text-[11px] text-muted">Changing a rule needs a regression run before release.</p>
              <Link
                href="/evaluation-gates"
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-[11px] font-bold text-ink shadow-sm hover:bg-soft"
              >
                <FlaskConical size={12} /> Run regression in Evaluation Gates
              </Link>
            </div>
          </div>

          <div className={PANEL}>
            <PanelHeader icon={BellRing} tone="warn" title="Escalation Rules" subtitle="Who reviews what, how fast, and how they are notified" />
            {!view ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : view.escalation_rules.length === 0 ? (
              <p className="text-xs text-muted">No escalation rules are configured.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                      <th className="font-bold pb-2.5 pr-3">Trigger</th>
                      <th className="font-bold pb-2.5 pr-3">Reviewer</th>
                      <th className="font-bold pb-2.5 pr-3">SLA</th>
                      <th className="font-bold pb-2.5 pr-3">Severity</th>
                      <th className="font-bold pb-2.5">Notify via</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {view.escalation_rules.map((rule) => (
                      <tr key={rule.id}>
                        <td className="py-2.5 pr-3 font-semibold text-ink">{rule.trigger_condition}</td>
                        <td className="py-2.5 pr-3 text-ink">{rule.reviewer_role}</td>
                        <td className="py-2.5 pr-3 font-mono text-ink">{rule.sla_hours}h</td>
                        <td className="py-2.5 pr-3">
                          <Pill tone={rule.severity === "Critical" ? "bad" : rule.severity === "High" ? "warn" : "info"}>{rule.severity}</Pill>
                        </td>
                        <td className="py-2.5 text-muted">{rule.notification_path}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-4 space-y-6">
          {/* RESTRICTED sub-classes, as routed by the classifier */}
          <div className={PANEL}>
            <PanelHeader icon={ShieldOff} tone="bad" title="RESTRICTED Sub-Classes (ZL-T0-04 §4)" subtitle="Route, reviewer and trigger patterns from the classifier" />
            {!view ? (
              <div className="flex items-center justify-center py-8 text-muted"><Loader2 className="animate-spin" size={16} /></div>
            ) : (
              <div className="space-y-3">
                {view.restricted_subclasses.map((sc) => (
                  <div key={sc.code} className="rounded-xl border border-bad/20 bg-bad/5 p-4 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-ink">{sc.code.replace("RESTRICTED_", "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</span>
                      <Pill tone={sc.clarification_permitted ? "warn" : "bad"}>
                        {sc.clarification_permitted ? "Reclassifiable" : "Hard block"}
                      </Pill>
                    </div>
                    <p className="text-[11px] text-muted leading-relaxed">{sc.description}</p>
                    <div className="flex flex-wrap gap-1.5">
                      <Pill tone={ROUTE_TONE[sc.route] ?? "neutral"}>{routeLabel(sc.route)}</Pill>
                      {sc.reviewer_role && <Pill>{sc.reviewer_role}</Pill>}
                      <Pill tone={sc.blocked_count ? "bad" : "neutral"}>{formatCount(sc.blocked_count)} blocked</Pill>
                    </div>
                    {sc.patterns.length > 0 && (
                      <details className="text-[10px] text-muted">
                        <summary className="cursor-pointer font-semibold">Trigger patterns ({sc.patterns.length})</summary>
                        <ul className="mt-1 space-y-1">
                          {sc.patterns.map((pattern) => (
                            <li key={pattern} className="break-all rounded border border-line/45 bg-panel/60 px-1.5 py-0.5 font-mono">{pattern}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                    <p className="text-[9px] text-muted font-mono">{sc.code}{sc.refusal_templates.length ? ` · ${sc.refusal_templates.join(", ")}` : ""}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Refusal Template Registry */}
          <div className={PANEL}>
            <PanelHeader icon={FileText} title="Refusal Template Registry (ZL-T0-04 §9)" subtitle={templates.length ? `${templates.length} templates in use` : undefined} />
            {loading && templates.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-muted">
                <Loader2 className="animate-spin mb-1" size={16} />
                <span className="text-xs">Fetching template registry...</span>
              </div>
            ) : templates.length === 0 ? (
              <p className="text-xs text-muted">No refusal templates returned.</p>
            ) : (
              <div className="space-y-3 max-h-[450px] overflow-y-auto pr-1">
                {templates.map((tpl) => (
                  <div key={tpl.template_id} className="rounded-xl border border-line/60 bg-soft/30 p-4 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-ink">{tpl.title}</span>
                      <span className="text-[9px] text-muted font-mono">{tpl.template_id}</span>
                    </div>
                    <p className="text-[11px] text-muted leading-relaxed">{tpl.body}</p>
                    {tpl.safe_alternative && (
                      <div className="text-[10px] text-ok border-t border-line/30 pt-1.5 mt-1.5">
                        <span className="font-bold uppercase tracking-wider">Alternative:</span> {tpl.safe_alternative}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      </div>
    </>
  );
}

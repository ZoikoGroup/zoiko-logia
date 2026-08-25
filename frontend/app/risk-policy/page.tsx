"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import {
  Scale,
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  AlertTriangle,
  Loader2,
  FileText,
  Terminal,
} from "lucide-react";
import { getTemplates } from "@/lib/safety-api";

const RISK_TAXONOMY = [
  {
    level: "LOW",
    tone: "ok" as const,
    icon: ShieldCheck,
    definition: "Informational, navigational, or learning material with no regulated judgment.",
    behavior: "Proceed with ordinary source grounding, boundary language where relevant.",
    examples: "UI help, glossary explanation, general concept overview.",
    bg: "bg-ok/5 border-ok/20 text-ok hover:shadow-ok/5",
  },
  {
    level: "MEDIUM",
    tone: "info" as const,
    icon: Scale,
    definition: "Technical context exists but answer is educational, non-client-specific, or workflow-oriented.",
    behavior: "Requires source bundle; limitation language required.",
    examples: "Worked learning example, generic journal entry explanation.",
    bg: "bg-info/5 border-info/20 text-info hover:shadow-info/5",
  },
  {
    level: "HIGH",
    tone: "warn" as const,
    icon: ShieldAlert,
    definition: "Answer may affect accounting treatment, tax outcome, audit judgment, or business decision.",
    behavior: "Requires high-confidence sources, jurisdiction scope, citations, and possible human review.",
    examples: "Revenue recognition, payroll filing deadline, lease classification.",
    bg: "bg-warn/5 border-warn/20 text-warn hover:shadow-warn/5",
  },
  {
    level: "RESTRICTED",
    tone: "bad" as const,
    icon: ShieldOff,
    definition: "System must not provide a definitive answer without routing through sub-class controls.",
    behavior: "Route per RESTRICTED sub-class — never provide restricted output directly.",
    examples: "Academic integrity, insufficient context advice, prohibited source use, control bypass.",
    bg: "bg-bad/5 border-bad/20 text-bad hover:shadow-bad/5",
  },
];

const RESTRICTED_SUBCLASSES = [
  {
    code: "RESTRICTED_ACADEMIC_INTEGRITY",
    title: "Academic Integrity",
    route: "Always block — offer concept explanation or study guidance.",
    reclassifiable: false,
  },
  {
    code: "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT",
    title: "Advice — Insufficient Context",
    route: "Ask targeted clarifying questions. If context becomes sufficient, reclassify as HIGH.",
    reclassifiable: true,
  },
  {
    code: "RESTRICTED_SOURCE_PROHIBITED",
    title: "Source Prohibited",
    route: "Route to license conflict path: metadata-only, internal summary, or human review.",
    reclassifiable: false,
  },
  {
    code: "RESTRICTED_CONTROL_BYPASS",
    title: "Control Bypass",
    route: "Security incident route. Log as safety event. Do not reveal detection details.",
    reclassifiable: false,
  },
];

const CLASSIFICATION_RULES = [
  { pattern: "Tax advice / filing request", risk: "HIGH", action: "→ Restricted when user-specific filing action requested" },
  { pattern: "Audit opinion / going concern", risk: "HIGH → RESTRICTED", action: "Route Audit Lead + Legal/Compliance" },
  { pattern: "No-source technical answer", risk: "HIGH", action: "Clarify / refuse / escalate — never guess" },
  { pattern: "Prompt injection / jailbreak", risk: "RESTRICTED", action: "→ SECURITY_INCIDENT, block & log" },
  { pattern: "Live exam / assessment", risk: "RESTRICTED", action: "→ Academic integrity block, no clarification path" },
  { pattern: "Personalized advice without context", risk: "RESTRICTED", action: "→ Clarification; reclassify when context provided" },
];

export default function RiskPolicyPage() {
  const [templates, setTemplates] = useState<
    { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
  >([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);

  useEffect(() => {
    getTemplates().then((data) => {
      setTemplates(data);
      setLoadingTemplates(false);
    });
  }, []);

  return (
    <main className="flex-1 overflow-y-auto p-6 space-y-6">
      <PageHeader
        title="Risk Policy"
        subtitle="Risk taxonomy, classification rules, restricted sub-classes, and refusal template registry."
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start max-w-7xl">
        {/* ── Risk Taxonomy & Rules ────────────────────────────────────── */}
        <div className="lg:col-span-8 space-y-6">
          {/* Taxonomy Grid */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center justify-between border-b border-line/50 pb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                  <Scale size={14} className="text-brand" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-ink">Risk Taxonomy Hierarchy (ZL-T0-04 §3)</h3>
                  <p className="text-[11px] text-muted">Active policy standard — v2026.07.07</p>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {RISK_TAXONOMY.map((r) => {
                const Icon = r.icon;
                return (
                  <div
                    key={r.level}
                    className={`rounded-xl border p-4.5 space-y-2.5 transition-all duration-300 hover:shadow-lg ${r.bg}`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon size={16} />
                      <span className="text-xs font-extrabold uppercase tracking-wide">{r.level} Risk</span>
                    </div>
                    <p className="text-xs text-ink leading-relaxed font-semibold">{r.definition}</p>
                    <div className="border-t border-line/30 pt-2 space-y-1">
                      <p className="text-[10px] text-muted leading-relaxed"><span className="font-bold">Protocol:</span> {r.behavior}</p>
                      <p className="text-[10px] text-muted leading-relaxed italic"><span className="font-bold">Examples:</span> {r.examples}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Classification Rules Matrix */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                <Terminal size={14} className="text-brand" />
              </div>
              <h3 className="text-sm font-bold text-ink">Governance Resolution Matrix</h3>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50 pb-2">
                    <th className="font-bold pb-2.5 w-60">Pattern Template</th>
                    <th className="font-bold pb-2.5 w-36">Risk Level</th>
                    <th className="font-bold pb-2.5">Routing Decision</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/40">
                  {CLASSIFICATION_RULES.map((rule) => (
                    <tr key={rule.pattern} className="hover:bg-soft/10 transition-colors">
                      <td className="py-3 font-semibold text-ink">{rule.pattern}</td>
                      <td className="py-3">
                        <Pill
                          tone={
                            rule.risk.includes("RESTRICTED")
                              ? "bad"
                              : rule.risk.includes("HIGH")
                                ? "warn"
                                : "info"
                          }
                        >
                          {rule.risk}
                        </Pill>
                      </td>
                      <td className="py-3 text-muted leading-relaxed font-medium">{rule.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap gap-2 pt-2 border-t border-line/50">
              <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[10px] font-bold text-ink hover:bg-soft transition-colors cursor-pointer shadow-sm">
                Run Regression Pack
              </button>
              <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[10px] font-bold text-ink hover:bg-soft transition-colors cursor-pointer shadow-sm">
                Preview Policy Impact
              </button>
              <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[10px] font-bold text-ink hover:bg-soft transition-colors cursor-pointer shadow-sm">
                Request Auth Sign-off
              </button>
            </div>
          </div>
        </div>

        {/* ── RESTRICTED Sub-Classes & Templates ───────────────────────── */}
        <div className="lg:col-span-4 space-y-6">
          {/* Sub-classes */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-bad/10 border border-bad/20">
                <ShieldOff size={14} className="text-bad" />
              </div>
              <h3 className="text-sm font-bold text-ink">RESTRICTED Sub-Classes (ZL-T0-04 §4)</h3>
            </div>

            <div className="space-y-3">
              {RESTRICTED_SUBCLASSES.map((sc) => (
                <div
                  key={sc.code}
                  className="rounded-xl border border-bad/20 bg-bad/5 p-4 space-y-2 hover:shadow-md transition-all duration-200"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-ink">{sc.title}</span>
                    <Pill tone={sc.reclassifiable ? "warn" : "bad"}>
                      {sc.reclassifiable ? "Reclassifiable" : "Hard Block"}
                    </Pill>
                  </div>
                  <p className="text-[11px] text-muted leading-relaxed">{sc.route}</p>
                  <p className="text-[9px] text-muted font-mono bg-panel/60 border border-line/45 px-1.5 py-0.5 rounded w-fit">{sc.code}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Refusal Template Registry */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                <FileText size={14} className="text-brand" />
              </div>
              <h3 className="text-sm font-bold text-ink">Refusal Template Registry (ZL-T0-04 §9)</h3>
            </div>

            {loadingTemplates ? (
              <div className="flex flex-col items-center justify-center py-10 text-muted">
                <Loader2 className="animate-spin mb-1" size={16} />
                <span className="text-xs">Fetching template registry...</span>
              </div>
            ) : (
              <div className="space-y-3 max-h-[450px] overflow-y-auto pr-1">
                {templates.map((tpl) => (
                  <div
                    key={tpl.template_id}
                    className="rounded-xl border border-line/60 bg-soft/30 p-4 space-y-2 transition-all duration-200 hover:bg-panel hover:shadow-md"
                  >
                    <div className="flex items-center justify-between">
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
    </main>
  );
}

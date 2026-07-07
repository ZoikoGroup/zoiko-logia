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
  FileText,
  AlertTriangle,
  CheckSquare,
  Loader2,
  ChevronDown,
} from "lucide-react";
import { getTemplates } from "@/lib/safety-api";

/* ── Risk taxonomy data (mirrors ZL-T0-04 §3) ───────────────────────────── */

const RISK_TAXONOMY = [
  {
    level: "LOW",
    tone: "ok" as const,
    icon: ShieldCheck,
    definition: "Informational, navigational, or learning material with no regulated judgment.",
    behavior: "Proceed with ordinary source grounding, boundary language where relevant.",
    examples: "UI help, glossary explanation, general concept overview.",
  },
  {
    level: "MEDIUM",
    tone: "info" as const,
    icon: Scale,
    definition: "Technical context exists but answer is educational, non-client-specific, or workflow-oriented.",
    behavior: "Requires source bundle; limitation language required.",
    examples: "Worked learning example, generic journal entry explanation.",
  },
  {
    level: "HIGH",
    tone: "warn" as const,
    icon: ShieldAlert,
    definition: "Answer may affect accounting treatment, tax outcome, audit judgment, or business decision.",
    behavior: "Requires high-confidence sources, jurisdiction scope, citations, and possible human review.",
    examples: "Revenue recognition, payroll filing deadline, lease classification.",
  },
  {
    level: "RESTRICTED",
    tone: "bad" as const,
    icon: ShieldOff,
    definition: "System must not provide a definitive answer without routing through sub-class controls.",
    behavior: "Route per RESTRICTED sub-class — never provide restricted output directly.",
    examples: "Academic integrity, insufficient context advice, prohibited source use, control bypass.",
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
  const [expandedSection, setExpandedSection] = useState<string>("taxonomy");

  useEffect(() => {
    getTemplates().then((data) => {
      setTemplates(data);
      setLoadingTemplates(false);
    });
  }, []);

  function toggle(section: string) {
    setExpandedSection((prev) => (prev === section ? "" : section));
  }

  return (
    <main className="flex-1 overflow-y-auto p-4 pt-0">
      <PageHeader
        title="Risk Policy"
        subtitle="Risk taxonomy, classification rules, restricted sub-classes, and refusal template registry."
      />

      <div className="space-y-6 max-w-5xl">
        {/* ── Risk Taxonomy ───────────────────────────────────────────── */}
        <Card
          title="Risk Taxonomy (ZL-T0-04 §3)"
          action={<Pill tone="ok">Active — v2026.07.07</Pill>}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {RISK_TAXONOMY.map((r) => {
              const Icon = r.icon;
              return (
                <div
                  key={r.level}
                  className={`rounded-xl border p-4 space-y-2 ${
                    r.tone === "ok"
                      ? "border-ok/30 bg-ok/5"
                      : r.tone === "info"
                        ? "border-info/30 bg-info/5"
                        : r.tone === "warn"
                          ? "border-warn/30 bg-warn/5"
                          : "border-bad/30 bg-bad/5"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Icon size={16} className={`text-${r.tone}`} />
                    <span className={`text-sm font-bold text-${r.tone}`}>{r.level}</span>
                  </div>
                  <p className="text-xs text-ink leading-relaxed">{r.definition}</p>
                  <p className="text-[11px] text-muted">{r.behavior}</p>
                  <p className="text-[11px] text-muted italic">e.g. {r.examples}</p>
                </div>
              );
            })}
          </div>
        </Card>

        {/* ── Classification Rules ────────────────────────────────────── */}
        <Card
          title="Classification Rules"
          action={<Pill tone="warn">Draft v2026.07.07</Pill>}
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-muted">
                <th className="font-medium pb-2 w-56">Pattern</th>
                <th className="font-medium pb-2 w-36">Risk Level</th>
                <th className="font-medium pb-2">Routing Action</th>
              </tr>
            </thead>
            <tbody>
              {CLASSIFICATION_RULES.map((rule) => (
                <tr key={rule.pattern} className="border-t border-line first:border-t-0">
                  <td className="py-2.5 font-semibold text-ink align-top">{rule.pattern}</td>
                  <td className="py-2.5 align-top">
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
                  <td className="py-2.5 text-muted align-top">{rule.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
              Run regression pack
            </button>
            <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
              Preview impact
            </button>
            <button className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
              Request approver
            </button>
          </div>
        </Card>

        {/* ── RESTRICTED Sub-Classes ──────────────────────────────────── */}
        <Card title="RESTRICTED Sub-Classes (ZL-T0-04 §4)">
          <div className="space-y-3">
            {RESTRICTED_SUBCLASSES.map((sc) => (
              <div
                key={sc.code}
                className="rounded-xl border border-bad/20 bg-bad/5 p-3.5 space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-ink">{sc.title}</span>
                  <Pill tone={sc.reclassifiable ? "warn" : "bad"}>
                    {sc.reclassifiable ? "Can reclassify" : "Hard block"}
                  </Pill>
                </div>
                <p className="text-xs text-muted">{sc.route}</p>
                <p className="text-[10px] text-muted font-mono">{sc.code}</p>
              </div>
            ))}
          </div>
        </Card>

        {/* ── Refusal Template Registry ───────────────────────────────── */}
        <Card title="Refusal Template Registry (ZL-T0-04 §9)">
          {loadingTemplates ? (
            <div className="flex items-center justify-center py-8 text-muted">
              <Loader2 className="animate-spin mr-2" size={16} /> Loading templates…
            </div>
          ) : (
            <div className="space-y-3">
              {templates.map((tpl) => (
                <div
                  key={tpl.template_id}
                  className="rounded-xl border border-line bg-soft p-3.5 space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-ink">{tpl.title}</span>
                    <span className="text-[10px] text-muted font-mono">{tpl.template_id}</span>
                  </div>
                  <p className="text-xs text-ink leading-relaxed">{tpl.body}</p>
                  {tpl.safe_alternative && (
                    <p className="text-xs text-ok">
                      <span className="font-semibold">Safe alternative:</span> {tpl.safe_alternative}
                    </p>
                  )}
                  {tpl.restricted_sub_class && (
                    <Pill tone="bad">{tpl.restricted_sub_class.replace("RESTRICTED_", "")}</Pill>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}

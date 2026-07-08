"use client";

import { useState } from "react";
import { PageHeader } from "@/components/governance/PageHeader";
import { Card } from "@/components/governance/Card";
import { Pill } from "@/components/governance/Pill";
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Send,
  BookOpen,
  ListChecks,
  Scale,
  Info,
} from "lucide-react";
import { validateOutput } from "@/lib/safety-api";

// ─── Spec-defined Prohibited Output Rules (ZL-T0-11 §7.1) ────────────────────

const PROHIBITED_RULES: {
  id: string;
  category: string;
  rule: string;
  severity: "HARD_BLOCK" | "SOFT_BLOCK";
  example: string;
}[] = [
  {
    id: "PB-01",
    category: "Professional Opinion",
    rule: "May not issue definitive professional opinions (tax, legal, audit) without qualified professional sign-off.",
    severity: "HARD_BLOCK",
    example: "\"You should file under IFRS 16\" → blocked; replace with limitation notice.",
  },
  {
    id: "PB-02",
    category: "Specific Advice",
    rule: "May not give user-specific actionable advice on regulated filings or transactions.",
    severity: "HARD_BLOCK",
    example: "\"Your company should record this as a finance lease\" → blocked.",
  },
  {
    id: "PB-03",
    category: "Certainty Language",
    rule: "Must not use certainty language ('will', 'must', 'you must do') in regulated-outcome contexts.",
    severity: "HARD_BLOCK",
    example: "\"You must report this income\" → converted to \"regulations require disclosure…\".",
  },
  {
    id: "PB-04",
    category: "Exam / Assessment Answers",
    rule: "Must not provide direct answers to exam questions, assessments, or academic submissions.",
    severity: "HARD_BLOCK",
    example: "\"Here is the answer to question 3\" → refused.",
  },
  {
    id: "PB-05",
    category: "Prohibited Source Content",
    rule: "Must not reproduce content from sources where license restrictions prohibit reproduction.",
    severity: "HARD_BLOCK",
    example: "Reproducing locked ICAEW study text verbatim → refused.",
  },
  {
    id: "PB-06",
    category: "PII / Sensitive Data",
    rule: "Must never include personal identifiable information in outputs unless it was in the original query scope.",
    severity: "HARD_BLOCK",
    example: "Leaking another user's data in response → security incident.",
  },
  {
    id: "PB-07",
    category: "Over-confidence",
    rule: "Should avoid overconfident statements on evolving tax rates, budgets, or jurisdiction-specific rules.",
    severity: "SOFT_BLOCK",
    example: "\"The VAT rate is 20%\" → append \"as of [date]; verify against current HMRC guidance\".",
  },
  {
    id: "PB-08",
    category: "Audit Opinion Wording",
    rule: "Must not draft or imply going concern conclusions, qualified opinions, or audit sign-off language.",
    severity: "HARD_BLOCK",
    example: "\"Based on these ratios, there is no going concern risk\" → refused; route Audit Lead.",
  },
];

// ─── Spec-defined Sufficient-Context Checklist (ZL-T0-11 §7.2) ───────────────

const CONTEXT_CHECKLIST = [
  {
    id: "CTX-1",
    condition: "Jurisdiction identified",
    detail: "At least one jurisdiction is present (UK, US, IFRS, UAE, India, EU…). Without it, treat as RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT.",
    required: true,
  },
  {
    id: "CTX-2",
    condition: "Entity type known",
    detail: "Query scope includes entity type (sole trader, partnership, listed company, etc.) for entity-specific standards.",
    required: true,
  },
  {
    id: "CTX-3",
    condition: "Applicable framework confirmed",
    detail: "Accounting or regulatory framework is specified or inferable (IFRS, UK GAAP, US GAAP, local tax code).",
    required: true,
  },
  {
    id: "CTX-4",
    condition: "Source bundle available",
    detail: "At least one non-expired, licensed source exists for the topic. Without a source, refuse with source-limitation notice.",
    required: true,
  },
];

// ─── Sample Queries for Demo ──────────────────────────────────────────────────

const SAMPLE_DRAFTS = [
  {
    label: "Safe: Educational explanation",
    text: "IFRS 16 requires lessees to recognise a right-of-use asset and a corresponding lease liability at the commencement date of the lease. This applies to most leases with a term of more than 12 months. For specific application to your situation, please consult a qualified accountant.",
  },
  {
    label: "Violation: Direct tax advice",
    text: "You must file your tax return under the self-assessment scheme. Since your income is above £100,000 your personal allowance is withdrawn and you will owe additional tax. I recommend filing immediately to avoid penalties.",
  },
  {
    label: "Violation: Audit opinion wording",
    text: "Based on the ratios you've provided, there is no going concern risk and the auditors will likely issue an unqualified opinion for the annual report.",
  },
  {
    label: "Violation: Academic answer",
    text: "Here is the complete answer to exam question 3: The correct journal entry is Dr. Lease Liability £50,000 Cr. Cash £50,000.",
  },
];

// ─── Severity badge ───────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Pill tone={severity === "HARD_BLOCK" ? "bad" : "warn"}>
      {severity === "HARD_BLOCK" ? "Hard Block" : "Soft Block"}
    </Pill>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ProfessionalBoundariesPage() {
  const [draftText, setDraftText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    is_safe: boolean;
    violations: { phrase: string; category: string; severity: string }[];
    cleaned_text: string;
  } | null>(null);
  const [usingFallback, setUsingFallback] = useState(false);

  async function handleValidate() {
    if (!draftText.trim()) return;
    setLoading(true);
    setResult(null);
    setUsingFallback(false);

    const res = await validateOutput(draftText);

    // If backend is unreachable, the API client returns { is_safe: true, violations: [], cleaned_text }
    // We detect that by checking if the response is identical to the no-op fallback
    // We run a local heuristic scan on top to make the demo useful without backend
    const localViolations: { phrase: string; category: string; severity: string }[] = [];
    const HARD_PATTERNS = [
      { re: /\b(you must|you should|you will|must file|should file|should record|should recognize)\b/i, cat: "Certainty Language", sev: "HARD_BLOCK" },
      { re: /\b(going concern|unqualified opinion|no going concern risk|auditors will)\b/i, cat: "Audit Opinion Wording", sev: "HARD_BLOCK" },
      { re: /\b(exam question|correct journal entry|here is the answer|complete answer to)\b/i, cat: "Exam Answer", sev: "HARD_BLOCK" },
      { re: /\b(i recommend|we recommend|my advice is|my recommendation)\b/i, cat: "Specific Advice", sev: "HARD_BLOCK" },
    ];
    const SOFT_PATTERNS = [
      { re: /\b(the (vat|tax|rate) is \d+%)\b/i, cat: "Over-confidence", sev: "SOFT_BLOCK" },
      { re: /\b(definitely|certainly|always)\b/i, cat: "Certainty Language", sev: "SOFT_BLOCK" },
    ];

    for (const p of [...HARD_PATTERNS, ...SOFT_PATTERNS]) {
      const m = draftText.match(p.re);
      if (m) localViolations.push({ phrase: m[0], category: p.cat, severity: p.sev });
    }

    // If backend returned data, use it; else use local heuristics
    if (res.violations.length > 0 || res.is_safe === false) {
      setResult(res);
    } else if (localViolations.length > 0) {
      setUsingFallback(true);
      const cleanedText =
        draftText +
        "\n\n⚠️ Professional Boundary Notice: This response has been flagged for review. " +
        "It may contain language that falls outside Kriton™ professional output boundaries. " +
        "Please consult a qualified professional before acting on this information.";
      setResult({
        is_safe: false,
        violations: localViolations,
        cleaned_text: cleanedText,
      });
    } else {
      setUsingFallback(true);
      setResult({ is_safe: true, violations: [], cleaned_text: res.cleaned_text });
    }

    setLoading(false);
  }

  return (
    <main className="flex-1 overflow-y-auto p-6 pt-0 space-y-6">
      <PageHeader
        title="Professional Boundaries"
        subtitle="Rules governing what Kriton™ can and cannot answer without human review — ZL-T0-11 §7. Validate draft LLM outputs against the prohibited output registry."
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start max-w-7xl">

        {/* ── Left Column: Validator Console ─────────────────────────────── */}
        <div className="lg:col-span-8 space-y-6">

          {/* Output Validator */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-5">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-brand/10 border border-brand/20">
                <Shield size={14} className="text-brand" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-ink">Output Boundary Validator (ZL-T0-11 §7)</h3>
                <p className="text-[11px] text-muted">Paste a draft LLM response below and validate it against the professional boundary rules.</p>
              </div>
            </div>

            {/* Sample presets */}
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Load Sample Draft</label>
              <div className="flex flex-wrap gap-2">
                {SAMPLE_DRAFTS.map((s) => (
                  <button
                    key={s.label}
                    onClick={() => { setDraftText(s.text); setResult(null); }}
                    className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[10px] font-semibold text-muted hover:bg-soft hover:text-ink transition-colors cursor-pointer"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Draft Output Text</label>
              <textarea
                id="boundary-draft-input"
                value={draftText}
                onChange={(e) => { setDraftText(e.target.value); setResult(null); }}
                rows={6}
                className="w-full rounded-xl border border-line bg-soft/40 px-4 py-3 text-xs text-ink leading-relaxed focus:outline-none focus:ring-2 focus:ring-brand/40 transition-all resize-none"
                placeholder="Paste the draft LLM response text here to check against professional boundary rules…"
              />
            </div>

            <button
              id="validate-boundary-btn"
              onClick={handleValidate}
              disabled={loading || !draftText.trim()}
              className="flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-xs font-bold text-white shadow-lg shadow-brand/20 hover:bg-brand/90 active:scale-95 transition-all disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              {loading ? "Validating…" : "Validate Against Boundary Rules"}
            </button>

            {usingFallback && result && (
              <div className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-[10px] text-warn">
                <AlertTriangle size={12} />
                Backend unreachable — local heuristic scan applied. Start the FastAPI server for full NLP-level boundary scanning.
              </div>
            )}
          </div>

          {/* Validation Result */}
          {result && (
            <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-5">
              {/* Overall Verdict */}
              <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${
                result.is_safe
                  ? "bg-ok/10 border-ok/30"
                  : "bg-bad/10 border-bad/30"
              }`}>
                {result.is_safe
                  ? <ShieldCheck size={20} className="text-ok" />
                  : <ShieldAlert size={20} className="text-bad" />}
                <div>
                  <div className={`text-sm font-extrabold ${result.is_safe ? "text-ok" : "text-bad"}`}>
                    {result.is_safe ? "Boundary Compliant — Safe to Release" : "Boundary Violations Detected — Review Required"}
                  </div>
                  <div className="text-[10px] text-muted">
                    {result.is_safe
                      ? "No professional boundary violations found. Output meets Kriton™ output standards."
                      : `${result.violations.length} violation(s) detected. This output must not be released without human review.`}
                  </div>
                </div>
              </div>

              {/* Violations Detail */}
              {result.violations.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-xs font-bold text-ink">Detected Violations</h4>
                  <div className="space-y-2">
                    {result.violations.map((v, i) => (
                      <div key={i} className={`rounded-xl border p-3.5 space-y-1 ${
                        v.severity === "HARD_BLOCK"
                          ? "bg-bad/5 border-bad/20"
                          : "bg-warn/5 border-warn/20"
                      }`}>
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-ink">{v.category}</span>
                          <SeverityBadge severity={v.severity} />
                        </div>
                        <p className="text-[11px] text-muted">
                          Triggered phrase: <code className={`font-mono px-1.5 py-0.5 rounded text-[10px] ${
                            v.severity === "HARD_BLOCK"
                              ? "bg-bad/20 text-bad"
                              : "bg-warn/20 text-warn"
                          }`}>{v.phrase}</code>
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Cleaned Output */}
              {result.cleaned_text && result.cleaned_text !== draftText && (
                <div className="space-y-2">
                  <h4 className="text-xs font-bold text-ink flex items-center gap-1.5">
                    <CheckCircle2 size={13} className="text-ok" />
                    Boundary-Safe Output (with notices appended)
                  </h4>
                  <div className="rounded-xl border border-ok/20 bg-ok/5 p-4 text-xs text-ink leading-relaxed whitespace-pre-wrap">
                    {result.cleaned_text}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right Column: Rules Reference ──────────────────────────────── */}
        <div className="lg:col-span-4 space-y-6">

          {/* Sufficient Context Checklist */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center gap-2 border-b border-line/50 pb-4">
              <div className="p-1.5 rounded-lg bg-ok/10 border border-ok/20">
                <ListChecks size={14} className="text-ok" />
              </div>
              <h3 className="text-sm font-bold text-ink">Sufficient Context (ZL-T0-11 §7.2)</h3>
            </div>
            <p className="text-[11px] text-muted">All 4 conditions must be met before Kriton™ can answer a regulated query. Missing conditions route to RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT.</p>
            <div className="space-y-3">
              {CONTEXT_CHECKLIST.map((item) => (
                <div key={item.id} className="rounded-xl border border-ok/20 bg-ok/5 p-3.5 space-y-1 hover:shadow-md transition-all duration-200">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={13} className="text-ok flex-shrink-0" />
                    <span className="text-xs font-bold text-ink">{item.condition}</span>
                  </div>
                  <p className="text-[10px] text-muted leading-relaxed pl-5">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Boundary Info */}
          <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-5 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-3">
            <div className="flex items-center gap-2 border-b border-line/50 pb-3">
              <div className="p-1.5 rounded-lg bg-info/10 border border-info/20">
                <Info size={14} className="text-info" />
              </div>
              <h3 className="text-sm font-bold text-ink">How It Works</h3>
            </div>
            <div className="space-y-2 text-[11px] text-muted leading-relaxed">
              <p>Every LLM response passes through <strong className="text-ink">validate_output()</strong> before delivery.</p>
              <p><strong className="text-bad">HARD_BLOCK</strong> violations prevent the response from being returned — a boundary-safe refusal is delivered instead.</p>
              <p><strong className="text-warn">SOFT_BLOCK</strong> violations append a professional limitation notice to the response and log a safety event.</p>
              <p>All violations are logged to the safety event audit trail and linked to the originating query ID.</p>
            </div>
          </div>

        </div>
      </div>

      {/* ── Full Prohibited Rules Table ──────────────────────────────────── */}
      <div className="rounded-2xl border border-line bg-panel/75 backdrop-blur-md p-6 shadow-[0_12px_30px_rgba(0,0,0,0.02)] space-y-4 max-w-7xl">
        <div className="flex items-center gap-2 border-b border-line/50 pb-4">
          <div className="p-1.5 rounded-lg bg-bad/10 border border-bad/20">
            <BookOpen size={14} className="text-bad" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-ink">Prohibited Output Registry (ZL-T0-11 §7.1)</h3>
            <p className="text-[11px] text-muted">Complete list of hard and soft boundary rules enforced by the professional boundary gate.</p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-line/50">
                <th className="font-bold pb-2.5 w-16">ID</th>
                <th className="font-bold pb-2.5 w-44">Category</th>
                <th className="font-bold pb-2.5">Rule</th>
                <th className="font-bold pb-2.5 w-28">Severity</th>
                <th className="font-bold pb-2.5">Example</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/40">
              {PROHIBITED_RULES.map((rule) => (
                <tr key={rule.id} className={`transition-colors ${rule.severity === "HARD_BLOCK" ? "hover:bg-bad/5" : "hover:bg-warn/5"}`}>
                  <td className="py-3 pr-4">
                    <code className="text-[10px] font-mono text-muted bg-soft/50 border border-line/40 px-1.5 py-0.5 rounded">
                      {rule.id}
                    </code>
                  </td>
                  <td className="py-3 pr-4 font-semibold text-ink">{rule.category}</td>
                  <td className="py-3 pr-4 text-muted leading-relaxed">{rule.rule}</td>
                  <td className="py-3 pr-4">
                    <SeverityBadge severity={rule.severity} />
                  </td>
                  <td className="py-3 text-muted italic leading-relaxed">{rule.example}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}

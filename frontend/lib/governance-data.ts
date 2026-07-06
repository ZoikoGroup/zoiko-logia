export const METRICS = [
  { label: "Active sources", value: "1,284", detail: "37 due for review" },
  { label: "Pending reviews", value: "42", detail: "11 legal/compliance" },
  { label: "Open escalations", value: "14", detail: "3 over SLA" },
  { label: "Source-drift alerts", value: "9", detail: "4 affect production" },
];

export const FOOTER_NOTE =
  "Competitive pattern synthesis: CoCounsel emphasizes trusted/authoritative content, citations, privacy/security and retention controls; Intapp Celeste emphasizes governed agentic AI, ethical walls, MNPI, independence and auditable compliance; Trullion emphasizes auditable AI workflows that trace AI actions back to source data. ZoikoLogia extends this with license-expiry countdowns, jurisdiction rollout readiness, source-drift alerts, and full audit replay.";

export type Escalation = {
  id: string;
  topic: string;
  risk: string;
  jurisdiction: string;
  owner: string;
  sla: string;
  status: string;
  detail: string;
};

export const ESCALATIONS: Escalation[] = [
  {
    id: "ESC-1842",
    topic: "VAT treatment, mixed supply",
    risk: "High",
    jurisdiction: "UK",
    owner: "Tax Lead",
    sla: "2h 14m",
    status: "Source dispute",
    detail: "Citation anchor valid; HMRC source current. User context includes cross-border invoice. Needs tax specialist note before limited answer release.",
  },
  {
    id: "ESC-1910",
    topic: "Going concern wording",
    risk: "Restricted",
    jurisdiction: "IFRS",
    owner: "Audit Lead",
    sla: "39m",
    status: "Legal boundary",
    detail: "Draft answer could imply audit opinion. Restricted output path blocks release until audit lead + legal/compliance reviewer attach decision note.",
  },
  {
    id: "ESC-1944",
    topic: "Payroll termination pay",
    risk: "High",
    jurisdiction: "US-CA",
    owner: "Jurisdiction Expert",
    sla: "Overdue",
    status: "Local SME",
    detail: "Jurisdiction pack coverage below launch threshold. Answer returned with unsupported-jurisdiction limitation and local expert request.",
  },
];

// [jurisdiction, readyPct, tone]
export const ROLLOUT: [string, number, "ok" | "warn" | "bad"][] = [
  ["UK", 92, "ok"],
  ["US-CA", 76, "warn"],
  ["UAE", 54, "bad"],
];

// [source, status, note]; Approved→ok, Pending SME→warn, Drift alert→bad
export const SOURCE_REGISTER: [string, string, string][] = [
  ["FASB ASC", "Approved", "Citation + export allowed"],
  ["AICPA practice aid", "Pending SME", "Display limited"],
  ["Local tax bulletin", "Drift alert", "Effective date changed"],
];

// [gate, status]; Passed→ok, Partial→warn, Pending→neutral
export const LAUNCH_GATES: [string, "Passed" | "Partial" | "Pending"][] = [
  ["Source coverage", "Passed"],
  ["Local SME sign-off", "Passed"],
  ["Risk/privacy review", "Partial"],
  ["Localization QA", "Pending"],
  ["Accessibility pass", "Pending"],
];

export const RISK_RULES: [string, string][] = [
  ["Tax advice request", "High → Restricted when user-specific filing action requested"],
  ["Audit opinion wording", "Restricted; route Audit Lead + Legal"],
  ["No-source technical answer", "Clarify / refuse / escalate; never guess"],
];

export const EVAL_GATES: { label: string; value: string; tone: "ok" | "warn" }[] = [
  { label: "Citation accuracy", value: "98.1%", tone: "ok" },
  { label: "Refusal correctness", value: "94.7%", tone: "warn" },
  { label: "Source conflict handling", value: "91.3%", tone: "warn" },
];
export const EVAL_CAPTION = "Gate requires named QA owner and failure replay before production deploy.";

// [provider, scope, status, restriction]; Active→ok, Conditional→warn, Suspended→bad
export const PROVIDERS: [string, string, string, string][] = [
  ["OpenAI Enterprise", "LLM model routing", "Active", "Zero-retention verified"],
  ["Vector DB EU", "Embeddings storage", "Conditional", "Transfer review due"],
  ["Tax source API", "Source retrieval", "Suspended", "License renewal missing"],
];

// [time, event, description]
export const AUDIT_TIMELINE: [string, string, string][] = [
  ["09:41:10", "Query submitted", "Tenant, role, jurisdiction, framework resolved"],
  ["09:41:12", "Source bundle selected", "IFRS + local tax commentary; one source excluded for license"],
  ["09:41:14", "Risk classified", "High: user-specific tax treatment"],
  ["09:42:03", "Escalated", "Tax Lead route; maker-checker required"],
  ["10:03:55", "Admin action", "Source drift alert linked to source record"],
];

export const ONTOLOGY_CARDS = [
  { heading: "Professional bodies", body: "ACCA, ICAEW, CPA, AICPA mapped to qualification, module, topic and learning outcome." },
  { heading: "Ontology coverage", body: "3,842 nodes; 211 prerequisite gaps; 17 tenant overlays awaiting reviewer approval." },
  { heading: "License-safe use", body: "Protected study content cannot display beyond permitted use; CPD outputs remain audit-linked." },
];

export const LOCALIZATION_CARD = {
  heading: "Localization & accessibility",
  body: "Translation-key UI, terminology review, keyboard focus, screen reader labels, non-color-only status.",
};

// [date, event, category, status]; Upcoming→info, At risk→warn, Overdue→bad
export const COMPLIANCE_CALENDAR: [string, string, string, "Upcoming" | "At risk" | "Overdue"][] = [
  ["Jul 15, 2026", "Quarterly source license renewal review", "Content governance", "Upcoming"],
  ["Aug 1, 2026", "GDPR data processing audit", "Privacy", "Upcoming"],
  ["Aug 20, 2026", "Model card review — Q3", "AI safety", "Upcoming"],
  ["Sep 5, 2026", "SOC 2 Type II renewal", "Compliance", "At risk"],
  ["Sep 30, 2026", "Annual accessibility audit", "Compliance", "Upcoming"],
];

// [model, role, environment, version, status]; Active→ok, Testing→warn, Deprecated→bad
export const MODEL_REGISTRY: [string, string, string, string, "Active" | "Testing" | "Deprecated"][] = [
  ["GPT-4 Turbo", "Primary reasoning model", "Production", "v2026.06", "Active"],
  ["Claude 3.5", "Secondary / fallback model", "Production", "v2026.05", "Active"],
  ["Internal Embedding Model", "Vector search embeddings", "Staging", "v0.9", "Testing"],
];

// [prompt, version, status]; Approved→ok, Pending review→warn
export const PROMPT_REGISTRY: [string, string, "Approved" | "Pending review"][] = [
  ["Policy Q&A v4", "v4.2", "Approved"],
  ["Risk Classification v2", "v2.1", "Pending review"],
  ["Escalation Summarizer", "v1.0", "Approved"],
];

export type Alert = {
  severity: "critical" | "high" | "medium";
  title: string;
  detail: string;
  age: string;
};

export const ALERTS: Alert[] = [
  { severity: "critical", title: "LLM provider outage — failover engaged", detail: "Primary provider unavailable, traffic rerouted", age: "12m ago" },
  { severity: "high", title: "Anomalous query volume from single API key", detail: "300% above baseline in the last hour", age: "52m ago" },
  { severity: "medium", title: "Model latency SLO breach", detail: "p95 response time exceeded threshold", age: "2h ago" },
];

// [id, title, severity, status, opened]; Investigating→warn, Resolved→ok
export const INCIDENTS: [string, string, string, "Investigating" | "Resolved", string][] = [
  ["INC-2311", "Vector index rebuild failure", "Critical", "Investigating", "4h ago"],
  ["INC-2304", "Source drift caused stale citations", "Medium", "Resolved", "1d ago"],
  ["INC-2291", "Unauthorized export attempt blocked", "High", "Resolved", "3d ago"],
];

// [role, description, permissions]
export const ROLES: [string, string, string][] = [
  ["Governance Ops Lead", "Owns day-to-day governance operations", "Full read/write across all modules"],
  ["Source Admin", "Manages source approvals and licensing", "Source licensing, Compliance calendar"],
  ["Syllabus Admin", "Maintains ontology & syllabus content", "Ontology & syllabus"],
  ["Jurisdiction Lead", "Owns jurisdiction rollout readiness", "Jurisdiction rollout"],
  ["Risk Admin", "Owns risk policy and evaluation gates", "Risk policy, Evaluation gates, Model & prompt registry"],
  ["System Auditor", "Read-only access for audit purposes", "Audit replay, Incident response (read-only)"],
];

// [gate, status]; Passed→ok, Partial→warn, Pending→neutral
export const RELEASE_GATES: [string, "Passed" | "Partial" | "Pending"][] = [
  ["Rights & licensing sign-off", "Passed"],
  ["Risk policy approval", "Passed"],
  ["Evaluation gate thresholds met", "Partial"],
  ["Audit event coverage", "Pending"],
  ["Rollback point verified", "Pending"],
];

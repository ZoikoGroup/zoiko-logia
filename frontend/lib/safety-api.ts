/**
 * Safety Service API client for the frontend.
 *
 * Tries the backend at http://localhost:8000. When the backend is
 * unreachable it falls back to a LOCAL classifier that mirrors the
 * rule-based engine — keeping the dashboard fully functional for
 * demo / development without running the Python service.
 */

const BACKEND = "http://localhost:8000/api/v1/safety";

// ─── Types ──────────────────────────────────────────────────────────────────

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "RESTRICTED";

export type SafetyDecision = {
  allowed: boolean;
  risk_level: RiskLevel;
  restricted_sub_class: string | null;
  route: string;
  confidence: number;
  requires_sources: boolean;
  requires_human_review: boolean;
  requires_citation: boolean;
  requires_professional_boundary: boolean;
  limitations: string[];
  refusal_text: string | null;
  safe_alternative: string | null;
  rules_applied: string[];
  query_id: string | null;
};

export type Escalation = {
  id: string;
  query_id: string;
  query_text: string;
  topic: string;
  risk_level: string;
  restricted_sub_class: string | null;
  jurisdiction: string;
  owner: string | null;
  reviewer_role: string | null;
  sla_deadline: string | null;
  status: string;
  route_reason: string | null;
  detail: string | null;
  reviewer_decision: string | null;
  reviewer_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

export type SafetyEvent = {
  id: number;
  event_type: string;
  query_id: string | null;
  payload: Record<string, unknown>;
  timestamp: string | null;
};

// ─── Backend API Calls ──────────────────────────────────────────────────────

async function tryBackend<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

export async function classifyQuery(
  query: string,
  jurisdiction: string = "",
  mode: string = "Workflow",
  source_confidence: string = "HIGH_CONFIDENCE",
  pre_bundle_state: string = "OK",
  privacy_class: string = "NONE",
  tenant_policy_conflict: boolean = false,
  tool_required: boolean = false,
): Promise<SafetyDecision> {
  // Try backend first
  const remote = await tryBackend<SafetyDecision>("/classify", {
    method: "POST",
    body: JSON.stringify({ 
      query, jurisdiction, mode, 
      source_confidence, pre_bundle_state, privacy_class, 
      tenant_policy_conflict, tool_required 
    }),
  });
  if (remote) return remote;

  // Fallback: local classifier
  return localClassify(query, jurisdiction, mode);
}

export async function validateOutput(text: string): Promise<{
  is_safe: boolean;
  violations: { phrase: string; category: string; severity: string }[];
  cleaned_text: string;
}> {
  const remote = await tryBackend<{
    is_safe: boolean;
    violations: { phrase: string; category: string; severity: string }[];
    cleaned_text: string;
  }>("/validate-output", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (remote) return remote;

  // Fallback: no violations
  return { is_safe: true, violations: [], cleaned_text: text };
}

export async function getEscalations(): Promise<Escalation[]> {
  const remote = await tryBackend<Escalation[]>("/escalations");
  if (remote) return remote;

  // Fallback: local mock escalations
  return MOCK_ESCALATIONS;
}

export async function actOnEscalation(
  caseId: string,
  action: string,
  reviewerId: string,
  reason: string = "",
): Promise<Escalation | null> {
  return tryBackend<Escalation>(`/escalations/${caseId}/action`, {
    method: "POST",
    body: JSON.stringify({ action, reviewer_id: reviewerId, reason }),
  });
}

export async function getSafetyEvents(): Promise<SafetyEvent[]> {
  const remote = await tryBackend<SafetyEvent[]>("/events?limit=30");
  if (remote) return remote;
  return [];
}

export async function getTemplates(): Promise<
  { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
> {
  const remote = await tryBackend<
    { template_id: string; title: string; body: string; safe_alternative: string; restricted_sub_class: string | null }[]
  >("/templates");
  if (remote) return remote;
  return MOCK_TEMPLATES;
}

// ─── Local Fallback Classifier ──────────────────────────────────────────────

const ACADEMIC_RE = /\b(solve\s+(my|this)\s+exam|exam\s+answer|quiz\s+answer|complete\s+(my|this)\s+assessment)\b/i;
const BYPASS_RE = /\b(ignore\s+instructions|jailbreak|system\s+prompt|bypass\s+safety|DAN\s+mode)\b/i;
const HIGH_KEYWORDS = ["tax filing", "tax return", "tax treatment", "tax advice", "audit opinion", "going concern", "legal opinion", "revenue recognition", "lease classification"];
const MEDIUM_KEYWORDS = ["journal entry", "worked example", "explain the concept", "how does", "define", "overview"];
const ADVICE_RE = /\b(my|our)\s+(company|client|firm)\b/i;

let _qid = 0;

function localClassify(query: string, jurisdiction: string, mode: string): SafetyDecision {
  const qid = `qry-local-${++_qid}`;
  const ql = query.toLowerCase();

  if (ACADEMIC_RE.test(query)) {
    return {
      allowed: false,
      risk_level: "RESTRICTED",
      restricted_sub_class: "RESTRICTED_ACADEMIC_INTEGRITY",
      route: "REFUSAL",
      confidence: 1,
      requires_sources: false,
      requires_human_review: false,
      requires_citation: false,
      requires_professional_boundary: false,
      limitations: ["Academic integrity violation — answer cannot be provided."],
      refusal_text:
        "**Academic Integrity**\n\nKriton™ cannot complete exam questions, provide assessment answers, or assist with academic dishonesty.",
      safe_alternative:
        "Kriton™ can explain the underlying concept or walk through a similar worked example.",
      rules_applied: ["l1-academic-integrity-block"],
      query_id: qid,
    };
  }

  if (BYPASS_RE.test(query)) {
    return {
      allowed: false,
      risk_level: "RESTRICTED",
      restricted_sub_class: "RESTRICTED_CONTROL_BYPASS",
      route: "SECURITY_INCIDENT",
      confidence: 1,
      requires_sources: false,
      requires_human_review: false,
      requires_citation: false,
      requires_professional_boundary: false,
      limitations: ["Request pattern cannot be processed."],
      refusal_text: "**Unable to Process**\n\nThis request cannot be processed.",
      safe_alternative: "",
      rules_applied: ["l1-control-bypass-block"],
      query_id: qid,
    };
  }

  if (ADVICE_RE.test(query) && !jurisdiction) {
    return {
      allowed: false,
      risk_level: "RESTRICTED",
      restricted_sub_class: "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT",
      route: "CLARIFICATION",
      confidence: 0.92,
      requires_sources: false,
      requires_human_review: false,
      requires_citation: false,
      requires_professional_boundary: false,
      limitations: ["Jurisdiction and entity context required."],
      refusal_text:
        "**Additional Context Required**\n\nPlease specify your jurisdiction, entity type, and applicable framework.",
      safe_alternative:
        "Once context is provided, Kriton™ can reclassify and proceed.",
      rules_applied: ["l2-advice-insufficient-context"],
      query_id: qid,
    };
  }

  const highScore = HIGH_KEYWORDS.filter((kw) => ql.includes(kw)).length;
  if (highScore >= 1) {
    return {
      allowed: true,
      risk_level: "HIGH",
      restricted_sub_class: null,
      route: "LLM",
      confidence: 0.84,
      requires_sources: true,
      requires_human_review: highScore >= 2,
      requires_citation: true,
      requires_professional_boundary: true,
      limitations: [
        "Answer must include source citations and professional boundary notice.",
        "This is workflow guidance — not a substitute for professional judgment.",
      ],
      refusal_text: null,
      safe_alternative: null,
      rules_applied: ["l2-high-risk-signal"],
      query_id: qid,
    };
  }

  const medScore = MEDIUM_KEYWORDS.filter((kw) => ql.includes(kw)).length;
  if (medScore >= 1 || mode === "Learning") {
    return {
      allowed: true,
      risk_level: "MEDIUM",
      restricted_sub_class: null,
      route: "LLM",
      confidence: 0.88,
      requires_sources: true,
      requires_human_review: false,
      requires_citation: false,
      requires_professional_boundary: false,
      limitations: ["Educational context — not specific professional advice."],
      refusal_text: null,
      safe_alternative: null,
      rules_applied: ["l2-medium-risk"],
      query_id: qid,
    };
  }

  return {
    allowed: true,
    risk_level: "LOW",
    restricted_sub_class: null,
    route: "LLM",
    confidence: 0.9,
    requires_sources: false,
    requires_human_review: false,
    requires_citation: false,
    requires_professional_boundary: false,
    limitations: [],
    refusal_text: null,
    safe_alternative: null,
    rules_applied: ["l2-low-risk-default"],
    query_id: qid,
  };
}

// ─── Mock Data (used when backend is offline) ───────────────────────────────

const MOCK_ESCALATIONS: Escalation[] = [
  {
    id: "ESC-1842",
    query_id: "qry-a1b2c3",
    query_text: "What is the VAT treatment on mixed supply in London?",
    topic: "VAT treatment, mixed supply",
    risk_level: "HIGH",
    restricted_sub_class: null,
    jurisdiction: "UK",
    owner: "Tax Lead",
    reviewer_role: "SME Reviewer",
    sla_deadline: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
    status: "PENDING",
    route_reason: "l2-high-risk-multi-signal",
    detail:
      "Citation anchor valid; HMRC source current. User context includes cross-border invoice. Needs tax specialist note before limited answer release.",
    reviewer_decision: null,
    reviewer_id: null,
    created_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
    resolved_at: null,
  },
  {
    id: "ESC-1910",
    query_id: "qry-d4e5f6",
    query_text: "Draft going concern wording for our annual report",
    topic: "Going concern wording",
    risk_level: "RESTRICTED",
    restricted_sub_class: "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT",
    jurisdiction: "IFRS",
    owner: "Audit Lead",
    reviewer_role: "SME Reviewer",
    sla_deadline: new Date(Date.now() + 39 * 60 * 1000).toISOString(),
    status: "UNDER_REVIEW",
    route_reason: "l2-advice-insufficient-context",
    detail:
      "Draft answer could imply audit opinion. Restricted output path blocks release until audit lead + legal/compliance reviewer attach decision note.",
    reviewer_decision: null,
    reviewer_id: null,
    created_at: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
    resolved_at: null,
  },
  {
    id: "ESC-1944",
    query_id: "qry-g7h8i9",
    query_text: "Calculate payroll termination pay for California employee",
    topic: "Payroll termination pay",
    risk_level: "HIGH",
    restricted_sub_class: null,
    jurisdiction: "US-CA",
    owner: "Jurisdiction Expert",
    reviewer_role: "SME Reviewer",
    sla_deadline: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
    status: "PENDING",
    route_reason: "l2-high-risk-single-signal",
    detail:
      "Jurisdiction pack coverage below launch threshold. Answer returned with unsupported-jurisdiction limitation and local expert request.",
    reviewer_decision: null,
    reviewer_id: null,
    created_at: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    resolved_at: null,
  },
];

const MOCK_TEMPLATES = [
  {
    template_id: "tpl-academic-001",
    title: "Academic Integrity",
    body: "Kriton™ cannot complete exam questions or assist with academic dishonesty.",
    safe_alternative: "Kriton™ can explain the underlying concept.",
    restricted_sub_class: "RESTRICTED_ACADEMIC_INTEGRITY",
  },
  {
    template_id: "tpl-advice-context-001",
    title: "Additional Context Required",
    body: "This question requires specific context before proceeding safely.",
    safe_alternative: "Please specify jurisdiction, entity type, and framework.",
    restricted_sub_class: "RESTRICTED_ADVICE_INSUFFICIENT_CONTEXT",
  },
  {
    template_id: "tpl-source-prohibited-001",
    title: "Source Not Available",
    body: "The relevant source cannot be used due to licensing restrictions.",
    safe_alternative: "Kriton™ can provide a general educational explanation.",
    restricted_sub_class: "RESTRICTED_SOURCE_PROHIBITED",
  },
  {
    template_id: "tpl-control-bypass-001",
    title: "Unable to Process",
    body: "This request cannot be processed.",
    safe_alternative: "",
    restricted_sub_class: "RESTRICTED_CONTROL_BYPASS",
  },
];

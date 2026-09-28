import type { AskKritonResponse } from "@/lib/api";

/**
 * Deterministic "Explore further" suggestion engine — an ordered chain of
 * small pattern-matching rules, each returning either a fixed question array
 * or `null` ("no match, try the next rule"). Nothing here calls a model —
 * every possible suggestion is one of a small, hand-authored, reviewable set.
 *
 * The backend doesn't send a `presentation` object (chart type / layout
 * classification) yet, so "layout" is inferred here from the answer text's
 * shape. Answers no longer contain LLM-authored ```chart/```mermaid fences
 * (see websearch.py's _FORMATTING_INSTRUCTIONS docstring) — visualization
 * signals for follow-ups would need to come from the response's typed
 * `visualization` field instead, not text-sniffing, if that's wanted later.
 * If the backend ever starts sending real presentation.follow_up_questions,
 * prefer those over this local inference.
 */

type Rule = () => string[] | null;

function firstMatch(rules: Rule[]): string[] {
  for (const rule of rules) {
    const result = rule();
    if (result !== null) return result;
  }
  return [];
}

// ── Intent patterns — matched against the ORIGINAL question text ───────────

const INTENT_RULES: { pattern: RegExp; questions: string[] }[] = [
  {
    pattern: /\b(journal entry|correcting entry|adjusting entry|reclass(ification)?|debit\s+and\s+credit)\b/i,
    questions: [
      "Show the original, incorrect, and correcting entries together.",
      "Explain the downstream P&L and AR impact.",
      "Give me another example of this.",
    ],
  },
  {
    pattern: /\b(evidence matrix|control matrix|evidence[- ]to[- ](control|assertion)\s+mapping)\b/i,
    questions: [
      "Apply this to a practical example.",
      "Turn this into a reviewer checklist.",
      "Explain when a critical override applies.",
    ],
  },
  {
    pattern: /\bswimlane\b/i,
    questions: [
      "Add sign-off requirements to each lane.",
      "Adapt this for a smaller team.",
      "Show the escalation path.",
    ],
  },
  {
    pattern: /\b(decision tree|which (path|option|route) (should|do)|decide (whether|if))\b/i,
    questions: [
      "Explain each branch of this decision tree.",
      "Add evidence and approval requirements to each branch.",
      "Show the escalation path for this decision.",
    ],
  },
  {
    pattern: /\b(timeline|schedule|chronology|milestones?)\b/i,
    questions: [
      "Turn this into an owner-and-deadline checklist.",
      "Explain the controls at each stage.",
      "Show common bottlenecks in this timeline.",
    ],
  },
  {
    pattern: /\bchecklist\b/i,
    questions: [
      "Explain why each item matters.",
      "Show common mistakes people make here.",
      "Adapt this checklist for a reviewer role.",
    ],
  },
  {
    // steps?(?!\s*line): "step"/"steps" not immediately followed by "line" —
    // otherwise a chart-type name like "step line chart" (STEP_LINE_CHART,
    // see response_planner.py's _CHART_VARIANTS) false-matched as a
    // process/workflow question and produced completely unrelated
    // process-flavoured follow-ups for an ordinary trend-chart query.
    pattern: /\b(process|procedure|workflow|steps?(?!\s*line)|sequence|how (do|does|to))\b/i,
    questions: [
      "What happens if a step in this process fails?",
      "Explain the control at each stage.",
      "Add an audit-logging step to this process.",
    ],
  },
];

// ── Layout inference from the answer text's shape (fallback tier) ──────────

function inferLayout(answerText: string): string {
  const hasTable = /\|.+\|.*\n\|[-:| ]+\|/.test(answerText);
  const hasOrderedSteps = /^\s*\d+\.\s+/m.test(answerText) && /\b(step|first|then|next|finally)\b/i.test(answerText);
  const hasCalculation = /(\$[\d,.]+|=\s*\$?[\d,.]+|\bformula\b|\bcalculat)/i.test(answerText);
  if (hasTable) return "comparison";
  if (hasOrderedSteps) return "step_by_step";
  if (hasCalculation) return "calculation";
  return "descriptive";
}

const LAYOUT_QUESTIONS: Record<string, string[]> = {
  calculation: [
    "Explain this result in plain terms.",
    "Show the assumptions and methodology behind this.",
    "Calculate this for a different scenario.",
  ],
  step_by_step: [
    "Turn this into a checklist.",
    "Explain common mistakes in this process.",
    "Show a worked example.",
  ],
  comparison: [
    "Highlight the most important differences.",
    "Turn this comparison into a decision checklist.",
    "Explain this comparison with a grounded example.",
  ],
  descriptive: [
    "Summarize this as a checklist.",
    "Explain this with a grounded example.",
    "What common mistakes should I avoid?",
  ],
};

const FALLBACK_QUESTIONS = ["Explain this in more detail.", "Give me a grounded example."];

// Rule 1 — an answer that required user input still missing gets no suggestions.
function missingInputRule(result: AskKritonResponse): string[] | null {
  const incomplete = result.outcome !== "answered" && result.outcome !== "clarification_required";
  return incomplete ? [] : null;
}

// Rule 2 — a pending clarification IS the only follow-up.
function clarificationPendingRule(result: AskKritonResponse): string[] | null {
  if (result.outcome !== "clarification_required") return null;
  return [result.next_action?.message ?? "Please provide more context."];
}

// Rule 3 — match the original question's intent against a fixed pattern set.
function intentPatternRule(originalQuery: string): string[] | null {
  const hit = INTENT_RULES.find((rule) => rule.pattern.test(originalQuery));
  return hit ? hit.questions : null;
}

// Rule 4 — fall back to the answer's overall shape.
function layoutRule(answerText: string): string[] | null {
  return LAYOUT_QUESTIONS[inferLayout(answerText)] ?? null;
}

/**
 * Resolves the 2–3 "Explore further" suggestions for a completed turn.
 * Returns [] when nothing should be suggested (incomplete answer) rather
 * than falling back — an empty answer never gets follow-up prompts.
 */
export function getFollowUpSuggestions(result: AskKritonResponse | null, originalQuery: string): string[] {
  if (!result) return [];

  const byOutcome = firstMatch([() => missingInputRule(result), () => clarificationPendingRule(result)]);
  if (byOutcome.length > 0 || result.outcome !== "answered") return byOutcome;

  const answerText = result.answer?.text ?? "";

  return firstMatch([
    () => intentPatternRule(originalQuery),
    () => layoutRule(answerText),
    () => FALLBACK_QUESTIONS,
  ]);
}

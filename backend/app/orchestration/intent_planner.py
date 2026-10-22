"""Structured intent planner — SHADOW MODE ONLY (build order step A).

A model reads the question (and recent turns) and proposes a structured task
plan: the intent, its sub-tasks, the tools it would use, the inputs that are
missing or invalid, and whether authoritative evidence is needed. The plan is
compared with what the existing rule-based router actually did and the
comparison is logged. Nothing here changes an answer, a tool call, a
permission, a source decision or a safety decision:

- the live hook (planner_shadow.py) is off unless KRITON_PLANNER_SHADOW=true,
  is never awaited by the request, and swallows its own failures;
- policy invariants (apply_policy_invariants) are applied to every proposal,
  so even a logged plan can never widen tools beyond the role's grant or drop
  an evidence requirement the rules impose — the model cannot override them;
- the call goes through the model gateway under the already-approved
  "query_classification" purpose, which redacts personal data first.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.domains.model_gateway import auxiliary as gateway

Intent = Literal[
    "calculation", "tax_calculation", "reconciliation", "research_standard", "research_tax",
    "live_data", "visualization", "document_analysis", "review", "explanation", "comparison",
    "summary", "clarification", "off_domain",
]
INTENTS: tuple[str, ...] = Intent.__args__  # type: ignore[attr-defined]
Tool = Literal["calculate", "search_knowledge_base", "search_web", "get_exchange_rate",
               "get_economic_indicator", "get_market_data", "render_chart"]
TOOLS: tuple[str, ...] = Tool.__args__  # type: ignore[attr-defined]


class SubTask(BaseModel):
    kind: Intent
    text: str = Field(description="The part of the request this sub-task answers, in a few words.")
    needs_evidence: bool = Field(description="True when this part must come from a source (a rule, rate, deadline, "
                                             "standard or published figure), false for arithmetic on given figures.")
    tools: list[Tool] = Field(description="The tools this part alone needs.")
    missing_inputs: list[str] = Field(description="Inputs this part needs that are not given anywhere.")


class TaskPlan(BaseModel):
    intent: Intent = Field(description="The primary intent.")
    sub_tasks: list[SubTask] = Field(description="Every separately answerable part of the request, in order.")
    tools: list[Tool] = Field(description="Only the tools needed. No tool for arithmetic on figures the user gave "
                                          "is wrong: use calculate. No search for pure arithmetic.")
    needs_authoritative_evidence: bool = Field(description="True when a rule, rate, threshold, standard or "
                                                           "legal requirement must come from a source.")
    standards: list[str] = Field(description="Standards or rules named or implied, e.g. 'IFRS 15', 'IAS 2', 'UK VAT'.")
    uses_conversation: bool = Field(description="True only when the request depends on figures or content "
                                                "from earlier turns.")
    missing_inputs: list[str] = Field(description="Inputs required to answer that the user has not given.")
    invalid_inputs: list[str] = Field(description="Inputs given but impossible, e.g. a negative tax rate.")
    wants_visualization: bool
    confidence: float = Field(description="0 to 1.")


_SYSTEM = """You plan how an accounting and finance assistant should handle a request. Do not answer it.
Return JSON matching the schema.

Intents:
- calculation: arithmetic on figures the user supplied (margins, ratios, break-even, depreciation, interest).
- tax_calculation: computing a tax amount (VAT, GST, income or corporation tax) from given figures.
- reconciliation: checking reported figures against each other or finding a difference.
- research_standard: what an accounting standard (IFRS, IAS, US GAAP, FRS) requires.
- research_tax: what a tax rule, rate, threshold or deadline is.
- live_data: current or historical market, exchange-rate or economic data.
- visualization: the main request is a chart of data.
- document_analysis: questions about an attached or uploaded file.
- review: checking pasted text claim by claim.
- explanation: a general concept explanation.
- comparison: comparing regimes, standards or options.
- summary: summarising supplied text.
- clarification: the request cannot be answered without an input that is missing or invalid.
- off_domain: not accounting, tax or finance.
Any amount of VAT, GST, sales tax, income tax or corporation tax worked out from given figures is
tax_calculation, never calculation.
Mixed requests: list every separately answerable part in sub_tasks, one sub-task per part, each with its own
kind, evidence need, tools and missing inputs. A calculation part is calculation or tax_calculation; a question
about a deadline, rate, threshold or tax rule is research_tax; "what <standard> says/requires" about an accounting
standard (IAS, IFRS, FRS, US GAAP) is research_standard, not explanation; a published statistic or average is
live_data. The intent is the kind of the first part the user asked for. One part lacking evidence never makes
another part a clarification.
Missing inputs — list them and make the intent clarification when the request cannot be answered without them:
- a VAT or tax amount needs the rate, whether amounts include or exclude tax, and the country unless a currency
  such as £ or ₹ names it ($ does not name a country);
- "my tax", "those expenses", "these figures", or accounting entries to show, with no figures given or earlier
  in the conversation;
- two different values given for the same input, even when one is introduced as a correction ("actually").
An amount in $ with no country named is missing the country. £ means the UK and ₹ means India.
Invalid inputs (a negative rate, a negative price or cost) are invalid, not missing; list them in
invalid_inputs and make the intent clarification. Valid inputs whose result is undefined (zero contribution)
are a calculation, not a clarification.
Figures from earlier turns count as given when the request builds on them ("same figures", "that", "suppose",
"on top of that", "instead"). uses_conversation is true whenever the request points back at an earlier turn
("explain that", "chart it", "show this as…", "the same figures").
Tools: calculate (arithmetic on the user's figures), search_knowledge_base (governed library), search_web
(rules, standards and facts not supplied), get_exchange_rate, get_economic_indicator, get_market_data,
render_chart. A question about what a standard, tax rule, rate, threshold or deadline says plans BOTH
search_knowledge_base and search_web. Never plan calculate when the user gave no figures and did not ask for a
worked example. An attached document is analysed with calculate for arithmetic on its figures."""


@dataclass
class PlanResult:
    plan: Optional[TaskPlan]
    latency_ms: float
    tokens: int = 0
    failure: str = ""
    invariants_applied: list[str] = field(default_factory=list)


def _strict_schema() -> dict:
    """Groq strict JSON-schema mode: every property required, no extras."""
    schema = TaskPlan.model_json_schema()

    def tighten(node: dict) -> None:
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        for value in node.values():
            if isinstance(value, dict):
                tighten(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        tighten(item)

    tighten(schema)
    for definition in schema.get("$defs", {}).values():
        tighten(definition)
    return schema


def _conversation_text(history: list[dict] | None) -> str:
    turns = []
    for message in (history or [])[-6:]:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", "")
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
        turns.append(f"{role}: {(content or '')[:600]}")
    return "\n".join(turns)


async def propose_plan(query: str, history: list[dict] | None = None, *, has_documents: bool = False) -> PlanResult:
    """One model call; never raises. The question goes through the gateway,
    which redacts personal data before it leaves."""
    started = time.monotonic()
    if not gateway.may_use("query_classification", "groq"):
        return PlanResult(None, 0.0, failure="not_configured")
    model = os.getenv("KRITON_PLANNER_MODEL") or os.getenv("GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b")
    conversation = _conversation_text(history)
    user = ((f"Earlier conversation:\n{conversation}\n\n" if conversation else "")
            # The planner cannot see files; it is told that one is attached, so
            # "the attached balance sheet" is document analysis, not missing input.
            + ("The user has attached a document to this request.\n\n" if has_documents else "")
            + f"Request:\n{query[:6000]}")
    failure = ""
    # One retry for malformed output only: two ordinary questions came back
    # as broken JSON once; a refusal is not retried.
    for _attempt in range(2):
        try:
            completion = await gateway.complete_auxiliary(
                purpose="query_classification", model=model, system=_SYSTEM, user=user,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "task_plan", "strict": True, "schema": _strict_schema()}},
                timeout=20.0,
            )
            plan = _with_hints(TaskPlan.model_validate(json.loads(completion.text or "{}")), query, history)
            return PlanResult(_consistent(plan), (time.monotonic() - started) * 1000,
                              tokens=completion.total_tokens or 0)
        except Exception as exc:  # noqa: BLE001 — shadow planning must never fail a caller
            failure = _failure_kind(exc)
            if failure != "malformed_output":
                break
    return PlanResult(None, (time.monotonic() - started) * 1000, failure=failure)


_REFERS_BACK = re.compile(r"\b(?:that|this|it|them|those|these|above|previous|earlier|same)\b", re.I)


def _with_hints(plan: TaskPlan, query: str, history: list | None) -> TaskPlan:
    """Deterministic facts the model missed, from the same checks the router
    uses: two values for one input given as a correction (int-contradictory-
    inputs was planned as a plain calculation), and a request that points
    back at an earlier turn ("Explain that with a simple numerical example"
    was planned as not using the conversation)."""
    from app.orchestration.calculations.engine import corrected_input
    corrected = corrected_input(query)
    if corrected is not None and not plan.missing_inputs:
        plan.missing_inputs = [corrected.message]
    if history and _REFERS_BACK.search(query) and not plan.uses_conversation:
        plan.uses_conversation = True
    return plan


_REFUSAL_TEXT = re.compile(r"\b(?:sorry|can(?:no|')t help|cannot help|unable to (?:help|assist)|can't assist)\b", re.I)


def _failure_kind(exc: Exception) -> str:
    """A model that declines to plan ("I'm sorry, but I can't help with
    that.") returns no JSON, which the provider reports as a 400; that is a
    refusal, not an outage. Unparseable or off-schema output is malformed."""
    text = str(exc)
    if "json_validate_failed" in text or "failed_generation" in text:
        return "model_refused" if _REFUSAL_TEXT.search(text) else "malformed_output"
    if type(exc).__name__ in ("ValidationError", "JSONDecodeError"):
        return "malformed_output"
    return type(exc).__name__


def _consistent(plan: TaskPlan) -> TaskPlan:
    """A plan that names missing or invalid inputs is a clarification; the
    model listed "negative VAT rate" and still called it a calculation."""
    if (plan.missing_inputs or plan.invalid_inputs) and plan.intent != "clarification":
        plan.intent = "clarification"  # type: ignore[assignment]
    return plan


def apply_policy_invariants(result: PlanResult, query: str, *, role: str = "ACCOUNTANT") -> PlanResult:
    """The rules, not the model, own permissions and evidence requirements.
    A proposal is narrowed to tools the role may use, and can never drop an
    evidence requirement the rules impose. Recorded, so the log shows where
    the model would have gone beyond policy."""
    if result.plan is None:
        return result
    from app.domains.identity.permissions import permissions_for_role
    from app.domains.model_gateway.service import tool_registry
    from app.orchestration.verification_service import requires_authoritative_evidence

    permitted = {spec.name for spec in tool_registry().allowed(permissions_for_role(role))}
    kept = [tool for tool in result.plan.tools if tool in permitted]
    if kept != list(result.plan.tools):
        result.invariants_applied.append("tools_outside_role_removed:" + ",".join(
            sorted(set(result.plan.tools) - set(kept))))
        result.plan.tools = kept  # type: ignore[assignment]
    if requires_authoritative_evidence(query) and not result.plan.needs_authoritative_evidence:
        result.invariants_applied.append("evidence_floor_applied")
        result.plan.needs_authoritative_evidence = True
    return result


# ── What the existing router did ───────────────────────────────────────────

_DATA_TOOLS = {"get_exchange_rate", "get_economic_indicator", "get_market_data"}
OFF_DOMAIN_MARKER = "designed to answer questions related to accounting"


def router_intent(*, route: str | None, outcome: str | None, answer_text: str, tools: set[str],
                  planned_reasons: list[str], formulas: list[str], has_chart: bool,
                  has_documents: bool) -> str:
    """The intent the existing rules acted on, read from what they did —
    the same derivation the benchmark uses (scripts/run_baseline_eval.py
    rule_intent), so live shadow logs and benchmark reports are comparable."""
    if (OFF_DOMAIN_MARKER in (answer_text or "").lower() or route in ("SECURITY_INCIDENT", "REJECTED", "REFUSAL")
            or outcome == "refused"):
        return "off_domain"
    if outcome == "clarification_required" or route == "CLARIFICATION":
        return "clarification"
    if (answer_text or "").startswith("I checked "):
        return "review"
    if has_documents:
        return "document_analysis"
    if tools & _DATA_TOOLS:
        return "live_data"
    if "render_chart" in tools or has_chart:
        return "visualization"
    if "gross_profit_reconciliation" in formulas:
        return "reconciliation"
    if any(formula.startswith("vat") or formula.startswith("output_vat") for formula in formulas):
        return "tax_calculation"
    if route == "CALCULATION" or "calculate" in tools:
        return "calculation"
    if "professional rule or authority named" in (planned_reasons or []):
        return "research_standard"
    return "explanation"


# Intents the benchmark labels coarsely; the planner's finer labels map onto
# them for scoring (research_tax and research_standard are both rule research).
_EQUIVALENT = {"research_tax": "research_standard", "summary": "explanation"}


def same_intent(a: str | None, b: str | None) -> bool:
    return bool(a and b) and _EQUIVALENT.get(a, a) == _EQUIVALENT.get(b, b)


def compare(plan: Optional[TaskPlan], *, router: str, router_tools: list[str]) -> dict:
    """Where the proposal and the router differ."""
    if plan is None:
        return {"planner_available": False}
    proposed, used = set(plan.tools), set(router_tools)
    return {
        "planner_available": True,
        "intent_agreement": same_intent(plan.intent, router),
        "planner_intent": plan.intent,
        "router_intent": router,
        "tools_only_planner": sorted(proposed - used),
        "tools_only_router": sorted(used - proposed),
        "planner_sub_tasks": [task.kind for task in plan.sub_tasks],
        "planner_missing_inputs": plan.missing_inputs,
        "planner_invalid_inputs": plan.invalid_inputs,
    }


def query_fingerprint(query: str) -> str:
    """Logs carry this, never the question text (as query_received does)."""
    import hashlib
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:32]


def numbers_in(text: str) -> int:
    return len(re.findall(r"\d", text or ""))

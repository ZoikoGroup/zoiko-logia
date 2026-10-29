"""Versioned registry of the tools an agent model may call.

Every tool is declared once as a ToolSpec — name, version, description, a
Pydantic input schema, data source, risk level, timeout and an optional
permission — and is only ever run through ToolRegistry.execute(), which is the
single enforcement point:

  unknown tool → permission check → JSON parse → schema validation
  → handler under a hard timeout → size-capped result

execute() never raises. Every failure comes back as a ToolResult with ok=False
and a stable error_code, so an agent loop can hand the outcome straight back
to the model ("that failed, because…") and the audit trail can record it,
instead of one bad tool call failing the whole answer.

The model proposes arguments; this module decides whether they are allowed
and well-formed before anything touches a network.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ValidationError

from app.orchestration.websearch import WebSource

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "1.0"

# What the model reads back is capped: a tool result goes into the next
# prompt, so an oversized payload would silently eat the token budget.
MAX_RESULT_CHARS = 6000

RiskLevel = Literal["low", "medium", "high"]
ErrorCode = Literal[
    "unknown_tool", "permission_denied", "write_action_blocked", "invalid_arguments", "timeout", "no_data", "tool_error", "retrieval_unavailable",
    # Set by the agent loop, not by execute():
    "duplicate_call", "budget_exhausted", "unverified_figures",
]


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    # Text the model reads as the tool's answer.
    content: str
    # Evidence for citations — the same WebSource shape the grounded answer
    # pipeline already cites from.
    sources: tuple[WebSource, ...] = ()
    # Deterministically built output blocks appended to the answer as-is
    # (e.g. a validated ```chart fence) — never retyped by the model.
    artifacts: tuple[str, ...] = ()
    error_code: ErrorCode | None = None
    # A calculation receipt (calc_tool): what was computed, by which tool
    # version, from which inputs (by hash), with which rounding and warnings.
    # Persisted as a calculation run so figures can be traced (§07.3).
    receipt: dict | None = None
    # Every receipt of a batched calculation, in item order (receipt is the
    # first, so readers of a single calculation are unchanged).
    receipts: tuple[dict, ...] = ()
    # Items a batched calculation evaluated, and how many failed.
    items_total: int | None = None
    items_failed: int | None = None

    @property
    def all_receipts(self) -> tuple[dict, ...]:
        return self.receipts or ((self.receipt,) if self.receipt else ())

    @classmethod
    def failure(cls, error_code: ErrorCode, content: str) -> "ToolResult":
        return cls(ok=False, content=content, error_code=error_code)


ToolHandler = Callable[[Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    data_source: str
    risk_level: RiskLevel
    timeout_seconds: float
    # None = available to every authenticated caller (e.g. public statistics).
    required_permission: str | None = None
    # Roles allowed to use the tool; None means any active user who may ask
    # Kriton (asking is authorised per engagement before the run starts).
    allowed_roles: frozenset[str] | None = None
    # Tools that change anything outside Kriton (filing, payments, postings,
    # external messages) are refused by policy whatever the caller's role
    # (ZL-ENG-AGT-01 §10.5). Every current tool is read-only.
    is_write_action: bool = False
    # Hand-written JSON schema, for a tool whose accepted shapes are clearer
    # declared directly than generated (render_chart's per-type union).
    parameters_schema: dict | None = None
    # Accountable team (§05.1). TBD until leads assign named owners.
    owner: str = "TBD"
    # "public" (open data, no tenant records), "tenant" (the caller's tenant
    # records only; the tool re-checks scope itself) or "none" (pure compute).
    tenant_scope: Literal["public", "tenant", "none"] = "none"
    # Retries for a transient failure (timeout, tool error), never for a
    # refusal or invalid arguments.
    max_retries: int = 0

    def function_schema(self) -> dict:
        """OpenAI/Groq-style function declaration for this tool."""
        parameters = dict(self.parameters_schema) if self.parameters_schema else self.args_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": parameters},
        }


POLICY_VERSION = "tool-policy-1"


@dataclass(frozen=True)
class PolicyDecision:
    """The policy service's answer for one proposed tool call. Created only by
    decide() from server-side facts (the stored user, the registry), never
    from model output (ZL-ENG-AGT-01 App. B2)."""
    decision_id: str
    tool: str
    allowed: bool
    reason_code: str
    role: str
    policy_version: str = POLICY_VERSION


def decide(spec: "ToolSpec | None", name: str, *, role: str, active: bool, same_tenant: bool,
           role_unchanged: bool, permissions: frozenset[str]) -> PolicyDecision:
    """Fail closed: every condition must hold for the call to be allowed."""
    if spec is None:
        reason = "unknown_tool"
    elif not active or not same_tenant:
        reason = "user_not_authorised"
    elif not role_unchanged:
        reason = "role_changed"
    elif spec.is_write_action:
        reason = "write_action_blocked"
    elif spec.allowed_roles is not None and role not in spec.allowed_roles:
        reason = "role_not_allowed"
    elif spec.required_permission and spec.required_permission not in permissions:
        reason = "permission_denied"
    else:
        reason = "allowed"
    return PolicyDecision(decision_id=f"pd-{uuid.uuid4().hex[:16]}", tool=name,
                          allowed=reason == "allowed", reason_code=reason, role=role)


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool '{spec.name}' is already registered")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def allowed(self, granted_permissions: frozenset[str]) -> list[ToolSpec]:
        return [
            spec for spec in self._tools.values()
            if spec.required_permission is None or spec.required_permission in granted_permissions
        ]

    def function_schemas(self, granted_permissions: frozenset[str]) -> list[dict]:
        """Declarations for only the tools this caller may use — a tool the
        caller can't run is never offered to the model in the first place."""
        return [spec.function_schema() for spec in self.allowed(granted_permissions)]

    async def execute(
        self, name: str, raw_arguments: str | dict | None, *, granted_permissions: frozenset[str],
        decision: PolicyDecision | None = None,
    ) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult.failure("unknown_tool", f"Unknown tool '{name}'. Available: {', '.join(self.names())}.")
        # A policy decision, when the caller runs one per step, must be for
        # this exact tool and must allow it.
        if decision is not None and (not decision.allowed or decision.tool != name):
            return ToolResult.failure("permission_denied", f"You are not permitted to use '{name}'.")
        if spec.is_write_action:
            return ToolResult.failure(
                "write_action_blocked",
                f"'{name}' would change something outside Kriton and is not allowed. Explain the steps instead.",
            )
        # Re-checked here even though function_schemas() already filters: the
        # model can name any tool in its output, offered or not.
        if spec.required_permission and spec.required_permission not in granted_permissions:
            return ToolResult.failure("permission_denied", f"You are not permitted to use '{name}'.")

        try:
            payload = json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
            if not isinstance(payload, dict):
                raise ValueError("arguments must be a JSON object")
            args = spec.args_model.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            return ToolResult.failure("invalid_arguments", f"Invalid arguments for '{name}': {_short_error(exc)}")

        result = None
        for attempt in range(spec.max_retries + 1):
            try:
                result = await asyncio.wait_for(spec.handler(args), timeout=spec.timeout_seconds)
                break
            except asyncio.TimeoutError:
                result = ToolResult.failure("timeout", f"'{name}' timed out after {spec.timeout_seconds:g}s. Do not guess the data.")
            except Exception as exc:  # a tool bug must not fail the whole answer
                logger.warning("Tool %s failed: %s", name, type(exc).__name__)
                result = ToolResult.failure("tool_error", f"'{name}' failed unexpectedly. Do not guess the data.")
            if attempt < spec.max_retries:
                logger.info("Retrying tool %s (attempt %d of %d)", name, attempt + 2, spec.max_retries + 1)

        if len(result.content) > MAX_RESULT_CHARS:
            # Every other field is kept: rebuilt field by field, a long batched
            # calculation lost all receipts but the first.
            result = dataclasses.replace(result, content=result.content[:MAX_RESULT_CHARS] + " …[truncated]")
        return result


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
            for err in exc.errors()[:3]
        )
    return str(exc)


def build_default_registry(*, batch_calculations: bool = False) -> ToolRegistry:
    """The production tool set. Imported lazily so the registry module itself
    stays free of connector imports (and their network clients).

    batch_calculations swaps in the calculator that also accepts
    `expressions` (calc_tool.CALCULATE_BATCH_TOOL). Off by default: production
    routing keeps the single-expression calculator until the batch form is
    reviewed (docs/kriton-batched-calculator-and-balance-provenance-design.md)."""
    from app.domains.model_gateway.tools.calc_tool import CALCULATE_BATCH_TOOL, CALCULATE_TOOL
    from app.domains.model_gateway.tools.chart_tool import RENDER_CHART_TOOL
    from app.domains.model_gateway.tools.economic_tool import ECONOMIC_INDICATOR_TOOL
    from app.domains.model_gateway.tools.fx_tool import EXCHANGE_RATE_TOOL
    from app.domains.model_gateway.tools.kb_tool import KNOWLEDGE_BASE_TOOL
    from app.domains.model_gateway.tools.market_tool import MARKET_DATA_TOOL
    from app.domains.model_gateway.tools.web_tool import SEARCH_WEB_TOOL

    registry = ToolRegistry()
    for spec in (KNOWLEDGE_BASE_TOOL, SEARCH_WEB_TOOL, EXCHANGE_RATE_TOOL, ECONOMIC_INDICATOR_TOOL, MARKET_DATA_TOOL,
                 CALCULATE_BATCH_TOOL if batch_calculations else CALCULATE_TOOL, RENDER_CHART_TOOL):
        registry.register(spec)
    return registry

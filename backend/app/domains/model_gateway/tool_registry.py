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
import json
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
    "unknown_tool", "permission_denied", "invalid_arguments", "timeout", "no_data", "tool_error",
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
    # Hand-written JSON schema, for a tool whose accepted shapes are clearer
    # declared directly than generated (render_chart's per-type union).
    parameters_schema: dict | None = None

    def function_schema(self) -> dict:
        """OpenAI/Groq-style function declaration for this tool."""
        parameters = dict(self.parameters_schema) if self.parameters_schema else self.args_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": parameters},
        }


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
    ) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult.failure("unknown_tool", f"Unknown tool '{name}'. Available: {', '.join(self.names())}.")
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

        try:
            result = await asyncio.wait_for(spec.handler(args), timeout=spec.timeout_seconds)
        except asyncio.TimeoutError:
            return ToolResult.failure("timeout", f"'{name}' timed out after {spec.timeout_seconds:g}s. Do not guess the data.")
        except Exception as exc:  # a tool bug must not fail the whole answer
            logger.warning("Tool %s failed: %s", name, type(exc).__name__)
            return ToolResult.failure("tool_error", f"'{name}' failed unexpectedly. Do not guess the data.")

        if len(result.content) > MAX_RESULT_CHARS:
            result = ToolResult(
                ok=result.ok, content=result.content[:MAX_RESULT_CHARS] + " …[truncated]",
                sources=result.sources, artifacts=result.artifacts, error_code=result.error_code,
            )
        return result


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
            for err in exc.errors()[:3]
        )
    return str(exc)


def build_default_registry() -> ToolRegistry:
    """The production tool set. Imported lazily so the registry module itself
    stays free of connector imports (and their network clients)."""
    from app.domains.model_gateway.tools.calc_tool import CALCULATE_TOOL
    from app.domains.model_gateway.tools.chart_tool import RENDER_CHART_TOOL
    from app.domains.model_gateway.tools.economic_tool import ECONOMIC_INDICATOR_TOOL
    from app.domains.model_gateway.tools.fx_tool import EXCHANGE_RATE_TOOL
    from app.domains.model_gateway.tools.market_tool import MARKET_DATA_TOOL

    registry = ToolRegistry()
    for spec in (EXCHANGE_RATE_TOOL, ECONOMIC_INDICATOR_TOOL, MARKET_DATA_TOOL, CALCULATE_TOOL, RENDER_CHART_TOOL):
        registry.register(spec)
    return registry

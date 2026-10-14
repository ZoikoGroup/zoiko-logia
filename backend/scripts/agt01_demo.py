"""ZL-ENG-AGT-01 §13/§14 demonstrations, runnable offline.

    cd backend && .venv/bin/python scripts/agt01_demo.py

Uses the real tool registry, calculator, chart tool, per-step policy and
figure reconciliation. The model is scripted (no provider call, no API key),
so every run is reproducible and the trace shows exactly what the controls
did. Synthetic data only.

Demo A  multi-step run: two calculations, a difference and a chart, with the
        per-step policy decision and the stop reason for each call.
Demo B  verified calculation and chart (12.0% / 12.5% / +0.5 pp), then the
        failure variants: zero denominator, missing revenue, mismatched
        currencies, an answer with an invented figure, and a user from
        another tenant.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.model_gateway.agent import AgentLimits, run_agent  # noqa: E402
from app.domains.model_gateway.tool_registry import build_default_registry, decide  # noqa: E402
from app.orchestration.calculations.engine import calculate_from_query  # noqa: E402
from app.orchestration.figure_reconciliation import unreconciled_figures  # noqa: E402

QUESTION = ("Compare FY2024 and FY2025 operating margins for Company A and chart the trend. "
            "FY2024: operating profit 120,000, revenue 1,000,000. "
            "FY2025: operating profit 150,000, revenue 1,200,000. (Synthetic data.)")
ROLE = "Admin"


def _call(call_id: str, name: str, args: dict):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _reply(content: str = "", calls=None, tokens: int = 400):
    message = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=tokens))


class ScriptedModel:
    """Stands in for the provider: returns the scripted replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_):
        return self.replies.pop(0)


def _authorizer(registry, *, same_tenant: bool = True):
    async def authorize(tool: str):
        return decide(registry.get(tool), tool, role=ROLE, active=True, same_tenant=same_tenant,
                      role_unchanged=True, permissions=frozenset())
    return authorize


def _trace(outcome) -> None:
    for record in outcome.tool_calls:
        status = "ok" if record.ok else f"refused: {record.error_code}"
        print(f"  step {record.step}  {record.tool:<16} policy={record.policy_reason or '-':<20}"
              f" decision={record.policy_decision_id or '-'}  {status}")
    print(f"  stop reason: {outcome.stop_reason}   tokens: {outcome.tokens_used}   charts: {len(outcome.artifacts)}")


CHART = {"type": "line", "title": "Company A operating margin (%)", "categories": ["FY2024", "FY2025"],
         "series": [{"name": "Operating margin %", "data": [12.0, 12.5]}]}


async def demo_a_multi_step() -> None:
    print("\nDemo A: multi-step run with per-step policy (QA demonstration 2)")
    registry = build_default_registry()
    model = ScriptedModel([
        _reply(calls=[_call("c1", "calculate", {"expression": "120000 / 1000000 * 100", "label": "FY2024 operating margin (%)"}),
                      _call("c2", "calculate", {"expression": "150000 / 1200000 * 100", "label": "FY2025 operating margin (%)"})]),
        _reply(calls=[_call("c3", "calculate", {"expression": "12.5 - 12.0", "label": "Change (percentage points)"})]),
        _reply(calls=[_call("c4", "render_chart", CHART)]),
        _reply("Operating margin rose from 12.0% in FY2024 to 12.5% in FY2025, up 0.5 pp."),
    ])
    outcome = await run_agent(model, model="scripted", system_prompt="", user_prompt=QUESTION,
                              registry=registry, granted_permissions=frozenset(), limits=AgentLimits(),
                              authorize=_authorizer(registry))
    _trace(outcome)
    print("  answer:", outcome.text.split("```")[0].strip())
    print("  figures without a source:", outcome.unreconciled_figures or "none")


async def demo_b_failures() -> None:
    print("\nDemo B: verified calculation and failure variants (QA demonstration 3)")
    registry = build_default_registry()

    print("  1. Zero denominator:")
    result = await registry.execute("calculate", {"expression": "120000 / 0"}, granted_permissions=frozenset())
    print("     ->", result.error_code, "-", result.content[:90])

    print("  2. Revenue missing, model invents a margin:")
    model = ScriptedModel([_reply("FY2024 margin was 12.0%."), _reply("FY2024 margin was 12.0%.")])
    outcome = await run_agent(model, model="scripted", system_prompt="", registry=registry,
                              user_prompt="FY2024 operating profit was 120,000. What was the operating margin?",
                              granted_permissions=frozenset())
    print("     -> withheld:", bool(outcome.unreconciled_figures), "| unsupported:", outcome.unreconciled_figures)

    print("  3. Mismatched currencies:")
    mixed = calculate_from_query("Revenue ₹500,000 and expenses $4,000. Calculate profit margin.")
    print("     ->", mixed.status, mixed.error_code)

    print("  4. An invented figure in otherwise correct prose:")
    print("     -> unsupported:", unreconciled_figures("Margin rose from 12.0% to 13.4%.", QUESTION))

    print("  5. A user from another tenant:")
    model = ScriptedModel([
        _reply(calls=[_call("c1", "calculate", {"expression": "120000 / 1000000 * 100"})]),
        _reply("No figures could be produced."),
    ])
    outcome = await run_agent(model, model="scripted", system_prompt="", user_prompt=QUESTION, registry=registry,
                              granted_permissions=frozenset(), authorize=_authorizer(registry, same_tenant=False))
    _trace(outcome)


async def main() -> None:
    await demo_a_multi_step()
    await demo_b_failures()


if __name__ == "__main__":
    asyncio.run(main())

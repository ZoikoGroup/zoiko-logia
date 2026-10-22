"""Live shadow hook for the intent planner (intent_planner.py).

Off unless KRITON_PLANNER_SHADOW=true. When on, the planner is started in the
background once a request has passed the safety pre-screen and the
certification check, and when the response is finalised its proposal is
compared with what the router actually did. The request never awaits any of
it and never sees its failures; the comparison is written to the
"kriton.planner.shadow" log and logs/planner-shadow.jsonl, with a hash of
the question and no question or answer text. No audit event, database row,
tool call or response field is produced or changed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.orchestration import intent_planner

logger = logging.getLogger("kriton.planner.shadow")
_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "planner-shadow.jsonl"
_PLAN_WAIT_SECONDS = 30.0
_inflight: set[asyncio.Task] = set()


def enabled() -> bool:
    return os.getenv("KRITON_PLANNER_SHADOW", "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Handle:
    task: asyncio.Task
    query_id: str
    fingerprint: str
    started: float


def _keep(task: asyncio.Task) -> None:
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _plan(query: str, history: list | None, role: str, has_documents: bool) -> intent_planner.PlanResult:
    result = await intent_planner.propose_plan(query, history, has_documents=has_documents)
    return intent_planner.apply_policy_invariants(result, query, role=role)


def start(query: str, history: list | None, *, query_id: str, role: str, has_documents: bool = False) -> Optional[Handle]:
    """Begin planning in the background. None when shadow mode is off."""
    if not enabled():
        return None
    try:
        task = asyncio.create_task(_plan(query, history, role, has_documents))
        _keep(task)
        return Handle(task, query_id, intent_planner.query_fingerprint(query), time.monotonic())
    except Exception:  # noqa: BLE001 — never surfaces to the request
        logger.warning("planner_shadow_start_failed", extra={"query_id": query_id})
        return None


def finish(handle: Optional[Handle], *, route: str | None, outcome: str | None, answer_text: str,
           planned_tools: list[str], planned_reasons: list[str], executed_tools: list[str],
           formulas: list[str], has_chart: bool, has_documents: bool) -> None:
    """Record what the router did and log the comparison in the background."""
    if handle is None:
        return
    try:
        router = intent_planner.router_intent(
            route=route, outcome=outcome, answer_text=answer_text,
            # What ran, as the benchmark derives it; the rule plan's own tool
            # list can name tools the agent never called.
            tools=set(executed_tools), planned_reasons=planned_reasons,
            formulas=formulas, has_chart=has_chart, has_documents=has_documents)
        facts = {"route": route, "outcome": outcome, "router_intent": router, "planned_tools": planned_tools,
                 "executed_tools": executed_tools, "request_ms": round((time.monotonic() - handle.started) * 1000)}
        _keep(asyncio.create_task(_compare_and_log(handle, facts)))
    except Exception:  # noqa: BLE001
        logger.warning("planner_shadow_finish_failed", extra={"query_id": handle.query_id})


async def _compare_and_log(handle: Handle, facts: dict) -> None:
    try:
        result = await asyncio.wait_for(asyncio.shield(handle.task), _PLAN_WAIT_SECONDS)
        record = {
            "query_id": handle.query_id, "query_fingerprint": handle.fingerprint, **facts,
            "planner_latency_ms": round(result.latency_ms), "planner_tokens": result.tokens,
            "planner_failure": result.failure, "invariants_applied": result.invariants_applied,
            **intent_planner.compare(result.plan, router=facts["router_intent"],
                                     router_tools=facts["executed_tools"] or facts["planned_tools"]),
            "planner_plan": result.plan.model_dump() if result.plan else None,
        }
        logger.info("planner_shadow", extra={"planner_shadow": record})
        await asyncio.to_thread(_append, record)
    except Exception:  # noqa: BLE001 — shadow mode must be invisible to requests
        logger.warning("planner_shadow_failed", extra={"query_id": handle.query_id})


def _append(record: dict) -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_FILE.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

"""Recorded multi-step runs against the REAL model and tools
(ZL-ENG-AGT-01 §02 "what we need to verify", §04 P0 deliverable).

    cd backend && .venv/bin/python scripts/agt01_live_demo.py --email you@example.com

Runs the governed agent loop with the configured provider (Groq), the real
tool registry, the per-step policy (from the user's stored record), the
knowledge base under that user's tenant and RLS identity, and the figure
check. Writes the full trace to docs/agt01/evidence/live_run_<timestamp>.json:
the plan, every tool call with its policy decision, planned/unplanned flag,
outcome and calculation receipt, the stop reason, tokens, sources and the
final answer. Uses synthetic figures only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

DEMOS = {
    "A_research": ("What is the UK VAT registration threshold, and how much VAT at the standard rate is due "
                   "on £120,000 of standard-rated sales? Cite the official source."),
    "B_calculation_chart": ("Company A (synthetic data): FY2024 operating profit 120,000 on revenue 1,000,000; "
                            "FY2025 operating profit 150,000 on revenue 1,200,000. Compare the operating margins, "
                            "give the change in percentage points, and chart the trend."),
}


async def run_one(name: str, question: str, user) -> dict:
    from app.domains.identity.permissions import permissions_for_role
    from app.domains.model_gateway import service as gateway
    from app.domains.model_gateway.agent import with_agent_instructions
    from app.domains.model_gateway.tool_registry import decide
    from app.orchestration.agent_plan import plan_request
    from app.orchestration.governed_retrieval import GovernedRetrievalContext, bind_context, reset_context
    from app.domains.command_center.service import scoped_session

    plan = plan_request(question)
    registry = gateway.tool_registry()
    trace: list[dict] = []

    async def authorize(tool: str):
        return decide(registry.get(tool), tool, role=user.role, active=user.is_active, same_tenant=True,
                      role_unchanged=True, permissions=permissions_for_role(user.role))

    async def on_done(record):
        trace.append(asdict(record))

    async with scoped_session(user) as db:
        token = bind_context(GovernedRetrievalContext(db=db, tenant_id=user.tenant_id, user_id=user.id,
                                                     query_id=f"live-{name}", jurisdiction="", framework="",
                                                     effective_date=None))
        try:
            started = datetime.now(timezone.utc)
            outcome = await gateway.run_agentic_completion(
                with_agent_instructions(question) + plan.as_prompt(),
                granted_permissions=permissions_for_role(user.role), on_tool_done=on_done,
                chart_requested="chart" in question.lower(), authorize=authorize,
                request_id=f"live-{name}", planned_tools=plan.tools,
            )
        finally:
            reset_context(token)
    return {
        "demo": name, "question": question, "started_at": started.isoformat(),
        "model": gateway.GROQ_DEFAULT_MODEL, "plan": plan.summary(),
        "tool_calls": trace,
        "stop_reason": outcome.stop_reason, "steps": outcome.steps, "tokens_used": outcome.tokens_used,
        "calculation_receipts": outcome.calculation_receipts,
        "unreconciled_figures": outcome.unreconciled_figures,
        "sources": [{"title": s.title, "url": s.url} for s in outcome.sources],
        "charts": len(outcome.artifacts),
        "answer": outcome.text,
    }


async def main(email: str) -> Path:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.domains.identity.models import User
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        if user is None:
            raise SystemExit(f"No user {email}")
        db.expunge(user)
    runs = [await run_one(name, question, user) for name, question in DEMOS.items()]
    out = BACKEND.parent / "docs" / "agt01" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"live_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"directive": "ZL-ENG-AGT-01 §02/§04", "runs": runs}, indent=2, default=str))
    for run in runs:
        print(f"\n== {run['demo']}: plan {run['plan']['planned_tools']}")
        for call in run["tool_calls"]:
            print(f"   step {call['step']} {call['tool']:<22} policy={call['policy_reason']:<10} "
                  f"planned={call['planned']} ok={call['ok']} {call['error_code'] or ''}")
        print(f"   stop={run['stop_reason']} tokens={run['tokens_used']} sources={len(run['sources'])} "
              f"charts={run['charts']} unsupported_figures={run['unreconciled_figures']}")
        print("   answer:", run["answer"].split("```")[0].strip()[:400].replace("\n", " "))
    print(f"\nTrace written to {path}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="An existing user whose role and tenant the run uses")
    asyncio.run(main(parser.parse_args().email))

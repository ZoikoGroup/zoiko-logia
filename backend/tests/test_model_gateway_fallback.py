"""
Model gateway provider fallback + cost/latency governance — before this,
model_gateway/service.py's _select_adapter() picked exactly one provider
(first configured) with no fallback if that provider's actual API call
failed at request time: a live outage would surface as a raw
"[Error connecting to ... API: ...]" string treated as the model's own
answer, and any OTHER configured provider was never attempted.

Run with: python tests/test_model_gateway_fallback.py
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.database import AsyncSessionLocal
from app.domains.model_gateway import cost_latency_governance
from app.domains.model_gateway.routing_fallback import complete_with_fallback
from app.domains.model_gateway.service import run_test_prompt
from sqlalchemy import text


class _FailingAdapter:
    async def complete(self, prompt: str) -> str:
        return "[Error: simulated provider outage]"


class _RaisingAdapter:
    async def complete(self, prompt: str) -> str:
        raise RuntimeError("simulated network exception")


class _WorkingAdapter:
    async def complete(self, prompt: str) -> str:
        return "a real completion"


async def test_falls_through_to_next_provider_on_string_error():
    result = await complete_with_fallback("q", [("primary", _FailingAdapter()), ("backup", _WorkingAdapter())])
    assert result.succeeded is True
    assert result.provider_used == "backup"
    assert result.attempts == ["primary", "backup"]
    print("test_falls_through_to_next_provider_on_string_error: PASSED")


async def test_falls_through_to_next_provider_on_raised_exception():
    """An adapter that raises (not just returns an error string) must still
    trigger fallback, not propagate and break the whole request."""
    result = await complete_with_fallback("q", [("primary", _RaisingAdapter()), ("backup", _WorkingAdapter())])
    assert result.succeeded is True
    assert result.provider_used == "backup"
    print("test_falls_through_to_next_provider_on_raised_exception: PASSED")


async def test_all_providers_failing_returns_last_failure_not_an_exception():
    result = await complete_with_fallback("q", [("a", _FailingAdapter()), ("b", _FailingAdapter())])
    assert result.succeeded is False
    assert result.output.startswith("[Error")
    print("test_all_providers_failing_returns_last_failure_not_an_exception: PASSED")


def test_cost_estimate_scales_with_length_and_is_nonnegative():
    short_cost = cost_latency_governance.estimate_cost_usd("groq", "hi", "hi")
    long_cost = cost_latency_governance.estimate_cost_usd("groq", "hi" * 10000, "hi" * 10000)
    assert short_cost >= 0 and long_cost >= 0
    assert long_cost > short_cost, "a longer prompt/output must estimate a higher cost"
    print("test_cost_estimate_scales_with_length_and_is_nonnegative: PASSED")


async def test_run_test_prompt_records_fallback_and_cost_fields():
    """End-to-end against the real DB and a real provider — confirms the
    live path (not just the unit-level fallback logic) actually records
    the new audit fields."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(text("SELECT id FROM prompt_templates LIMIT 1"))
        prompt_row = row.fetchone()
        if prompt_row is None:
            print("test_run_test_prompt_records_fallback_and_cost_fields: SKIPPED (no prompt_templates seeded)")
            return
        tenant_id = f"test-tenant-gw-{uuid.uuid4().hex[:8]}"
        await run_test_prompt(db, prompt_row[0], "regression test query for gateway fallback", tenant_id=tenant_id)

        result = await db.execute(
            text("SELECT payload FROM audit_events WHERE event_name = 'model_run_completed' "
                 "AND tenant_id = :tid ORDER BY event_time DESC LIMIT 1"),
            {"tid": tenant_id},
        )
        event_row = result.fetchone()
        assert event_row is not None, "run_test_prompt must record a model_run_completed audit event"
        payload = event_row[0]
        for field in ("provider_attempts", "fallback_occurred", "succeeded", "latency_ms", "estimated_cost_usd"):
            assert field in payload, f"missing new field {field!r} in model_run_completed payload"
        print("test_run_test_prompt_records_fallback_and_cost_fields: PASSED")


async def main():
    await test_falls_through_to_next_provider_on_string_error()
    await test_falls_through_to_next_provider_on_raised_exception()
    await test_all_providers_failing_returns_last_failure_not_an_exception()
    test_cost_estimate_scales_with_length_and_is_nonnegative()
    await test_run_test_prompt_records_fallback_and_cost_fields()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

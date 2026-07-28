"""
Model Gateway per-model registry routing — proves _select_model_and_adapter
is real ModelDefinition-driven selection, not flat first-provider-wins, and
that every skip path (not implemented / not configured / not Active) is
distinguishable, plus the bottom-rung fallback still works when the
registry can't resolve anything.

Each test creates its own disposable rows and deletes only what it created
(not a full-table wipe) — this may run against an already-seeded dev DB.

Run locally (from backend/, venv active):
    python3 tests/test_model_gateway_routing.py
"""
import asyncio
import os
import sys
import uuid
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.domains.identity.models import Tenant, User
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.model_gateway.service import _select_model_and_adapter, run_test_prompt
from app.domains.audit_ledger.models import AuditEvent
from sqlalchemy import select


async def _make_model(db, *, role, provider, status="Active") -> ModelDefinition:
    row = ModelDefinition(
        name=f"Test Model {uuid.uuid4().hex[:8]}", role=role, provider=provider,
        environment="Production", version="v-test", status=status,
    )
    db.add(row)
    await db.flush()
    return row


async def _cleanup_models(db, *rows) -> None:
    for row in rows:
        await db.delete(row)
    await db.commit()


async def test_provider_preference_order_within_same_role():
    async with AsyncSessionLocal() as db:
        openai_row = await _make_model(db, role="Primary reasoning model", provider="openai")
        groq_row = await _make_model(db, role="Primary reasoning model", provider="groq")
        await db.commit()

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "OPENAI_API_KEY": "test-key"}):
            selection = await _select_model_and_adapter(db)

        assert selection.model is not None
        # Asserts on provider, not this test's specific row id: a real
        # Active groq row may already exist in the registry (e.g. the
        # backfilled production row) alongside this test's own groq_row,
        # tying on (role_rank, provider_rank) — either groq row winning is
        # correct behavior, only an openai (or other) row winning would be
        # a real failure.
        assert selection.model.provider == "groq", "groq must be preferred over openai per _PROVIDER_PREFERENCE_ORDER"
        assert selection.selection_path == "registry"

        await _cleanup_models(db, openai_row, groq_row)
    print("test_provider_preference_order_within_same_role: PASSED")


async def test_active_implemented_row_beats_active_unimplemented_row():
    async with AsyncSessionLocal() as db:
        # Higher role-rank (Primary) but unimplemented provider — must be
        # skipped, not crash, not silently "win" by ranking alone. Uses
        # provider="mock" as the guaranteed-reachable winner (MockProviderAdapter
        # is always "configured" regardless of env vars — see
        # _adapter_is_configured) and pops both real provider keys, so this
        # is deterministic regardless of any other real/pre-existing
        # registry rows: any competing real groq/openai row gets skipped
        # for "not configured" (no key), never for the wrong reason.
        anthropic_row = await _make_model(db, role="Primary reasoning model", provider="anthropic")
        mock_row = await _make_model(db, role="Secondary / fallback model", provider="mock")
        await db.commit()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            selection = await _select_model_and_adapter(db)

        assert selection.model is not None
        assert selection.model.id == mock_row.id, (
            f"expected the mock row to win (always configured, unreachable by any real key); "
            f"got model={selection.model}, skip_trace={selection.skip_trace}"
        )
        assert selection.selection_path == "registry"
        assert any(
            anthropic_row.id in reason and "not implemented" in reason for reason in selection.skip_trace
        ), f"expected this test's anthropic row to be skipped as not-implemented; skip_trace={selection.skip_trace}"

        await _cleanup_models(db, anthropic_row, mock_row)
    print("test_active_implemented_row_beats_active_unimplemented_row: PASSED")


async def test_testing_status_row_is_skipped():
    async with AsyncSessionLocal() as db:
        # provider="mock" specifically: mock is always "configured"
        # regardless of env vars, so the only thing that can prevent it
        # winning is its Testing status — isolates the assertion from
        # whether any real groq/openai/anthropic row happens to also be
        # present. Both real API keys are popped so any pre-existing real
        # Active row is skipped for lack of config, not a false win.
        testing_row = await _make_model(db, role="Primary reasoning model", provider="mock", status="Testing")
        await db.commit()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            selection = await _select_model_and_adapter(db)

        assert selection.model is None, "a Testing-status row must never be the winning selection"
        assert selection.selection_path == "fallback_chain"
        assert any(
            testing_row.id in reason and "not Active" in reason for reason in selection.skip_trace
        ), f"expected this test's Testing row to be skipped as not-Active; skip_trace={selection.skip_trace}"

        await _cleanup_models(db, testing_row)
    print("test_testing_status_row_is_skipped: PASSED")


async def test_fallback_chain_used_when_registry_has_no_answering_candidate():
    async with AsyncSessionLocal() as db:
        # A row that exists but isn't in _ANSWERING_ROLES at all (e.g. an
        # embeddings model) must never be considered a candidate.
        embedding_row = await _make_model(db, role="Vector search embeddings", provider="self_hosted")
        await db.commit()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            selection = await _select_model_and_adapter(db)

        assert selection.model is None
        assert selection.selection_path == "fallback_chain"
        assert type(selection.adapter).__name__ == "MockProviderAdapter", (
            "with no answering-role candidates and no provider API keys set, "
            "the mock adapter must be the final answer, not an exception"
        )

        await _cleanup_models(db, embedding_row)
    print("test_fallback_chain_used_when_registry_has_no_answering_candidate: PASSED")


async def test_audit_payload_contains_selected_model_definition_id():
    async with AsyncSessionLocal() as db:
        tenant = Tenant(name=f"Routing Test Tenant {uuid.uuid4().hex[:8]}")
        db.add(tenant)
        await db.flush()

        user = User(
            tenant_id=tenant.id,
            email=f"{uuid.uuid4().hex[:8]}@model-gateway-routing-test.local",
            full_name="Routing Test User",
        )
        db.add(user)
        await db.flush()

        model_row = await _make_model(db, role="Primary reasoning model", provider="groq")
        prompt_row = PromptTemplate(
            name="Routing Test Prompt", version="v1.0", status="Approved",
            mode="Workflow", submitted_by=user.id, approved_by=user.id,
        )
        db.add(prompt_row)
        await db.commit()

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=False):
            await run_test_prompt(db, prompt_row.id, "test input", tenant_id="GLOBAL_CONTROL")

        result = await db.execute(
            select(AuditEvent)
            .where(AuditEvent.event_name == "model_run_completed", AuditEvent.subject_id == prompt_row.id)
            .order_by(AuditEvent.ingested_at.desc())
        )
        event = result.scalars().first()
        assert event is not None
        # Doesn't require this test's own model_row specifically to be the
        # winner — a real Active groq row (e.g. the backfilled production
        # row) may tie with it on (role_rank, provider_rank) and win
        # instead, which is equally correct. What matters is that *some*
        # real ModelDefinition.id was recorded (proving registry-driven
        # selection, not the flat fallback chain) and it's a groq row.
        assert event.payload["model_definition_id"] is not None
        assert event.payload["selection_path"] == "registry"
        winning_model = await db.get(ModelDefinition, event.payload["model_definition_id"])
        assert winning_model is not None and winning_model.provider == "groq"

        await db.delete(prompt_row)
        await db.delete(model_row)
        await db.delete(user)
        await db.delete(tenant)
        await db.commit()
    print("test_audit_payload_contains_selected_model_definition_id: PASSED")


async def main():
    await test_provider_preference_order_within_same_role()
    await test_active_implemented_row_beats_active_unimplemented_row()
    await test_testing_status_row_is_skipped()
    await test_fallback_chain_used_when_registry_has_no_answering_candidate()
    await test_audit_payload_contains_selected_model_definition_id()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

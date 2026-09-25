import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.model_gateway import service
from app.domains.model_gateway.models import ModelDefinition, ModelRun
from app.domains.model_gateway.policy import deployment_eligibility, eligible_deployments
from app.domains.model_gateway.schemas import GatewayContext
from app.domains.model_gateway.schemas import ModelDefinitionCreate, ModelDefinitionUpdate
from fastapi import HTTPException

def _context(**updates) -> GatewayContext:
    values = {
        "tenant_id": "tenant-1",
        "actor_id": "user-1",
        "correlation_id": "corr-1",
        "task_type": "policy_research",
        "data_classification": "CONFIDENTIAL",
        "processing_region": "uk",
        "requested_tools": [],
        "model_transmission_allowed": True,
        "retrieval_version": "source-passages-lexical-v1",
    }
    values.update(updates)
    return GatewayContext(**values)


def _deployment(identifier: str, provider: str, priority: int = 10, **updates) -> ModelDefinition:
    values = {
        "id": identifier,
        "name": f"{provider}-approved-model",
        "role": "answer",
        "environment": "Production",
        "version": "v1",
        "status": "Approved",
        "provider": provider,
        "deployment_region": "uk",
        "permitted_data_classes": ["INTERNAL", "CONFIDENTIAL"],
        "supported_task_types": ["policy_research"],
        "allowed_tools": [],
        "retention_policy": "zero-retention",
        "training_opt_out": True,
        "evaluation_manifest_id": "eval-1",
        "policy_version": "f7.1",
        "priority": priority,
        "enabled": True,
    }
    values.update(updates)
    return ModelDefinition(**values)


def test_eligibility_denies_each_unapproved_boundary(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.model_gateway.policy.provider_is_configured", lambda _: True)
    assert deployment_eligibility(
        _deployment("d1", "groq", permitted_data_classes=["PUBLIC"]), _context()
    ).reason_code == "DATA_CLASS_NOT_PERMITTED"
    assert deployment_eligibility(
        _deployment("d2", "groq", deployment_region="us"), _context()
    ).reason_code == "REGION_NOT_PERMITTED"
    assert deployment_eligibility(
        _deployment("d3", "groq", allowed_tools=[]),
        _context(requested_tools=["web.search"]),
    ).reason_code == "TOOLS_NOT_PERMITTED"
    assert deployment_eligibility(
        _deployment("d4", "groq"), _context(model_transmission_allowed=False)
    ).reason_code == "MODEL_TRANSMISSION_DENIED"


def test_selection_is_deterministic_and_filters_every_fallback(monkeypatch) -> None:
    monkeypatch.setattr("app.domains.model_gateway.policy.provider_is_configured", lambda _: True)
    denied = _deployment("denied", "openai", priority=1, deployment_region="us")
    second = _deployment("second", "groq", priority=20)
    first = _deployment("first", "gemini", priority=10)
    rows, reasons = eligible_deployments([second, denied, first], _context())
    assert [row.id for row in rows] == ["first", "second"]
    assert reasons["denied"] == "REGION_NOT_PERMITTED"


@pytest.mark.asyncio
async def test_execution_uses_eligible_fallback_and_persists_manifest(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    class FailingAdapter:
        async def complete(self, prompt: str, model: str | None = None) -> str:
            return "[Error connecting to provider: quota exceeded]"

    class WorkingAdapter:
        async def complete(self, prompt: str, model: str | None = None) -> str:
            return "governed answer"

    monkeypatch.setattr("app.domains.model_gateway.policy.provider_is_configured", lambda _: True)
    monkeypatch.setattr(
        service, "_adapter_for_provider",
        lambda provider: FailingAdapter() if provider == "gemini" else WorkingAdapter(),
    )

    async with sessions() as db:
        db.add_all([
            _deployment("primary", "gemini", priority=1),
            _deployment("fallback", "groq", priority=2),
        ])
        await db.commit()
        result = await service.run_policy_completion(db, "prompt", _context())
        assert result.output_text == "governed answer"
        assert result.deployment_id == "fallback"
        assert [attempt.outcome for attempt in result.attempts] == ["failed", "completed"]
        rows = list((await db.execute(__import__("sqlalchemy").select(ModelRun))).scalars())
        assert len(rows) == 1
        assert rows[0].output_hash
        assert rows[0].attempts[0]["reason_code"] == "PROVIDER_RATE_LIMITED"
        assert rows[0].retrieval_version == "source-passages-lexical-v1"
    await engine.dispose()


@pytest.mark.asyncio
async def test_no_eligible_deployment_fails_closed_and_records_decision(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.domains.model_gateway.policy.provider_is_configured", lambda _: True)

    async with sessions() as db:
        db.add(_deployment("public-only", "groq", permitted_data_classes=["PUBLIC"]))
        await db.commit()
        with pytest.raises(service.GatewayUnavailableError) as exc:
            await service.run_policy_completion(db, "secret prompt", _context())
        assert exc.value.reason_code == "NO_ELIGIBLE_DEPLOYMENT"
        rows = list((await db.execute(__import__("sqlalchemy").select(ModelRun))).scalars())
        assert rows[0].status == "unavailable"
        assert rows[0].output_hash is None
        assert "DATA_CLASS_NOT_PERMITTED" in (rows[0].error_detail or "")
    await engine.dispose()


@pytest.mark.asyncio
async def test_registry_approval_is_maker_checker_and_edits_revoke_approval() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    payload = ModelDefinitionCreate(
        name="approved-model", provider="groq", deployment_region="uk",
        permitted_data_classes=["INTERNAL"],
        supported_task_types=["general_question"],
        retention_policy="zero-retention", training_opt_out=True,
        evaluation_manifest_id="eval-1",
    )
    async with sessions() as db:
        row = await service.register_model(db, payload, "maker")
        assert row.status == "PendingReview" and not row.enabled
        with pytest.raises(HTTPException) as exc:
            await service.approve_model(db, row.id, "maker")
        assert exc.value.status_code == 403
        row = await service.approve_model(db, row.id, "checker")
        assert row.status == "Approved" and row.enabled
        row = await service.update_model(
            db, row.id, ModelDefinitionUpdate(priority=5), "editor"
        )
        assert row.status == "PendingReview" and not row.enabled
        assert row.approved_by is None
    await engine.dispose()

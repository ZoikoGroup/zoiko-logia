from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.permissions import MODEL_MANAGE
from app.domains.identity.rbac import require_permission
from app.domains.model_gateway.schemas import (
    ModelDefinitionPublic,
    PromptTemplatePublic,
    TestRunRequest,
    TestRunResponse,
)
from app.domains.model_gateway import registry_view
from app.domains.model_gateway.errors import ProviderRequestRejected
from app.domains.model_gateway.service import approve_prompt, list_models, list_prompts, run_test_prompt

router = APIRouter(tags=["model_gateway"])


@router.get("/models", response_model=list[ModelDefinitionPublic])
async def get_models(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> list[ModelDefinitionPublic]:
    models = await list_models(db)
    return [ModelDefinitionPublic.model_validate(m) for m in models]


@router.get("/prompts", response_model=list[PromptTemplatePublic])
async def get_prompts(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> list[PromptTemplatePublic]:
    prompts = await list_prompts(db)
    return [PromptTemplatePublic.model_validate(p) for p in prompts]


@router.post("/prompts/{prompt_id}/approve", response_model=PromptTemplatePublic)
async def post_approve_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> PromptTemplatePublic:
    prompt = await approve_prompt(db, actor.id, prompt_id, tenant_id=actor.tenant_id)
    return PromptTemplatePublic.model_validate(prompt)


@router.post("/model-gateway/test-run", response_model=TestRunResponse)
async def post_test_run(
    payload: TestRunRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> TestRunResponse:
    try:
        prompt, output = await run_test_prompt(db, payload.prompt_id, payload.input_text, actor.id, tenant_id=actor.tenant_id)
    except ProviderRequestRejected as exc:
        raise HTTPException(status_code=503, detail=exc.user_message) from None
    return TestRunResponse(prompt_id=prompt.id, prompt_name=prompt.name, output_text=output)


@router.get("/model-gateway/registry")
async def get_registry_overview(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> dict:
    """Models each runtime role really uses, registry matches and usage."""
    return await registry_view.registry_overview(db, tenant_id=actor.tenant_id)


@router.get("/model-gateway/system-instructions")
async def get_system_instructions(actor: User = Depends(require_permission(MODEL_MANAGE))) -> list[dict]:
    """The system prompts the answer path sends, with content fingerprints."""
    return registry_view.system_instructions()


@router.get("/model-gateway/change-history")
async def get_change_history(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> list[dict]:
    """Prompt approvals from the audit ledger, newest first."""
    return await registry_view.change_history(db, tenant_id=actor.tenant_id)

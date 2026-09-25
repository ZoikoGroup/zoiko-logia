from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.permissions import MODEL_MANAGE
from app.domains.identity.rbac import require_permission
from app.domains.model_gateway.schemas import (
    ModelDefinitionPublic,
    ModelDefinitionCreate,
    ModelDefinitionUpdate,
    ModelRunPublic,
    PromptTemplatePublic,
    TestRunRequest,
    TestRunResponse,
)
from app.domains.model_gateway.service import (
    approve_model, approve_prompt, list_model_runs, list_models, list_prompts,
    register_model, run_test_prompt, update_model,
)

router = APIRouter(tags=["model_gateway"])


@router.get("/models", response_model=list[ModelDefinitionPublic])
async def get_models(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> list[ModelDefinitionPublic]:
    models = await list_models(db)
    return [ModelDefinitionPublic.model_validate(m) for m in models]


@router.post("/models", response_model=ModelDefinitionPublic)
async def post_model(
    payload: ModelDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> ModelDefinitionPublic:
    return ModelDefinitionPublic.model_validate(
        await register_model(db, payload, actor.id, actor.tenant_id)
    )


@router.patch("/models/{model_id}", response_model=ModelDefinitionPublic)
async def patch_model(
    model_id: str,
    payload: ModelDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> ModelDefinitionPublic:
    return ModelDefinitionPublic.model_validate(
        await update_model(db, model_id, payload, actor.id, actor.tenant_id)
    )


@router.post("/models/{model_id}/approve", response_model=ModelDefinitionPublic)
async def post_approve_model(
    model_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> ModelDefinitionPublic:
    return ModelDefinitionPublic.model_validate(
        await approve_model(db, model_id, actor.id, actor.tenant_id)
    )


@router.get("/model-gateway/runs", response_model=list[ModelRunPublic])
async def get_model_runs(
    correlation_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MODEL_MANAGE)),
) -> list[ModelRunPublic]:
    rows = await list_model_runs(
        db, tenant_id=actor.tenant_id, correlation_id=correlation_id,
    )
    return [ModelRunPublic.model_validate(row) for row in rows]


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
    prompt, output = await run_test_prompt(db, payload.prompt_id, payload.input_text, actor.id, tenant_id=actor.tenant_id)
    return TestRunResponse(prompt_id=prompt.id, prompt_name=prompt.name, output_text=output)

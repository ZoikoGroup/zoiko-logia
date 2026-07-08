from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.domains.model_gateway.schemas import (
    ModelDefinitionPublic,
    PromptTemplatePublic,
    TestRunRequest,
    TestRunResponse,
)
from app.domains.model_gateway.service import approve_prompt, list_models, list_prompts, run_test_prompt

router = APIRouter(tags=["model_gateway"])


@router.get("/models", response_model=list[ModelDefinitionPublic])
async def get_models(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[ModelDefinitionPublic]:
    models = await list_models(db)
    return [ModelDefinitionPublic.model_validate(m) for m in models]


@router.get("/prompts", response_model=list[PromptTemplatePublic])
async def get_prompts(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[PromptTemplatePublic]:
    prompts = await list_prompts(db)
    return [PromptTemplatePublic.model_validate(p) for p in prompts]


@router.post("/prompts/{prompt_id}/approve", response_model=PromptTemplatePublic)
async def post_approve_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> PromptTemplatePublic:
    prompt = await approve_prompt(db, admin.id, prompt_id)
    return PromptTemplatePublic.model_validate(prompt)


@router.post("/model-gateway/test-run", response_model=TestRunResponse)
async def post_test_run(
    payload: TestRunRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TestRunResponse:
    prompt, output = await run_test_prompt(db, payload.prompt_id, payload.input_text)
    return TestRunResponse(prompt_id=prompt.id, prompt_name=prompt.name, output_text=output)

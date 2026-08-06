"""
Ask Kriton™ REST API — ZL-ENG-02 §4.

POST /api/v1/orchestration/ask
Required header: Idempotency-Key: <client-generated-key>

Controls:
  - Authentication context (tenant_id, user_id) resolved from auth; never trusted from body.
  - Idempotency: duplicate Idempotency-Key returns original result without re-execution.
  - Rate limiting: enforced before retrieval or model work.
"""
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.core.rate_limit import limiter
from app.core.supabase_auth import verify_token
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.orchestration.ranking_experiments import check_and_maybe_pause
from app.orchestration.schemas import AskKritonRequest, AskKritonResponse, VisualizationTelemetryRequest
from app.orchestration.service import ask_kriton
from app.orchestration.visualization_telemetry import record_visualization_event
from app.orchestration.visualization_preferences import VisualizationPreferences, get_preferences, put_preferences, reset_preferences
from app.orchestration.visualization_personalization_consent import PersonalizationConsent, get_consent, put_consent, delete_personalization
from app.orchestration.visualization_personalization import PersonalizationSummary, build_personalization_summary, reset_learned_profile
from app.orchestration.visualization_gaps import record_gap_event, VisualizationGapType, DataShapeClass, FallbackOutputType
from app.core.config import get_settings
from app.orchestration.presentation_dataprofile import RANKING_VERSION

router = APIRouter(prefix="/orchestration", tags=["Ask Kriton™ Orchestration"])


@router.get("/visualization-preferences", response_model=VisualizationPreferences)
async def get_visualization_preferences(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await get_preferences(db, current_user.tenant_id, current_user.id)


@router.put("/visualization-preferences", response_model=VisualizationPreferences)
async def update_visualization_preferences(payload: VisualizationPreferences, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await put_preferences(db, current_user.tenant_id, current_user.id, payload)


@router.delete("/visualization-preferences", response_model=VisualizationPreferences)
async def delete_visualization_preferences(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await reset_preferences(db, current_user.tenant_id, current_user.id)


# ── V10 — consent-based visualization personalization (self-service) ───────
# Every endpoint here is scoped to the CALLER's own (tenant_id, actor_id) via
# get_current_user — a user can never read or modify another user's
# personalization consent or learned profile (requirement: SECURITY #1/#2).

@router.get("/visualization-personalization/consent", response_model=PersonalizationConsent)
async def get_visualization_personalization_consent(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await get_consent(db, current_user.tenant_id, current_user.id)


@router.put("/visualization-personalization/consent", response_model=PersonalizationConsent)
async def update_visualization_personalization_consent(
    payload: PersonalizationConsent, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """The only write path for consent — never inferred from usage
    (requirement 4). Disabling here takes effect on the very next request:
    resolve_personalization_hint reads consent live, so there is no
    separate "stop learning" step (requirement 5)."""
    return await put_consent(db, current_user.tenant_id, current_user.id, payload)


@router.get("/visualization-personalization/summary", response_model=PersonalizationSummary)
async def get_visualization_personalization_summary(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Chart-type labels and counts only — never event history (requirement:
    "Do not expose detailed event history")."""
    return await build_personalization_summary(db, current_user.tenant_id, current_user.id)


@router.post("/visualization-personalization/reset", status_code=204)
async def reset_visualization_personalization(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    """DATA RETENTION #3: removes the learned profile only — consent
    settings are untouched, so personalization keeps learning fresh."""
    await reset_learned_profile(db, current_user.tenant_id, current_user.id)


@router.delete("/visualization-personalization", status_code=204)
async def delete_visualization_personalization(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    """The combined "Disable and delete profile" action — removes consent
    AND the learned profile (DATA RETENTION #5)."""
    await delete_personalization(db, current_user.tenant_id, current_user.id)


def _user_key(request: Request) -> str:
    """Rate-limit key: the authenticated user's id, not IP — this is an
    authenticated API and a shared NAT/office IP must not share one bucket."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    claims = verify_token(token) if token else None
    return claims.sub if claims else "anonymous"


@router.post("/ask", response_model=AskKritonResponse)
@limiter.limit("30/minute", key_func=_user_key)
async def post_ask(
    request: Request,
    payload: AskKritonRequest,
    db: AsyncSession = Depends(get_db),
    sync_db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
) -> AskKritonResponse:
    """
    Submit a query to Kriton™. Returns a deterministic route-driven response contract.

    The response outcome/route drives frontend rendering — do not infer state from answer text.
    Internal hashes, policy internals and audit chain material are not exposed (§12).
    """
    return await ask_kriton(
        db,
        sync_db,
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role,
        request=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/visualization-events", status_code=204)
@limiter.limit("120/minute", key_func=_user_key)
async def post_visualization_event(
    request: Request,
    payload: VisualizationTelemetryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Records one client-originated visualization telemetry event (view
    switch, export, save, render failure — see VisualizationTelemetryRequest
    for the exact closed set). tenant_id/actor_id are resolved from auth,
    never trusted from the body, matching /ask. Best-effort: this never
    raises — record_visualization_event swallows its own failures — so a
    telemetry outage can never surface as a user-facing error on this
    endpoint, and the frontend caller (lib/telemetry.ts) doesn't await it
    in a way that could block a chart interaction either way.
    """
    await record_visualization_event(
        db,
        event_name=payload.event_name,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        conversation_id=payload.conversation_id,
        query_id=payload.query_id,
        analytical_intent=payload.analytical_intent,
        original_chart_type=payload.original_chart_type,
        active_chart_type=payload.active_chart_type,
        alternative_count=payload.alternative_count,
        selection_source=payload.selection_source,
        renderer=payload.renderer,
        schema_version=payload.schema_version,
        chart_family=payload.chart_family,
        ranking_version=payload.ranking_version,
        experiment_id=payload.experiment_id,
        experiment_group=payload.experiment_group,
    )
    # v7 — a client-reported render failure is one of the two live
    # "automatic pause trigger" signals (the other is the fallback path in
    # service.py) — see ranking_experiments.check_and_maybe_pause.
    if payload.event_name == "visualization_render_failed" and payload.experiment_id:
        await check_and_maybe_pause(db, payload.experiment_id)
    if payload.event_name == "visualization_render_failed" and payload.active_chart_type:
        await record_gap_event(
            db, tenant_id=current_user.tenant_id, actor_id=current_user.id,
            conversation_id=payload.conversation_id, analytical_intent=payload.analytical_intent,
            requested_chart_type=payload.active_chart_type, gap_type=VisualizationGapType.RENDERER_FAILURE,
            data_shape_class=DataShapeClass.REGISTRY_VALIDATED, fallback_chart_type=None,
            fallback_output_type=FallbackOutputType.TABLE, registry_candidate_count=0,
            ranking_version=payload.ranking_version or RANKING_VERSION, environment=get_settings().APP_ENV.lower(),
        )

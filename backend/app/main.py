from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.database import async_engine, SessionLocal
from app.db.base import Base

settings = get_settings()


def _seed_defaults():
    """Seed default risk policy and refusal templates if tables are empty."""
    db = SessionLocal()
    try:
        from app.domains.risk_safety.models import RiskPolicy, RefusalTemplateRow, RestrictedSubClass

        # Seed a default risk policy if none exists
        if db.query(RiskPolicy).count() == 0:
            db.add(RiskPolicy(
                id="pol-default-v1",
                version="v2026.07.07",
                scope="global",
                owner="ai-risk-committee",
                rules=[
                    {"pattern": "tax filing|tax return|tax treatment", "risk": "HIGH"},
                    {"pattern": "audit opinion|audit report|going concern", "risk": "HIGH"},
                    {"pattern": "legal opinion|legal advice", "risk": "HIGH"},
                    {"pattern": "journal entry|worked example", "risk": "MEDIUM"},
                    {"pattern": "solve exam|exam answer", "risk": "RESTRICTED"},
                    {"pattern": "jailbreak|ignore instructions", "risk": "RESTRICTED"},
                ],
                approver="system-init",
            ))

        # Seed refusal templates from the in-memory registry
        if db.query(RefusalTemplateRow).count() == 0:
            from app.domains.risk_safety.refusal_templates import get_all_templates
            for tpl in get_all_templates():
                sub = tpl.get("restricted_sub_class")
                db.add(RefusalTemplateRow(
                    id=tpl["template_id"],
                    template_type="refusal" if sub else "limitation",
                    restricted_sub_class=RestrictedSubClass(sub) if sub else None,
                    title=tpl["title"],
                    body=tpl["body"],
                    safe_alternative=tpl.get("safe_alternative", ""),
                    approved_by="system-init",
                ))

        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: create tables, seed, and dispose of engine."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _seed_defaults()
    yield
    await async_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ZoikoLogia API & Safety Service",
        description="AI Governance, Safety, Risk Classification & Escalation Service.",
        version="1.0.0",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core API endpoints from main branch
    app.include_router(api_v1_router, prefix="/api/v1")

    # Safety-specific API endpoints
    from app.domains.risk_safety.router import router as safety_router
    app.include_router(safety_router, prefix="/api/v1")

    return app


app = create_app()


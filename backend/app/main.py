"""
FastAPI application entrypoint.

Creates app instance, mounts /api/v1 router, startup/shutdown hooks.
Initializes database tables on first boot and seeds default risk policies.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import engine, SessionLocal
from app.db.base import Base

# Import all models so Base.metadata knows about them
from app.domains.risk_safety import models as _risk_models  # noqa: F401

# Import routers
from app.domains.risk_safety.router import router as safety_router


# ─── Lifespan (startup / shutdown) ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup; seed defaults if empty."""
    Base.metadata.create_all(bind=engine)
    _seed_defaults()
    yield
    # Shutdown logic (connection pool cleanup etc.) goes here


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


# ─── App Instance ───────────────────────────────────────────────────────────

app = FastAPI(
    title="ZoikoLogia Safety Service",
    description=(
        "AI Safety, Risk Classification & Escalation Service for Kriton™. "
        "Classifies every request before allowing LLM generation."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS (allow Next.js frontend on :3000) ──────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount routers under /api/v1 ─────────────────────────────────────────────
app.include_router(safety_router, prefix="/api/v1")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "zoikologia-safety"}

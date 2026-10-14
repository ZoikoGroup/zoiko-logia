"""Operations views: what this deployment is actually connected to, and
whether those connections are up right now.

Everything is read from the running configuration or measured live. Secret
values are never returned — only whether a setting is present. Nothing here
is sample data: a component that is not configured says so, and the provider
due-diligence register (not built yet) is reported as "not assessed".
"""
from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.audit_ledger import service as audit_service

CHECK_TIMEOUT_SECONDS = 4.0


def _set(name: str) -> bool:
    """Present and not a .env.example placeholder like "<api-key>"."""
    value = (os.getenv(name) or "").strip()
    return bool(value) and "<" not in value and ">" not in value


def _any(*names: str) -> bool:
    return any(_set(n) for n in names)


def _approved_providers() -> set[str] | None:
    raw = os.getenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "").strip()
    return {p.strip().lower() for p in raw.split(",") if p.strip()} if raw else None


# (key, display name, env vars that configure it, what it is used for, model settings shown)
_MODEL_PROVIDERS = [
    ("groq", "Groq", ("GROQ_API_KEY",), "Answer composition, risk & intent classification, claim verification",
     ("GROQ_MODEL", "GROQ_FAST_ANSWER_MODEL", "GROQ_CLASSIFIER_MODEL", "GROQ_VERIFIER_MODEL")),
    ("google", "Google Gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "Answer composition fallback, risk classification",
     ("GEMINI_MODEL", "GEMINI_CLASSIFIER_MODEL")),
    ("openai", "OpenAI", ("OPENAI_API_KEY",), "Model gateway adapter", ()),
    ("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",), "Model gateway adapter (not implemented yet)", ()),
    ("azure", "Azure OpenAI", ("AZURE_OPENAI_API_KEY",), "Model gateway adapter (not implemented yet)", ()),
]

# (display name, category, env var holding a key or None for keyless public APIs, enable flag or None)
_DATA_SOURCES = [
    ("FRED (St. Louis Fed)", "Economic data", "FRED_API_KEY", None),
    ("Alpha Vantage", "Market data", "ALPHA_VANTAGE_API_KEY", None),
    ("Finnhub", "Market data", "FINNHUB_API_KEY", None),
    ("Polygon", "Market data", "POLYGON_API_KEY", None),
    ("Companies House", "Company filings (UK)", "COMPANIES_HOUSE_API_KEY", None),
    ("Tavily", "Web search", "TAVILY_API_KEY", None),
    ("Yahoo Finance", "Market data", None, "YAHOO_EQUITY_ENABLED"),
    ("DBnomics", "Economic data", None, None),
    ("Frankfurter", "FX rates", None, None),
    ("SEC EDGAR", "Company filings (US)", None, None),
    ("US Treasury", "Fiscal data", None, None),
    ("World Bank", "Economic data", None, None),
    ("Bank of England", "Central bank data", None, None),
    ("Bank of Canada", "Central bank data", None, None),
    ("Reserve Bank of Australia", "Central bank data", None, None),
    ("Australian Bureau of Statistics", "Statistics", None, None),
    ("CSO Ireland", "Statistics", None, None),
    ("GOV.UK / legislation.gov.uk", "Official guidance", None, None),
]


def model_providers() -> list[dict]:
    approved = _approved_providers()
    rows = []
    for key, name, env, purpose, model_vars in _MODEL_PROVIDERS:
        configured = _any(*env)
        rows.append({
            "key": key, "name": name, "configured": configured, "purpose": purpose,
            # None = no allow-list configured, so the gateway does not restrict providers.
            "approved": None if approved is None else key in approved,
            "models": {var: os.getenv(var) for var in model_vars if _set(var)},
            # The Provider Due Diligence Register (ZL-T0-12) is not built yet.
            "dueDiligence": "not_assessed",
        })
    return rows


def data_sources() -> list[dict]:
    rows = []
    for name, category, key_var, flag_var in _DATA_SOURCES:
        if key_var:
            configured, access = _set(key_var), "API key"
        elif flag_var:
            configured, access = (os.getenv(flag_var, "").lower() in {"1", "true", "yes"}), "Public (opt-in)"
        else:
            configured, access = True, "Public, no key"
        rows.append({"name": name, "category": category, "access": access, "configured": configured})
    return rows


def integrations() -> list[dict]:
    s = get_settings()
    storage = os.getenv("OBJECT_STORAGE_PROVIDER") or s.OBJECT_STORAGE_PROVIDER
    return [
        {"name": "Supabase Auth", "purpose": "Sign-in, MFA, invitations",
         "configured": bool(s.SUPABASE_URL) and bool(s.SUPABASE_SERVICE_ROLE_KEY)},
        {"name": "SearXNG", "purpose": "Web search for answers", "configured": _set("SEARXNG_URL")},
        {"name": "Kroki", "purpose": "Diagram rendering", "configured": _set("KROKI_URL")},
        {"name": "Redis / Celery", "purpose": "Background jobs and caches",
         "configured": _any("CELERY_BROKER_URL", "REDIS_URL")},
        {"name": "Answer cache", "purpose": "Repeat-question cache", "configured": _set("ANSWER_CACHE_REDIS_URL")},
        # Always available: "local" means the backend's own disk.
        {"name": "Object storage", "purpose": "Uploaded documents and generated files", "configured": True,
         "detail": "Local disk on the backend server" if storage == "local" else storage},
        {"name": "Embeddings", "purpose": "Semantic retrieval",
         "configured": (os.getenv("EMBEDDING_PROVIDER") or "local").lower() != "none",
         "detail": os.getenv("EMBEDDING_MODEL") or "BAAI/bge-small-en-v1.5"},
        {"name": "ZoikoSuite", "purpose": "Embedded Kriton in accounting workflows", "configured": False,
         "detail": "Integration not built yet"},
    ]


async def _http_check(client: httpx.AsyncClient, name: str, url: str | None, *, headers: dict | None = None) -> dict:
    if not url:
        return {"name": name, "state": "not_configured", "latencyMs": None, "detail": "Not configured"}
    start = time.perf_counter()
    try:
        response = await client.get(url, headers=headers or {})
        latency = round((time.perf_counter() - start) * 1000)
        ok = response.status_code < 500
        return {"name": name, "state": "operational" if ok else "down", "latencyMs": latency,
                "detail": f"HTTP {response.status_code}"}
    except (httpx.HTTPError, OSError) as exc:
        return {"name": name, "state": "down", "latencyMs": None, "detail": type(exc).__name__}


async def _tcp_check(name: str, url: str | None) -> dict:
    if not url:
        return {"name": name, "state": "not_configured", "latencyMs": None, "detail": "Not configured"}
    parsed = urlparse(url)
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(parsed.hostname, parsed.port or 6379), CHECK_TIMEOUT_SECONDS)
        writer.close()
        return {"name": name, "state": "operational", "latencyMs": round((time.perf_counter() - start) * 1000),
                "detail": "Reachable"}
    except (OSError, asyncio.TimeoutError) as exc:
        return {"name": name, "state": "down", "latencyMs": None, "detail": type(exc).__name__}


async def _database_check(db: AsyncSession) -> dict:
    start = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        return {"name": "Database", "state": "operational",
                "latencyMs": round((time.perf_counter() - start) * 1000), "detail": "Query succeeded"}
    except Exception as exc:  # noqa: BLE001 — report, never raise, from a health check
        return {"name": "Database", "state": "down", "latencyMs": None, "detail": type(exc).__name__}


async def status_checks(db: AsyncSession, tenant_id: str) -> list[dict]:
    """Live checks, run concurrently with short timeouts. The model providers
    are reported as configured or not — calling them would spend tokens."""
    s = get_settings()
    supabase_headers = {"apikey": s.SUPABASE_SERVICE_ROLE_KEY} if s.SUPABASE_SERVICE_ROLE_KEY else {}
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
        external = await asyncio.gather(
            _http_check(client, "Supabase Auth",
                        f"{s.SUPABASE_URL.rstrip('/')}/auth/v1/health" if s.SUPABASE_URL else None,
                        headers=supabase_headers),
            _http_check(client, "Web search (SearXNG)", os.getenv("SEARXNG_URL") if _set("SEARXNG_URL") else None),
            _http_check(client, "Diagrams (Kroki)",
                        f"{os.getenv('KROKI_URL', '').rstrip('/')}/health" if _set("KROKI_URL") else None),
            _tcp_check("Redis / Celery", os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL")
                       if _any("CELERY_BROKER_URL", "REDIS_URL") else None),
        )
    checks = [await _database_check(db), *external]
    chain = await audit_service.verify_tenant_chain(db, tenant_id)
    checks.append({"name": "Audit ledger (this workspace)", "state": "operational" if chain["passed"] else "down",
                   "latencyMs": None,
                   "detail": f"Hash chain verified across {chain['events_checked']} event(s)" if chain["passed"]
                   else f"Hash chain broken at {chain['first_broken_event_id']}"})
    configured = [p["name"] for p in model_providers() if p["configured"]]
    checks.append({"name": "AI model providers", "state": "operational" if configured else "down",
                   "latencyMs": None,
                   "detail": ("Configured: " + ", ".join(configured)) if configured else "No provider API key configured"})
    return checks

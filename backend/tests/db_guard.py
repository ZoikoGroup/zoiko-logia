"""Integration tests write tenants, users and sources. They must never run
against a shared or production database: fixtures such as "Tenant A Only Doc"
reached the live Supabase database because the guard was only an opt-in flag,
the modules could also be run as scripts, and DATABASE_URL in backend/.env
points at production."""
from __future__ import annotations

import os
from urllib.parse import urlparse

# Local machines and docker-compose service names.
_ISOLATED_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "db", "test-db", "postgres-test"}


def database_host(url: str | None = None) -> str:
    url = url if url is not None else os.getenv("DATABASE_URL", "")
    return (urlparse(url.replace("+asyncpg", "")).hostname or "").lower()


def integration_db_allowed() -> bool:
    """Opted in AND pointed at a local/containerised database."""
    return os.getenv("RUN_DB_INTEGRATION_TESTS") == "1" and database_host() in _ISOLATED_HOSTS


def require_isolated_database() -> None:
    """For the modules' script entry points, which bypass pytest's skip."""
    host = database_host()
    if host not in _ISOLATED_HOSTS:
        raise SystemExit(
            f"Refusing to write test fixtures to database host {host or '(unset)'}; "
            "point DATABASE_URL at a local or containerised test database."
        )

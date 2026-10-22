"""Passage-cache freshness and isolation across backend processes, on an
isolated PostgreSQL with the production row-level-security policies.

Opt-in: runs only when PASSAGE_CACHE_PG_ADMIN_URL (a superuser) and
PASSAGE_CACHE_PG_APP_URL (a non-superuser, like zoiko_app) point at a
throwaway database, which this test REBUILDS. Never point it at a shared or
production database.

Two worker processes each keep their own cache and query as the app role
under RLS; the test process changes data behind them with raw SQL, as
another backend process, a migration or a script would."""
import asyncio
import hashlib
import multiprocessing
import os
import uuid

import pytest

ADMIN_URL = os.environ.get("PASSAGE_CACHE_PG_ADMIN_URL", "")
APP_URL = os.environ.get("PASSAGE_CACHE_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(not (ADMIN_URL and APP_URL), reason="isolated PostgreSQL not configured")

# The production policies (pg_policies on the hosted database, 2026-10-17), verbatim.
_OWNED_OR_PUBLIC = ("((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR (EXISTS ( SELECT 1 "
                    "FROM (source_versions sv JOIN sources s ON (((s.id)::text = (sv.source_id)::text))) "
                    "WHERE (((sv.id)::text = ({table}.{column})::text) AND (s.is_tenant_private = false))))")
POLICIES = {
    "sources": ("tenant_isolation_sources",
                "((current_setting('app.tenant_id'::text, true) IS NOT NULL) AND (current_setting('app.tenant_id'::text, true) <> ''::text) "
                "AND ((NOT is_tenant_private) OR ((tenant_id)::text = current_setting('app.tenant_id'::text, true))))", None),
    "source_versions": ("tenant_isolation_source_versions",
                        "((current_setting('app.tenant_id'::text, true) IS NOT NULL) AND (current_setting('app.tenant_id'::text, true) <> ''::text) "
                        "AND (((tenant_id)::text = current_setting('app.tenant_id'::text, true)) OR ((source_id)::text IN ( SELECT sources.id "
                        "FROM sources WHERE (NOT sources.is_tenant_private)))))", None),
    "source_passages": ("source_passages_tenant_isolation",
                        _OWNED_OR_PUBLIC.format(table="source_passages", column="source_version_id"),
                        "((tenant_id)::text = current_setting('app.tenant_id'::text, true))"),
    "source_rights": ("source_rights_tenant_isolation",
                      _OWNED_OR_PUBLIC.format(table="source_rights", column="source_version_id"),
                      "((tenant_id)::text = current_setting('app.tenant_id'::text, true))"),
    "source_relationships": ("source_relationships_tenant_isolation",
                             _OWNED_OR_PUBLIC.format(table="source_relationships", column="from_version_id"),
                             "((tenant_id)::text = current_setting('app.tenant_id'::text, true))"),
}
QUERY = "When is revenue from a contract with a customer recognised under IFRS 15?"
TEXT = "Revenue from a contract with a customer is recognised when control of the goods transfers to the customer."


def _worker(connection, app_url: str) -> None:
    """One backend process: its own engine, its own passage cache, the app
    role under RLS. Commands: ("bundle", tenant) and ("texts", tenant, ids)."""
    os.environ.update({"EMBEDDING_PROVIDER": "none", "CLAIM_VERIFICATION": "off"})
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.orchestration import passage_cache as cache_module
    from app.orchestration import retrieve
    cache = cache_module.PassageCache(max_bytes=10_000_000, ttl_seconds=600)
    retrieve.passage_cache = cache
    loads = []
    real = cache_module._load_rows

    async def counting(db, version_ids, **kwargs):
        loads.append(len(version_ids))
        return await real(db, version_ids, **kwargs)
    cache_module._load_rows = counting
    engine = create_async_engine(app_url)
    loop = asyncio.new_event_loop()

    async def run(command):
        kind, tenant, *rest = command
        async with engine.connect() as raw_connection:
            raw = await raw_connection.get_raw_connection()
            await raw.driver_connection.execute(
                "SELECT set_config('app.tenant_id', $1, false), set_config('app.user_id', $2, false)", tenant, "user")
            async with AsyncSession(bind=raw_connection) as db:
                if kind == "bundle":
                    bundle = await retrieve.build_source_bundle(db, query=QUERY, jurisdiction="GB", tenant_id=tenant,
                                                                framework="IFRS")
                    out = [(p.passage_id, p.source_version_id, p.content_hash) for p in bundle.passages]
                else:
                    out = [(p.id, p.content) for p in await cache.load(db, tenant_id=tenant, version_ids=rest[0])]
                await db.rollback()
        return {"result": out, "loads": len(loads), "hits": cache.hits}

    while (command := connection.recv()) is not None:
        try:
            connection.send(loop.run_until_complete(run(command)))
        except Exception as exc:  # report, do not hang the test
            connection.send({"error": f"{type(exc).__name__}: {exc}"})
    loop.run_until_complete(engine.dispose())


class Process:
    def __init__(self):
        context = multiprocessing.get_context("spawn")
        self.pipe, child = context.Pipe()
        self.process = context.Process(target=_worker, args=(child, APP_URL), daemon=True)
        self.process.start()

    def ask(self, *command) -> dict:
        self.pipe.send(command)
        if not self.pipe.poll(60):
            raise TimeoutError("worker did not answer")
        reply = self.pipe.recv()
        assert "error" not in reply, reply["error"]
        return reply

    def stop(self):
        self.pipe.send(None)
        self.process.join(10)


@pytest.fixture(scope="module")
def admin():
    """A synchronous superuser connection to the isolated database, schema rebuilt."""
    from sqlalchemy import create_engine, text

    from app.db.base import Base           # imports every domain's models
    engine = create_engine(ADMIN_URL.replace("+asyncpg", "+psycopg2"))
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        Base.metadata.create_all(connection)
        app_role = APP_URL.split("://", 1)[1].split(":", 1)[0]
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {app_role}"))
        connection.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {app_role}"))
        # The version's maker and checker are real users (foreign keys).
        from sqlalchemy.orm import Session

        from app.domains.identity.models import Tenant, User
        with Session(bind=connection) as session:
            session.add(Tenant(id="tenant-a", name="Tenant A"))
            session.flush()
            for user_id in ("maker", "checker"):
                session.add(User(id=user_id, tenant_id="tenant-a", email=f"{user_id}@example.test", full_name=user_id))
            session.flush()
        for table, (name, qual, check) in POLICIES.items():
            connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            connection.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            connection.execute(text(f"CREATE POLICY {name} ON {table} USING ({qual})"
                                    + (f" WITH CHECK ({check})" if check else "")))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def processes(admin):
    first, second = Process(), Process()
    yield first, second
    first.stop()
    second.stop()


def seed(admin, *, tenant="tenant-a", private=False, text_value=TEXT, title=None):
    from sqlalchemy.orm import Session

    from app.domains.source_library.models import Source
    ids = {key: f"{key}-{uuid.uuid4().hex[:8]}" for key in ("source", "version", "passage")}
    with Session(admin) as session:
        session.add(Source(id=ids["source"], tenant_id=tenant, category="standards",
                           title=title or f"IFRS 15 Revenue {ids['source']}", publisher="Standards Board",
                           owner="Standards Board", source_class="authoritative", jurisdiction_scope="GB",
                           framework_scope="IFRS", authority_level="primary", is_tenant_private=private))
        session.flush()
        add_version(session, ids, tenant)
        add_passage(session, ids["version"], ids["passage"], tenant, text_value)
        session.commit()
    return ids


def add_version(session, ids, tenant, status="ACTIVE"):
    from app.domains.source_library.models import SourceRight, SourceVersion
    session.add(SourceVersion(id=ids["version"], tenant_id=tenant, source_id=ids["source"], version_label="2026",
                              status=status, content_hash=hashlib.sha256(ids["version"].encode()).hexdigest(),
                              submitted_by="maker", approved_by="checker"))
    session.flush()
    for operation in ("retrieval", "model_transmission", "display", "summary"):
        session.add(SourceRight(tenant_id=tenant, source_version_id=ids["version"], operation=operation,
                                decision="allow", rights_version=1, reason_code="TEST_ALLOW"))
    session.flush()


def add_passage(session, version_id, passage_id, tenant, text_value):
    from app.domains.source_library.models import SourcePassage
    session.add(SourcePassage(id=passage_id, tenant_id=tenant, source_version_id=version_id, locator="paragraph 1",
                              sequence=1, content=text_value,
                              content_hash=hashlib.sha256(text_value.encode()).hexdigest(), language="en"))
    session.flush()


def sql(admin, statement, **params):
    from sqlalchemy import text
    with admin.begin() as connection:
        connection.execute(text(statement), params)


def mine(reply, ids):
    return [row for row in reply["result"] if row[1] == ids["version"] or row[0] == ids["passage"]]


def test_a_text_change_made_elsewhere_is_seen_by_both_processes(admin, processes):
    first, second = processes
    ids = seed(admin)
    for process in processes:
        assert mine(process.ask("bundle", "tenant-a"), ids)
    loads_before = [process.ask("bundle", "tenant-a")["loads"] for process in processes]   # warm: no new load
    new = TEXT + " For services, revenue is recognised over time."
    sql(admin, "UPDATE source_passages SET content = :c, content_hash = :h WHERE id = :id",
        c=new, h=hashlib.sha256(new.encode()).hexdigest(), id=ids["passage"])
    for process, before in zip(processes, loads_before):
        reply = process.ask("bundle", "tenant-a")
        assert mine(reply, ids)[0][2] == hashlib.sha256(new.encode()).hexdigest() and reply["loads"] == before + 1


def test_text_changed_without_its_hash_is_not_served_stale(admin, processes):
    first, _ = processes
    ids = seed(admin)
    assert first.ask("texts", "tenant-a", [ids["version"]])["result"][0][1] == TEXT
    same_length = TEXT.replace("goods", "items")                    # same length: only md5 can tell
    assert len(same_length) == len(TEXT)
    sql(admin, "UPDATE source_passages SET content = :c WHERE id = :id", c=same_length, id=ids["passage"])
    assert first.ask("texts", "tenant-a", [ids["version"]])["result"][0][1] == same_length


def test_a_new_source_version_replaces_the_cached_one(admin, processes):
    first, _ = processes
    ids = seed(admin)
    assert mine(first.ask("bundle", "tenant-a"), ids)
    replacement = {**ids, "version": f"version-{uuid.uuid4().hex[:8]}", "passage": f"passage-{uuid.uuid4().hex[:8]}"}
    sql(admin, "UPDATE source_versions SET status = 'SUPERSEDED' WHERE id = :id", id=ids["version"])
    from sqlalchemy.orm import Session
    with Session(admin) as session:
        add_version(session, replacement, "tenant-a")
        add_passage(session, replacement["version"], replacement["passage"], "tenant-a", TEXT + " Updated edition.")
        session.commit()
    result = first.ask("bundle", "tenant-a")["result"]
    assert not mine({"result": result}, ids) and mine({"result": result}, replacement)


def test_a_withdrawn_version_disappears_from_every_process(admin, processes):
    ids = seed(admin)
    for process in processes:
        assert mine(process.ask("bundle", "tenant-a"), ids)
    sql(admin, "UPDATE source_versions SET status = 'WITHDRAWN' WHERE id = :id", id=ids["version"])
    for process in processes:
        assert not mine(process.ask("bundle", "tenant-a"), ids)


def test_a_revoked_right_disappears_from_every_process(admin, processes):
    ids = seed(admin)
    for process in processes:
        assert mine(process.ask("bundle", "tenant-a"), ids)
    sql(admin, "UPDATE source_rights SET decision = 'deny', reason_code = 'REVOKED' "
               "WHERE source_version_id = :id AND operation = 'retrieval'", id=ids["version"])
    for process in processes:
        assert not mine(process.ask("bundle", "tenant-a"), ids)


def test_tenants_are_separated_by_rls_even_with_a_warm_cache(admin, processes):
    first, second = processes
    ids = seed(admin, tenant="tenant-a", private=True)
    assert mine(first.ask("bundle", "tenant-a"), ids)                       # cached in process 1 for tenant A
    assert not mine(first.ask("bundle", "tenant-b"), ids)                   # same process, tenant B: nothing
    assert first.ask("texts", "tenant-b", [ids["version"]])["result"] == []  # even asked directly: RLS hides it
    assert not mine(second.ask("bundle", "tenant-b"), ids)                  # another process, tenant B: nothing


def test_a_private_source_made_public_and_back_is_followed(admin, processes):
    first, _ = processes
    ids = seed(admin, tenant="tenant-a", private=False)
    assert mine(first.ask("bundle", "tenant-b"), ids)                       # public: tenant B may read it
    sql(admin, "UPDATE sources SET is_tenant_private = true WHERE id = :id", id=ids["source"])
    assert not mine(first.ask("bundle", "tenant-b"), ids)                   # made private: gone for B at once

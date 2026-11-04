"""Phase 1 acceptance: isolated storage only, never the configured app database."""
import asyncio
import hashlib
import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base
from app.domains.identity.models import Tenant, User, ServiceAccount
from app.domains.source_library.models import Source, SourceVersion, SourcePassage, SourceRight, ReviewerIdentity, SourceApproval
from app.domains.source_library.service import approve_source_version, add_relationship
from app.domains.audit_ledger.models import AuditEvent
from app.domains.audit_ledger.event_envelope import compute_payload_hash, compute_chain_hash
from app.orchestration.applicability import requested_period
from app.orchestration.retrieve import build_source_bundle


@pytest.fixture(autouse=True)
def _source_review_enforced(monkeypatch):
    # These controls are the strict mode (KRITON_SOURCE_REVIEW_ENFORCEMENT);
    # off, self-approved and undated versions are still used (licensing.py).
    monkeypatch.setenv("KRITON_SOURCE_REVIEW_ENFORCEMENT", "true")


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await seed(db)
        yield db
    await engine.dispose()


async def seed(db):
    db.add(Tenant(id="t", name="test"))
    await db.flush()
    for uid, person in (("maker", "p1"), ("checker", "p2"), ("alias", "p1")):
        db.add(User(id=uid, tenant_id="t", email=uid+"@example.test", full_name=uid, role="Admin"))
        db.add(ReviewerIdentity(user_id=uid, person_id=person, auth_subject=uid,
                               identity_kind="individual", enabled=True, verified_by="identity-admin"))
    await db.commit()


def actor(uid="checker", **changes):
    return SimpleNamespace(id=uid, tenant_id="t", role="Admin", is_active=True, auth_verified=True,
                           auth_method=changes.get("auth_method", "session"), auth_subject=uid,
                           auth_aal="aal2", impersonated_by=None)


async def proposal(db, vid="v1", source_id="s1", start=date(2020, 1, 1), end=None,
                   country="United Kingdom", status="PROPOSED"):
    if await db.get(Source, source_id) is None:
        db.add(Source(id=source_id, tenant_id="t", category="tax", title="VAT rate guidance",
                      publisher="Test authority", source_class="official_guidance",
                      jurisdiction_scope=country, framework_scope="", is_tenant_private=False))
        await db.flush()
    content="VAT rate guidance and VAT registration threshold rules."
    db.add(SourceVersion(id=vid, source_id=source_id, tenant_id="t", status=status,
                         submitted_by="maker", approved_by="checker" if status != "PROPOSED" else None,
                         effective_from=start, effective_to=end, content_hash=hashlib.sha256(vid.encode()).hexdigest()))
    await db.flush()
    db.add(SourcePassage(id="p-"+vid, source_version_id=vid, tenant_id="t", locator="Section 1", sequence=1,
                         content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(), procedure="general"))
    for op in ("retrieval", "model_transmission", "display"):
        db.add(SourceRight(tenant_id="t", source_version_id=vid, operation=op, decision="allow", rights_version=1))
    await db.commit()


async def approve(db, vid="v1", who=None, predecessor=None):
    who=who or actor()
    return await approve_source_version(db, who.id, "s1", vid, tenant_id="t",
                                        authenticated_actor=who, predecessor_id=predecessor)


@pytest.mark.parametrize("uid,method", [("maker","session"),("alias","session"),("checker","api_key")])
async def test_independence_is_person_not_username(store, uid, method):
    await proposal(store)
    with pytest.raises(HTTPException) as exc:
        await approve(store, who=actor(uid, auth_method=method))
    assert exc.value.status_code == 403
    assert (await store.get(SourceVersion,"v1")).status == "PROPOSED"


@pytest.mark.parametrize("kind", ["seed", "shared", "service"])
async def test_non_individual_reviewer_rejected(store, kind):
    await proposal(store)
    (await store.get(ReviewerIdentity,"checker")).identity_kind=kind
    await store.commit()
    with pytest.raises(HTTPException) as exc:
        await approve(store)
    assert exc.value.status_code == 403


async def test_unauthenticated_and_service_account_rejected(store):
    await proposal(store)
    with pytest.raises(HTTPException):
        await approve_source_version(store,"checker","s1","v1",tenant_id="t")
    store.add(ServiceAccount(id="checker",tenant_id="t",name="service",owner_user_id="maker",created_by="maker"))
    await store.commit()
    with pytest.raises(HTTPException):
        await approve(store)


async def test_approval_supersession_and_audit_atomic_success(store):
    await proposal(store,"old",start=date(2020,1,1),end=date(2024,12,31),status="APPROVED")
    await proposal(store,"new",start=date(2025,1,1))
    await approve(store,"new",predecessor="old")
    old=await store.get(SourceVersion,"old")
    assert old.status == "SUPERSEDED" and old.superseded_at is not None
    assert old.superseded_by_version_id == "new"
    event=(await store.execute(select(AuditEvent))).scalar_one()
    assert event.payload["auth_subject"] == "checker"
    assert event.payload["decision"] == "APPROVED"
    assert event.payload_hash == compute_payload_hash(event.payload)
    assert event.chain_hash == compute_chain_hash(event.id,event.event_name,event.payload_hash,event.previous_chain_hash)
    assert await store.get(SourceApproval,"new")


async def test_commit_failure_rolls_back_all_business_and_audit_changes(store, monkeypatch):
    await proposal(store,"old",end=date(2024,12,31),status="APPROVED")
    await proposal(store,"new",start=date(2025,1,1))
    async def failure():
        await store.flush()
        raise RuntimeError("injected commit failure")
    monkeypatch.setattr(store,"commit",failure)
    with pytest.raises(RuntimeError, match="injected"):
        await approve(store,"new",predecessor="old")
    assert (await store.get(SourceVersion,"old")).status == "APPROVED"
    assert (await store.get(SourceVersion,"new")).status == "PROPOSED"
    assert (await store.execute(select(AuditEvent))).scalars().all() == []
    assert await store.get(SourceApproval,"new") is None


async def test_overlap_and_ungoverned_supersession_rejected(store):
    await proposal(store,"old",status="APPROVED")
    await proposal(store,"new",start=date(2025,1,1))
    with pytest.raises(HTTPException) as exc:
        await approve(store,"new",predecessor="old")
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        await add_relationship(store,from_version_id="new",to_version_id="old",relationship_type="supersedes",tenant_id="t",actor_id="checker")


@pytest.mark.parametrize("start,end", [(None,None),(date(2026,1,1),date(2025,1,1))])
async def test_missing_and_invalid_effective_dates_rejected(store,start,end):
    await proposal(store,start=start,end=end)
    with pytest.raises(HTTPException) as exc:
        await approve(store)
    assert exc.value.status_code == 409


async def test_historical_current_spanning_and_unknown_applicability(store):
    await proposal(store,"old",end=date(2024,12,31),status="APPROVED")
    await proposal(store,"new",start=date(2025,1,1),status="APPROVED")
    old=await store.get(SourceVersion,"old")
    old.status="SUPERSEDED";old.superseded_by_version_id="new"
    await store.commit()
    async def ask(query):
        return await build_source_bundle(store,query=query,jurisdiction="United Kingdom",tenant_id="t")
    historical=await ask("VAT rate guidance in 2024")
    assert {s.version_id for s in historical.sources} == {"old"}
    current=await ask("VAT rate guidance today")
    assert {s.version_id for s in current.sources} == {"new"}
    spanning=await ask("VAT rate guidance from 2024-04-01 to 2025-03-31")
    assert not spanning.clarification_required
    assert {s.version_id for s in spanning.sources} == {"old", "new"}
    assert {(s.evidence_period_start,s.evidence_period_end) for s in spanning.sources} == {
        (date(2024,4,1),date(2024,12,31)),(date(2025,1,1),date(2025,3,31))}
    from app.orchestration.governed_retrieval import retrieve_governed_evidence
    replay, texts = await retrieve_governed_evidence(
        store, query="UK VAT rate guidance from 2024-04-01 to 2025-03-31",
        jurisdiction="United Kingdom", tenant_id="t", query_id="period-replay")
    assert {source.version_id for source in replay.sources} == {"old", "new"}
    assert len(texts) == 2
    assert any("2024-04-01 to 2024-12-31" in content for _,_,content in texts)
    assert any("2025-01-01 to 2025-03-31" in content for _,_,content in texts)
    (await store.get(SourceVersion,"new")).effective_from=None
    await store.commit()
    unknown=await ask("VAT rate guidance in 2026")
    assert unknown.clarification_required and not unknown.passages


async def test_conflicting_versions_and_proposals_are_not_answer_evidence(store):
    await proposal(store,"a",status="APPROVED")
    await proposal(store,"b",status="APPROVED")
    await proposal(store,"c")
    result=await build_source_bundle(store,query="VAT rate guidance in 2024",jurisdiction="United Kingdom",tenant_id="t")
    assert result.clarification_required and not result.passages
    assert "c" not in {s.version_id for s in result.sources}


async def test_multicountry_separate_labels_and_filter_conflict(store):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    await proposal(store,"in",source_id="in",country="India",status="APPROVED")
    result=await build_source_bundle(store,query="UK and India VAT rate guidance in 2024",jurisdiction="Any",tenant_id="t")
    assert {s.evidence_jurisdiction for s in result.sources} == {"India","United Kingdom"}
    conflict=await build_source_bundle(store,query="UK and India VAT rate guidance",jurisdiction="United Kingdom",tenant_id="t")
    assert conflict.clarification_required and not conflict.passages
    ambiguous=await build_source_bundle(store,query="VAT rate guidance",jurisdiction="Any",tenant_id="t")
    assert ambiguous.clarification_required


def test_financial_year_calendar_is_not_guessed():
    assert requested_period("FY 2024-25 VAT rate").clarification
    assert requested_period("historical VAT rate").clarification
    assert requested_period("VAT in 2024").start == date(2024,1,1)


def test_migration_upgrade_downgrade_preserves_audit_and_status(tmp_path):
    path=Path(__file__).resolve().parents[1]/"alembic/versions/j5e6f7a8b9c0_source_review_periods.py"
    spec=importlib.util.spec_from_file_location("phase1_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine("sqlite:///"+str(tmp_path/"migration.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE source_versions (id VARCHAR PRIMARY KEY, status VARCHAR)"))
        conn.execute(text("CREATE TABLE source_passages (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE audit_events (id VARCHAR PRIMARY KEY, payload VARCHAR)"))
        conn.execute(text("INSERT INTO source_versions VALUES ('legacy', 'APPROVED')"))
        conn.execute(text("INSERT INTO audit_events VALUES ('history', 'unchanged')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(text("SELECT reporting_period_start FROM source_versions")).scalar() is None
            migration.downgrade()
            migration.upgrade()
        assert conn.execute(text("SELECT status FROM source_versions")).scalar() == "APPROVED"
        assert conn.execute(text("SELECT payload FROM audit_events")).scalar() == "unchanged"
    engine.dispose()


@pytest.mark.skipif(__import__("os").getenv("PHASE1_LOCAL_POSTGRES") != "1", reason="Disposable local PostgreSQL must be explicitly started")
async def test_postgres_concurrent_approvals_serialize_and_audit_chain():
    # Fixed disposable endpoint; never reads DATABASE_URL or app credentials.
    engine=create_async_engine("postgresql+asyncpg://kailanaresh@127.0.0.1:55439/postgres")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as db:
        await seed(db)
        await proposal(db,"one")
        await proposal(db,"two")
    async def attempt(vid):
        async with factory() as db:
            try:
                await approve(db,vid)
                return "approved"
            except HTTPException as exc:
                await db.rollback()
                return exc.status_code
    results=await asyncio.gather(attempt("one"),attempt("two"))
    assert sorted(map(str,results)) == ["409","approved"]
    async with factory() as db:
        versions=(await db.execute(select(SourceVersion))).scalars().all()
        assert sum(v.status == "APPROVED" for v in versions) == 1
        events=(await db.execute(select(AuditEvent))).scalars().all()
        assert len(events) == 1 and events[0].previous_chain_hash is None
        assert events[0].payload_hash == compute_payload_hash(events[0].payload)
        assert events[0].chain_hash == compute_chain_hash(events[0].id,events[0].event_name,events[0].payload_hash,None)
    # A real PostgreSQL transaction is flushed, then failed before commit.
    async with factory() as db:
        winner=(await db.execute(select(SourceVersion).where(SourceVersion.status == "APPROVED"))).scalar_one()
        winner.effective_to=date(2026,12,31)
        await db.commit()
        await proposal(db,"replacement",start=date(2027,1,1))
        original_commit=db.commit
        async def failed_commit():
            await db.flush()
            raise RuntimeError("postgres injected failure")
        db.commit=failed_commit
        with pytest.raises(RuntimeError,match="injected"):
            await approve(db,"replacement",predecessor=winner.id)
        db.commit=original_commit
        replacement=await db.get(SourceVersion,"replacement")
        assert replacement.status == "PROPOSED" and replacement.approved_by is None
        winner=(await db.execute(select(SourceVersion).where(SourceVersion.status == "APPROVED"))).scalar_one()
        assert winner.superseded_by_version_id is None
        assert len((await db.execute(select(AuditEvent))).scalars().all()) == 1
        await approve(db,"replacement",predecessor=winner.id)
        events=(await db.execute(select(AuditEvent).order_by(AuditEvent.ingested_at))).scalars().all()
        assert len(events) == 2 and events[1].previous_chain_hash == events[0].chain_hash
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_dashboard_counts_receipts_not_reviewed_labels(store):
    from app.domains.command_center.service import source_snapshot
    await proposal(store)
    version=await store.get(SourceVersion,"v1")
    version.quality_state="REVIEWED"
    await store.commit()
    before=await source_snapshot(store,"t",datetime.now(timezone.utc))
    assert before["reviewed"] == 0
    await approve(store)
    after=await source_snapshot(store,"t",datetime.now(timezone.utc))
    assert after["reviewed"] == 1


@pytest.mark.parametrize("status", ["PROPOSED","UNDER_REVIEW"])
async def test_pending_versions_excluded(store,status):
    await proposal(store,status=status)
    bundle=await build_source_bundle(store,query="UK VAT rate guidance in 2024",jurisdiction="UK",tenant_id="t")
    assert not bundle.passages


async def test_self_approved_legacy_record_excluded_without_status_mutation(store):
    await proposal(store,status="APPROVED")
    version=await store.get(SourceVersion,"v1")
    version.approved_by="maker";version.quality_state="REVIEWED"
    await store.commit()
    bundle=await build_source_bundle(store,query="UK VAT rate guidance",jurisdiction="UK",tenant_id="t")
    assert not bundle.passages
    assert (await store.get(SourceVersion,"v1")).status == "APPROVED"


async def test_passage_reporting_period_bounds(store):
    await proposal(store,status="APPROVED")
    passage=await store.get(SourcePassage,"p-v1")
    # Legacy metadata is installed using raw SQL only in this isolated fixture.
    await store.execute(text("UPDATE source_passages SET reporting_period_start='2024-01-01', reporting_period_end='2024-12-31' WHERE id='p-v1'"))
    await store.commit()
    included=await build_source_bundle(store,query="UK VAT rate guidance in 2024",jurisdiction="UK",tenant_id="t")
    excluded=await build_source_bundle(store,query="UK VAT rate guidance in 2025",jurisdiction="UK",tenant_id="t")
    assert included.passages and not excluded.passages


@pytest.mark.skipif(__import__("os").getenv("PHASE1_LOCAL_POSTGRES") != "1", reason="Disposable local PostgreSQL required")
def test_postgres_migration_snapshot_restore_and_audit_preservation(tmp_path):
    import subprocess
    import uuid
    name="phase1_"+uuid.uuid4().hex[:10]
    restored=name+"_restore"
    admin=create_engine("postgresql+psycopg2://kailanaresh@127.0.0.1:55439/postgres",isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text('CREATE DATABASE "'+name+'"'))
        conn.execute(text('CREATE DATABASE "'+restored+'"'))
    engine=create_engine("postgresql+psycopg2://kailanaresh@127.0.0.1:55439/"+name)
    target=create_engine("postgresql+psycopg2://kailanaresh@127.0.0.1:55439/"+restored)
    path=Path(__file__).resolve().parents[1]/"alembic/versions/j5e6f7a8b9c0_source_review_periods.py"
    spec=importlib.util.spec_from_file_location("phase1_pg_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE source_versions (id VARCHAR PRIMARY KEY, status VARCHAR)"))
            conn.execute(text("CREATE TABLE source_passages (id VARCHAR PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE audit_events (id VARCHAR PRIMARY KEY, payload VARCHAR, chain_hash VARCHAR)"))
            conn.execute(text("INSERT INTO source_versions VALUES ('legacy','APPROVED')"))
            conn.execute(text("INSERT INTO audit_events VALUES ('history','original payload','original chain')"))
        # The client tools on PATH, matching the server: /opt/homebrew/bin pointed
        # at PostgreSQL 14 after a restart and could not dump the 18 server.
        import shutil
        snapshot=tmp_path/"pre-migration-snapshot.dump"
        subprocess.run([shutil.which("pg_dump") or "pg_dump","-h","127.0.0.1","-p","55439","-U","kailanaresh","-Fc","-f",str(snapshot),name],check=True)
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                migration.downgrade()
                migration.upgrade()
            assert conn.execute(text("SELECT status FROM source_versions")).scalar() == "APPROVED"
            assert conn.execute(text("SELECT payload,chain_hash FROM audit_events")).one() == ("original payload","original chain")
        subprocess.run([shutil.which("pg_restore") or "pg_restore","-h","127.0.0.1","-p","55439","-U","kailanaresh","-d",restored,str(snapshot)],check=True)
        with target.connect() as conn:
            assert conn.execute(text("SELECT status FROM source_versions")).scalar() == "APPROVED"
            assert conn.execute(text("SELECT payload,chain_hash FROM audit_events")).one() == ("original payload","original chain")
        snapshot.with_suffix(".sha256").write_text(hashlib.sha256(snapshot.read_bytes()).hexdigest()+"\n")
    finally:
        engine.dispose();target.dispose()
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE "'+restored+'"'))
            conn.execute(text('DROP DATABASE "'+name+'"'))
        admin.dispose()


async def test_approval_receipt_cannot_be_rewritten(store):
    await proposal(store)
    await approve(store)
    receipt=await store.get(SourceApproval,"v1")
    receipt.reviewer_person_id="p1"
    with pytest.raises(ValueError,match="append-only"):
        await store.flush()
    await store.rollback()


def test_correction_planner_is_pure_and_prioritizes_highest_use():
    path=Path(__file__).resolve().parents[1]/"scripts/plan_source_review_correction.py"
    spec=importlib.util.spec_from_file_location("phase1_plan",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rows=[dict(version_id=str(i),source_id=str(i),status="APPROVED",submitted_by="seed",
               approved_by="seed",usage_count=i) for i in range(22)]
    original=repr(rows)
    result=module.plan(rows)
    assert result["first_six"] == [str(i) for i in range(21,15,-1)]
    assert result["count_matches"] and result["executed"] is False
    assert repr(rows) == original


async def test_superseded_historical_content_remains_immutable(store):
    await proposal(store,"old",end=date(2024,12,31),status="APPROVED")
    await proposal(store,"new",start=date(2025,1,1))
    await approve(store,"new",predecessor="old")
    passage=await store.get(SourcePassage,"p-old")
    passage.content="rewritten historical rule"
    with pytest.raises(ValueError,match="immutable"):
        await store.flush()
    await store.rollback()


async def test_historical_tax_without_any_dated_evidence_requires_clarification(store):
    bundle=await build_source_bundle(store,query="UK VAT rate in 2024",jurisdiction="United Kingdom",tenant_id="t")
    assert bundle.clarification_required and not bundle.passages


async def test_ambiguous_framework_requires_clarification(store):
    bundle=await build_source_bundle(store,query="Compare UK and India under IFRS and US GAAP",jurisdiction="Any",tenant_id="t")
    assert "framework" in bundle.clarification_required and not bundle.passages


async def test_backdated_approval_cannot_overlap_expired_history(store):
    await proposal(store,"old",start=date(2020,1,1),end=date(2024,12,31),status="EXPIRED")
    await proposal(store,"new",start=date(2023,1,1),end=date(2025,12,31))
    with pytest.raises(HTTPException) as exc:
        await approve(store,"new")
    assert exc.value.status_code == 409

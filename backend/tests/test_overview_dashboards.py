"""Pure logic behind the live Overview pages (command_center/service.py).

The aggregation queries need a real database and are exercised by the
endpoint itself; these tests pin down the rules that turn counts into what
the pages say: relative times, evidence freshness, the greeting name and the
direction of each evaluation gate.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.domains.command_center.service import (
    _exceptions_label,
    _freshness,
    _plural,
    ago,
    display_name,
    gate_results,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def test_ago_reads_naturally_and_accepts_naive_utc():
    assert ago(NOW - timedelta(seconds=20), NOW) == "just now"
    assert ago(NOW - timedelta(minutes=5), NOW) == "5 min ago"
    assert ago(NOW - timedelta(hours=3), NOW) == "3 hr ago"
    assert ago(NOW - timedelta(days=1, hours=2), NOW) == "1 day ago"
    # escalation_cases stores naive UTC timestamps
    assert ago((NOW - timedelta(days=12)).replace(tzinfo=None), NOW) == "12 days ago"
    assert ago(None, NOW) == "never"
    assert ago(NOW + timedelta(days=3), NOW) == "in 3 days"


def test_freshness_is_relative_to_the_assessment_window():
    current = _freshness((NOW - timedelta(days=5)).isoformat(), NOW, 30)
    stale = _freshness((NOW - timedelta(days=87)).isoformat(), NOW, 30)
    assert current["state"] == "current" and current["label"] == "Current · 5 days ago"
    assert stale["state"] == "stale" and stale["label"] == "Stale · 87 days ago"
    assert _freshness(None, NOW, 30)["state"] == "unknown"
    # the same evidence is current again under a wider window
    assert _freshness((NOW - timedelta(days=87)).isoformat(), NOW, 90)["state"] == "current"


def test_gate_direction_matches_the_metric():
    limits = {"citation_precision": 0.95, "source_recall": 0.9, "latency_p95": 2.5, "pii_leak": 0.0, "tool_accuracy": 0.98}
    metrics = {"citation_precision": 0.0, "source_recall": 0.92, "latency_p95": 1.4, "pii_leak": 0.0}
    results = {r["metric"]: r for r in gate_results(metrics, limits, ["pii_leak"])}
    assert results["citation_precision"]["passed"] is False      # higher is better, below threshold
    assert results["source_recall"]["passed"] is True
    assert results["latency_p95"]["passed"] is True              # lower is better
    assert results["pii_leak"]["passed"] is True and results["pii_leak"]["zeroTolerance"] is True
    assert "tool_accuracy" not in results                        # not measured → not reported


def test_zero_tolerance_leak_fails_on_any_leak():
    [result] = gate_results({"cross_tenant_leak": 0.01}, {"cross_tenant_leak": 0.0}, ["cross_tenant_leak"])
    assert result["passed"] is False and result["zeroTolerance"] is True


def test_display_name_prefers_first_name_then_full_name_then_email():
    assert display_name(SimpleNamespace(first_name="Naresh", full_name="Kaila Naresh", email="x@y.z")) == "Naresh"
    assert display_name(SimpleNamespace(first_name="", full_name="Kaila Naresh", email="x@y.z")) == "Kaila"
    assert display_name(SimpleNamespace(first_name="", full_name="", email="kailanaresh62@gmail.com")) == "kailanaresh62"


def test_labels():
    assert _plural(1, "incident") == "1 incident"
    assert _plural(23, "incident") == "23 incidents"
    assert _exceptions_label(0, 0) == "None"
    assert _exceptions_label(1, 2, 3) == "1 critical · 2 high · 3 other"


async def test_overview_never_opens_more_than_its_connection_cap(monkeypatch):
    """The hosted pooler allows 15 clients; the Overview must not burst."""
    import asyncio
    from contextlib import asynccontextmanager
    from app.domains.command_center import service

    open_now, peak = 0, 0

    @asynccontextmanager
    async def fake_session(user):
        nonlocal open_now, peak
        open_now += 1
        peak = max(peak, open_now)
        try:
            yield object()
        finally:
            open_now -= 1

    async def group(_session):
        await asyncio.sleep(0.01)
        return 1

    monkeypatch.setattr(service, "scoped_session", fake_session)
    monkeypatch.setattr(service, "_overview_slots", None)
    results = await asyncio.gather(*(service.run_parallel(SimpleNamespace(), group, group, group, group, group)
                                     for _ in range(3)))
    assert [sum(r) for r in results] == [5, 5, 5]
    assert peak <= service.OVERVIEW_DB_CONNECTIONS


async def test_dashboard_views_read_persisted_records_and_keep_tenant_boundaries(monkeypatch):
    """Exercise actual aggregation SQL, not mocked counts or API fixtures."""
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.base import Base
    from app.domains.command_center import service
    from app.domains.identity.models import Tenant, User
    from app.domains.kriton_workspace.models import SavedAnswer
    from app.orchestration.models import ReviewCase
    from app.domains.evaluation.models import EvaluationDataset, EvaluationRun, ThresholdSet

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with sessions() as db:
            a = User(id="overview-a",tenant_id="overview-t1",email="a@test.local",full_name="User A",role="Admin")
            b = User(id="overview-b",tenant_id="overview-t2",email="b@test.local",full_name="User B",role="Admin")
            db.add_all([Tenant(id="overview-t1",name="First workspace"),Tenant(id="overview-t2",name="Second workspace"),a,b])
            await db.flush()
            for user in (a,b):
                db.add(SavedAnswer(id="saved-"+user.id,tenant_id=user.tenant_id,user_id=user.id,query_id="q",query_text="Saved by "+user.id,answer_text="Answer",risk_level="LOW"))
            for index, state in enumerate(("open","needs_evidence","resolved","released")):
                db.add(ReviewCase(id=f"overview-r{index}",tenant_id=a.tenant_id,query_id=f"q{index}",correlation_id="c",risk_level="HIGH",confidence_state="SUFFICIENT",reason="test",status=state,reviewer_id=a.id,resolved_at=NOW if state in ("resolved","released") else None))
            db.add_all([
                EvaluationDataset(id="overview-d1",version="1",domain="safety",tenant_id=a.tenant_id),
                EvaluationDataset(id="overview-d2",version="1",domain="safety",tenant_id=b.tenant_id),
                ThresholdSet(id="overview-th",dataset_id="overview-d1",dataset_version_id="1",metrics={"citation_precision":.95},owner="test",approver="test"),
                EvaluationRun(id="overview-e1",dataset_id="overview-d1",threshold_set_id="overview-th",config_hash="x",status="RUNNING",metrics_summary={},created_at=NOW.replace(tzinfo=None)),
                EvaluationRun(id="overview-e2",dataset_id="overview-d2",threshold_set_id="overview-th",config_hash="x",status="COMPLETED",metrics_summary={"citation_precision":1},created_at=(NOW+timedelta(seconds=1)).replace(tzinfo=None)),
            ])
            await db.commit()

        @asynccontextmanager
        async def session(_user):
            async with sessions() as db:
                yield db
        monkeypatch.setattr(service,"scoped_session",session)
        monkeypatch.setattr(service,"_overview_slots",None)
        workspace = await service.build_my_workspace(a,NOW)
        assert workspace["counts"]["savedAnswers"] == 1
        assert workspace["counts"]["reviewsResolved"] == 2
        assert all("overview-b" not in item["title"] for item in workspace["recentActivity"])
        command = await service.build_command_center(a,NOW)
        assert command["workspaceName"] == "First workspace"
        assert command["reviewQueue"]["open"] == 2
        governance = await service.build_governance(a,NOW,30,"CONNECTED")
        evaluation = next(domain for domain in governance["domains"] if domain["key"] == "evaluation")
        assert evaluation["state"] == "Not assessed"  # unfinished run cannot be green
        async with sessions() as db:
            snapshot = await service.evaluation_snapshot(db,a.tenant_id)
            assert snapshot["runId"] == "overview-e1" # newer foreign run is excluded
    finally:
        await engine.dispose()

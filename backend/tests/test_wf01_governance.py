"""WF-01 release governance: authority resolution, gap ownership, as-built
manifests, the runtime QA ledger, the release verdict and the D4 defaults.

Each control is tested by its refusal: unknown, NOT_RUN, unadjudicated,
self-approved, stale or unpinned evidence never counts as passing."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.db.base import Base
from app.domains.admin_governance import authority, gap_ownership, release_verdict, releases
from app.domains.admin_governance.governance_access import require_governance
from app.domains.admin_governance.models import ReleaseCandidate
from app.domains.evaluation import qa_ledger
from app.domains.evaluation.models import ResultPack
from app.domains.evaluation.qa_models import QaBaseline, QaCase
from app.domains.evaluation.threshold_register import validate_metrics
from app.domains.identity.models import User
from app.domains.identity.permissions import (
    ALL_PERMISSIONS, GOVERNANCE_READ, WF01_PERMISSIONS, permissions_for_role,
)
from app.domains.identity.rbac import get_current_user
from app.domains.operations import asbuilt

GOV = "gov-tenant"


def _actor(name: str, role: str = "Document Control", tenant: str = GOV):
    return SimpleNamespace(id=name, role=role, tenant_id=tenant, full_name=name, email=f"{name}@example.com")


def _code(exc: pytest.ExceptionInfo) -> str:
    return exc.value.detail["code"]


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    for name, value in {"KRITON_GOVERNANCE_TENANT_ID": GOV, "KRITON_ENVIRONMENT": "local-dev",
                        "KRITON_QA_ADAPTER_BASE_URL": "", "KRITON_QA_ADAPTER_API_KEY": "",
                        "KRITON_GOVERNANCE_SIGNING_KEY": ""}.items():
        monkeypatch.setattr(s, name, value)
    return s


SMALL_REGISTER = {
    "version": "test-1",
    "documents": [
        {"path": "docs/a.docx", "sha256": "a" * 64, "title": "Standard A", "declared_ids": [{"id": "ZL-ENG-06"}],
         "canonical_id": None, "state": "ID_COLLISION"},
        {"path": "docs/b.docx", "sha256": "b" * 64, "title": "Standard B", "declared_ids": [{"id": "ZL-ENG-06"}],
         "canonical_id": None, "state": "ID_COLLISION"},
    ],
    "collisions": [{"legacy_id": "ZL-ENG-06", "candidates": [{"described_as": "Standard A"},
                                                              {"described_as": "Standard B"}]}],
    "unavailable_references": [{"id": "ZL-T0-05"}],
}


# ── Permissions (D2, D3) ────────────────────────────────────────────────────

def test_tenant_admin_holds_no_wf01_permission():
    assert not (WF01_PERMISSIONS & ALL_PERMISSIONS)
    assert not (WF01_PERMISSIONS & permissions_for_role("Admin"))
    assert "authority.ratify" not in permissions_for_role("Document Control")
    assert "authority.propose" not in permissions_for_role("Chief Architect")
    assert "qa.adjudicate" not in permissions_for_role("QA Automation")


# ── A1: authority register ─────────────────────────────────────────────────

async def test_collision_and_unavailable_references_stay_unresolved(sessions):
    async with sessions() as db:
        await authority.import_register(db, SMALL_REGISTER)
        assert (await authority.import_register(db, SMALL_REGISTER))["added"] == 0      # idempotent
        with pytest.raises(HTTPException) as exc:
            await authority.resolve(db, "ZL-ENG-06")
        assert _code(exc) == "COLLISION_UNRESOLVED"
        ref = await authority.resolve(db, "ZL-T0-05")
        assert ref["state"] == "EVIDENCE_UNAVAILABLE_IN_REPO" and ref["canonical_id"] is None
        with pytest.raises(HTTPException) as exc:
            await authority.resolve(db, "ZL-NOPE-01")
        assert _code(exc) == "UNKNOWN_REFERENCE"
        assert (await authority.summary(db))["unresolved_collisions"] == ["ZL-ENG-06"]


async def test_the_repository_register_keeps_zl_eng_06_unresolved(sessions):
    async with sessions() as db:
        await authority.import_register(db)
        summary = await authority.summary(db)
        assert "ZL-ENG-06" in summary["unresolved_collisions"]
        assert summary["states"].get("EVIDENCE_UNAVAILABLE_IN_REPO", 0) > 0
        assert summary["states"].get("CANONICAL_RATIFIED", 0) == 0


async def test_a_document_not_held_cannot_be_given_an_identifier(sessions):
    async with sessions() as db:
        await authority.import_register(db, SMALL_REGISTER)
        with pytest.raises(HTTPException) as exc:
            await authority.propose(db, _actor("dc"), legacy_id="ZL-T0-05", mapping={"ref:ZL-T0-05": "ZL-T0-05-A"},
                                    reason="r", key="k1")
        assert _code(exc) == "EVIDENCE_UNAVAILABLE"
        with pytest.raises(HTTPException) as exc:
            await authority.propose(db, _actor("dc"), legacy_id="ZL-ENG-06", mapping={"docs/missing.docx": "ZL-ENG-06-X"},
                                    reason="r", key="k2")
        assert _code(exc) == "EVIDENCE_UNAVAILABLE"


async def test_proposal_validation_refuses_bad_and_duplicate_identifiers(sessions):
    async with sessions() as db:
        await authority.import_register(db, SMALL_REGISTER)
        for mapping, code in (({"docs/a.docx": "not an id"}, "INVALID_IDENTIFIER"),
                              ({"docs/a.docx": "ZL-ENG-06-IQ", "docs/b.docx": "ZL-ENG-06-IQ"}, "DUPLICATE_CANONICAL_ID"),
                              ({}, "PROPOSAL_INCOMPLETE")):
            with pytest.raises(HTTPException) as exc:
                await authority.propose(db, _actor("dc"), legacy_id="ZL-ENG-06", mapping=mapping, reason="r", key=code)
            assert _code(exc) == code


async def test_ratification_needs_another_person_and_current_revisions(sessions):
    mapping = {"docs/a.docx": "ZL-ENG-06-IQ", "docs/b.docx": "ZL-ENG-06-MT"}
    async with sessions() as db:
        await authority.import_register(db, SMALL_REGISTER)
        proposal = await authority.propose(db, _actor("dc"), legacy_id="ZL-ENG-06", mapping=mapping, reason="split", key="p1")
        replay = await authority.propose(db, _actor("dc"), legacy_id="ZL-ENG-06", mapping=mapping, reason="split", key="p1")
        assert replay["id"] == proposal["id"]
        with pytest.raises(HTTPException) as exc:
            await authority.ratify(db, _actor("dc"), proposal_id=proposal["id"], decision="RATIFY", reason="r", key="r0")
        assert _code(exc) == "INDEPENDENCE_REQUIRED"
        stale = await authority.propose(db, _actor("dc"), legacy_id="ZL-ENG-06", mapping=mapping, reason="again", key="p2")
        await authority.ratify(db, _actor("ca", "Chief Architect"), proposal_id=proposal["id"], decision="RATIFY",
                               reason="ok", key="r1")
        with pytest.raises(HTTPException) as exc:
            await authority.ratify(db, _actor("ca", "Chief Architect"), proposal_id=proposal["id"], decision="RATIFY",
                                   reason="ok", key="r2")
        assert _code(exc) == "ALREADY_DECIDED"
        with pytest.raises(HTTPException) as exc:
            await authority.ratify(db, _actor("ca", "Chief Architect"), proposal_id=stale["id"], decision="RATIFY",
                                   reason="ok", key="r3")
        assert _code(exc) == "STALE_REVISION"
        assert (await authority.resolve(db, "ZL-ENG-06-IQ"))["record_key"] == "docs/a.docx"
        assert (await authority.summary(db))["unresolved_collisions"] == []


# ── D1: gap ownership ──────────────────────────────────────────────────────

async def test_gap_ownership_adoption_is_not_ratification(sessions):
    async with sessions() as db:
        assert (await gap_ownership.current(db))["status"] == "NOT_ADOPTED"
        adoption = await gap_ownership.adopt(db, _actor("po"), "a1")
        assert (await gap_ownership.current(db))["status"] == "ADOPTED_PENDING_RATIFICATION"
        with pytest.raises(HTTPException) as exc:
            await gap_ownership.ratify(db, _actor("po"), adoption_id=adoption["id"],
                                       content_sha256=adoption["content_sha256"], key="r1")
        assert _code(exc) == "INDEPENDENCE_REQUIRED"
        with pytest.raises(HTTPException) as exc:
            await gap_ownership.ratify(db, _actor("ca"), adoption_id=adoption["id"], content_sha256="0" * 64, key="r2")
        assert _code(exc) == "STALE_REVISION"
        await gap_ownership.ratify(db, _actor("ca"), adoption_id=adoption["id"], content_sha256=adoption["content_sha256"],
                                   key="r3")
        assert (await gap_ownership.current(db))["status"] == "RATIFIED"


def test_gap_allocation_covers_all_30_gaps_once():
    allocation = gap_ownership.proposed()["allocation"]
    assert sorted(allocation) == [f"G{n:02d}" for n in range(1, 31)]
    assert set(allocation.values()) == {"WF-01", "WF-02", "WF-03"}


# ── A2: as-built manifests ─────────────────────────────────────────────────

def _small_app():
    app = FastAPI()

    @app.get("/governed")
    async def governed(_=Depends(require_governance(GOVERNANCE_READ))):
        return {}

    return app


def test_collect_maps_requirements_to_served_routes_and_tests(monkeypatch, tmp_path):
    requirement_map = tmp_path / "map.json"
    requirement_map.write_text(json.dumps({"requirements": [
        {"requirement_id": "R-OK", "service": "s", "method": "GET", "path": "/governed", "permission": GOVERNANCE_READ,
         "tests": ["tests/test_wf01_governance.py::test_collect_maps_requirements_to_served_routes_and_tests"]},
        {"requirement_id": "R-NOROUTE", "service": "s", "method": "GET", "path": "/absent", "permission": "", "tests": []},
        {"requirement_id": "R-NOTEST", "service": "s", "method": "GET", "path": "/governed", "permission": GOVERNANCE_READ,
         "tests": ["tests/test_wf01_governance.py::test_that_does_not_exist"]},
        {"requirement_id": "R-WRONGPERM", "service": "s", "method": "GET", "path": "/governed",
         "permission": "release.verify", "tests": []},
    ]}))
    monkeypatch.setattr(asbuilt, "REQUIREMENT_MAP", requirement_map)
    manifest = asbuilt.collect(_small_app())
    status = {m["requirement_id"]: m["status"] for m in manifest["mappings"]}
    assert status == {"R-OK": "MAPPED", "R-NOROUTE": "UNMAPPED", "R-NOTEST": "UNMAPPED", "R-WRONGPERM": "UNMAPPED"}
    assert all(not f["name"].endswith("_KEY") for f in manifest["flags"])
    assert all("value" not in f for f in manifest["flags"])


def test_the_repository_requirement_map_is_fully_mapped_by_the_application():
    from app.main import app
    manifest = asbuilt.collect(app)
    unmapped = [(m["requirement_id"], m["reason"]) for m in manifest["mappings"] if m["status"] != "MAPPED"]
    assert manifest["mappings"] and unmapped == []


def _manifest(clean=True, unmapped=False, environment="staging"):
    return {"commit_sha": "c" * 40, "tree_clean": clean, "branch": "b", "schema_head": "h", "environment": environment,
            "flags": [], "routes_total": 1,
            "mappings": [{"requirement_id": "R", "service": "s", "method": "GET", "path": "/p", "permission": "",
                          "flag": "", "test_refs": [], "status": "UNMAPPED" if unmapped else "MAPPED",
                          "reason": "x" if unmapped else ""}]}


async def test_asbuilt_verification_is_independent_and_refuses_uncommitted_or_unmapped(sessions):
    async with sessions() as db:
        dirty = await asbuilt.record(db, _actor("qa"), _manifest(clean=False), "m1")
        assert (await asbuilt.record(db, _actor("qa"), _manifest(clean=False), "m1"))["id"] == dirty["id"]
        assert dirty["verification"] == "NOT_RUN"
        with pytest.raises(HTTPException) as exc:
            await asbuilt.verify(db, _actor("qa"), dirty["id"], decision="VERIFIED", note="", key="v0")
        assert _code(exc) == "INDEPENDENCE_REQUIRED"
        with pytest.raises(HTTPException) as exc:
            await asbuilt.verify(db, _actor("cto"), dirty["id"], decision="VERIFIED", note="", key="v1")
        assert _code(exc) == "UNVERIFIABLE_UNCOMMITTED"
        gaps = await asbuilt.record(db, _actor("qa"), _manifest(unmapped=True), "m2")
        with pytest.raises(HTTPException) as exc:
            await asbuilt.verify(db, _actor("cto"), gaps["id"], decision="VERIFIED", note="", key="v2")
        assert _code(exc) == "UNMAPPED_REQUIREMENTS"


# ── A3: the runtime QA ledger ──────────────────────────────────────────────

async def test_pack_import_plans_292_not_run_observations(sessions):
    async with sessions() as db:
        first = await qa_ledger.import_pack(db)
        assert first["imported"] and not (await qa_ledger.import_pack(db))["imported"]
        assert (await db.execute(select(func.count()).select_from(QaCase))).scalar() == 72
        assert (await db.execute(select(func.count()).select_from(QaBaseline).where(QaBaseline.status == "NOT_RUN"))).scalar() == 292
        assert (await db.execute(select(func.count()).select_from(QaCase).where(QaCase.requires_upload))).scalar() == 19
        summary = await qa_ledger.summary(db)
        assert summary["case_counts"] == {"NOT_RUN": 72}
        assert summary["observation_status"]["NOT_RUN"] == 292
        assert summary["p0_passed"] == 0 and summary["p0_total"] == 38


async def test_adapter_is_missing_without_configuration_and_unverified_with_a_bad_key(settings):
    assert (await qa_ledger.adapter_readiness())["readiness"] == "MISSING"
    settings.KRITON_QA_ADAPTER_BASE_URL, settings.KRITON_QA_ADAPTER_API_KEY = "http://adapter.test", "a-session-token"
    assert (await qa_ledger.adapter_readiness())["readiness"] == "UNVERIFIED"
    settings.KRITON_QA_ADAPTER_API_KEY = "zlk_test"
    refused = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    assert (await qa_ledger.adapter_readiness(refused))["readiness"] == "UNVERIFIED"


PINNED = {"release_sha": "c" * 40, "environment": "local-dev", "model": "m", "retriever": "r", "prompt_version": "p",
          "policy_version": "v", "region": "local", "oracle_version": "o1", "adapter_id": "http-v1"}


def _deployed_api(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health/version":
        return httpx.Response(200, json={"build_id": "local"})
    if request.url.path == "/api/v1/auth/me":
        return httpx.Response(200, json={"id": "svc-1", "role": "QA Automation"})
    assert request.url.path == qa_ledger.ASK_PATH
    # The ask route refuses a request_id that differs from the Idempotency-Key.
    assert json.loads(request.content)["request_id"] == request.headers["Idempotency-Key"]
    return httpx.Response(200, json={"query_id": "q", "outcome": "answered", "route": "LLM",
                                     "answer": {"text": "An answer.", "citations": [{"url": "https://example.org"}]}})


async def test_runs_must_be_pinned_and_qualify_only_in_staging_on_a_clean_build(sessions, settings):
    async with sessions() as db:
        await qa_ledger.import_pack(db)
        with pytest.raises(HTTPException) as exc:
            await qa_ledger.create_run(db, _actor("qa"), {**PINNED, "model": ""}, "k0", readiness={"readiness": "CONNECTED"})
        assert _code(exc) == "UNPINNED_CONFIGURATION"
        run = await qa_ledger.create_run(db, _actor("qa"), PINNED, "k1", readiness={"readiness": "CONNECTED"})
        assert run["qualifying"] is False
        settings.KRITON_ENVIRONMENT = "staging"
        staging = await qa_ledger.create_run(db, _actor("qa"), {**PINNED, "environment": "staging"}, "k2",
                                             readiness={"readiness": "CONNECTED"})
        assert staging["qualifying"] is False          # no clean as-built manifest of the pinned SHA


async def test_execution_blocks_unprovisioned_fixtures_and_never_passes_unadjudicated(sessions, settings):
    settings.KRITON_QA_ADAPTER_BASE_URL, settings.KRITON_QA_ADAPTER_API_KEY = "http://adapter.test", "zlk_test"
    client = httpx.AsyncClient(transport=httpx.MockTransport(_deployed_api))
    async with sessions() as db:
        await qa_ledger.import_pack(db)
        run = await qa_ledger.create_run(db, _actor("qa"), PINNED, "k1", readiness={"readiness": "CONNECTED"})
        result = await qa_ledger.execute(db, run["id"], case_ids=["A01", "F01", "E05"], limit=50, client=client)
        assert result["recorded"] == {"EXECUTED": 5, "BLOCKED": 8, "FAILED_TO_EXECUTE": 0}
        again = await qa_ledger.execute(db, run["id"], case_ids=["A01", "F01", "E05"], limit=50, client=client)
        assert sum(again["recorded"].values()) == 0          # resumable, never duplicated
        observed = await qa_ledger.observations(db, run["id"])
        blocked = [o for o in observed if o["state"] == "BLOCKED"]
        assert {o["case_id"] for o in blocked} == {"A01", "F01"}
        assert all("not provisioned" in o["reason"] or "upload" in o["reason"] for o in blocked)
        summary = await qa_ledger.summary(db)
        assert summary["case_status"]["E05"] == "INCONCLUSIVE"
        assert summary["case_status"]["A01"] == "BLOCKED"
        assert summary["observation_status"]["NOT_RUN"] == 292 - 13
        executed = next(o for o in observed if o["state"] == "EXECUTED")
        assert executed["automated_checks"]["mock_completion"] is False and "passed" not in executed["automated_checks"]
        with pytest.raises(HTTPException) as exc:
            await qa_ledger.adjudicate(db, _actor("qa"), executed["id"], verdict="PASSED", oracle_version="o1",
                                       reason="r", key="a0")
        assert _code(exc) == "INDEPENDENCE_REQUIRED"
        with pytest.raises(HTTPException) as exc:
            await qa_ledger.adjudicate(db, _actor("iqa"), blocked[0]["id"], verdict="PASSED", oracle_version="o1",
                                       reason="r", key="a1")
        assert _code(exc) == "EVIDENCE_NOT_RUN"
        for i, o in enumerate(x for x in observed if x["state"] == "EXECUTED"):
            signed = await qa_ledger.adjudicate(db, _actor("iqa"), o["id"], verdict="PASSED", oracle_version="o1",
                                                reason="r", key=f"p{i}")
            assert signed["signature_status"] == "UNSIGNED_NO_KEY"
        # Every repetition adjudicated PASSED, but in a non-qualifying run: not a pass.
        assert (await qa_ledger.summary(db))["case_status"]["E05"] == "INCONCLUSIVE"
    await client.aclose()


async def test_execution_refuses_without_a_connected_adapter(sessions, settings):
    async with sessions() as db:
        await qa_ledger.import_pack(db)
        run = await qa_ledger.create_run(db, _actor("qa"), PINNED, "k1", readiness={"readiness": "MISSING"})
        with pytest.raises(HTTPException) as exc:
            await qa_ledger.execute(db, run["id"])
        assert _code(exc) == "ADAPTER_NOT_CONNECTED"
        assert (await qa_ledger.summary(db))["observation_status"]["NOT_RUN"] == 292


def test_the_adapter_calls_a_route_the_application_serves():
    # A mock once accepted /api/v1/ask, which the application does not serve:
    # the live run returned 404 for every observation.
    from app.main import app
    served = {(r["method"], r["path"]) for r in asbuilt.routes(app)}
    assert ("POST", qa_ledger.ASK_PATH) in served
    assert ("GET", "/api/v1/auth/me") in served and ("GET", "/health/version") in served


def test_ask_text_is_sent_exactly():
    assert qa_ledger.ask_text("ASK What is 2+2?\nPASS 4") == "What is 2+2?"
    assert qa_ledger.ask_text("PASS no ask") == ""


# ── Release verdict ────────────────────────────────────────────────────────

async def test_verdict_is_no_go_on_an_empty_ledger_with_every_gate_unsatisfied(sessions, settings):
    async with sessions() as db:
        computed = await release_verdict.compute(db)
        assert computed["verdict"] == "NO_GO"
        states = {k: g["state"] for k, g in computed["gates"].items()}
        assert states == {"authority": "NOT_RUN", "ownership": "NOT_RUN", "qa_pack": "BLOCKED", "asbuilt": "NOT_RUN",
                          "runtime_qa": "NOT_RUN", "signing": "BLOCKED"}
        recorded = await release_verdict.record(db, _actor("cto", "CTO"), "v1")
        assert recorded["verdict"] == "NO_GO"
        assert (await release_verdict.record(db, _actor("cto", "CTO"), "v1"))["id"] == recorded["id"]


async def test_verdict_stays_no_go_with_the_repository_evidence(sessions, settings):
    settings.KRITON_GOVERNANCE_SIGNING_KEY = "local-test-key"
    async with sessions() as db:
        await authority.import_register(db)
        await qa_ledger.import_pack(db)
        await gap_ownership.adopt(db, _actor("po"), "a1")
        await asbuilt.record(db, _actor("qa"), _manifest(environment="local-dev"), "m1")
        gates = (await release_verdict.compute(db))["gates"]
        assert gates["authority"]["state"] == "BLOCKED" and "ZL-ENG-06" in gates["authority"]["reason"]
        assert gates["ownership"]["state"] == "PENDING"
        assert gates["asbuilt"]["state"] == "BLOCKED" and "not staging" in gates["asbuilt"]["reason"]
        assert gates["runtime_qa"]["state"] == "NOT_RUN"
        assert gates["signing"]["state"] == "SATISFIED"


async def test_platform_release_promotion_is_refused_while_no_go(sessions, settings, monkeypatch):
    monkeypatch.setattr(releases, "gate_states", lambda r, live, names: [])
    monkeypatch.setattr(releases, "derived_status", lambda r, gates: "approved")
    async def no_names(db, tenant):
        return {}
    monkeypatch.setattr(releases, "_names", no_names)
    async with sessions() as db:
        for tenant in (GOV, "customer"):
            db.add(ReleaseCandidate(id=f"rel-{tenant}", tenant_id=tenant, ref="REL-1", name="n", version="1",
                                    component="Platform", created_by="author"))
        await db.commit()
        with pytest.raises(ValueError, match="NO_GO"):
            await releases.transition(db, _actor("cto", "Admin"), {}, f"rel-{GOV}", "deploy", "")
        # A customer tenant's own release record is unaffected by the platform verdict.
        deployed = await releases.transition(db, _actor("admin", "Admin", "customer"), {}, "rel-customer", "deploy", "")
        assert deployed.status == "deployed"


# ── D4: unknown is never pass ──────────────────────────────────────────────

def test_result_pack_defaults_are_not_pass():
    columns = ResultPack.__table__.c
    assert columns.contamination_scan_status.default.arg == "NOT_RUN"
    assert columns.zero_tolerance_passed.default.arg is False


def test_an_unmeasured_metric_fails_its_threshold():
    passed, failures = validate_metrics({"restricted_block_rate": None}, {"restricted_block_rate": 1.0},
                                        ["restricted_block_rate"])
    assert passed is False and failures[0]["metric"] == "restricted_block_rate"
    passed, _ = validate_metrics({}, {"restricted_block_rate": 1.0}, ["restricted_block_rate"])
    assert passed is False


# ── API: governance membership, permissions, idempotency ──────────────────

@pytest.fixture
def api(sessions, settings):
    from app.domains.admin_governance.router import router as admin_router
    from app.domains.evaluation.router import router as evaluation_router
    from app.domains.operations.router import router as operations_router
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(operations_router)
    app.include_router(evaluation_router, prefix="/evaluation")

    async def db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db
    return app


def _as(app, role, tenant=GOV, user_id="u1"):
    app.dependency_overrides[get_current_user] = lambda: User(id=user_id, tenant_id=tenant, role=role,
                                                              email=f"{user_id}@example.com", is_active=True)


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_api_refuses_without_governance_tenant_membership_or_permission(api, settings):
    async with await _client(api) as client:
        _as(api, "Admin")
        assert (await client.get("/admin/release-verdict")).status_code == 403          # tenant Admin: no permission
        _as(api, "CTO", tenant="customer")
        response = await client.get("/admin/release-verdict")
        assert response.status_code == 403 and response.json()["detail"]["code"] == "NOT_GOVERNANCE_MEMBER"
        settings.KRITON_GOVERNANCE_TENANT_ID = ""
        _as(api, "CTO")
        response = await client.get("/admin/release-verdict")
        assert response.json()["detail"]["code"] == "GOVERNANCE_TENANT_NOT_CONFIGURED"


async def test_api_writes_need_an_idempotency_key_and_the_workflow_reads_no_go(api):
    async with await _client(api) as client:
        _as(api, "QA Automation")
        response = await client.post("/evaluation/qa/pack")
        assert response.status_code == 400 and response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert (await client.post("/evaluation/qa/pack", headers={"Idempotency-Key": "i1"})).json()["imported"] is True
        assert (await client.get("/evaluation/qa/summary")).json()["observation_status"]["NOT_RUN"] == 292
        assert (await client.get("/evaluation/qa/adapter")).json()["readiness"] == "MISSING"
        response = await client.post("/evaluation/qa/runs", json={"pinned": {"model": "m"}}, headers={"Idempotency-Key": "r1"})
        assert response.status_code == 422 and response.json()["detail"]["code"] == "UNPINNED_CONFIGURATION"
        _as(api, "Document Control", user_id="dc")
        assert (await client.post("/admin/authority/import", headers={"Idempotency-Key": "i2"})).status_code == 200
        response = await client.get("/admin/authority/resolve", params={"reference": "ZL-ENG-06"})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "COLLISION_UNRESOLVED"
        _as(api, "CTO", user_id="cto")
        verdict = (await client.get("/admin/release-verdict")).json()
        assert verdict["verdict"] == "NO_GO"
        assert verdict["gates"]["authority"]["state"] == "BLOCKED"

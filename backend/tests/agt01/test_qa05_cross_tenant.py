"""QA 5 — cross-tenant attempt: zero disclosure; tool denied."""
from agt01_support import call, reply, run

from app.domains.source_library.licensing import SourceUseContext, _decide
from types import SimpleNamespace
from datetime import datetime, timezone


async def test_a_user_from_another_tenant_cannot_run_a_tool():
    outcome, trace, _ = await run([
        reply(calls=[call("c1", "search_knowledge_base", {"query": "client tax file for Company B"})]),
        reply("That information is not available."),
    ], same_tenant=False)
    assert [(r.tool, r.ok, r.policy_reason) for r in trace] == [("search_knowledge_base", False, "user_not_authorised")]
    assert outcome.sources == []


def test_another_tenants_private_source_is_never_usable():
    version = SimpleNamespace(revoked_at=None, superseded_by_version_id=None, status="APPROVED",
                              effective_from=None, effective_to=None)
    source = SimpleNamespace(is_tenant_private=True, tenant_id="tenant-b", jurisdiction_scope="UK", framework_scope="")
    decision = _decide(version, source, SimpleNamespace(decision="allow", valid_from=None, valid_to=None,
                                                        rights_version=1, reason_code="OK"),
                       SourceUseContext(tenant_id="tenant-a", jurisdiction="UK"), "retrieval",
                       datetime.now(timezone.utc))
    assert not decision.allowed and decision.reason_code == "TENANT_PRIVATE_BOUNDARY"


def test_an_engagement_restricted_source_is_usable_only_inside_its_engagement():
    """§06.2: filter by engagement as well as tenant and licence."""
    version = SimpleNamespace(revoked_at=None, superseded_by_version_id=None, status="APPROVED",
                              effective_from=None, effective_to=None)
    source = SimpleNamespace(is_tenant_private=True, tenant_id="tenant-a", jurisdiction_scope="", framework_scope="")
    right = SimpleNamespace(decision="allow", valid_from=None, valid_to=None, rights_version=1,
                            reason_code="OK", terms_reference="engagement:eng-007")
    now = datetime.now(timezone.utc)
    inside = _decide(version, source, right, SourceUseContext(tenant_id="tenant-a", engagement_id="eng-007"), "retrieval", now)
    other = _decide(version, source, right, SourceUseContext(tenant_id="tenant-a", engagement_id="eng-999"), "retrieval", now)
    none = _decide(version, source, right, SourceUseContext(tenant_id="tenant-a"), "retrieval", now)
    assert inside.allowed and not other.allowed and not none.allowed
    assert other.reason_code == "ENGAGEMENT_BOUNDARY"

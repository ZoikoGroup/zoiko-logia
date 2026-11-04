"""A requested jurisdiction of "Any", "all" or "*" means no jurisdiction
filter, as an empty one does; a named jurisdiction still filters (25 Oct 2026:
"Any" was read as a jurisdiction of that name and excluded all 65 in-force
sources). No model, database or network.
"""
from datetime import date, datetime

import pytest

from app.domains.source_library.licensing import SourceUseContext, _decide, _scope_matches

UK = "UK,GB,United Kingdom"


@pytest.mark.parametrize("requested", ["", "Any", "any", " ANY ", "All", "all", "*"])
def test_any_all_and_star_mean_no_filter(requested):
    assert _scope_matches(UK, requested)
    assert _scope_matches("US", requested)
    assert _scope_matches("India,IN", requested)


@pytest.mark.parametrize("configured, requested, matches", [
    (UK, "United Kingdom", True), (UK, "uk", True), (UK, "GB", True),
    (UK, "India", False), (UK, "United States", False), (UK, "International", False),
    ("India,IN", "India", True), ("India,IN", "United Kingdom", False),
    ("Global", "India", True),                     # a global source applies everywhere, as before
    ("", "India", True),                           # an unscoped source, as before
    (UK, "Anywhere", False),                       # only the exact words lift the filter
])
def test_named_jurisdictions_still_filter(configured, requested, matches):
    assert _scope_matches(configured, requested) is matches


class _Version:
    status, effective_from, effective_to, revoked_at, superseded_by_version_id = "ACTIVE", None, None, None, None
    id, source_id, tenant_id = "v1", "s1", "GLOBAL_CONTROL"


class _Source:
    id, tenant_id, is_tenant_private, licence_state, framework_scope = "s1", "GLOBAL_CONTROL", False, "permitted", ""
    jurisdiction_scope = UK


@pytest.mark.parametrize("requested, reason", [("Any", None), ("United Kingdom", None), ("India", "JURISDICTION_MISMATCH")])
def test_the_rights_decision_follows(requested, reason):
    context = SourceUseContext(tenant_id="t", jurisdiction=requested, effective_date=date(2026, 10, 25))
    decision = _decide(_Version(), _Source(), None, context, "retrieval", now=datetime(2026, 10, 25))
    assert (decision.reason_code == "JURISDICTION_MISMATCH") is (reason == "JURISDICTION_MISMATCH")

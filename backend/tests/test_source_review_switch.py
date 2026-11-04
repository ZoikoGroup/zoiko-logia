"""KRITON_SOURCE_REVIEW_ENFORCEMENT: Phase 1's strict source rules are rolled
out by switch (4 Nov 2026 impact assessment). Existing library versions were
approved by their own importer and many carry no effective date; retrieval
always dates its request. Off (the default), they are used as before; on, a
self-approved version and an undated one for a dated request are refused."""
from datetime import date, datetime

import pytest

from app.domains.source_library.licensing import SourceUseContext, _decide, source_review_enforced


class _Version:
    status, effective_to, revoked_at, superseded_by_version_id = "ACTIVE", None, None, None
    id, source_id, tenant_id = "v1", "s1", "GLOBAL_CONTROL"

    def __init__(self, *, approved_by="reviewer", submitted_by="importer", effective_from=date(2025, 1, 1)):
        self.approved_by, self.submitted_by, self.effective_from = approved_by, submitted_by, effective_from


class _Source:
    id, tenant_id, is_tenant_private, licence_state, framework_scope = "s1", "GLOBAL_CONTROL", False, "permitted", ""
    jurisdiction_scope = "UK"


def _reason(version, *, enforced, monkeypatch, effective_date=date(2026, 11, 4)):
    if enforced:
        monkeypatch.setenv("KRITON_SOURCE_REVIEW_ENFORCEMENT", "true")
    else:
        monkeypatch.delenv("KRITON_SOURCE_REVIEW_ENFORCEMENT", raising=False)
    context = SourceUseContext(tenant_id="t", jurisdiction="UK", effective_date=effective_date)
    return _decide(version, _Source(), None, context, "retrieval", now=datetime(2026, 11, 4)).reason_code


def test_the_switch_is_off_unless_set(monkeypatch):
    monkeypatch.delenv("KRITON_SOURCE_REVIEW_ENFORCEMENT", raising=False)
    assert source_review_enforced() is False
    monkeypatch.setenv("KRITON_SOURCE_REVIEW_ENFORCEMENT", "on")
    assert source_review_enforced() is True


@pytest.mark.parametrize("version", [
    _Version(approved_by="importer", submitted_by="importer"),     # self-approved (C7)
    _Version(effective_from=None),                                # undated, dated request (C4)
])
def test_off_uses_existing_versions_as_before(version, monkeypatch):
    # Reaches the rights check (no right row here), not a Phase 1 refusal.
    assert _reason(version, enforced=False, monkeypatch=monkeypatch) == "RIGHT_UNKNOWN"


def test_on_refuses_a_self_approved_version(monkeypatch):
    assert _reason(_Version(approved_by="importer", submitted_by="importer"), enforced=True,
                   monkeypatch=monkeypatch) == "INDEPENDENT_REVIEW_REQUIRED"


def test_on_refuses_an_undated_version_for_a_dated_request(monkeypatch):
    assert _reason(_Version(effective_from=None), enforced=True, monkeypatch=monkeypatch) == "APPLICABILITY_UNKNOWN"


@pytest.mark.parametrize("enforced", [False, True])
def test_period_coverage_applies_either_way(enforced, monkeypatch):
    # A version that starts after the requested date does not cover it.
    late = _Version(effective_from=date(2027, 1, 1))
    assert _reason(late, enforced=enforced, monkeypatch=monkeypatch) == "PERIOD_NOT_COVERED"

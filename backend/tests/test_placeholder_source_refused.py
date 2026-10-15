"""The proposed FASB placeholder correction (status PROPOSED, licence
unknown) cannot be used as evidence; neither can an ACTIVE version with no
recorded right (its state today)."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from app.domains.source_library.licensing import SourceUseContext, _decide

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
SOURCE = NS(is_tenant_private=False, tenant_id="GLOBAL_CONTROL", jurisdiction_scope="Global", framework_scope="")
CONTEXT = SourceUseContext(tenant_id="t1")


def _version(status):
    return NS(revoked_at=None, superseded_by_version_id=None, status=status, effective_from=None, effective_to=None)


def test_a_proposed_version_is_not_approved_evidence():
    allow = NS(valid_from=None, valid_to=None, decision="allow", terms_reference="", rights_version=1, reason_code=None)
    decision = _decide(_version("PROPOSED"), SOURCE, allow, CONTEXT, "model_transmission", NOW)
    assert not decision.allowed and decision.reason_code == "VERSION_NOT_APPROVED"


def test_todays_active_placeholder_without_a_right_is_already_refused():
    decision = _decide(_version("ACTIVE"), SOURCE, None, CONTEXT, "model_transmission", NOW)
    assert not decision.allowed and decision.reason_code == "RIGHT_UNKNOWN"

"""A chat's earlier file, restored and read on a follow-up, counts as evidence."""
import pytest

from app.orchestration.service import _evidence_scope


@pytest.mark.parametrize("scope, sent, restored_read, expected", [
    # The reported case: follow-up sent as WEB_ONLY with no files, the chat's
    # fixed-asset register restored and read -> its figures must be citable.
    ("WEB_ONLY", False, True, "COMBINED"),
    ("WEB_ONLY", False, False, "WEB_ONLY"),          # no file in the chat
    ("WEB_ONLY", True, True, "WEB_ONLY"),            # an explicit request is kept
    ("DOCUMENTS_ONLY", True, True, "DOCUMENTS_ONLY"),
    ("DOCUMENTS_THEN_WEB", False, True, "DOCUMENTS_THEN_WEB"),
    ("COMBINED", False, True, "COMBINED"),
])
def test_evidence_scope(scope, sent, restored_read, expected):
    assert _evidence_scope(scope, sent, restored_read) == expected

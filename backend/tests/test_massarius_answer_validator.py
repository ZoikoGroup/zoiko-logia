"""ZL-ENG-03 Acceptance Criterion 7 — answer_validator.py (Checkpoint C)
blocks invalid output end-to-end and returns a degraded route rather than
the invalid answer, including the internal_reasoning_only non-exposure case."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.massarius.answer_validator import validate_answer, validate_answer_or_raise
from app.domains.massarius.errors import ValidationFailed
from app.orchestration.schemas import SourceBundle, SourceSummary

_BUNDLE = SourceBundle(
    source_bundle_id="sb-1",
    eligible_source_count=1,
    sources=[SourceSummary(id="s1", title="FRS 102", category="standards", jurisdiction_scope="UK", version_label="v1", status="ACTIVE")],
    authority_level="secondary",
    confidence_state="sufficient",
    source_display_states={"s1": "show"},
)


def test_clean_grounded_cited_answer_passes():
    result = validate_answer("Under FRS 102, this may generally apply. [REF-1]", _BUNDLE)
    assert result.passed
    print("test_clean_grounded_cited_answer_passes: PASSED")


def test_ungrounded_substantive_answer_fails():
    empty_bundle = SourceBundle(source_bundle_id="sb-empty", eligible_source_count=0, sources=[])
    result = validate_answer(
        "This is a long, substantive answer with no sources backing it at all, over fifty characters.",
        empty_bundle,
    )
    assert not result.passed
    assert any("Grounding" in f for f in result.failures)
    print("test_ungrounded_substantive_answer_fails: PASSED")


def test_unbound_citation_fails():
    result = validate_answer("See [REF-9] for details.", _BUNDLE)
    assert not result.passed
    assert any("Citation binding" in f for f in result.failures)
    print("test_unbound_citation_fails: PASSED")


def test_prohibited_claim_degrades_to_refusal():
    result = validate_answer("I certify that this is correct. [REF-1]", _BUNDLE)
    assert not result.passed
    assert result.degraded_route == "REFUSAL"
    print("test_prohibited_claim_degrades_to_refusal: PASSED")


def test_authority_ceiling_blocks_overreach_on_non_primary_source():
    result = validate_answer("This is the only correct treatment. [REF-1]", _BUNDLE)
    assert not result.passed
    assert any("Authority ceiling" in f for f in result.failures)
    print("test_authority_ceiling_blocks_overreach_on_non_primary_source: PASSED")


def test_confidence_support_blocks_unhedged_certainty_on_limited_confidence():
    limited_bundle = _BUNDLE.model_copy(update={"confidence_state": "limited"})
    result = validate_answer("This is definitely correct. [REF-1]", limited_bundle)
    assert not result.passed
    assert any("Confidence support" in f for f in result.failures)
    print("test_confidence_support_blocks_unhedged_certainty_on_limited_confidence: PASSED")


def test_disclaimer_presence_required_when_flagged():
    result = validate_answer(
        "A reasonably long answer with enough content to pass grounding checks. [REF-1]",
        _BUNDLE,
        disclaimer_required=True,
    )
    assert not result.passed
    assert any("Disclaimer presence" in f for f in result.failures)
    print("test_disclaimer_presence_required_when_flagged: PASSED")


def test_internal_reasoning_only_source_never_exposed():
    """The licence exposure check — a source marked internal_reasoning_only
    must never leak into the answer text, even by title."""
    private_bundle = SourceBundle(
        source_bundle_id="sb-private",
        eligible_source_count=1,
        sources=[SourceSummary(id="s1", title="Confidential Internal Memo", category="internal", jurisdiction_scope="UK", version_label="v1", status="ACTIVE")],
        source_display_states={"s1": "internal_reasoning_only"},
    )
    result = validate_answer("Per the Confidential Internal Memo, proceed as follows. [REF-1]", private_bundle)
    assert not result.passed
    assert any("Licence exposure" in f for f in result.failures)
    assert result.degraded_route == "REFUSAL"
    print("test_internal_reasoning_only_source_never_exposed: PASSED")


def test_validate_answer_or_raise_raises_typed_exception():
    """The literal spec shape — a direct call must raise ValidationFailed,
    not just return a falsy result, for callers that want to catch it."""
    try:
        validate_answer_or_raise("See [REF-9].", _BUNDLE)
        raise AssertionError("validate_answer_or_raise should have raised ValidationFailed")
    except ValidationFailed as e:
        assert e.failures
    print("test_validate_answer_or_raise_raises_typed_exception: PASSED")


if __name__ == "__main__":
    print("Running Massarius answer_validator tests (AC7)...")
    test_clean_grounded_cited_answer_passes()
    test_ungrounded_substantive_answer_fails()
    test_unbound_citation_fails()
    test_prohibited_claim_degrades_to_refusal()
    test_authority_ceiling_blocks_overreach_on_non_primary_source()
    test_confidence_support_blocks_unhedged_certainty_on_limited_confidence()
    test_disclaimer_presence_required_when_flagged()
    test_internal_reasoning_only_source_never_exposed()
    test_validate_answer_or_raise_raises_typed_exception()
    print("All tests passed successfully!")

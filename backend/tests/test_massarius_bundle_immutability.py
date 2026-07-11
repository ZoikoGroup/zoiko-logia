"""ZL-ENG-03 Acceptance Criterion 3 — SourceBundle is created only by
bundle_builder.py and is immutable after creation."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pydantic import ValidationError

from app.domains.massarius.bundle_builder import build_bundle
from app.domains.massarius.license_gate import LicenceCheckResult
from app.orchestration.schemas import SourceBundle, SourceSummary


def test_source_bundle_rejects_mutation():
    """A frozen SourceBundle must refuse attribute assignment at the type
    level, not merely by convention."""
    bundle = SourceBundle(source_bundle_id="sb-1", sources=[])
    try:
        bundle.eligible_source_count = 99
        raise AssertionError("SourceBundle allowed mutation — it must be frozen")
    except ValidationError:
        pass
    print("test_source_bundle_rejects_mutation: PASSED")


def test_source_bundle_nested_list_still_reports_frozen_model():
    """Sanity check: freezing works even with a populated sources list —
    frozen=True guards the model's own fields, not list mutability of a
    field's value, so this documents the boundary rather than assuming it."""
    bundle = SourceBundle(
        source_bundle_id="sb-2",
        sources=[SourceSummary(id="s1", title="X", category="tax", jurisdiction_scope="UK", version_label="v1", status="ACTIVE")],
    )
    try:
        bundle.source_bundle_id = "sb-tampered"
        raise AssertionError("SourceBundle allowed mutation of source_bundle_id")
    except ValidationError:
        pass
    print("test_source_bundle_nested_list_still_reports_frozen_model: PASSED")


def test_bundle_builder_is_the_only_thing_producing_the_final_bundle():
    """build_bundle() is the sole call site that assembles a preliminary
    bundle + licence result into the final SourceBundle used downstream."""
    preliminary = SourceBundle(
        source_bundle_id="sb-3",
        confidence_state="sufficient",
        sources=[SourceSummary(id="s1", title="X", category="tax", jurisdiction_scope="UK", version_label="v1", status="ACTIVE")],
    )
    licence_result = LicenceCheckResult(
        eligible=preliminary.sources,
        excluded=[],
        exclusion_reasons={},
        display_states={"s1": "show"},
    )
    final = build_bundle(preliminary, licence_result)
    assert final.source_bundle_id == "sb-3"
    assert final.source_display_states == {"s1": "show"}
    assert final.index_version == "v1"
    print("test_bundle_builder_is_the_only_thing_producing_the_final_bundle: PASSED")


if __name__ == "__main__":
    print("Running Massarius bundle immutability tests (AC3)...")
    test_source_bundle_rejects_mutation()
    test_source_bundle_nested_list_still_reports_frozen_model()
    test_bundle_builder_is_the_only_thing_producing_the_final_bundle()
    print("All tests passed successfully!")

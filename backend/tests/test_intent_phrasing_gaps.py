"""
Regression suite for six intent-classification/domain-gate phrasing gaps
found via live testing:

  1. "Correlate X with Y" (imperative verb) wasn't recognized as CORRELATION
     intent, nor split into two subjects — fell through to the ordinary
     single-series path and silently matched the wrong series.
  2. "How spread out is X?" wasn't recognized as DISTRIBUTION intent.
  3. "Relationship between X and Y" where X/Y are real economic statistics
     was always read as an entity-relationship-graph request, even when no
     real graph could be extracted — needed disambiguation toward
     CORRELATION when the subjects are genuinely statistical.
  4. "Ownership chain" (unlike "ownership structure"/"ownership network")
     wasn't recognized as a graph-shaped intent.
  5. Bare "Matrix of: ..." (unlike "as a matrix"/"matrix view") wasn't
     recognized as an explicit heatmap request or relationship intent.
  6. "Partner"/"sign-off"/"delivery note"/"goods receipt"/"requisition"
     weren't in _ACCOUNTING_ENTITY_HINTS, so a standard audit sign-off
     workflow ("Draft Report -> Peer Review -> Partner Sign-off -> Issued")
     was force-refused as off-domain.
  7. An explicit "exact"/"precise" ask ("Give me the exact quarterly CPI
     values for the last 8 quarters") was classified as TREND, not
     PRECISE_DATA, because _TREND_HINTS's "last \\d+ (years?|quarters?|
     months?)" was checked first and won — the query rendered a trend chart
     instead of the exact-values table the user explicitly asked for.
"""
from app.orchestration.intent_classifier import (
    classify_intent, CORRELATION, DISTRIBUTION, RELATIONSHIP, NETWORK, PRECISE_DATA, TREND,
)
from app.orchestration.dbnomics import _split_correlation_subjects
from app.orchestration.response_planner import detect_explicit_heatmap_request
from app.orchestration.service import _structured_visual_query_is_in_domain


def test_correlate_with_imperative_classified_as_correlation():
    assert classify_intent("Correlate UK inflation with India CPI") == CORRELATION


def test_correlate_with_imperative_splits_subjects():
    assert _split_correlation_subjects("Correlate UK inflation with India CPI") == ("UK inflation", "India CPI")


def test_how_spread_out_classified_as_distribution():
    assert classify_intent("How spread out is India's CPI?") == DISTRIBUTION


def test_relationship_between_statistics_classified_as_correlation():
    assert classify_intent("Any relationship between India CPI and UK inflation?") == CORRELATION


def test_relationship_between_statistics_splits_subjects():
    assert _split_correlation_subjects("Any relationship between India CPI and UK inflation?") == (
        "India CPI", "UK inflation",
    )


def test_relationship_between_entities_still_classified_as_relationship():
    # Guard: the new stat-keyword disambiguation must not hijack a genuine
    # entity-relationship-graph question that happens to share the phrase.
    assert classify_intent("Show the relationship between Company A and Company B") == RELATIONSHIP


def test_ownership_chain_classified_as_graph_intent():
    assert classify_intent("Show the ownership chain: Holdco owns Opco; Opco owns Propco.") == NETWORK


def test_bare_matrix_of_classified_as_relationship():
    q = "Matrix of: Delivery Note supports Invoice; Invoice supports Payment Voucher."
    assert classify_intent(q) == RELATIONSHIP


def test_bare_matrix_of_detected_as_explicit_heatmap_request():
    q = "Matrix of: Delivery Note supports Invoice; Invoice supports Payment Voucher."
    assert detect_explicit_heatmap_request(q) is True


def test_partner_sign_off_workflow_no_longer_force_refused():
    q = "Interactive flow: Draft Report -> Peer Review -> Partner Sign-off -> Issued."
    assert _structured_visual_query_is_in_domain(q) is True


def test_generic_non_accounting_flow_still_force_refused():
    # Guard: the new accounting-entity words must not over-broaden the gate.
    q = "Interactive flow: Draft PR -> Code Review -> Merge -> Deployed."
    assert _structured_visual_query_is_in_domain(q) is False


def test_exact_precise_data_request_wins_over_an_incidental_time_range():
    q = "Give me the exact quarterly CPI values for the UK for the last 8 quarters"
    assert classify_intent(q) == PRECISE_DATA


def test_plain_time_range_without_exact_wording_still_classified_as_trend():
    # Guard: reordering PRECISE_DATA ahead of TREND must not swallow an
    # ordinary trend request that has no "exact"/"precise"/"convert" wording.
    q = "Show India CPI over the last 10 years"
    assert classify_intent(q) == TREND

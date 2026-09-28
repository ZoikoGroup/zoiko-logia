"""Charts and narration from uploaded documents.

Asking for "the assets in this document as a pie chart" produced a bar chart
of assets AND liabilities, described as a falling trend:

    "their assests decreased from 418,000 in Inventory to 87,000 in Deferred
     tax liability. The minimum was 87,000 … the maximum was 703,000"

Three separate wrongs in one answer. Inventory did not come before a tax
liability and nothing decreased — they are line items, not periods. An asset
and a liability were charted as peers. And the pie that was asked for was
replaced without a word.
"""
from __future__ import annotations

import pytest

from app.orchestration.data_shape import PART_TO_WHOLE, classify_data_shape
from app.orchestration.document_evidence import build_document_evidence
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.response_planner import plan_response
from app.orchestration.service import _grounded_domain_fallback
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator
from app.orchestration.websearch import WebSource

BALANCE_SHEET = """BALANCE SHEET EXTRACT AT 31 MARCH 2026
Non-current assets
 Intangible assets - software and licences 340,000
 Property, plant and equipment 1,265,000
 Total non-current assets 1,605,000
Current assets
 Inventory 418,000
 Trade receivables 703,000
 Cash at bank 512,000
 Total current assets 1,633,000
Liabilities
 Trade payables 396,000
 Deferred tax liability 87,000
"""

SOURCES = [
    WebSource(title="accounts.pdf — Page 2", url="", snippet=BALANCE_SHEET,
              provider="uploaded_document", freshness="uploaded", source_id="doc-1")
]


def _decide(query: str):
    evidence = build_document_evidence(query, SOURCES)
    intent = classify_intent(query)
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    result = VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query)
    return evidence, shape, result


# ── the requested chart is the chart drawn ──────────────────────────────────

def test_a_pie_chart_of_document_figures_is_drawn():
    _evidence, shape, result = _decide("show the assets in this document as a pie chart")
    assert shape == PART_TO_WHOLE
    assert result.selected == "DONUT"
    assert result.variant == "PIE_CHART"


def test_without_a_named_composition_chart_no_slices_are_built():
    """Slices are only ever built deliberately. A plain question about the
    document must not silently become a pie."""
    evidence, _shape, _result = _decide("what are the key figures in this document")
    assert evidence.composition == []


# ── assets are not liabilities ──────────────────────────────────────────────

def test_asking_for_assets_excludes_liabilities():
    """A balance sheet is one section holding two opposite kinds of figure.
    In a pie, where every slice reads as part of one whole, mixing them is
    not a near-miss — it is false."""
    evidence, _shape, _result = _decide("show the assets in this document as a pie chart")
    labels = {item.dimension.lower() for item in evidence.observations}
    assert "inventory" in labels
    assert "trade receivables" in labels
    assert not any("payable" in label for label in labels)
    assert not any("liability" in label for label in labels)


def test_the_kept_rows_reconcile_to_the_documents_own_total():
    """Current assets in the file total 1,633,000. The extracted rows must
    come to exactly that — proof the right rows were kept and the total row
    itself was excluded rather than charted beside its parts."""
    evidence, _shape, _result = _decide("show the assets in this document as a pie chart")
    assert sum(item.value for item in evidence.observations) == 1_633_000


def test_asking_for_liabilities_excludes_assets():
    evidence, _shape, _result = _decide("show the liabilities in this document as a pie chart")
    labels = {item.dimension.lower() for item in evidence.observations}
    assert any("payable" in label or "liability" in label for label in labels)
    assert "inventory" not in labels


# ── narration ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query",
    [
        "what are the key figures in this document",
        "show the assets in this document as a pie chart",
    ],
)
def test_line_items_are_never_described_as_a_trend(query):
    evidence = build_document_evidence(query, SOURCES)
    text = _grounded_domain_fallback(query, evidence) or ""
    assert text
    for word in ("decreased from", "increased from", "fluctuated from"):
        assert word not in text, f"{word!r} describes categories as a movement over time: {text}"


def test_the_narration_names_the_largest_and_smallest_instead():
    evidence = build_document_evidence("what are the key figures in this document", SOURCES)
    text = _grounded_domain_fallback("what are the key figures in this document", evidence) or ""
    assert "largest is Trade receivables" in text
    assert "smallest is Deferred tax liability" in text
    assert "not a series over time" in text


def test_the_total_is_described_as_the_rows_shown_only():
    """The document's own totals were removed so none is charted beside its
    components — so the sum quoted must not be presented as a figure the
    document states."""
    evidence = build_document_evidence("show the assets in this document as a pie chart", SOURCES)
    text = _grounded_domain_fallback("show the assets…as a pie chart", evidence) or ""
    assert "1,633,000" in text
    assert "sum of those lines only" in text


def test_the_slice_caveat_says_what_the_shares_are_of():
    evidence = build_document_evidence("show the assets in this document as a pie chart", SOURCES)
    assert evidence.composition
    assert "not of any total stated" in (evidence.composition_caveat or "")
    assert evidence.composition_is_estimated is False


def test_shares_sum_to_one_hundred_percent():
    evidence = build_document_evidence("show the assets in this document as a pie chart", SOURCES)
    assert round(sum(slice_.value for slice_ in evidence.composition), 6) == 100.0

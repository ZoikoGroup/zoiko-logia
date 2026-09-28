"""Two reachability fixes in orchestration/extraction.py.

Both are cases where a chart the pipeline fully supports could not be produced
from a question a user would naturally write — not a missing capability, but a
threshold or vocabulary in the extractor that was stricter than the capability
it feeds.
"""
from __future__ import annotations

import pytest

from app.orchestration.data_shape import classify_data_shape
from app.orchestration.evidence import Entity, EvidenceModel, Relationship
from app.orchestration.extraction import extract_graph, extract_user_visual_evidence
from app.orchestration.intent_classifier import GRAPH_INTENTS, PROCESS, classify_intent
from app.orchestration.response_planner import plan_response
from app.orchestration.visualization.orchestrator import VisualizationOrchestrator


def _chart_for(query: str) -> str | None:
    """The chart type the pipeline settles on, assembled as service.py does."""
    intent = classify_intent(query)
    evidence = extract_user_visual_evidence(query, intent)
    graph = extract_graph(query)
    if graph and (intent in GRAPH_INTENTS or intent == PROCESS):
        evidence = evidence if not evidence.is_empty() else EvidenceModel()
        evidence.entities = [Entity(id=node, name=node) for node in graph.nodes]
        evidence.relationships = [
            Relationship(source_id=edge.source, target_id=edge.target, type=edge.type)
            for edge in graph.edges
        ]
        evidence.subject = evidence.subject or query[:80]
    shape = classify_data_shape(evidence, intent)
    plan = plan_response(query, intent, shape)
    return VisualizationOrchestrator().decide(evidence, shape, plan, "spec", query).selected


# ── Sample size ─────────────────────────────────────────────────────────────

def test_four_values_are_enough_for_a_box_plot():
    """box_plot declares minimum_observations=4, but the extractor demanded
    eight — the HISTOGRAM floor — so four to seven values were discarded before
    any capability could accept them."""
    assert _chart_for(
        "show the distribution of invoice times as a box plot: 4, 8, 15, 16"
    ) == "BOX"


def test_three_values_remain_too_few():
    assert _chart_for(
        "show the distribution of invoice times as a box plot: 4, 8, 15"
    ) is None


def test_a_histogram_still_requires_its_own_eight():
    """Lowering the extractor's floor must not lower the histogram's. That
    rule belongs to the capability, not to the code reading the numbers."""
    assert _chart_for(
        "show the distribution of these times: 1,2,2,3,3,3,4,5,5,7,8,8,10,12"
    ) == "HISTOGRAM"


# ── Relationship vocabulary ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query, expected",
    [
        ("show as a heatmap: Control A mitigates Risk One; Control B mitigates Risk Two", "HEATMAP"),
        ("show this as a graph: Invoice supports Payment; Payment settles Liability", "EVIDENCE_GRAPH"),
        ("show this as a graph: Manager approves Invoice; Invoice triggers Payment", "EVIDENCE_GRAPH"),
        ("show this as a graph: Bank Statement reconciles Cash Ledger", "EVIDENCE_GRAPH"),
        ("show this as a graph: Supplier issues Invoice; Invoice is approved by Manager", "EVIDENCE_GRAPH"),
    ],
)
def test_control_and_settlement_verbs_are_understood(query, expected):
    assert _chart_for(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "the invoice supports the payment claim made last quarter",
        "explain how a manager approves an invoice",
        "this control mitigates the risk of duplicate payment",
    ],
)
def test_ordinary_prose_still_draws_nothing(query):
    """The capitalised-entity guard is what makes a wider verb list safe: a
    new verb widens what can be drawn from a structured sentence, never what
    counts as one."""
    assert _chart_for(query) is None

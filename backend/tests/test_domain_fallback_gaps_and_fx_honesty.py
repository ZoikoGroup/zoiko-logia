"""
Regression suite for three bugs found via live testing:

  1. frankfurter.py's _CURRENCY_CODES listed AED/SAR/RUB as recognised even
     though Frankfurter (ECB daily reference rates) never publishes rates for
     them — _find_rate silently returned None, and the LLM then fabricated an
     approximate rate from its own training data instead of saying "not
     available" (a data-honesty violation, not just a UX gap).

  2. _grounded_domain_fallback()'s relationship-graph branch only recognised
     a narrow, separately-maintained verb list (_ACCOUNTING_RELATIONS) that
     had drifted out of sync with extraction.py's _RELATION_VERBS — "supports"
     was added there but never mirrored here, so a genuinely in-domain,
     correctly-extracted relationship ("Purchase Order supports Goods
     Receipt") kept a false off-domain refusal.

  3. Its PROCESS branch used an even narrower hardcoded keyword list
     (invoice|payment|audit|journal|expense|purchase order) that missed
     ordinary accounting-process phrasing like "tax filing process".
"""
from app.orchestration.frankfurter import _CURRENCY_CODES, _find_currencies
from app.orchestration.evidence import EvidenceModel
from app.orchestration.service import (
    _grounded_domain_fallback, _structured_visual_query_is_in_domain,
)
from app.orchestration.visualization.orchestrator import (
    _build_evidence_graph_spec, _build_process_flow_spec,
)
from app.orchestration.evidence import Entity, Relationship


# ── Frankfurter currency-list honesty ────────────────────────────────────

def test_aed_no_longer_falsely_recognised():
    assert "AED" not in _CURRENCY_CODES


def test_sar_no_longer_falsely_recognised():
    assert "SAR" not in _CURRENCY_CODES


def test_rub_no_longer_falsely_recognised():
    assert "RUB" not in _CURRENCY_CODES


def test_aed_inr_query_no_longer_reaches_find_rate_as_a_pair():
    # Only one recognised code now (INR) — _find_rate's len(codes) >= 2 gate
    # correctly can't fire, so no silent None-then-fabrication path opens.
    assert _find_currencies("Convert 500 AED to INR") == ["INR"]


def test_genuinely_supported_pair_still_recognised():
    assert _find_currencies("What is the current EUR to INR rate?") == ["EUR", "INR"]


# ── _grounded_domain_fallback relationship-graph gap ─────────────────────

def test_supports_verb_relationship_corrects_false_refusal():
    q = "Show as a matrix view: Purchase Order supports Goods Receipt; Goods Receipt supports Invoice."
    text = _grounded_domain_fallback(q, EvidenceModel())
    assert text is not None
    assert "I'm designed to answer" not in text
    assert "Purchase Order supports Goods Receipt" in text


# ── _grounded_domain_fallback PROCESS gap ────────────────────────────────

def test_tax_filing_process_flowchart_corrects_false_refusal():
    q = "Show the tax filing process as a flowchart: Return Prepared -> Reviewed -> Filed -> Acknowledged."
    text = _grounded_domain_fallback(q, EvidenceModel())
    assert text is not None
    assert "I'm designed to answer" not in text


def test_flow_diagram_wording_is_deterministically_in_scope():
    q = "Show a flow diagram for: Calculate Gross Pay -> Deduct Tax -> Pay Net Salary"
    assert _structured_visual_query_is_in_domain(q) is True
    text = _grounded_domain_fallback(q, EvidenceModel())
    assert text is not None
    assert "3 supplied accounting-workflow stages" in text


def test_show_relationship_as_network_wording_is_deterministically_in_scope():
    q = "Show this relationship as a network: Parent Company owns Subsidiary; Subsidiary pays Supplier."
    assert _structured_visual_query_is_in_domain(q) is True
    text = _grounded_domain_fallback(q, EvidenceModel())
    assert text is not None
    assert "Parent Company owns Subsidiary" in text
    assert "Subsidiary pays Supplier" in text


def test_generic_non_accounting_flowchart_still_returns_none():
    # Guard: a technical/non-accounting flowchart should NOT be force-corrected.
    q = "Show this as a flowchart: Draft -> Manager Review -> Approved -> Published."
    assert _grounded_domain_fallback(q, EvidenceModel()) is None


def test_customer_compliance_flow_gets_deterministic_visual_answer():
    q = (
        "Show the process flow: Customer identity documentation received -> "
        "Automated sanctions screening completed -> Senior compliance review required -> "
        "Final onboarding decision recorded."
    )
    assert _structured_visual_query_is_in_domain(q) is True
    text = _grounded_domain_fallback(q, EvidenceModel())
    assert text is not None
    assert "4 supplied accounting-workflow stages" in text
    assert "cannot create visual" not in text


def test_structured_visuals_do_not_repeat_supplied_counts_below_renderer():
    evidence = EvidenceModel(
        entities=[Entity(id="a", name="A"), Entity(id="b", name="B")],
        relationships=[Relationship(source_id="a", target_id="b", type="next")],
    )
    assert _build_evidence_graph_spec(evidence, "graph").summary == ""
    assert _build_process_flow_spec(evidence, "flow").summary == ""

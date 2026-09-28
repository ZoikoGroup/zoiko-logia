"""
Regression suite for two extraction.py bugs found via live end-to-end
testing: hyphenated entity/stage identifiers ("Invoice-2024", "Sign-off")
silently broke both extractors entirely (returned None), and passive/audit-
trail verbs ("supports", "is audited by") weren't in the relation vocabulary
despite being exactly the kind of language websearch.py's domain gate
explicitly recognizes as in-domain accounting/audit language.
"""
from app.orchestration.extraction import extract_graph, extract_arrow_chain, extract_relation_clauses
from app.orchestration.intent_classifier import classify_intent, EVIDENCE_ANALYSIS
from app.orchestration.service import _structured_visual_query_is_in_domain


def test_evidence_trail_phrasing_classified_as_evidence_analysis():
    # Regression: found via live testing — "evidence trail" (without the
    # word "audit" immediately before it) wasn't in the intent hints, so
    # despite extract_graph() correctly finding the relationship, intent
    # stayed FACT and no graph was ever built.
    q = "Visualize the evidence trail: Working-Paper-7 supports Audit-Finding-3."
    assert classify_intent(q) == EVIDENCE_ANALYSIS


def test_structured_domain_scope_accepts_audit_evidence():
    q = "Visualize the evidence trail: Working-Paper-7 supports Audit-Finding-3."
    assert _structured_visual_query_is_in_domain(q) is True


def test_structured_domain_scope_rejects_software_dependencies():
    q = "Show the dependency graph: Frontend-Service depends on Auth-API; Auth-API depends on User-Database."
    assert _structured_visual_query_is_in_domain(q) is False


def test_structured_domain_scope_rejects_generic_publishing_flow():
    q = "Show this as a flowchart: Draft -> Manager Review -> Approved -> Published."
    assert _structured_visual_query_is_in_domain(q) is False


def test_structured_domain_scope_accepts_invoice_flow():
    q = "Show this as an interactive workflow: Invoice -> Review -> Approval -> Payment."
    assert _structured_visual_query_is_in_domain(q) is True


def test_semicolon_separated_audit_edges_are_merged():
    q = (
        "Visualize every supplied entity and relationship as an interactive evidence graph: "
        "Audit Finding -> Revenue Assertion; Revenue Assertion -> Sales Ledger; "
        "Sales Ledger -> Invoice Sample."
    )
    graph = extract_graph(q)
    assert graph is not None
    assert graph.nodes == ["Audit Finding", "Revenue Assertion", "Sales Ledger", "Invoice Sample"]
    assert len(graph.edges) == 3
    assert _structured_visual_query_is_in_domain(q) is True


def test_semicolon_separated_tax_graph_is_in_domain():
    q = (
        "Show the tax evidence graph: Tax Provision -> Deferred Tax Schedule; "
        "Deferred Tax Schedule -> General Ledger; General Ledger -> Tax Return."
    )
    graph = extract_graph(q)
    assert graph is not None
    assert len(graph.edges) == 3
    assert _structured_visual_query_is_in_domain(q) is True


def test_hyphenated_entities_with_new_verbs_extract_correctly():
    q = "Invoice-2024 supports Journal-Entry-88; Journal-Entry-88 is audited by Auditor-Team-A."
    graph = extract_graph(q)
    assert graph is not None
    assert graph.nodes == ["Invoice-2024", "Journal-Entry-88", "Auditor-Team-A"]
    edge_types = {(e.source, e.target): e.type for e in graph.edges}
    assert edge_types[("Invoice-2024", "Journal-Entry-88")] == "supports"
    assert edge_types[("Journal-Entry-88", "Auditor-Team-A")] == "is_audited_by"


def test_hyphenated_final_stage_in_arrow_chain_extracts_correctly():
    q = "Trial Balance -> Adjusting Entries -> Financial Statements -> Review -> Sign-off."
    graph = extract_arrow_chain(q)
    assert graph is not None
    assert graph.nodes[-1] == "Sign-off"
    assert graph.edges[-1].target == "Sign-off"


def test_hyphenated_arrow_chain_stage_in_the_middle_extracts_correctly():
    q = "Draft -> Legal-Review -> Sign-off -> Archive."
    graph = extract_arrow_chain(q)
    assert graph is not None
    assert graph.nodes == ["Draft", "Legal-Review", "Sign-off", "Archive"]


def test_arrow_chain_ending_in_question_mark_extracts_correctly():
    # Regression: the trailing lookahead only accepted "." (or end-of-
    # string/newline) as a chain terminator while the LEADING boundary
    # already treated ".!?" as equivalent sentence-enders — a query phrased
    # as a question ("...Onboard?") silently extracted nothing at all.
    q = "What are the steps in this process: Submit application -> Verify identity -> Approve -> Onboard?"
    graph = extract_arrow_chain(q)
    assert graph is not None
    assert graph.nodes == ["Submit application", "Verify identity", "Approve", "Onboard"]


def test_arrow_chain_ending_in_exclamation_mark_extracts_correctly():
    q = "Do this now: Draft -> Review -> Approve!"
    graph = extract_arrow_chain(q)
    assert graph is not None
    assert graph.nodes == ["Draft", "Review", "Approve"]


def test_supports_and_is_audited_by_recognised_as_relation_verbs():
    graph = extract_relation_clauses("Report supports Finding; Finding is audited by Reviewer.")
    assert graph is not None
    types = [e.type for e in graph.edges]
    assert "supports" in types
    assert "is_audited_by" in types


# ── Regression guard: previously-working (non-hyphenated) cases still work,
# and the false-positive guard against ordinary prose still holds. ─────────

def test_existing_non_hyphenated_relation_clause_still_works():
    graph = extract_relation_clauses("Acme Corp owns Beta Ltd.")
    assert graph is not None
    assert graph.edges[0].type == "owns"


def test_existing_non_hyphenated_arrow_chain_still_works():
    graph = extract_arrow_chain("Invoice -> Review -> Approval -> Payment.")
    assert graph is not None
    assert graph.nodes == ["Invoice", "Review", "Approval", "Payment"]


def test_false_positive_guard_still_holds_with_wider_verb_vocabulary():
    assert extract_relation_clauses("He owns a small business.") is None
    assert extract_relation_clauses("The team supports each other.") is None

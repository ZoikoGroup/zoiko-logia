"""The benchmark's own checks (scripts/run_baseline_eval.py): chart types,
missing inputs, tool expectations and the current-rules intent proxy."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("eval_harness", Path(__file__).resolve().parents[1] / "scripts" / "run_baseline_eval.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


def test_chart_types_fold_synonyms_and_read_chart_blocks():
    result = {"visualization": {"type": "DONUT"},
              "answer": {"text": 'x\n```chart\n{"type": "area", "data": []}\n```'}}
    assert harness.chart_types(result) == {"pie", "line"}


def test_visual_and_missing_input_and_tool_checks():
    case = {"source": "intelligence", "expect_visual": "none", "expect_missing_inputs": ["rate"],
            "expect_tools": ["get_exchange_rate"], "forbid_tools": ["search_web"]}
    result = {"outcome": "answered", "answer": {"text": "```chart\n{\"type\": \"bar\"}\n```"},
              "_tools_used": ["search_web"]}
    failures = harness.score(case, result)
    kinds = sorted({f.split(":", 1)[0] for f in failures})
    assert kinds == ["missing_inputs", "tools", "visual"]
    assert sum(f.startswith("tools:") for f in failures) == 2


def test_chart_alternatives_pass_when_any_matches():
    case = {"source": "intelligence", "expect_visual": "chart:bar_or_pie"}
    assert harness.score(case, {"answer": {"text": ""}, "visualization": {"type": "PIE"}}) == []
    assert any(f.startswith("visual:") for f in harness.score(case, {"answer": {"text": ""}, "visualization": {"type": "LINE"}}))


def test_rule_intent_reads_route_tools_and_formulas():
    assert harness.rule_intent({}, {"route": "CLARIFICATION", "outcome": "clarification_required"}) == "clarification"
    assert harness.rule_intent({}, {"route": "CALCULATION", "calculation": {"formula_ids": ["vat_liability"]}}) == "tax_calculation"
    assert harness.rule_intent({}, {"route": "CALCULATION", "calculation": {"formula_ids": ["gross_profit", "gross_profit_reconciliation"]}}) == "reconciliation"
    assert harness.rule_intent({}, {"route": "LLM", "_tools_used": ["get_exchange_rate"]}) == "live_data"
    assert harness.rule_intent({"attach": "x.csv"}, {"route": "LLM"}) == "document_analysis"
    assert harness.rule_intent({}, {"route": "LLM", "answer": {"text": "I checked 5 factual claims"}}) == "review"


def test_existing_cases_keep_their_old_visual_check():
    # The older sets use expect_visual: true; it must still mean "a chart is attached".
    assert harness.score({"expect_visual": True}, {"answer": {"text": "no chart"}}) == ["visual: expected a chart or diagram, got none"]


def test_an_expired_token_is_reported_for_re_sign_in():
    import httpx

    def reply(request):
        return httpx.Response(401, json={"detail": "Could not validate credentials"})

    with httpx.Client(base_url="http://test/api/v1", transport=httpx.MockTransport(reply)) as client:
        result = harness.ask(client, "q", [], case_id="c1")
    assert result.get("_unauthorized") is True

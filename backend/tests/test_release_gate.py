"""scripts/release_gate.py decision logic, without running any evaluation."""
import importlib.util
import sys
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "scripts" / "release_gate.py"
_spec = importlib.util.spec_from_file_location("release_gate", _path)
gate = importlib.util.module_from_spec(_spec)
sys.modules["release_gate"] = gate
_spec.loader.exec_module(gate)


def _result(case_id: str, passed: bool, category: str = "accuracy", failures=None) -> dict:
    return {"id": case_id, "passed": passed, "category": category,
            "failures": failures if failures is not None else ([] if passed else ["content: missing 'x'"])}


def test_a_case_that_passed_at_the_last_release_and_now_fails_is_a_regression():
    verdict = gate.judge("uk_vat", [_result("a", True), _result("b", False), _result("c", False)],
                         {"min_pass_rate": 0.3}, baseline={"b": True, "c": False})
    assert verdict["regressions"] == ["b"]  # c never passed, so it is not a regression


def test_pass_rate_below_the_minimum_is_flagged():
    verdict = gate.judge("uk_vat", [_result("a", True), _result("b", False)], {"min_pass_rate": 0.9}, baseline={})
    assert verdict["rate"] == 0.5 and verdict["below_minimum"]


def test_any_failure_in_a_zero_tolerance_category_is_reported():
    results = [_result("s1", True, "safety"), _result("s2", False, "safety"), _result("x", False, "accuracy")]
    verdict = gate.judge("regression", results, {"min_pass_rate": 0.0, "zero_tolerance_categories": ["safety"]}, baseline={})
    assert verdict["zero_tolerance_failures"] == ["s2"]


def test_unreachable_service_is_unevaluated_not_a_wrong_answer():
    results = [_result("a", True), _result("b", False, failures=["error: HTTP 503: database unavailable"])]
    verdict = gate.judge("uk_vat", results, {"min_pass_rate": 1.0}, baseline={"b": True})
    assert verdict["unevaluated"] == ["b"]
    assert verdict["regressions"] == [] and verdict["rate"] == 1.0 and not verdict["below_minimum"]


def test_empty_mandatory_dataset_fails_but_empty_initial_gold_is_allowed():
    assert gate.judge('uk_vat', [], {'min_pass_rate': .9}, {})['below_minimum']
    assert not gate.judge('gold', [], {'allow_empty': True}, {})['below_minimum']


def test_metric_gate_cannot_be_hidden_by_overall_accuracy():
    result = {**_result('a', True), 'metrics': {'retrieval': False}}
    verdict = gate.judge('uk_vat', [result], {'min_metric_rates': {'retrieval': .85, 'citation': .85}}, {})
    assert verdict['rate'] == 1.0
    assert verdict['metric_failures'] == ['retrieval', 'citation']

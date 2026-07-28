"""
Unit tests for app/domains/calculation/expression_evaluator.py — the
sandboxed AST-based arithmetic evaluator (Phase 1 of the governed
calculation architecture, docs/calculation_architecture.md).

Security-critical: this module is the only place a model-proposed string
ever gets turned into a number. Every rejection case below is a security
boundary test, not just a correctness test.
"""
import os
import sys
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.calculation.expression_evaluator import evaluate_expression


# ── Valid arithmetic ────────────────────────────────────────────────────────

def test_addition():
    r = evaluate_expression("2 + 3")
    assert r.status == "verified"
    assert r.result == "5"


def test_subtraction():
    r = evaluate_expression("250000 - 180000")
    assert r.status == "verified"
    assert r.result == "70000"


def test_multiplication():
    r = evaluate_expression("1200 * 0.0725")
    assert r.status == "verified"
    assert Decimal(r.result) == Decimal("87.0000")


def test_division():
    r = evaluate_expression("100 / 4")
    assert r.status == "verified"
    assert r.result == "25"


def test_parentheses_change_precedence():
    r = evaluate_expression("(2 + 3) * 4")
    assert r.status == "verified"
    assert r.result == "20"


def test_unary_negative():
    r = evaluate_expression("-5 + 3")
    assert r.status == "verified"
    assert r.result == "-2"


def test_unary_positive():
    r = evaluate_expression("+5")
    assert r.status == "verified"
    assert r.result == "5"


def test_decimal_precision_not_binary_float():
    """0.1 + 0.2 == 0.30000000000000004 in binary float — must be exact here."""
    r = evaluate_expression("0.1 + 0.2")
    assert r.status == "verified"
    assert r.result == "0.3"


def test_nested_parentheses():
    r = evaluate_expression("((250000 - 180000) / 250000) * 100")
    assert r.status == "verified"
    assert Decimal(r.result) == Decimal("28")


# ── Rejections: correctness edge cases ──────────────────────────────────────

def test_division_by_zero():
    r = evaluate_expression("1 / 0")
    assert r.status == "error"
    assert any("zero" in e.lower() for e in r.errors)


def test_invalid_syntax():
    r = evaluate_expression("2 + + + )")
    assert r.status == "error"


def test_empty_expression():
    r = evaluate_expression("")
    assert r.status == "error"


def test_whitespace_only_expression():
    r = evaluate_expression("   ")
    assert r.status == "error"


# ── Rejections: security boundary — no code execution primitive is ever reachable ──

def test_rejects_name_reference():
    r = evaluate_expression("a + 1")
    assert r.status == "error"


def test_rejects_function_call():
    r = evaluate_expression("len([1, 2, 3])")
    assert r.status == "error"


def test_rejects_dunder_import_call():
    r = evaluate_expression('__import__("os").system("ls")')
    assert r.status == "error"


def test_rejects_attribute_access():
    r = evaluate_expression("(1).__class__")
    assert r.status == "error"


def test_rejects_import_statement():
    r = evaluate_expression("import os")
    assert r.status == "error"


def test_rejects_list_literal():
    r = evaluate_expression("[1, 2, 3]")
    assert r.status == "error"


def test_rejects_dict_literal():
    r = evaluate_expression("{'a': 1}")
    assert r.status == "error"


def test_rejects_indexing():
    r = evaluate_expression("[1,2,3][0]")
    assert r.status == "error"


def test_rejects_lambda():
    r = evaluate_expression("(lambda: 1)()")
    assert r.status == "error"


def test_rejects_boolean_operators():
    r = evaluate_expression("1 and 2")
    assert r.status == "error"


def test_rejects_comparison_operators():
    r = evaluate_expression("1 < 2")
    assert r.status == "error"


def test_rejects_power_operator():
    """Power is explicitly excluded from the allow-list — deliberately not
    supported (unbounded blowup risk from a small expression, e.g. 9**9**9)."""
    r = evaluate_expression("2 ** 100")
    assert r.status == "error"


def test_rejects_string_literal():
    r = evaluate_expression('"hello"')
    assert r.status == "error"


# ── Resource-exhaustion guards ──────────────────────────────────────────────

def test_rejects_extremely_long_expression():
    expr = "1" + "+1" * 500
    r = evaluate_expression(expr)
    assert r.status == "error"
    assert any("length" in e.lower() for e in r.errors)


def test_rejects_excessive_operation_count():
    expr = "1" + "+1" * 50  # under the length cap, over the operation-count cap
    r = evaluate_expression(expr)
    assert r.status == "error"
    assert any("nodes" in e.lower() or "operations" in e.lower() for e in r.errors)


def test_rejects_excessive_numeric_magnitude():
    r = evaluate_expression("1e30")
    assert r.status == "error"
    assert any("magnitude" in e.lower() for e in r.errors)


def test_rejects_magnitude_from_multiplication_blowup():
    """A small expression whose intermediate RESULT is unreasonably large —
    not just a literal that's too big to start with."""
    r = evaluate_expression("999999999999999999 * 999999999999999999")
    assert r.status == "error"
    assert any("magnitude" in e.lower() for e in r.errors)


def test_accepts_deeply_parenthesized_but_trivial_expression():
    """Pure grouping parentheses don't add AST depth in Python's ast module
    — only nested operations do. A harmless expression wrapped in many
    parens must still evaluate, not be mistaken for a resource-exhaustion attempt."""
    r = evaluate_expression("(" * 20 + "1" + ")" * 20)
    assert r.status == "verified"
    assert r.result == "1"


# ── Structured output shape ──────────────────────────────────────────────────

def test_result_record_has_expected_shape():
    r = evaluate_expression("2 + 2", inputs={"a": "2", "b": "2"}, unit="USD")
    d = r.to_dict()
    assert d["engine"] == "expression_evaluator"
    assert d["expression"] == "2 + 2"
    assert d["result"] == "4"
    assert d["unit"] == "USD"
    assert d["status"] == "verified"
    assert d["inputs"] == {"a": "2", "b": "2"}
    assert d["calculation_id"].startswith("calc-")


def test_every_call_gets_a_unique_calculation_id():
    r1 = evaluate_expression("1 + 1")
    r2 = evaluate_expression("1 + 1")
    assert r1.calculation_id != r2.calculation_id

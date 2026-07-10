import os
import sys

# Ensure backend root is in search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domains.risk_safety.models import RiskLevel
from app.domains.risk_safety.routing_matrix import ROUTING_MATRIX, ROUTING_MATRIX_VERSION, resolve

_CONFIDENCE_STATES = ("HIGH_CONFIDENCE", "LOW_CONFIDENCE", "NO_ELIGIBLE_SOURCE")
# classify()'s L2 scoring only ever assigns LOW/MEDIUM/HIGH — RESTRICTED is
# decided entirely in pre_screen() and never reaches the matrix.
_RISK_LEVELS = (RiskLevel.LOW.value, RiskLevel.MEDIUM.value, RiskLevel.HIGH.value)


def test_every_combination_resolves():
    """Every (risk_level, confidence_state) pair classify() can ever produce
    must resolve to a rule — no silent KeyError at request time."""
    for risk_level in _RISK_LEVELS:
        for confidence_state in _CONFIDENCE_STATES:
            rule = resolve(risk_level, confidence_state)
            assert rule is not None
            assert rule.route is not None
    print("test_every_combination_resolves: PASSED")


def test_matrix_has_explicit_entry_for_every_combination():
    """No combination should be silently falling through to _DEFAULTS —
    every one of the 9 real combinations gets its own explicit rule."""
    for risk_level in _RISK_LEVELS:
        for confidence_state in _CONFIDENCE_STATES:
            assert (risk_level, confidence_state) in ROUTING_MATRIX, (
                f"missing explicit routing_matrix entry for ({risk_level}, {confidence_state})"
            )
    print("test_matrix_has_explicit_entry_for_every_combination: PASSED")


def test_high_risk_degrades_without_strong_sources():
    """HIGH risk must never be auto-answered without a confident source —
    the whole point of RG-01 tightening is that low/no source strength on a
    high-risk query forces a human, it can't slip through as LLM-answered."""
    low_conf = resolve(RiskLevel.HIGH.value, "LOW_CONFIDENCE")
    no_source = resolve(RiskLevel.HIGH.value, "NO_ELIGIBLE_SOURCE")
    assert low_conf.allowed is False
    assert no_source.allowed is False
    print("test_high_risk_degrades_without_strong_sources: PASSED")


def test_low_risk_always_answerable():
    """LOW risk should never be blocked outright regardless of source
    strength — worst case it asks for clarification."""
    for confidence_state in _CONFIDENCE_STATES:
        rule = resolve(RiskLevel.LOW.value, confidence_state)
        assert rule.allowed or rule.route.value == "CLARIFICATION"
    print("test_low_risk_always_answerable: PASSED")


def test_matrix_version_is_set():
    assert ROUTING_MATRIX_VERSION
    print("test_matrix_version_is_set: PASSED")


if __name__ == "__main__":
    print("Running routing matrix unit tests...")
    test_every_combination_resolves()
    test_matrix_has_explicit_entry_for_every_combination()
    test_high_risk_degrades_without_strong_sources()
    test_low_risk_always_answerable()
    test_matrix_version_is_set()
    print("All tests passed successfully!")

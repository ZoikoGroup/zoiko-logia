"""Provider-independent refusal for unmistakably out-of-domain prompts."""

import pytest

from app.orchestration.service import _is_deterministically_out_of_scope


@pytest.mark.parametrize("query", [
    "Recommend a movie for tonight.",
    "Tell me a joke.",
    "Plan a holiday to Japan.",
    "Who won the football match yesterday?",
])
def test_known_out_of_scope_queries_do_not_need_a_model(query):
    assert _is_deterministically_out_of_scope(query)


@pytest.mark.parametrize("query", [
    "Tell me an accounting joke.",
    "Recommend a finance movie expense policy.",
    "What was the match rate for bank reconciliation entries?",
    "Plan the tax treatment for employee holiday pay.",
])
def test_accounting_queries_are_not_caught_by_narrow_scope_gate(query):
    assert not _is_deterministically_out_of_scope(query)

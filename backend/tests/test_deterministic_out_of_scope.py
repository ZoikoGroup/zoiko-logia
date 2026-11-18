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


@pytest.mark.parametrize("query", [
    "what is ai", "What is AI?", "explain machine learning", "what is python", "capital of france",
    "who is the president of usa", "what is the weather today", "explain photosynthesis", "symptoms of diabetes",
    "best movies 2026", "write a poem",
])
def test_an_unrelated_subject_is_refused_without_a_model(query):
    """18 Nov 2026: "what is ai" was answered with a definition of AI."""
    assert _is_deterministically_out_of_scope(query)


@pytest.mark.parametrize("query", [
    "how is AI used in auditing", "can ai help accountants", "python code to calculate depreciation",
    "impact of AI on the finance function", "what is the capital of a company", "football club revenue",
    "tax on cricket prize money", "explain ACCA syllabus", "apple stock price", "what is the gdp of india",
    "what is goodwill", "what is tax",
])
def test_an_unrelated_word_inside_a_domain_question_is_answered(query):
    assert not _is_deterministically_out_of_scope(query)

"""Regression tests for the Groq/OpenAI adapters' shared system prompt text.

Real gap (2026-08-03): the prompt told the model to tabulate comparable
numeric values, but never said (a) a category with multiple measures
(headcount, revenue, margin, ...) needs one column PER measure rather than
one collapsed column, or (b) numbers the user states directly in their own
query are legitimate data to use, not just retrieved source text. Both
gaps caused real, observed failures: multi-measure answers silently
dropped down to a single column before ever reaching the chart-selection
engine, and inline user-supplied datasets were sometimes treated as
unsupported. The two adapters intentionally duplicate this string rather
than sharing a constant (see their own module comments) — asserting on
both keeps them from silently drifting apart.
"""
from app.domains.model_gateway.providers.groq_adapter import _SYSTEM_PROMPT as GROQ_SYSTEM_PROMPT
from app.domains.model_gateway.providers.openai_adapter import _SYSTEM_PROMPT as OPENAI_SYSTEM_PROMPT


def test_groq_and_openai_system_prompts_stay_identical():
    assert GROQ_SYSTEM_PROMPT == OPENAI_SYSTEM_PROMPT


def test_system_prompt_requires_one_column_per_measure():
    for prompt in (GROQ_SYSTEM_PROMPT, OPENAI_SYSTEM_PROMPT):
        assert "more than one associated numeric measure" in prompt
        assert "never collapse multiple requested measures into a single column" in prompt


def test_system_prompt_treats_user_supplied_numbers_as_usable_data():
    for prompt in (GROQ_SYSTEM_PROMPT, OPENAI_SYSTEM_PROMPT):
        assert "the user's own message" in prompt
        assert "legitimate data to use" in prompt


def test_system_prompt_still_forbids_inventing_figures():
    # The new guidance widens what counts as usable data; it must not
    # weaken the existing never-fabricate rule.
    for prompt in (GROQ_SYSTEM_PROMPT, OPENAI_SYSTEM_PROMPT):
        assert "never invent or estimate figures to populate a table" in prompt


def test_system_prompt_forbids_placeholder_tables_and_malformed_markdown():
    # Real gap (2026-08-04): an educational ASC 606 answer produced a
    # table with placeholder cells ("the applicable amount" instead of a
    # real figure) and a stray, malformed "|---|---|---|" separator row
    # rendered as leaked literal text rather than a parsed table.
    for prompt in (GROQ_SYSTEM_PROMPT, OPENAI_SYSTEM_PROMPT):
        assert "placeholder text" in prompt
        assert "the applicable amount" in prompt
        assert "separator row goes immediately beneath the header row" in prompt

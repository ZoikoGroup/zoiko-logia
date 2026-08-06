"""Regression tests for build_grounded_context's over-budget-chunk handling.

Real gap (2026-08-06): "What is accrued revenue?" and "Explain the
accounting cycle..." both correctly routed to the right governed source (a
real, ~15,000-char accounting-fundamentals document), but that single chunk
alone exceeds the 8,000-char budget — the old behavior dropped it entirely
rather than truncating, so a genuinely relevant source produced zero
context and the query failed as "insufficient sources" / "clarify your
jurisdiction", a response that doesn't even make sense for what was
actually a context-budget implementation detail, not a real source gap.
"""
from app.domains.rag.context_fit import build_grounded_context


def _chunk(text: str, title: str = "Test Source") -> dict:
    return {"text": text, "metadata": {"title": title, "version": "v1", "jurisdiction": "Global", "file_path": "x"}}


def test_a_chunk_smaller_than_the_budget_is_included_unchanged():
    context, refs = build_grounded_context([_chunk("Short relevant content.")])
    assert "Short relevant content." in context
    assert len(refs) == 1


def test_an_over_budget_chunk_is_truncated_not_dropped():
    huge_text = "A" * 20000
    context, refs = build_grounded_context([_chunk(huge_text)], max_chars=8000)
    assert context != ""
    assert len(refs) == 1
    assert "A" in context
    assert len(context) <= 8000 + 200  # header/citation overhead allowance


def test_truncation_still_respects_the_overall_budget():
    huge_text = "B" * 50000
    context, refs = build_grounded_context([_chunk(huge_text)], max_chars=1000)
    assert len(context) < 1500
    assert len(refs) == 1


def test_a_chunk_too_small_to_be_useful_after_truncation_is_dropped():
    # If almost no budget remains, including a nearly-empty fragment isn't
    # worth it — must still degrade to "no context" rather than a useless
    # scrap, same as the old behavior for this specific edge case.
    context, refs = build_grounded_context(
        [_chunk("first chunk " * 50), _chunk("second chunk content " * 5000)],
        max_chars=700,
    )
    # First chunk fits; second has essentially no room left and is dropped.
    assert len(refs) == 1


def test_multiple_chunks_first_fits_second_gets_truncated():
    small = _chunk("Small first chunk.", title="First")
    huge = _chunk("C" * 20000, title="Second")
    context, refs = build_grounded_context([small, huge], max_chars=8000)
    assert len(refs) == 2
    assert "Small first chunk." in context
    assert "First" in context and "Second" in context

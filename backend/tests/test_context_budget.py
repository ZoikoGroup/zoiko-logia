"""Evidence budget — orchestration/websearch.py.

Groq's on-demand tier allows 8,000 tokens per minute, covering the system
prompt, the evidence and the answer together. Nothing bounded the evidence:
attaching five documents sent every chunk of all five, the request blew past
the cap, and the 429 came back with a 45-second reset — far beyond the single
short retry the Groq adapter performs. The user saw "Refused — policy
blocked", which it never was.
"""
from __future__ import annotations

from app.orchestration.websearch import (
    _MIN_SOURCE_CHARS,
    _context_allowances,
    _context_budget,
    WebSource,
)


def _sources(*lengths: int) -> list[WebSource]:
    return [
        WebSource(title=f"doc {i}", url="", snippet="x" * length, source_id=f"d{i}")
        for i, length in enumerate(lengths, start=1)
    ]


def test_small_evidence_is_never_touched():
    lengths = (400, 900, 1_200)
    assert _context_allowances(_sources(*lengths)) == list(lengths)


def test_total_evidence_stays_within_the_budget():
    allowances = _context_allowances(_sources(*([20_000] * 5)))
    assert sum(allowances) <= _context_budget()


def test_short_sources_keep_all_their_text_and_give_back_the_rest():
    """A few short snippets must not force a long one to be cut: the spare
    share is returned to the sources that need it."""
    allowances = _context_allowances(_sources(200, 200, 60_000))
    assert allowances[0] == 200
    assert allowances[1] == 200
    assert allowances[2] > _context_budget() // 3, (
        "the long source should inherit the share the short ones did not use"
    )


def test_no_source_is_cut_below_a_usable_size():
    """A 200-character fragment of a balance sheet is worse than nothing — it
    looks like evidence while being too small to answer from."""
    allowances = _context_allowances(_sources(*([50_000] * 40)))
    assert all(allowance >= _MIN_SOURCE_CHARS for allowance in allowances)


def test_one_large_document_cannot_crowd_out_the_others():
    """"compare these documents" depends on every attachment surviving."""
    allowances = _context_allowances(_sources(80_000, 5_000, 5_000, 5_000, 5_000))
    assert all(allowance > 0 for allowance in allowances)
    assert min(allowances[1:]) >= _MIN_SOURCE_CHARS


def test_truncation_is_declared_in_the_prompt():
    """A shortened source must be visible as shortened, or the model answers
    confidently from half a document."""
    from app.orchestration.websearch import build_web_grounded_prompt

    prompt = build_web_grounded_prompt("summarise these", _sources(*([40_000] * 4)))
    assert "shortened" in prompt
    assert len(prompt) < 200_000


def test_no_sources_still_returns_a_prompt():
    from app.orchestration.websearch import build_web_grounded_prompt

    assert build_web_grounded_prompt("what is payroll", [])
    assert _context_allowances([]) == []

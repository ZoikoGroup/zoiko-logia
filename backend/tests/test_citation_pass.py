"""An answer written from sources but citing none gets their markers (citation_pass.py)."""
from unittest.mock import AsyncMock

from app.orchestration.citation_pass import cite_sources

FAIL = "Kriton is temporarily unable to reach the language model provider."
ANSWER = ("Tax is any compulsory payment levied by a government. "
          "Income tax is a tax charged on the income of individuals and companies.")
SNIPPETS = {
    "REF-1": "Tax on personal income is defined as the taxes levied on the net income of individuals and companies.",
    "REF-2": "Tax revenue trends in Asia and the Pacific show growth in consumption taxes.",
}


async def test_a_supported_sentence_gets_its_marker():
    reply = ANSWER.replace("companies.", "companies [REF-1].")
    out = await cite_sources(ANSWER, SNIPPETS, AsyncMock(return_value=reply), FAIL)
    assert "[REF-1]" in out and out.replace(" [REF-1]", "") == ANSWER


async def test_a_marker_after_the_full_stop_is_checked_against_its_own_sentence():
    reply = ANSWER.replace("companies.", "companies. [REF-1]")
    assert "[REF-1]" in await cite_sources(ANSWER, SNIPPETS, AsyncMock(return_value=reply), FAIL)


async def test_a_marker_on_an_unrelated_source_is_dropped():
    reply = ANSWER.replace("government.", "government [REF-2].")
    assert await cite_sources(ANSWER, SNIPPETS, AsyncMock(return_value=reply), FAIL) == ANSWER


async def test_changed_wording_a_failure_or_an_already_cited_answer_is_left_alone():
    changed = AsyncMock(return_value="Tax is a payment [REF-1]. Income tax is different.")
    assert await cite_sources(ANSWER, SNIPPETS, changed, FAIL) == ANSWER
    assert await cite_sources(ANSWER, SNIPPETS, AsyncMock(return_value=FAIL), FAIL) == ANSWER
    cited = ANSWER + " [REF-1]"
    never = AsyncMock()
    assert await cite_sources(cited, SNIPPETS, never, FAIL) == cited
    never.assert_not_awaited()

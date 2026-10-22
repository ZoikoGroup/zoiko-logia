"""An honest "I can't do this, because…" reply is shown, not escalated."""
from app.domains.massarius.answer_validator import validate_answer
from app.orchestration.limitation_reply import is_limitation_reply
from app.orchestration.schemas import SourceBundle

BALANCE_SHEET = (
    "I’m unable to prepare a balance sheet from the uploaded ledger because the data does not include any "
    "classification of the nominal codes into asset, liability, or equity accounts, nor does it indicate debit "
    "versus credit entries. Without that information, I cannot determine the appropriate line‑item totals or "
    "verify that assets equal liabilities + equity."
)
TEN_YEARS = (
    "I’m unable to retrieve a ten‑year historical price series for Apple (AAPL) and Microsoft (MSFT) with the "
    "available data tools, so a line chart comparing their stock prices over the last ten years cannot be "
    "produced at this time."
)


def test_the_two_real_escalated_replies_are_limitation_replies():
    assert is_limitation_reply(BALANCE_SHEET)
    assert is_limitation_reply(TEN_YEARS)


def test_replies_with_figures_claims_or_citations_are_not():
    assert not is_limitation_reply("I’m unable to find the 2025 figure, but revenue was 4,200 in 2024.")
    assert not is_limitation_reply("I cannot confirm this [REF-1].")
    assert not is_limitation_reply("IFRS 15 requires revenue to be recognised when control transfers to the customer.")
    assert not is_limitation_reply("I’m unable to " + "explain this in detail " * 60)
    assert not is_limitation_reply("")


def _grounding_failed(result) -> bool:
    return any("Grounding check failed" in f for f in (result.failures if result else []))


def test_the_grounding_check_lets_a_limitation_reply_through():
    bundle = SourceBundle.model_construct(eligible_source_count=0, eligible_sources=[], excluded_sources=[])
    released = validate_answer(BALANCE_SHEET, bundle, ungrounded_answer_allowed=is_limitation_reply(BALANCE_SHEET))
    assert not _grounding_failed(released)
    claim = "IFRS 15 requires revenue to be recognised when control transfers to the customer, in five steps."
    assert _grounding_failed(validate_answer(claim, bundle, ungrounded_answer_allowed=is_limitation_reply(claim)))

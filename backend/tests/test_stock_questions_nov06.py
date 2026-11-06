"""Stock questions from the 6 Nov 2026 manual test: price questions worded
"closing price", "share prices" or "the price of <ticker>" fetched no data and
were refused as off-topic; calculations with every figure given were asked
which company; a share-price answer with no source was pointed to the IFRS
Foundation and the tax authority."""
import pytest

from app.domains.market_data.registry import INTENT_QUOTE, detect_intent
from app.orchestration.clarification_requirements import clarification
from app.orchestration.source_guarantee import official_sources_note
from app.orchestration.task_contract import build_task_contract


@pytest.mark.parametrize("question", [
    "What was Microsoft's closing price on the last trading day?",
    "Compare the current share prices of Tesla, Nvidia and Amazon.",
    "What is the price of XYZQ123?",
    "What is Apple's current share price?",
    "What's the price of Shell?",
])
def test_price_questions_fetch_market_data(question):
    assert detect_intent(question) == INTENT_QUOTE


@pytest.mark.parametrize("question", [
    "What is the transfer price of goods between subsidiaries?",
    "What is the price of a bond with a 5% coupon?",
    "What is the price elasticity of demand?",
    "Explain the closing process for month end",
    "How is revenue recognised under IFRS 15?",
])
def test_other_price_wording_is_not_a_market_lookup(question):
    assert detect_intent(question) is None


@pytest.mark.parametrize("question", [
    "A share costs $150 and earnings per share are $6. What is the P/E ratio?",
    "A share costs $60 and pays an annual dividend of $3. What is the dividend yield?",
    "A company has 2 billion shares at $50 each. What is its market capitalisation?",
])
def test_a_market_ratio_with_its_figures_is_calculated_not_asked_about(question):
    assert clarification(build_task_contract(question), task_query=question) is None


@pytest.mark.parametrize("question", ["What's the share price?", "What is the dividend yield?"])
def test_a_market_figure_with_no_company_or_figures_still_asks(question):
    assert "company" in (clarification(build_task_contract(question), task_query=question) or "")


@pytest.mark.parametrize("question", [
    "What is the share price of Reliance Industries on the NSE?",
    "What was Apple's exact share price at 10:32 am yesterday? Just give me a number.",
    "What is the price of XYZQ123?",
])
def test_an_unsourced_share_price_answer_points_to_the_exchange(question):
    note = official_sources_note(question)
    assert "stock exchange" in note and "IFRS Foundation" not in note and "tax authority" not in note


# ── Through the answer path (agent mode, market data faked: no network) ───────
from types import SimpleNamespace  # noqa: E402

from app.domains.model_gateway.agent import AgentOutcome  # noqa: E402
from app.orchestration import service  # noqa: E402
from app.orchestration.accounting_concepts import correct_standard_references  # noqa: E402
from app.orchestration.live_data import LiveDataResult  # noqa: E402
from app.orchestration.websearch import WebSource  # noqa: E402
from tests.test_answer_status_pipeline import pipeline  # noqa: E402,F401  (fixture)

QUOTES = {"TSLA": "Tesla (TSLA): 343.69", "NVDA": "Nvidia (NVDA): 181.6", "AMZN": "Amazon (AMZN): 260.21"}


def _quotes(monkeypatch, *symbols):
    fetched = []

    async def fake_fetch(query):
        fetched.append(query)
        sources = [WebSource(title=f"finnhub — {s} quote (delayed)", url=f"https://finnhub.io/{s}", snippet=QUOTES[s],
                             provider="finnhub") for s in symbols]
        return LiveDataResult(sources=sources, deterministic_answer="\n\n".join(QUOTES[s] for s in symbols) or None)
    monkeypatch.setattr(service, "fetch_live_data", fake_fetch)
    return fetched


async def test_a_share_price_comparison_is_fetched_up_front_and_shows_every_company(pipeline, monkeypatch):
    fetched = _quotes(monkeypatch, "TSLA", "NVDA", "AMZN")
    response, _ = await pipeline.ask("Compare the current share prices of Tesla, Nvidia and Amazon.")
    assert fetched, "fetched before the agent, which may run out of time"
    assert all(quote in response.answer.text for quote in QUOTES.values())
    pipeline.agent.assert_not_awaited()


async def test_a_forecast_about_a_share_price_is_reasoned_with_the_quote_as_evidence(pipeline, monkeypatch):
    _quotes(monkeypatch, "TSLA")
    pipeline.answers(AgentOutcome(text="Future prices cannot be predicted; the latest quote is 343.69 [REF-1]."))
    response, _ = await pipeline.ask("Will Tesla's share price go up next week?")
    pipeline.agent.assert_awaited()
    assert "cannot be predicted" in response.answer.text


async def test_an_unknown_ticker_is_not_found_rather_than_off_topic(pipeline, monkeypatch):
    _quotes(monkeypatch)
    # The model refuses on whichever path composes the answer.
    pipeline.answers(AgentOutcome(text=service._MODEL_DOMAIN_REFUSAL_TEXT))
    pipeline.rewrite.return_value = service._MODEL_DOMAIN_REFUSAL_TEXT

    async def refuse(*args, **kwargs):
        return SimpleNamespace(id="prompt-test", name="test"), service._MODEL_DOMAIN_REFUSAL_TEXT
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt", refuse)
    response, _ = await pipeline.ask("What is the price of XYZQ123?")
    assert "couldn't find a listed security matching “XYZQ123”" in response.answer.text
    assert service._MODEL_DOMAIN_REFUSAL not in response.answer.text


def test_ifrs_18_cited_for_revenue_is_corrected_to_ifrs_15():
    text, notes = correct_standard_references("S3.1 – IFRS 18 (Revenue from Contracts with Customers)")
    assert "IFRS 15 (Revenue from Contracts with Customers)" in text and notes
    kept = "IFRS 18 sets out general presentation and disclosure requirements."
    assert correct_standard_references(kept) == (kept, [])

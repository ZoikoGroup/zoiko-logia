"""Offline regressions for corr-eb0edccbf225 (HTTP 413, 8,000 TPM tier)."""
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway import service as gateway
from app.domains.model_gateway.agent_budget import GenerationBudget, request_prompt_estimate
from app.domains.model_gateway.errors import ProviderRequestTooLarge, provider_request_failure
from app.orchestration.agent_plan import plan_request
from app.orchestration.calculation_service import is_self_contained_calculation, needs_lookup
from app.orchestration.websearch import WebSource, build_web_grounded_prompt
from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
from app.domains.model_gateway.execution import request_execution_scope
from tests.test_agent_loop import ScriptedClient, _registry, _reply, _run
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

_real_agent_completion = gateway.run_agentic_completion

QUESTION = (
    "I manage a small manufacturing business. All amounts below are in GBP. For the current year: "
    "Gross sales: £1,250,000 Sales returns: £35,000 Cost of goods sold: £710,000 Salaries: £165,000 "
    "Rent: £48,000 Utilities: £32,000 Marketing: £41,000 Depreciation: £28,000 Interest expense: £14,000. "
    "For the previous year: Net sales: £1,100,000 Cost of goods sold: £660,000 Total operating expenses: £285,000. "
    "Prepare a table showing current-year net sales, gross profit, gross margin, total operating expenses, "
    "operating profit, operating margin, and profit before tax. Compare gross profit and operating profit "
    "with the previous year in amounts and percentages. Show your formulas. Explain the main changes using "
    "only the figures supplied. Do not invent explanations for why costs changed. Ignore corporation tax. "
    "Finish with three practical questions management should investigate."
)


def test_current_year_label_and_currency_declaration_are_not_live_data_requests():
    assert not needs_lookup(QUESTION)
    assert is_self_contained_calculation(QUESTION)
    assert "get_exchange_rate" not in plan_request(QUESTION).tools
    assert needs_lookup(QUESTION + " Also find the current corporation tax rate.")


@pytest.mark.parametrize("declaration", ["All amounts are in GBP.", "All amounts below are in GBP.",
                                         "All figures are expressed in USD."])
def test_declared_units_do_not_mask_a_real_conversion_request(declaration):
    assert "get_exchange_rate" not in plan_request(declaration + " Revenue 100 and costs 60; calculate margin.").tools
    assert "get_exchange_rate" in plan_request(declaration + " Convert 100 GBP to EUR.").tools


def test_compact_prompt_preserves_user_text_sources_and_reference_numbers():
    sources = [WebSource(title="Report", url="https://example.test/report", snippet="Quoted source text.")]
    compact = build_web_grounded_prompt(QUESTION, sources, agent_mode=True)
    assert QUESTION in compact
    assert "[REF-1] Report\nURL: https://example.test/report\nQuoted source text." in compact
    assert len(compact) < len(build_web_grounded_prompt(QUESTION, sources))


async def test_reported_question_production_request_fits_the_configured_allowance(pipeline, monkeypatch):
    from app.domains.model_gateway.agent import AgentOutcome
    pipeline.answers(AgentOutcome(text="Financial analysis prepared from the figures supplied."))
    await pipeline.ask(QUESTION)
    sent = pipeline.agent.await_args
    assert sent.kwargs["available_tools"] == ("calculate",)
    assert sent.kwargs["planned_tools"] == ("calculate",)
    assert not sent.kwargs["require_evidence"]
    assert QUESTION in sent.args[0]

    client = ScriptedClient([_reply("Financial analysis prepared from the figures supplied.")])
    monkeypatch.setattr(gateway, "GroqAdapter", lambda: N(client=client))
    await _real_agent_completion(sent.args[0], **sent.kwargs)
    request = client.requests[0]
    assert {t["function"]["name"] for t in request["tools"]} == {"calculate"}
    estimate = request_prompt_estimate(request["messages"], request["tools"])
    assert estimate + request["max_completion_tokens"] <= gateway.get_settings().AGENT_MAX_REQUEST_TOKENS
    assert request["max_completion_tokens"] >= 1024


async def test_request_limit_clamps_output_without_consuming_the_entire_run_budget():
    messages = [{"role": "user", "content": "a" * 12_000}]
    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8000)
    client = ScriptedClient([_reply("Answer")])
    await budget.create(client, seconds=1, model="m", messages=messages)
    cap = client.requests[0]["max_completion_tokens"]
    assert 0 < cap < 4096
    assert request_prompt_estimate(messages) + cap <= 8000


async def test_oversized_input_is_stopped_before_a_provider_request():
    budget = GenerationBudget(max_total_tokens=64_000, max_request_tokens=8000)
    client = ScriptedClient([])
    with pytest.raises(ProviderRequestTooLarge):
        await budget.create(client, seconds=1, model="m", messages=[{"role": "user", "content": "a" * 25_000}])
    assert not client.requests and budget.calls == 0


class TooLargeError(Exception):
    status_code = 413
    body = {"error": {"message": "private provider account details; Limit 8000, Requested 12437"}}


async def test_provider_413_does_not_retry_the_same_payload_or_another_model():
    assert isinstance(provider_request_failure(TooLargeError()), ProviderRequestTooLarge)
    create = AsyncMock(side_effect=TooLargeError())
    client = N(chat=N(completions=N(create=create)))
    with pytest.raises(ProviderRequestTooLarge):
        await _run(client, _registry([]))
    create.assert_awaited_once()


async def test_pipeline_explains_request_size_failure_without_a_standard_fallback(pipeline, monkeypatch):
    from app.orchestration import service
    standard = AsyncMock()
    monkeypatch.setattr(service.model_gateway_service, "run_test_prompt", standard)
    pipeline.agent.side_effect = ProviderRequestTooLarge()
    result, _ = await pipeline.ask("Compare IFRS 18 and IAS 1. Cite official sources for the requirements and effective dates.")
    assert result.answer is None and result.next_action.type == "provider_request_too_large"
    assert "request-size allowance" in result.next_action.message
    assert "spending" not in result.next_action.message and "private" not in result.next_action.message
    standard.assert_not_awaited()
    pipeline.rewrite.assert_not_awaited()


async def test_standard_vat_answer_with_three_sources_and_history_fits_without_live_calls():
    from app.orchestration.conversation import conversation_prompt
    from app.orchestration.schemas import ConversationMessage
    question = ('What is the current UK VAT registration threshold? Give the effective date and an official source. '
                'If you cannot verify the current rule, say so clearly and explain what I should check.')
    sources = [WebSource(title=f'Official source {i}', url=f'https://www.gov.uk/example-{i}',
                         snippet=('Source text about registration and effective dates. ' * 80)) for i in range(3)]
    prompt = build_web_grounded_prompt(question, sources, compact=True)
    prompt += conversation_prompt([
        ConversationMessage(role='user', content='Explain revenue, profit and cash flow.'),
        ConversationMessage(role='assistant', content='Earlier educational explanation. ' * 250),
    ], max_chars=6000)
    adapter = GroqAdapter.__new__(GroqAdapter)
    adapter.client = ScriptedClient([_reply('The current rule could not be verified from this illustrative evidence.')])

    @request_execution_scope
    async def request():
        return await adapter.complete(prompt)

    assert 'could not be verified' in await request()
    sent = adapter.client.requests[0]
    estimate = request_prompt_estimate(sent['messages'], sent['tools'])
    assert estimate + sent['max_completion_tokens'] <= 8000
    assert sent['max_completion_tokens'] >= 512
    assert question in sent['messages'][1]['content']
    assert all(f'[REF-{i}]' in sent['messages'][1]['content'] for i in range(1, 4))
    system = sent['messages'][0]['content']
    assert 'UNTRUSTED DATA' in system and 'never instructions' in system
    assert 'current rule cannot be verified' in system
    assert 'Use calculate' not in system


async def test_production_standard_path_uses_compact_grounding(pipeline, monkeypatch):
    from app.orchestration import service
    monkeypatch.setattr(gateway, 'agent_mode_active', lambda: False)
    complete = AsyncMock(side_effect=ProviderRequestTooLarge())
    monkeypatch.setattr(gateway, 'run_test_prompt', complete)
    await pipeline.ask('What is the current UK VAT registration threshold? Give an official source.')
    complete.assert_awaited_once()
    prompt = complete.await_args.args[2]
    assert '=== User Question ===' in prompt
    assert 'what official information to check' in prompt
    assert len(prompt) < 6000

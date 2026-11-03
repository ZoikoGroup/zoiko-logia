"""E3: the model-first classifier's live shadow. Off by default; when on, a
background task classifies and logs beside the contract, and the answer is
unaffected. The model is stubbed: no network.
"""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import classifier_shadow, model_part_classifier
from app.orchestration.model_part_classifier import ModelPart
from app.orchestration.task_contract import build_task_contract
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


def _model(*parts):
    async def classify_request(request, texts, timeout=None, mode="text", countries=True):
        assert len(parts) == len(texts)
        return list(parts), SimpleNamespace(total_tokens=900)
    return classify_request


def _part(index, fact, countries, counterparties=()):
    return ModelPart(index=index, needs_official=fact in ("rate", "threshold", "deadline", "rule"), fact_type=fact,
                     tax_countries=list(countries), counterparty_countries=list(counterparties), period_kind="unspecified",
                     confidence="high")


def test_it_is_off_by_default(monkeypatch):
    monkeypatch.setattr(model_part_classifier, "classify_request", AsyncMock(side_effect=AssertionError("no call when off")))
    assert classifier_shadow.start(build_task_contract("What is the UK VAT rate?"), "What is the UK VAT rate?", "q") is None


async def test_the_design_is_applied(monkeypatch):
    query = "I'm a UK consultant invoicing a German business client. Do I charge UK VAT?"
    monkeypatch.setattr(model_part_classifier, "classify_request", _model(_part(1, "rule", ["UK", "GERMANY"], ["GERMANY"])))
    record = await classifier_shadow.classify(build_task_contract(query), query)
    part = record["parts"][0]
    assert part["source"] == "model" and part["tax_countries"] == ["UK"] and "GERMANY" in part["counterparties"]
    assert part["period"] == "implied_current"
    assert "gov.uk" in part["domains"] and not any("bundesfinanz" in d for d in part["domains"])


async def test_a_calculation_on_the_users_figures_is_decided_by_the_guard(monkeypatch):
    query = "Calculate the VAT payable: UK company, sales £100,000, purchases £50,000, VAT 20%."
    monkeypatch.setattr(model_part_classifier, "classify_request", _model(_part(1, "rate", ["UK"])))
    part = (await classifier_shadow.classify(build_task_contract(query), query))["parts"][0]
    assert part["source"] == "guard:user_figures" and not part["needs_official"] and part["domains"] == []


async def test_the_rule_table_answers_when_the_model_fails(monkeypatch):
    query = "What is the current UK VAT registration threshold?"
    monkeypatch.setattr(model_part_classifier, "classify_request", AsyncMock(side_effect=TimeoutError()))
    record = await classifier_shadow.classify(build_task_contract(query), query)
    assert record["model_error"] == "TimeoutError" and record["parts"][0]["source"] == "fallback"
    assert record["parts"][0]["fact_type"] == "threshold"


@pytest.mark.parametrize("text, period", [
    ("Which source should be used to verify current GST rates in Australia?", "current"),
    ("What rate of UK VAT used to be charged on fuel?", "historical"),
    ("The UK rate used to apply to all supplies; what is it?", "historical"),
    ("Which HMRC guidance can be used to support a VAT claim?", "implied_current"),
])
def test_used_to_is_historical_only_in_its_past_sense(text, period):
    assert classifier_shadow._final(text, text, _part(1, "rule", ["UK"]))["period"] == period


def _replies(*outcomes):
    """A stub that answers each call in turn, recording the mode asked for."""
    modes = []

    async def classify_request(request, texts, timeout=None, mode="text", countries=True):
        modes.append(mode)
        outcome = outcomes[len(modes) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return [outcome], SimpleNamespace(total_tokens=900)
    return classify_request, modes


async def test_a_rejected_plain_text_reply_is_retried_once_with_low_reasoning(monkeypatch):
    query = "What is the current UK VAT registration threshold?"
    stub, modes = _replies(ValueError("parts missing or out of order"), _part(1, "threshold", ["UK"]))
    monkeypatch.setattr(model_part_classifier, "classify_request", stub)
    record = await classifier_shadow.classify(build_task_contract(query), query)
    assert modes == ["text", "low"] and record["retried"] and record["parts"][0]["source"] == "model"


async def test_the_rule_table_answers_when_the_retry_is_rejected_too(monkeypatch):
    query = "What is the current UK VAT registration threshold?"
    stub, modes = _replies(ValueError("bad"), ValueError("bad again"))
    monkeypatch.setattr(model_part_classifier, "classify_request", stub)
    record = await classifier_shadow.classify(build_task_contract(query), query)
    assert modes == ["text", "low"] and record["parts"][0]["source"] == "fallback"


async def test_a_provider_failure_is_not_retried(monkeypatch):
    query = "What is the current UK VAT registration threshold?"
    stub, modes = _replies(TimeoutError())
    monkeypatch.setattr(model_part_classifier, "classify_request", stub)
    record = await classifier_shadow.classify(build_task_contract(query), query)
    assert modes == ["text"] and record["parts"][0]["source"] == "fallback" and not record["retried"]


@pytest.mark.parametrize("text, period", [
    ("Jersey's GST used to be 3%. What is it now?", "current"),
    ("The UK rate used to be 17.5%. What applies currently?", "current"),
    ("What rate of UK VAT used to be charged on fuel?", "historical"),
    ("The rate used to be 3% in 2008. What is it now?", "year"),
])
def test_now_or_currently_outranks_used_to(text, period):
    assert classifier_shadow._final(text, text, _part(1, "rate", ["UK"]))["period"] == period


def test_when_the_model_swaps_the_roles_the_users_own_country_answers():
    text = "A UK company sells services to a French business customer. Which country's VAT rules apply?"
    part = classifier_shadow._final(text, text, _part(1, "rule", ["FRANCE"], ["UK"]))
    assert part["tax_countries"] == ["UK"] and not any("impots" in d for d in part["domains"])


def test_a_request_for_an_official_source_needs_official_sources_for_every_country_named():
    text = "Which tax authority should a Singapore supplier check for GST on sales to an Indian client?"
    part = classifier_shadow._final(text, text, _part(1, "explanation", [], ["INDIA"]))
    assert part["needs_official"] and part["fact_type"] == "rule" and part["source"].endswith("rule:official_source")
    assert set(part["tax_countries"]) == {"SINGAPORE", "INDIA"}


def test_what_applies_to_a_named_countrys_tax_is_a_rule_but_a_general_concept_is_not():
    applies = "What tax considerations apply when a UK company pays a dividend?"
    concept = "Explain how deferred tax works"
    named = "Explain how the UK Annual Investment Allowance works"
    assert classifier_shadow._final(applies, applies, _part(1, "explanation", []))["fact_type"] == "rule"
    assert classifier_shadow._final(named, named, _part(1, "explanation", []))["tax_countries"] == ["UK"]
    assert not classifier_shadow._final(concept, concept, _part(1, "explanation", []))["needs_official"]


def test_the_fixed_rules_leave_the_calculation_guard_alone():
    text = "Calculate the VAT payable: UK company, sales £100,000, purchases £50,000, VAT 20%. Which tax authority applies?"
    assert classifier_shadow._final(text, text, _part(1, "rate", ["UK"]))["source"] == "guard:user_figures"


def test_the_model_is_given_the_labelling_rules():
    system, _ = model_part_classifier.prompt("q", ["q"])
    for rule in ("which official source", "considerations, obligations", "Explain how", "\"Used to\" means historical only",
                 "forms, returns, slips", "which documents, records, evidence"):
        assert rule in system
    assert "NORWAY" not in system and "MALAYSIA" in system


async def test_the_answer_is_the_same_with_the_shadow_on(pipeline, monkeypatch, caplog):
    query = "What is the current UK VAT registration threshold?"
    pipeline.answers(AgentOutcome(text="The threshold is set by HMRC."))
    off, _ = await pipeline.ask(query)
    monkeypatch.setenv("KRITON_CLASSIFIER_SHADOW", "true")
    monkeypatch.setattr(model_part_classifier, "classify_request", _model(_part(1, "threshold", ["UK"])))
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    pipeline.answers(AgentOutcome(text="The threshold is set by HMRC."))
    on, _ = await pipeline.ask(query)
    await asyncio.gather(*list(classifier_shadow._tasks))
    assert (on.outcome, on.answer.text if on.answer else None) == (off.outcome, off.answer.text if off.answer else None)
    assert any("stage=classified" in r.getMessage() for r in caplog.records)


async def test_a_failing_shadow_never_reaches_the_request(pipeline, monkeypatch):
    monkeypatch.setenv("KRITON_CLASSIFIER_SHADOW", "true")
    monkeypatch.setattr(classifier_shadow, "classify", AsyncMock(side_effect=RuntimeError("boom")))
    pipeline.answers(AgentOutcome(text="Answer."))
    response, _ = await pipeline.ask("What is the current UK VAT registration threshold?")
    await asyncio.gather(*list(classifier_shadow._tasks), return_exceptions=True)
    assert response.outcome


def test_a_registry_term_places_an_official_part_with_no_country():
    text = "Explain the purpose of the taxable payments annual report."
    part = classifier_shadow._final(text, text, _part(1, "explanation", []))
    assert part["needs_official"] and part["tax_countries"] == ["AUSTRALIA"] and "ato.gov.au" in part["domains"]
    assert part["country_terms"][0]["country"] == "AUSTRALIA"


def test_a_registry_term_does_not_override_the_models_countries():
    text = "What is the CT600 deadline for a company?"
    assert classifier_shadow._final(text, text, _part(1, "deadline", ["UK"]))["tax_countries"] == ["UK"]


@pytest.mark.parametrize("text, model_countries, on, expected", [
    ("When must an employer file Form IR21?", ["UK"], True, ["SINGAPORE"]),           # registry decides
    ("When must an employer file Form IR21?", ["UK"], False, ["UK"]),                 # switch off: baseline
    ("When must a UK employer file Form IR21?", ["UK"], True, ["UK"]),                # an explicit name wins
    ("A UK company receives a W-8BEN request. What UK tax points apply?", ["UK"], True, ["UK"]),
    ("How does PAYE work for new staff?", ["UK"], True, ["UK"]),                      # ambiguous term: no override
    ("Explain the difference between a T4 slip and Form 1040.", ["CANADA"], True, ["CANADA"]),  # two countries: no override
    ("When is the IR10 due?", ["UK"], True, ["UK"]),                                  # unmapped term: no override
])
def test_the_country_override_is_narrow(monkeypatch, text, model_countries, on, expected):
    monkeypatch.setenv("KRITON_COUNTRY_OVERRIDE", "1" if on else "0")
    assert classifier_shadow._final(text, text, _part(1, "deadline", model_countries))["tax_countries"] == expected

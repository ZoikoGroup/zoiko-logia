"""The user's selected jurisdiction reaches the country resolver (31 Oct 2026,
after the set-13 classifier runs showed it was not passed through classify()).
Resolver and classifier shadow only; both switches off by default. No model,
no network."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import classifier_shadow, model_part_classifier
from app.orchestration.country_resolution import resolve, selected_key
from app.orchestration.model_part_classifier import ModelPart
from app.orchestration.task_contract import build_task_contract
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


@pytest.mark.parametrize("value, key", [
    ("UK", "UK"), ("US", "US"), ("US-CA", "US"), ("India", "INDIA"), ("UAE", "UAE"), ("EU", "EU"),
    ("", None), (None, None), ("Any", None), ("IFRS", None), ("GLOBAL", None),   # not countries
])
def test_selector_values_become_country_keys(value, key):
    assert selected_key(value) == key


def test_the_selection_decides_only_without_text_evidence():
    assert resolve("What is the late filing penalty for annual returns?", selected="India").countries == ["INDIA"]
    assert resolve("What is the late filing penalty in Malaysia?", selected="India").countries == ["MALAYSIA"]
    assert resolve("What is the late filing penalty?", selected="IFRS").status == "unknown"


def _part(fact):
    return ModelPart(index=1, needs_official=True, fact_type=fact, tax_countries=[], counterparty_countries=[],
                     period_kind="unspecified", confidence="high")


@pytest.mark.parametrize("question, selected, expected", [
    ("What is the corporate tax return deadline?", "UAE", ["UAE"]),              # selection only
    ("What are the employee EPF rates?", "US", []),                              # selection outside the candidates: not used
    ("What GST rate applies to imported digital services?", "India", ["INDIA"]),  # ambiguous term + matching selection
    ("What is the UK corporation tax deadline?", "UAE", ["UK"]),                 # an explicit name wins
    ("What is the corporate tax return deadline?", "IFRS", []),                  # not a country: ignored
])
def test_the_classifier_shadow_passes_the_selection_to_the_resolver(monkeypatch, question, selected, expected):
    monkeypatch.setenv("KRITON_COUNTRY_RESOLUTION", "1")
    part = classifier_shadow._final(question, question, _part("deadline"), selected)
    assert part["tax_countries"] == expected


async def test_classify_carries_the_selection(monkeypatch):
    monkeypatch.setenv("KRITON_COUNTRY_RESOLUTION", "1")

    async def classify_request(request, texts, timeout=None, mode="text", countries=True):
        return [_part("deadline")], SimpleNamespace(total_tokens=10)
    monkeypatch.setattr(model_part_classifier, "classify_request", classify_request)
    query = "When is the corporate tax return due?"
    record = await classifier_shadow.classify(build_task_contract(query), query, "UAE")
    assert record["parts"][0]["tax_countries"] == ["UAE"]
    assert record["parts"][0]["country_resolution"]["evidence"][-1] == {"kind": "E5", "value": "UAE"}


def test_with_the_switch_off_the_selection_changes_nothing():
    query = "When is the corporate tax return due?"
    assert classifier_shadow._final(query, query, _part("deadline"), "UAE")["country_resolution"] is None


def test_the_task_contract_records_the_selection(monkeypatch):
    query = "When is the corporate tax return due?"
    monkeypatch.setenv("KRITON_COUNTRY_RESOLUTION", "1")
    with_selection = build_task_contract(query, selected_jurisdiction="UAE").retrieval[0]
    without = build_task_contract(query).retrieval[0]
    assert with_selection.country_resolution["countries"] == ["UAE"] and without.country_resolution["status"] == "unknown"
    assert with_selection.jurisdictions == without.jurisdictions         # recorded only: routing unchanged


async def test_the_request_jurisdiction_reaches_both_shadow_calls(pipeline, monkeypatch):  # noqa: F811
    from app.orchestration import service, task_contract
    from app.orchestration.schemas import AskKritonRequest
    seen = {}
    real_build = task_contract.shadow_build
    def shadow_build(query, **kwargs):
        seen["contract"] = kwargs.get("selected_jurisdiction")
        return real_build(query, **kwargs)
    monkeypatch.setattr(task_contract, "shadow_build", shadow_build)
    monkeypatch.setattr(classifier_shadow, "start", lambda contract, request, query_id, selected=None: seen.setdefault("shadow", selected))
    pipeline.answers(AgentOutcome(text="The rate is set by the CBIC."))
    await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                             request=AskKritonRequest(query="What is the GST rate on restaurant services?", jurisdiction="India"))
    # the service normalises the selector value ("India" -> "INDIA") before these calls
    assert selected_key(seen["contract"]) == selected_key(seen["shadow"]) == "INDIA"

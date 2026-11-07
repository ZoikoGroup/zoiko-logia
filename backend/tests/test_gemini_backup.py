"""Gemini is a backup to Groq, never the answering provider by default
(Operations Closure, 4 Nov 2026), and every answer receipt names the provider
that answered and those that failed before it."""
import asyncio
from types import SimpleNamespace

import pytest

from app.domains.model_gateway import service
from app.orchestration import workflow_state
from app.orchestration.router import answer_receipt


def _fake(name: str, reply: str):
    async def complete(self, prompt, model=None):
        self.calls.append(model)
        return reply
    return type(name, (), {"__init__": lambda self: setattr(self, "calls", []), "complete": complete})


@pytest.fixture
def providers(monkeypatch):
    def configure(*, primary="groq", agent_mode=True, groq="groq answer", gemini="gemini answer"):
        monkeypatch.setenv("GROQ_API_KEY", "q")
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "groq,gemini")
        monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(
            MODEL_GATEWAY_PRIMARY_PROVIDER=primary, KRITON_AGENT_MODE=agent_mode))
        monkeypatch.setattr(service, "GroqAdapter", _fake("GroqAdapter", groq))
        monkeypatch.setattr(service, "GeminiAdapter", _fake("GeminiAdapter", gemini))
    return configure


def _answer(prompt="q", model=None):
    run = workflow_state.WorkflowRun()
    token = workflow_state.current_run.set(run)
    try:
        output = asyncio.run(service._complete_with_fallback(prompt, model))
    finally:
        workflow_state.current_run.reset(token)
    return output, run


def test_a_gemini_key_does_not_make_gemini_answer_or_switch_agent_mode_off(providers):
    providers()
    assert service.answering_provider() == "groq"
    assert service.agent_mode_active()
    assert service.agent_mode_status()["reasons"] == []


def test_groq_answers_and_the_receipt_names_it(providers):
    providers()
    output, run = _answer()
    assert output == "groq answer"
    assert run.model_providers == ["groq"] and run.model_provider_failures == []


def test_gemini_answers_only_when_groq_fails_and_the_receipt_shows_the_failover(providers):
    providers(groq="[Error: provider unavailable]")
    output, run = _answer(model="llama-fast")
    assert output == "gemini answer"
    assert run.model_providers == ["gemini"]
    assert run.model_provider_failures == ["groq"]
    receipt = answer_receipt(SimpleNamespace(query_id="q", answer=None, safety=None, visualization=None,
                                             calculation=None), run)
    assert receipt["model_providers"] == ["gemini"] and receipt["model_provider_failures"] == ["groq"]


def test_gemini_never_receives_a_groq_model_id(providers, monkeypatch):
    providers(groq="[Error: down]")
    seen = []
    original = service._adapter

    def tracking(name):
        adapter = original(name)
        seen.append((name, adapter))
        return adapter
    monkeypatch.setattr(service, "_adapter", tracking)
    _answer(model="llama-fast")
    gemini_calls = [a.calls for name, a in seen if name == "gemini" and a.calls]
    assert gemini_calls == [[None]]


def test_choosing_gemini_first_is_explicit_and_turns_the_tool_loop_off(providers):
    providers(primary="gemini")
    assert service.answering_provider() == "gemini"
    assert not service.agent_mode_active()
    assert "gemini answers first" in service.agent_mode_status()["reasons"][0]


def test_no_gemini_key_means_no_gemini_fallback(providers, monkeypatch):
    providers(groq="[Error: down]")
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(RuntimeError):
        _answer()

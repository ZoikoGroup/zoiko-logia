"""Unit tests for the schema-constrained LLM fallback tier in
app/orchestration/presentation_llm_classifier.py. These test classify()
directly against a fake OpenAI client so no network/API key is needed.
"""
import json

import pytest

from app.orchestration import presentation_llm_classifier as classifier


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, respond):
        self._respond = respond

    def create(self, **kwargs):
        return self._respond(kwargs)


class _FakeChat:
    def __init__(self, respond):
        self.completions = _FakeCompletions(respond)


class _FakeOpenAI:
    """Stands in for openai.OpenAI(...) — captures init kwargs, delegates
    chat.completions.create() to whatever the test wants to return/raise."""

    last_init_kwargs: dict = {}

    def __init__(self, **kwargs):
        _FakeOpenAI.last_init_kwargs = kwargs
        self.chat = _FakeChat(self._respond)

    def _respond(self, kwargs):
        return self.__class__._respond_fn(kwargs)


def _install_fake_openai(monkeypatch, respond_fn):
    _FakeOpenAI._respond_fn = staticmethod(respond_fn)
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)


@pytest.fixture(autouse=True)
def _enabled_with_key(monkeypatch):
    monkeypatch.setenv("PRESENTATION_LLM_CLASSIFIER_MODE", "fallback")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")


def _payload_response(payload: dict) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload))


def test_valid_response_is_parsed_into_guide_classification(monkeypatch):
    _install_fake_openai(monkeypatch, lambda kwargs: _payload_response({
        "guide_type": "process",
        "confidence": 0.92,
        "reasoning_summary": "Sequential onboarding steps with no branching.",
        "requires_clarification": False,
    }))
    result = classifier.classify("Show me the onboarding steps", ["Step one", "Step two"])
    assert result is not None
    assert result.guide_type == "process"
    assert result.confidence == 0.92
    assert result.requires_clarification is False
    assert result.model


def test_unsupported_guide_type_is_rejected(monkeypatch):
    # Simulates a provider response that slipped an out-of-domain value past
    # the strict JSON-schema enum (e.g. a future model regression) — classify()
    # must still refuse to trust it rather than passing "gauge" upstream as a
    # PresentationGuide.type, which would fail Pydantic validation deep inside
    # the response path instead of failing safely here.
    _install_fake_openai(monkeypatch, lambda kwargs: _payload_response({
        "guide_type": "gauge",
        "confidence": 0.95,
        "reasoning_summary": "Looks like a gauge.",
        "requires_clarification": False,
    }))
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None


def test_malformed_json_falls_back_safely(monkeypatch):
    _install_fake_openai(monkeypatch, lambda kwargs: _FakeResponse("not valid json {"))
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None


def test_out_of_range_confidence_falls_back_safely(monkeypatch):
    _install_fake_openai(monkeypatch, lambda kwargs: _payload_response({
        "guide_type": "process",
        "confidence": 1.7,
        "reasoning_summary": "Overconfident.",
        "requires_clarification": False,
    }))
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None


def test_provider_timeout_returns_none_without_raising(monkeypatch):
    def _raise_timeout(kwargs):
        raise TimeoutError("provider timed out")
    _install_fake_openai(monkeypatch, _raise_timeout)
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None


def test_provider_error_returns_none_without_raising(monkeypatch):
    def _raise_error(kwargs):
        raise RuntimeError("connection reset")
    _install_fake_openai(monkeypatch, _raise_error)
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None


def test_reasoning_summary_is_stripped_of_markup_and_code_fences(monkeypatch):
    _install_fake_openai(monkeypatch, lambda kwargs: _payload_response({
        "guide_type": "process",
        "confidence": 0.8,
        "reasoning_summary": "Looks like a ```process<script>alert(1)</script>``` flow.",
        "requires_clarification": False,
    }))
    result = classifier.classify("Show me something", ["Step one"])
    assert result is not None
    assert "<" not in result.reasoning_summary
    assert ">" not in result.reasoning_summary
    assert "```" not in result.reasoning_summary


def test_classify_returns_none_when_mode_is_off(monkeypatch):
    monkeypatch.setenv("PRESENTATION_LLM_CLASSIFIER_MODE", "off")
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None


def test_classify_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = classifier.classify("Show me something", ["Step one"])
    assert result is None

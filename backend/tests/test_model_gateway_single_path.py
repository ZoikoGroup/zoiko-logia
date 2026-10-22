"""One model-call path (ZL-ENG-AGT-01 §11, implementation rule 10).

Provider SDKs may be imported only by the model gateway; everything else
calls the gateway. The auxiliary gateway refuses unregistered purposes and
unapproved providers, and redacts protected data before sending.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domains.model_gateway import auxiliary as gateway

APP = Path(__file__).resolve().parents[1] / "app"
GATEWAY = APP / "domains" / "model_gateway"
PROVIDER_SDKS = ("groq", "openai", "anthropic", "google.genai", "google.generativeai", "mistralai", "cohere")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            if node.module == "google":
                names.update(f"google.{alias.name}" for alias in node.names)
    return names


def test_no_module_outside_the_gateway_imports_a_provider_sdk():
    offenders = []
    for path in APP.rglob("*.py"):
        if GATEWAY in path.parents:
            continue
        for name in _imports(path):
            if any(name == sdk or name.startswith(sdk + ".") for sdk in PROVIDER_SDKS):
                offenders.append(f"{path.relative_to(APP.parent)} imports {name}")
    assert offenders == [], "Call the model gateway instead:\n" + "\n".join(offenders)


async def test_unregistered_purpose_and_unapproved_provider_are_refused(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    with pytest.raises(gateway.GatewayRefused):
        await gateway.complete_auxiliary(purpose="free_text_chat", model="m", system="s", user="u")
    with pytest.raises(gateway.GatewayRefused):  # Gemini is not approved for claim verification
        await gateway.complete_auxiliary(purpose="claim_verification", provider="gemini", model="m", system="s", user="u")
    monkeypatch.setenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "gemini")
    with pytest.raises(gateway.GatewayRefused):  # deployment no longer approves Groq
        await gateway.complete_auxiliary(purpose="risk_classification", model="m", system="s", user="u")
    assert not gateway.may_use("risk_classification", "groq")


async def test_missing_credentials_are_reported_not_sent(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert not gateway.may_use("risk_classification", "groq")
    with pytest.raises(gateway.GatewayNotConfigured):
        await gateway.complete_auxiliary(purpose="risk_classification", model="m", system="s", user="u")


async def test_protected_data_is_redacted_before_it_is_sent(monkeypatch):
    sent = []

    class _Completions:
        async def create(self, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="LOW"))],
                                   usage=SimpleNamespace(prompt_tokens=5, completion_tokens=1, total_tokens=6))

    monkeypatch.setattr(gateway, "AsyncGroq", lambda api_key, **options: SimpleNamespace(chat=SimpleNamespace(completions=_Completions())))
    monkeypatch.setenv("GROQ_API_KEY", "test")
    result = await gateway.complete_auxiliary(
        purpose="risk_classification", model="m", system="s",
        user="Email jane.doe@example.com about her VAT return",
    )
    assert result.text == "LOW" and result.total_tokens == 6
    assert "jane.doe@example.com" not in sent[0]["messages"][1]["content"]


def test_the_answer_path_uses_only_approved_providers(monkeypatch):
    """§11.5: an unapproved provider is never selected or used as a fallback."""
    from app.domains.model_gateway import service
    from app.domains.model_gateway.providers.google_adapter import GeminiAdapter
    from app.domains.model_gateway.providers.groq_adapter import GroqAdapter
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    monkeypatch.setenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "groq,gemini")
    assert isinstance(service._select_adapter(), GeminiAdapter)
    monkeypatch.setenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "groq")
    assert isinstance(service._select_adapter(), GroqAdapter)
    monkeypatch.setenv("MODEL_GATEWAY_APPROVED_PROVIDERS", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert not isinstance(service._select_adapter(), GroqAdapter)  # Groq configured but not approved

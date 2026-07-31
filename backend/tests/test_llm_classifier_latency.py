import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.domains.risk_safety import llm_classifier


def test_concurrent_semantic_classification_uses_one_provider_request(monkeypatch):
    llm_classifier.clear_cache()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0
    calls_lock = threading.Lock()

    payload = {
        "risk_level": "MEDIUM",
        "confidence": 0.91,
        "intent": "interpret",
        "advice_signal": False,
        "missing_context": [],
        "reason_codes": ["accounting_interpretation"],
        "domain": "accounting",
        "retrieval_query": "ASC 606 contract recognition implications",
        "response_format": "adaptive",
        "requested_depth": "standard",
        "requires_current_sources": False,
    }

    class FakeCompletions:
        def create(self, **kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.10)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    def classify():
        return llm_classifier.classify(
            "Assess unusual contract implications",
            jurisdiction="US",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: classify(), range(2)))

    cached = classify()

    assert calls == 1
    assert all(result is not None for result in results)
    assert cached is not None
    assert cached.intent == "interpret"

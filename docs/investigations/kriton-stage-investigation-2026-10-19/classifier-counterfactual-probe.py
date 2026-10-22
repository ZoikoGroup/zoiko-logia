"""Diagnostic only: restore just the original context classifier, not source files."""
import pytest

@pytest.fixture(autouse=True)
def original_context_classifier(monkeypatch):
    from app.orchestration import service
    def original(query):
        text = query or ''
        if service._SAME_DATA_REFERENCE.search(text) or service._ELLIPTICAL_FOLLOW_UP.search(text):
            return True
        return bool(service._UNDER_SPECIFIED_METRIC_FORMAT.search(text) and not service.countries_in_query(text))
    monkeypatch.setattr(service, '_looks_like_contextual_follow_up', original)

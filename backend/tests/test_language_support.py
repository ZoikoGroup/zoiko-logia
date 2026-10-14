"""Multilingual scope (ZL-ENG-AGT-01 §09, QA demonstration 9): unsupported
languages get an honest scope limit, never a translated or invented answer."""
import pytest

from app.orchestration.language_support import SUPPORT_MATRIX, detect_language, scope_message


@pytest.mark.parametrize("question, expected", [
    ("What is the UK VAT registration threshold?", "en"),
    ("Explain Section 44AB of the Income-tax Act for a business with turnover of ₹1 crore.", "en"),
    ("¿Cuál es el plazo para presentar el impuesto de sociedades en España para mi empresa?", "es"),
    ("Quel est le taux de TVA pour les services de restauration en France ?", "fr"),
    ("Wie hoch ist die Steuer für eine GmbH in Deutschland und was ist der Freibetrag?", "de"),
    ("आयकर अधिनियम की धारा 44AB क्या है?", "hi"),
    ("12,000 / 4", None),
])
def test_detection_is_conservative(question, expected):
    assert detect_language(question) == expected


def test_the_scope_message_is_honest_and_in_both_languages():
    message = scope_message("es")
    assert "inglés" in message and "English only" in message and "not answered" in message


def test_the_matrix_lists_only_english_as_supported():
    assert {row.language for row in SUPPORT_MATRIX} == {"en"}


async def test_a_spanish_question_is_not_answered(monkeypatch):
    from unittest.mock import AsyncMock
    from app.orchestration import review, service
    from app.orchestration.schemas import AskKritonRequest
    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    response = await service.ask_kriton(
        db=object(), sync_db=object(), actor_id="u", tenant_id="t", role="Admin",
        request=AskKritonRequest(query="¿Cuál es el plazo para presentar el impuesto de sociedades en España para mi empresa?"),
    )
    assert response.outcome == "rejected" and response.answer is None
    assert "English only" in response.next_action.message

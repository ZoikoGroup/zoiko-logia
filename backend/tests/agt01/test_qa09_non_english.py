"""QA 9 — non-English request: unsupported language gets an honest scope limit."""
from app.orchestration.language_support import detect_language, scope_message
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.task_context import ResolutionInput, resolve_task_context


def test_a_spanish_question_is_refused_with_a_scope_limit():
    question = "¿Cuál es el plazo para presentar el impuesto de sociedades en España para mi empresa?"
    assert detect_language(question) == "es"
    decision = resolve_task_context(AskKritonRequest(query=question), ResolutionInput(actor_id="u", tenant_id="t", role="Admin"))
    assert decision.status == "unsupported" and decision.reason_codes == ["UNSUPPORTED_LANGUAGE"]
    assert "English only" in scope_message("es")


def test_an_english_question_is_supported():
    decision = resolve_task_context(AskKritonRequest(query="What is the UK VAT registration threshold?"),
                                    ResolutionInput(actor_id="u", tenant_id="t", role="Admin"))
    assert "UNSUPPORTED_LANGUAGE" not in decision.reason_codes

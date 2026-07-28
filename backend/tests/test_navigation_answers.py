from app.orchestration.navigation_answers import resolve_navigation_answer


def test_saved_answers_navigation_is_deterministic():
    answer = resolve_navigation_answer("Where can I find my saved answers?")

    assert answer is not None
    assert answer.destination == "Saved Answers"
    assert answer.path == "/saved-answers"
    assert "[Saved Answers](/saved-answers)" in answer.text


def test_navigation_survives_wrapping_curly_quote():
    answer = resolve_navigation_answer("Where can I find my saved answers?”")

    assert answer is not None
    assert answer.path == "/saved-answers"


def test_real_accounting_question_does_not_take_navigation_fast_path():
    assert resolve_navigation_answer(
        "Where can I find the saved answers that explain accrual accounting?"
    ) is None


def test_unknown_destination_does_not_hallucinate_a_route():
    assert resolve_navigation_answer("Where can I find my tax election wizard?") is None


async def test_mediator_navigation_fast_path_skips_retrieval_and_model(monkeypatch):
    import app.orchestration.service as service
    from app.orchestration.schemas import AskKritonRequest

    async def no_cached_result(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "check_idempotency", no_cached_result)
    monkeypatch.setattr(service, "store_idempotency", noop)
    monkeypatch.setattr(service, "audit_query_received", noop)
    monkeypatch.setattr(service, "audit_request_validated", noop)
    monkeypatch.setattr(service, "audit_prescreen_completed", noop)
    monkeypatch.setattr(service, "audit_risk_classified", noop)
    monkeypatch.setattr(service, "audit_route_selected", noop)
    monkeypatch.setattr(service, "_finalise_and_return", noop)
    monkeypatch.setattr(
        service,
        "build_source_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("retrieval must not run")),
    )
    monkeypatch.setattr(
        service.model_gateway_service,
        "run_test_prompt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("model must not run")),
    )

    response = await service.ask_kriton(
        object(), object(), actor_id="user-1", tenant_id="tenant-1", role="learner",
        request=AskKritonRequest(query="Where can I find my saved answers?”"),
        idempotency_key="navigation-test-1",
    )

    assert response.outcome == "answered"
    assert response.safety.risk_level == "ZERO"
    assert response.source_bundle is None
    assert response.answer is not None
    assert response.answer.prompt_id == "deterministic-product-navigation"

"""Regression tests for the deterministic off-domain refusal fast path
(orchestration/service.py, 2026-08-06).

Live bug: "What's the weather like today?" had no deterministic off-domain
gate at all — it fell through to full LLM composition, which sometimes
produced an incomplete/repetitive response that Checkpoint C escalated to
human review instead of the expected clean refusal. The only existing
off-domain handling looked for a fixed refusal phrase inside the LLM's own
output — a string match against text from an unwired prompt path
(websearch.py's _DOMAIN_GATE) the real governed composition prompt never
actually produces, so it never fired.
"""
from app.orchestration.retrieve import CategoryDecision


async def test_confidently_uncategorized_query_gets_the_clean_refusal_without_retrieval_or_model(monkeypatch):
    import app.orchestration.service as service
    from app.orchestration.schemas import AskKritonRequest

    async def no_cached_result(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    async def fake_classify_category(query):
        return CategoryDecision("standards", "default")

    monkeypatch.setattr(service, "check_idempotency", no_cached_result)
    monkeypatch.setattr(service, "store_idempotency", noop)
    monkeypatch.setattr(service, "audit_query_received", noop)
    monkeypatch.setattr(service, "audit_request_validated", noop)
    monkeypatch.setattr(service, "audit_prescreen_completed", noop)
    monkeypatch.setattr(service, "audit_risk_classified", noop)
    monkeypatch.setattr(service, "audit_route_selected", noop)
    monkeypatch.setattr(service, "audit_query_classified", noop)
    monkeypatch.setattr(service, "_finalise_and_return", noop)
    monkeypatch.setattr(service, "classify_category", fake_classify_category)
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
        request=AskKritonRequest(query="What's the weather like today?"),
        idempotency_key="off-domain-test-1",
    )

    assert response.outcome == "answered"
    assert response.safety.risk_level == "ZERO"
    assert response.source_bundle is None
    assert response.answer is not None
    assert response.answer.prompt_id == "deterministic-off-domain-refusal"
    assert "Accounting, Taxation, Payroll, Finance" in response.answer.text
    assert response.answer.citations == []


def test_real_accounting_questions_never_classify_as_confidently_uncategorized():
    """Guards against the new off-domain gate being too broad: every one
    of these (including deliberately obscurely-phrased ones) must resolve
    via the deterministic rule or the semantic fallback — never fall all
    the way through to method="default", which is what the off-domain
    fast path in service.py keys on."""
    from app.orchestration.retrieve import classify_category
    import asyncio

    real_questions = [
        "Explain what a trial balance is.",
        "How do I reconcile petty cash discrepancies?",
        "What are the FICA withholding requirements for a Texas employer?",
        "Walk me through EITC eligibility for a head of household filer.",
        "What is the going concern assumption?",
    ]
    for query in real_questions:
        decision = asyncio.run(classify_category(query))
        assert decision.method not in ("default", "default_with_azure_shadow"), (
            f"{query!r} wrongly fell through to {decision.method!r}"
        )

"""The answer model is chosen by the work a question needs, never by its risk
alone (24 Oct 2026): "Explain this comparison with a grounded example" was
rated ZERO risk and answered by the small fast model, which counted £50,000
of VAT-inclusive purchases as the input VAT.

Every entry point is covered: a typed question, each Explore-further chip and
the chart offer (read from the frontend, so a new chip is covered when it is
added), the quick modes, a conversation follow-up, attached documents and
non-general task types. Risk classification itself is untouched.
No model, database or network.
"""
import inspect
import re
from pathlib import Path

import pytest

from app.orchestration import audit_events, service
from app.orchestration.service import answer_model_route

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
FAST = "openai/gpt-oss-20b"


def route(question, **kwargs):
    kwargs.setdefault("risk_level", "ZERO")
    kwargs.setdefault("fast_available", True)
    return answer_model_route(question, **kwargs)


def _chip_texts() -> list[str]:
    source = (FRONTEND / "lib" / "follow-up-suggestions.ts").read_text()
    return sorted(set(re.findall(r'"([A-Z][^"]{10,}[.?])"', source)))


def _quick_mode_prompts() -> list[str]:
    source = (FRONTEND / "app" / "ask-kriton" / "page.tsx").read_text()
    return re.findall(r'label: "[^"]+", icon: \w+, prompt: "([^"]*)"', source)


# ── Entry points that reach the answer model ─────────────────────────────

def test_the_frontend_lists_were_found():
    assert len(_chip_texts()) >= 30 and "Explain this comparison with a grounded example." in _chip_texts()
    assert len(_quick_mode_prompts()) == 5


@pytest.mark.parametrize("chip", _chip_texts())
def test_every_follow_up_chip_uses_the_full_model(chip):
    # handleFollowUp sends "<chip> Context: <the answered question>".
    model, reason = route(f"{chip} Context: what is tax")
    assert model is None and "follow-up chip" in reason


@pytest.mark.parametrize("kind", ["bar", "pie", "line"])
def test_a_chart_offer_uses_the_full_model(kind):
    assert route(f"Show this as a {kind} chart. Context: Compare VAT and GST")[0] is None


@pytest.mark.parametrize("prompt", _quick_mode_prompts())
def test_a_quick_mode_with_accounting_work_uses_the_full_model(prompt):
    assert route(f"{prompt}Record the journal entries for a £12,000 sale including VAT")[0] is None


def test_the_workflow_quick_mode_is_reasoning_work_itself():
    assert route("Turn this into a practical accounting workflow: month-end close")[0] is None


@pytest.mark.parametrize("question", [
    "Give me an example of VAT on a £10,000 sale",
    "Calculate corporation tax on profits of 150,000",
    "What journal entries record a deferred tax asset?",
    "How do I account for a finance lease?",
    "IFRS 16 versus ASC 842",
    "What is the present value of £1,000 in 3 years at 5%?",
    "What is the input VAT on purchases of £6,000?",
    "Explain the treatment of a provision",
])
def test_typed_reasoning_questions_use_the_full_model(question):
    assert route(question)[0] is None


@pytest.mark.parametrize("question", ["what is tax", "hello", "What does IFRS stand for?", "What is IFRS 16?",
                                      "Who issues IFRS standards?", "What is the tax point?"])
def test_plain_low_risk_questions_may_use_the_fast_model(question):
    for risk in ("ZERO", "LOW"):
        model, reason = route(question, risk_level=risk)
        assert model == FAST and reason == f"fast model: plain {risk} risk question"


@pytest.mark.parametrize("context, reason", [
    ({"follows_up": True}, "follow-up on the conversation"),
    ({"has_documents": True}, "documents attached"),
    ({"task_type": "reconciliation"}, "task type reconciliation"),
    ({"multi_question": True}, "several questions"),
])
def test_conversation_documents_and_tasks_use_the_full_model(context, reason):
    model, why = route("what is tax", **context)
    assert model is None and reason in why


# ── Risk still governs safety; it only ever raises the model ─────────────

@pytest.mark.parametrize("risk", ["MEDIUM", "HIGH", "RESTRICTED"])
def test_higher_risk_always_uses_the_full_model(risk):
    assert route("what is tax", risk_level=risk) == (None, f"full model: {risk} risk")


def test_no_fast_model_without_a_fast_provider():
    assert route("what is tax", fast_available=False)[0] is None


def test_the_service_routes_through_this_one_decision():
    source = inspect.getsource(service.ask_kriton)
    assert source.count("answer_model_route(") == 1
    assert "GROQ_FAST_ANSWER_MODEL" not in source          # no second, risk-only selection


# ── Auditable ────────────────────────────────────────────────────────────

async def test_the_model_and_its_reason_are_audited(monkeypatch):
    emitted = []

    async def emit(db, name, *args, **kwargs):
        emitted.append((name, args[-1]))
    monkeypatch.setattr(audit_events, "_emit", emit)
    await audit_events.audit_composition_completed(
        None, query_id="q", correlation_id="c", tenant_id="t", audit_chain_id="a", actor_id="u", prompt_id="p",
        output_hash="h", model=FAST, model_route_reason="fast model: plain ZERO risk question")
    assert emitted == [("composition_completed", {"prompt_id": "p", "output_hash": "h", "model": FAST,
                                                  "model_route_reason": "fast model: plain ZERO risk question"})]


def test_the_service_passes_the_model_and_reason_to_the_audit():
    source = inspect.getsource(service.ask_kriton)
    assert "model_route_reason=\"full model: agent loop\" if agent_outcome is not None else model_route_reason" \
        in source

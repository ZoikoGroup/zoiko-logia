"""A correct answer is not labelled Partial for want of a [REF-n] marker, and a
genuinely unsupported one still is (4 Nov 2026 manual tests).

"I can't read this receipt" about an image whose content OCR withheld, and
"Hardware: 1,800" read from the attached chart, were both shown as "Partial —
retrieved sources were not linked to the released claims", because neither
carried a citation marker. The final check now asks whether what the answer
states comes from its sources."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import service
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.websearch import WebSource
from tests.test_answer_status_pipeline import pipeline  # noqa: F401  (fixture)

NOT_LINKED = "Incomplete answer: retrieved sources were not linked to the released claims"
BLURRED = ("[Blurred image: the text below was read unreliably (sharpness 0.09) and every figure in it is withheld "
           "as [unreadable]. Do not state or guess any amount, date or reference from it; say it cannot be read "
           "reliably and ask for a clearer copy or the original file.]\nAmount due: [unreadable]")
UNSUPPORTED_SCRIPT = ("[Low-confidence reading: some of the text in this image appears to be in a script this reader "
                      "does not support (for example Devanagari, Arabic or Tamil); it is not a question of image "
                      "quality, and is shown as [unreadable text]. Do not guess what it says; ask the user for the text "
                      "or a clearer copy.]\n[unreadable text]")
CHART = ("[Chart read by position: the value printed above each category label is Software 4,200; Hardware 1,800; "
         "Services 3,100; the printed values add up to 9,100 (worked out from the values; the chart prints no total).]\n"
         "Software\tHardware\tServices")
FLOW = "Northbridge purchase-to-pay approval flow\nPurchase order  Goods received  Supplier invoice  3-way match?"


def citation(ref="REF-1", source="doc-1", preview=None):
    return SimpleNamespace(ref_id=ref, source_id=source, url=None, evidence_preview=preview)


# ── The rule ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, source, bound", [
    ("I can't read the amount on this invoice; the image is too blurred. Please send a clearer copy.", BLURRED, True),
    ("The receipt is in a script I can't read. Please type the total shown on it.", UNSUPPORTED_SCRIPT, True),
    ("The chart shows Hardware: 1,800 (Software 4,200, Services 3,100).", CHART, True),
    ("Hardware is shown as 1,800 [REF-1].", CHART, True),
    # Genuinely unsupported: a figure the source does not hold, or claims from a
    # readable source with no marker.
    ("The chart shows Hardware: 2,400.", CHART, False),
    ("Hardware is 1,800, which is 19.78% of the total.", CHART, False),
    ("The diagram shows a purchase order, a goods receipt and an invoice check.", FLOW, False),
    # "I can't read it" about a readable document is not excused.
    ("I can't read this document.", FLOW, False),
])
def test_an_answer_is_bound_by_what_it_states(text, source, bound):
    assert service._answer_bound_to_sources(text, [citation()], {"doc-1": source}) is bound


def test_the_preview_stands_in_when_the_full_text_was_not_recorded():
    assert service._answer_bound_to_sources("Hardware: 1,800.", [citation(preview=CHART[:240])], {}) is True


def test_step_numbers_and_ordinals_are_not_figures():
    assert service._figures("Step 1, then 2: Q4 is 3,100 and FY2025 grew 25.00%") == {"3100", "25.00"}


# ── Through the answer pipeline ─────────────────────────────────────────────

async def _ask(pipeline, monkeypatch, question, snippet, answer):
    monkeypatch.setattr(service, "retrieve_document_sources", AsyncMock(return_value=[
        WebSource(title="upload.png — Image", url="", snippet=snippet, provider="uploaded_document",
                  freshness="uploaded", source_id="doc-1")]))
    pipeline.answers(AgentOutcome(text=answer))
    return await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                    request=AskKritonRequest(query=question, document_ids=["doc-1"]))


# Statements only: a reply that also asks for a copy is a clarification
# (test_a_cannot_read_reply_that_asks_for_a_copy_is_a_clarification_whatever_its_verb).
@pytest.mark.parametrize("question, snippet, answer", [
    ("Can you read this invoice?", BLURRED,
     "No. This invoice image is too blurred to read reliably, so no amount, date or reference can be taken from it."),
    ("What does this receipt say?", UNSUPPORTED_SCRIPT,
     "The receipt is written in a script that cannot be read here, so its contents cannot be stated."),
])
async def test_a_correct_cannot_read_answer_is_not_labelled_partial(pipeline, monkeypatch, question, snippet, answer):
    response = await _ask(pipeline, monkeypatch, question, snippet, answer)
    assert response.answer is not None
    assert not any(NOT_LINKED in note for note in response.answer.limitations)
    assert response.answer.completeness == "complete"


async def test_a_figure_read_from_the_attached_chart_is_not_labelled_partial(pipeline, monkeypatch):
    response = await _ask(pipeline, monkeypatch, "What value does this chart show for Hardware?", CHART,
                          "The chart shows Hardware: 1,800.")
    assert not any(NOT_LINKED in note for note in response.answer.limitations)
    assert response.answer.completeness == "complete"


async def test_claims_from_a_readable_document_with_no_marker_are_still_labelled_partial(pipeline, monkeypatch):
    response = await _ask(pipeline, monkeypatch, "Describe what this shows.", FLOW,
                          "The diagram shows a purchase order, a goods receipt and an invoice check.")
    assert any(NOT_LINKED in note for note in response.answer.limitations)
    assert response.answer.completeness == "partial"


async def test_a_figure_the_document_does_not_hold_is_never_released_as_complete(pipeline, monkeypatch):
    # Figure verification withholds it before the binding check is reached:
    # "no factual answer was verified" is stricter than Partial.
    response = await _ask(pipeline, monkeypatch, "Describe what this shows.", CHART, "The chart shows Hardware: 2,400.")
    assert response.answer.completeness in {"none", "partial"}
    assert "2,400" not in (response.answer.text or "")


# ── The same kind of answer gets the same status ───────────────────────────

@pytest.mark.parametrize("ask", [
    "Could you please supply a clearer copy of the receipt (or type out the amount shown)?",
    "Could you provide a clearer copy of the invoice?",
    "Please upload a clearer image or the original file.",
    "Could you type out the total shown on the receipt?",
])
def test_every_way_of_asking_for_a_clearer_copy_is_a_clarification(ask):
    from app.domains.model_gateway.agent import is_agent_clarification
    assert is_agent_clarification(ask, AgentOutcome(text=ask))


@pytest.mark.parametrize("text", [
    "The receipt total is 88.00; please note the tax is included.",
    "Subtotal 80.00 + tax 8.00 = 88.00, so the total is correct.",
])
def test_an_answer_that_mentions_please_is_not_a_clarification(text):
    from app.domains.model_gateway.agent import is_agent_clarification
    assert not is_agent_clarification(text, AgentOutcome(text=text))


async def test_a_cannot_read_reply_that_asks_for_a_copy_is_a_clarification_whatever_its_verb(pipeline, monkeypatch):
    # The first 16 run said "supply" and was released as an answer labelled Partial;
    # the second said "provide" and was a clarification.
    response = await _ask(pipeline, monkeypatch, "What is the total amount on this receipt?", UNSUPPORTED_SCRIPT,
                          "I'm unable to read the amount shown on the receipt image you provided. Could you please "
                          "supply a clearer copy of the receipt (or type out the amount shown) so I can determine the total?")
    assert response.outcome == "clarification_required"
    assert response.answer is None and "clearer copy" in response.next_action.message

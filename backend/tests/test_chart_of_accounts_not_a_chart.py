"""'Chart of accounts' is an accounting term, not a chart request.

A pasted review asked to be commented on contained "...mapped to the chart of
accounts...". That read as a chart request, so the model's commentary was
replaced by a deterministic chart narration of three document rows, titled
with the whole pasted message.
"""
from app.orchestration import service
from app.orchestration.document_evidence import EvidenceModel, Observation, _subject
from app.orchestration.intent_classifier import classify_intent
from app.orchestration.response_planner import detect_explicit_visual_request

PASTED = (
    "## Trial Balance\n\n| Particulars | Amount |\n| --- | --- |\n| Inventory | 418,000 |\n"
    "| Trade Receivables | 703,000 |\n| Cash at Bank | 512,000 |\n\n"
    "The nominal codes need to be mapped to the chart of accounts before preparing financial statements.\n"
    "comment on the above"
)


def test_chart_of_accounts_is_not_a_chart_request():
    assert not detect_explicit_visual_request("Map the nominal codes to the chart of accounts.")
    assert not detect_explicit_visual_request("Review our charts of accounts structure")
    assert not detect_explicit_visual_request(PASTED)


def test_real_chart_requests_still_are():
    for query in ("Give me a chart of revenue by region", "chart for monthly sales",
                  "show the chart of accounts balances as a bar chart"):
        assert detect_explicit_visual_request(query), query


def test_a_comment_on_pasted_tables_gets_a_text_answer_and_no_chart():
    evidence = EvidenceModel(
        subject=_subject(PASTED), provider="uploaded_document", dimensions=["category"], measures=["value"],
        observations=[Observation(dimension=n, value=v, measure="value")
                      for n, v in (("Inventory", 418000), ("Trade receivables", 703000), ("Cash at bank", 512000))],
        coverage_complete=True,
    )
    intent = classify_intent(PASTED)
    shape = service.classify_data_shape(evidence, intent)
    plan = service.plan_response(PASTED, intent, shape)
    assert plan.response_mode == "TEXT_ONLY" and not plan.visual_required
    assert service.VisualizationOrchestrator().decide(evidence, shape, plan, spec_id="t", query=PASTED).spec is None


def test_a_long_message_is_never_used_as_a_chart_title():
    assert _subject("x " * 200) == "Uploaded document"
    assert _subject("Show revenue by region as a bar chart") == "Revenue by region"

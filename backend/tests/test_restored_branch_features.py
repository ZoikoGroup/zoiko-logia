"""Features from Naresh-new that the main merge silently dropped.

The Phase 0 reconciliation (every Naresh-new commit compared with the merged
code) found seven behaviours missing while all 1,764 tests still passed — no
test exercised them. These tests make a repeat loss visible: behaviour is
tested directly where the code can be called on its own, and the pipeline
wiring is pinned where a test would otherwise need the full ask_kriton stack.
"""
import inspect

from app.domains.risk_safety.refusal_templates import get_template
from app.orchestration import service
from app.orchestration.calculation_service import build_calculation
from app.orchestration.schemas import ConversationMessage
from app.orchestration.websearch import formatting_instructions


def test_follow_up_calculation_uses_figures_from_the_earlier_turn():
    # 188a6ad: "cost of sales increased by 10%, revenue unchanged" names no
    # figures of its own; they come from the previous question.
    history = [ConversationMessage(role="user", content="Revenue is 250,000 and cost of sales is 160,000. What is the gross margin?")]
    calculation = build_calculation(
        "If cost of sales increased by 10% and revenue stayed unchanged, what is the gross margin?", history,
    )
    assert calculation is not None
    assert calculation.widget.output_value == "29.6"  # (250000 - 176000) / 250000 * 100


def test_integrity_refusal_offers_the_legitimate_alternative():
    template = get_template("ACCOUNTING_INTEGRITY")
    assert template.body and template.safe_alternative


def test_formatting_rules_answer_every_question_and_show_working():
    rules = formatting_instructions("What is 18% GST on ₹50,000? And what is the UK VAT rate?")
    assert "answer EVERY one" in rules
    assert "show the working step by step" in rules
    assert "Indian" in rules and "grouping" in rules


def test_pipeline_keeps_the_restored_steps_wired():
    source = inspect.getsource(service.ask_kriton)
    # 559f16b / d8119d5: wrong arithmetic is corrected once before validation.
    assert "composition.calculation_correction" in source
    # 188a6ad: fraud/concealment refusals carry the legitimate alternative.
    assert 'get_refusal_template("ACCOUNTING_INTEGRITY")' in source
    # 188a6ad: follow-up calculations see the screened conversation history.
    assert "screened_history(request.conversation_history)" in source
    # 559f16b: HIGH-risk questions are answered as general guidance.
    assert "Give general guidance only" in source
    # 7d9cafa / 13ae7b8: the answer says what it rests on when unsourced.
    assert "No sources could be retrieved for this answer" in source


def test_a_bare_number_is_not_a_verified_calculation():
    # Reported live: "What is 18% GST on ₹50,000? …" showed a Verified
    # calculation box reading "18" beside the real answer (₹9,000).
    gst = build_calculation("What is 18% GST on ₹50,000? Also, what is the UK VAT rate?")
    assert gst is None or gst.widget.output_value != "18"
    assert build_calculation("What is 18?") is None
    assert build_calculation("What is 250 * 4?").widget.output_value == "1000"


def test_follow_up_is_not_asked_again_for_an_input_given_one_turn_earlier():
    # Reported live: the early calculation engine (current message only) asked
    # for revenue the user had just given; the pipeline must defer to the
    # history-aware calculation in that case.
    from app.orchestration.calculations.engine import calculate_from_query

    follow_up = "If cost of sales increased by 10% and revenue stayed unchanged, what is the gross margin?"
    assert calculate_from_query(follow_up).status == "clarification_required"
    assert "screened_history(request.conversation_history),\n    ) is not None" in inspect.getsource(service.ask_kriton)


def test_percentage_of_an_amount_is_a_verified_calculation():
    gst = build_calculation("What is 18% GST on ₹50,000? Also, what is the UK VAT rate?")
    assert gst.widget.formula_name == "GST amount" and gst.widget.output_value == "9000"
    assert build_calculation("Calculate 5% TDS on 2 lakh").widget.output_value == "10000"
    assert build_calculation("Revenue grew 10% on last year to 5,00,000.") is None


def test_a_follow_up_completed_by_earlier_figures_needs_no_web_search():
    # Reported live: the 29.6% follow-up was labelled "source grounded" with
    # five unrelated web sources.
    from app.orchestration.calculation_service import is_self_contained_calculation

    history = [ConversationMessage(role="user", content="Revenue is 2,50,000 and cost of sales is 1,60,000. What is the gross margin?")]
    follow_up = "If cost of sales increased by 10% and revenue stayed unchanged, what is the gross margin?"
    assert is_self_contained_calculation(follow_up, history)
    # Still searched when part of the question needs a looked-up rate.
    assert not is_self_contained_calculation("What is 18% GST on ₹50,000? Also, what is the UK VAT rate?")


def test_depreciation_reads_inputs_written_before_their_label():
    # Baseline calc-02: "a $20,000 asset with a 5-year life" was asked for
    # "asset cost, useful life" although both were in the question.
    from app.orchestration.calculations.engine import calculate_from_query

    result = calculate_from_query(
        "Calculate straight-line depreciation for a $20,000 asset with a 5-year life and $2,000 salvage value."
    )
    assert result.status == "success"
    assert result.outputs[0].display_value == "$3,600.00"


def test_general_guidance_rewrite_keeps_facts_and_drops_instructions():
    request = service._general_guidance_request("You must register within 30 days of exceeding £90,000.")
    assert "You must register within 30 days of exceeding £90,000." in request  # the facts to keep
    assert "never as an instruction to the reader" in request and "Keep every fact, figure and source" in request

"""Task Contract, Stage A (shadow): built from the existing models, recorded,
never read by the pipeline. No model, database or network."""
import json
import logging

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import task_contract
from app.orchestration.answer_coverage import RequestedDeliverable
from app.orchestration.calculations.lease import lease_calculation
from app.orchestration.calculations.schemas import CalculationTaskState
from app.orchestration.intent_planner import SubTask
from app.orchestration.schemas import ConversationMessage as M
from app.orchestration.task_contract import build_task_contract
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

CASE = ("CloudLedger Ltd – Quarter-End Review\n\nThe Background:\n\nCloudLedger Ltd is a UK software company registered "
        "for VAT. It made standard-rated sales of £240,000 and standard-rated purchases of £90,000; all figures exclude "
        "VAT and VAT is 20%.\n\nQuestions to Answer:\n\n• Q1 (VAT): Calculate the VAT payable for the quarter.\n"
        "• Q2 (IFRS 15): Allocate the £120,000 transaction price between the licence and the support.\n"
        "• Q3 (Correction): Prepare the journal entry to correct management's revenue recognition.")
LEASE = ("Annual payments of $50,000 are due at the end of each year for 4 years. The incremental borrowing rate is 6%.\n\n"
         "Task for the Bot:\n1. Calculate the initial lease liability.\n2. Prepare the journal entry at commencement.")


def test_it_is_composed_of_the_existing_models():
    contract = build_task_contract(CASE)
    assert all(isinstance(part, SubTask) for part in contract.parts)
    assert all(isinstance(item, RequestedDeliverable) for item in contract.deliverables)
    with_calc = contract.with_calculation(lease_calculation(LEASE))
    assert isinstance(with_calc.calculation, CalculationTaskState)


def test_a_case_study_separates_its_questions_from_its_background():
    contract = build_task_contract(CASE)
    assert contract.message_type == "case_study" and contract.has_background
    assert len(contract.parts) == 3
    assert {"amount", "allocation", "journal_entry"} <= set(contract.deliverable_kinds())
    sources = {fact.source for fact in contract.facts}
    assert {"request", "background"} <= sources                 # £120,000 asked; £240,000 in the background
    assert contract.missing_inputs == []                        # the VAT facts are in the background


def test_it_is_deterministic():
    assert build_task_contract(CASE).model_dump() == build_task_contract(CASE).model_dump()


def test_a_context_statement_asks_for_nothing():
    contract = build_task_contract("We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025.")
    assert contract.message_type == "context" and contract.parts == [] and contract.deliverables == []


def test_the_calculation_and_its_inputs_are_recorded_with_provenance():
    contract = build_task_contract(LEASE).with_calculation(lease_calculation(LEASE))
    assert contract.calculation_status == "success" and "numerical_correctness" in contract.validations
    assert any(fact.source == "calculator_input" for fact in contract.facts)


def test_a_missing_calculator_input_is_a_missing_input():
    question = "Calculate the lease liability for payments of £10,000 a year at 5% for 3 years."
    contract = build_task_contract(question).with_calculation(lease_calculation(question))
    assert contract.calculation_status == "clarification_required" and contract.missing_inputs


def test_context_another_stage_would_add_outside_the_case_is_recorded():
    history = [M(role="user", content="We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."),
               M(role="user", content="We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years.")]
    contract = build_task_contract("Explain how IFRS 16 lease payments are presented in the cash flow statement.", history=history)
    assert contract.case.history_turns == 2
    assert set(contract.case.essential_turns_outside_scope) <= {0, 1}
    assert all(not fact.in_scope for fact in contract.facts if fact.source == "history" and fact.turn not in contract.case.relevant_turns)


def test_the_log_record_holds_no_message_text(caplog):
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    task_contract.record(build_task_contract(CASE), query_id="q1", stage="understood")
    logged = caplog.records[-1].getMessage()
    assert "CloudLedger" not in logged and "240,000" not in logged and '"message_type": "case_study"' in logged


def test_the_shadow_file_is_written_only_when_enabled(tmp_path, monkeypatch):
    target = tmp_path / "contract.jsonl"
    monkeypatch.setattr(task_contract, "_LOG_FILE", target)
    monkeypatch.delenv("KRITON_TASK_CONTRACT_SHADOW", raising=False)
    task_contract.record(build_task_contract(CASE), query_id="q1", stage="understood")
    assert not target.exists()
    monkeypatch.setenv("KRITON_TASK_CONTRACT_SHADOW", "true")
    task_contract.record(build_task_contract(CASE), query_id="q1", stage="understood")
    assert json.loads(target.read_text().splitlines()[0])["contract"]["message_type"] == "case_study"


def test_a_failing_build_never_raises(monkeypatch):
    monkeypatch.setattr(task_contract, "build_task_contract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert task_contract.shadow_build(CASE) is None
    task_contract.record(None, query_id="q1", stage="understood")


@pytest.mark.parametrize("question", [CASE, LEASE, "What is IFRS 16?",
                                      "Calculate the lease liability for payments of £10,000 a year at 5% for 3 years."])
async def test_the_answer_is_identical_with_the_contract_failing(pipeline, monkeypatch, question):
    """Shadow mode: the contract building, failing or not, never changes the response."""
    def ask_once():
        pipeline.answers(AgentOutcome(text="Model answer placeholder."))
        return pipeline.ask(question)
    normal, _ = await ask_once()
    monkeypatch.setattr(task_contract, "build_task_contract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    broken, _ = await ask_once()
    ignore = {"query_id", "correlation_id", "audit_reference", "request_integrity", "latency_ms", "generated_at"}
    assert normal.model_dump(exclude=ignore) == broken.model_dump(exclude=ignore)

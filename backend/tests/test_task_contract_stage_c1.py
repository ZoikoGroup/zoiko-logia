"""Task Contract, Stage C-1 (shadow): retrieval requirements.

Each part records whether it needs an official current figure or rule (rate,
threshold, deadline, legal or tax rule), or is a calculation on given figures
or a conceptual explanation that needs none; with the jurisdiction, the
publisher from the existing map and an existing connector. Recorded only:
nothing reads it to retrieve. No model, database or network.
"""
import pathlib
import re

import pytest

from app.orchestration.task_contract import build_task_contract

ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"


def _only(query):
    requirements = build_task_contract(query).retrieval
    assert len(requirements) == 1, requirements
    return requirements[0]


@pytest.mark.parametrize("query, fact", [
    ("What is the current UK VAT registration threshold?", "threshold"),
    ("What is the main rate of corporation tax in the UK for 2026?", "rate"),
    ("When is the UK self assessment online filing deadline?", "deadline"),
    ("Is input tax credit allowed on motor vehicles used for employee transport under GST in India?", "rule"),
    ("Is hot takeaway food zero-rated for VAT in the UK?", "rule"),
    ("Convert £10,000 to euros at today's exchange rate.", "rate"),
])
def test_an_official_figure_or_rule_is_recorded(query, fact):
    requirement = _only(query)
    assert requirement.needs_official and requirement.fact_type == fact


@pytest.mark.parametrize("query, fact", [
    ("Explain how lease payments are presented in the statement of cash flows under IFRS 16.", "standard"),
    ("Why do tax authorities set VAT registration thresholds?", "explanation"),
    ("Is VAT a tax on consumption or on profits?", "explanation"),
    ("Can you attest that our VAT return is correct?", "explanation"),
    ("Calculate the VAT payable: UK company, sales £100,000, purchases £50,000, VAT 20%, figures exclude VAT, "
     "all standard-rated.", "calculation"),
    ("Convert $2,500 to pounds at an exchange rate of £1 = $1.25.", "calculation"),
    ("A loan of £40,000 carries interest at 6% a year. Calculate the interest for the first year.", "calculation"),
])
def test_conceptual_questions_and_calculations_need_no_official_figure(query, fact):
    requirement = _only(query)
    assert not requirement.needs_official and requirement.fact_type == fact
    assert requirement.publisher is None and requirement.connector is None


def test_a_shared_tax_word_does_not_borrow_another_countrys_publisher():
    singapore = _only("What is the standard GST rate in Singapore?")
    assert singapore.jurisdictions == ["SINGAPORE"] and singapore.publisher is None    # IRAS: not in the map
    india = _only("What is the GST rate on renewable energy devices after the 2025 changes?")
    assert "CBIC" in india.publisher


def test_existing_connectors_only():
    assert _only("What is the current UK VAT registration threshold?").connector == "hmrc_vat_registration"
    assert _only("What is the current Bank of England base rate?").connector == "bank_of_england"
    assert _only("Can a VAT-registered business reclaim VAT on business purchases in the UK?").connector is None


def test_each_part_has_its_own_requirement():
    contract = build_task_contract("A UK sole trader asks two things. 1. What is the current VAT registration threshold? "
                                   "2. Explain why voluntary registration might help a small business.")
    assert [(r.needs_official, r.fact_type) for r in contract.retrieval] == [(True, "threshold"), (False, "explanation")]
    assert contract.summary()["retrieval"][0]["connector"] == "hmrc_vat_registration"


def test_a_context_statement_records_no_retrieval():
    assert build_task_contract("Our company reports under IFRS and has a 31 December year end.").retrieval == []


def test_shadow_only_nothing_reads_the_requirements():
    # registry_shadow.py (S4) reads them only to log the registry's selection;
    # clarification_requirements.py to ask for a country an official part needs.
    readers = [path.name for path in ROOT.rglob("*.py")
               if path.name not in {"task_contract.py", "registry_shadow.py", "clarification_requirements.py"}
               and re.search(r"\.retrieval\b|retrieval_requirements|RetrievalRequirement", path.read_text())]
    assert readers == []


def test_nothing_reads_the_registry_selection():
    readers = [path.name for path in ROOT.rglob("*.py") if path.name != "registry_shadow.py"
               and re.search(r"registry_shadow\.(?!record\b)|RegistrySelection", path.read_text())]
    assert readers == []


def test_a_failure_records_nothing_and_does_not_reach_the_request(monkeypatch):
    from app.orchestration import task_contract

    def broken(text, context):
        raise ValueError("boom")
    monkeypatch.setattr(task_contract, "_requirement", broken)
    contract = build_task_contract("What is the current UK VAT registration threshold?")
    assert contract.retrieval == [] and contract.deliverables

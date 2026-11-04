"""dev3 floors D1-D4 (labelling policy v2, 31 Oct 2026): positive and negative
cases written from the rules (no dev3 or Set 13 wording). No model, no network."""
import pytest

from app.orchestration import classifier_shadow
from app.orchestration.model_part_classifier import ModelPart, prompt


def _model(fact):
    return ModelPart(index=1, needs_official=fact in ("rate", "threshold", "deadline", "rule"), fact_type=fact,
                     tax_countries=[], counterparty_countries=[], period_kind="unspecified", confidence="high")


def _final(text, fact):
    part = classifier_shadow._final(text, text, _model(fact))
    return part["needs_official"], part["fact_type"]


@pytest.mark.parametrize("text, expected", [
    # D1 positive: a registry term or form code + what it is / is for / reports
    ("What does the P60 show an employee?", (True, "rule")),
    ("What is Form 4868 for?", (False, "explanation")),           # negative: "for?" alone is not a purpose phrase
    ("What is Form 4868 used for?", (True, "rule")),
    ("Why would a landlord submit Form NR4?", (True, "rule")),
    # D1 negative: no country-specific item
    ("What is deferred tax?", (False, "explanation")),
    ("What does a cash flow statement show?", (False, "explanation")),
    ("What does IAS 16 cover?", (False, "explanation")),           # a standard, not a form
])
def test_d1_purpose_of_a_country_specific_item(text, expected):
    assert _final(text, "explanation") == expected


@pytest.mark.parametrize("text, expected", [
    ("How is the employer CPF share worked out?", (True, "rule")),           # D2: registry term, no figures
    ("How is stamp duty on shares computed?", (True, "rule")),               # D2: tax word, no figures
    ("How is straight-line depreciation calculated?", (False, "explanation")),  # D2: no tax, no figures
    ("Calculate the levy on £50,000 at 0.5%.", (False, "calculation")),       # negative: the user's figures (guard)
])
def test_d2_method_without_figures(text, expected):
    assert _final(text, "calculation") == expected


@pytest.mark.parametrize("text, fact, expected", [
    ("When must the annual employer return be filed?", "rule", (True, "deadline")),
    ("By when must excise duty be paid?", "rule", (True, "deadline")),
    ("When are quarterly payroll payments due?", "explanation", (True, "deadline")),
    ("When must a business register for GST?", "rule", (True, "rule")),       # negative: registration excluded
    ("When should a company consider changing its year end?", "explanation", (False, "explanation")),  # negative
])
def test_d3_when_due_is_a_deadline(text, fact, expected):
    assert _final(text, fact) == expected


@pytest.mark.parametrize("text, expected", [
    ("What information is needed to register a Canadian payroll account?", (True, "rule")),
    ("What details are required to calculate UK statutory sick pay?", (True, "rule")),
    ("What information is needed to prepare a budget?", (False, "explanation")),   # negative: no country
])
def test_d4_information_needed_for_a_named_countrys_rule(text, expected):
    assert _final(text, "explanation") == expected


def test_the_instructions_state_p1_p3_p4_and_the_purpose_rule():
    for countries in (True, False):
        system, _ = prompt("q", ["q"], countries=countries)
        for phrase in ("practical compliance question", "is for, shows, reports", "method of an official calculation",
                       "paid, submitted, filed or lodged is deadline"):
            assert phrase in system


@pytest.mark.parametrize("text, expected", [
    # D2b: the method of an accounting (not official) calculation stays explanation
    ("How is goodwill amortisation worked out under straight-line methods?", (False, "explanation")),
    ("How are weighted average inventory costs calculated?", (False, "explanation")),
    # negatives: a tax, registry term or country keeps the official rule
    ("How is payroll tax calculated on bonuses?", (True, "rule")),
    ("How is the employer KiwiSaver contribution worked out?", (True, "rule")),
    ("How are capital allowances calculated in the UK?", (True, "rule")),
])
def test_d2b_an_accounting_method_is_not_official(text, expected):
    assert _final(text, "rule") == expected

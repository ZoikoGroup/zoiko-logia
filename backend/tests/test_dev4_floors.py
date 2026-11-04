"""Approved dev4 classifier checks; synthetic policy cases, no model or HTTP."""
import pytest
from app.orchestration import classifier_shadow as shadow
from app.orchestration.model_part_classifier import ModelPart, prompt


def final(text, fact):
    model = ModelPart(1, fact in ('rate', 'threshold', 'deadline', 'rule'), fact, [], [], 'unspecified', 'high')
    result = shadow._final(text, text, model)
    return result['needs_official'], result['fact_type']


@pytest.mark.parametrize('verb,obj', [
    ('notify', 'the tax office'), ('tell', 'the customs authority'),
    ('inform', 'the payroll department'), ('report', 'a withholding adjustment'),
    ('issue', 'a VAT invoice'), ('give', 'a contribution statement'),
    ('send', 'a tax return'), ('obtain', 'an export permit'),
    ('complete', 'tax documentation'), ('generate', 'an excise invoice'),
    ('make', 'a customs statement'),
])
def test_e1_compliance_action_timing(verb, obj):
    assert final(f'When must a trader {verb} {obj}?', 'rule') == (True, 'deadline')


@pytest.mark.parametrize('text', [
    'Within how many days must a trader issue a customs invoice?',
    'When must a VAT-registered trader issue an invoice?',
    'When is a contribution statement given to the worker?',
    'By when must excise documentation be completed before dispatch?',
    'When must an employer inform HMRC about a new benefit?',
])
def test_e1_passive_and_other_time_prefixes(text):
    assert final(text, 'explanation') == (True, 'deadline')


@pytest.mark.parametrize('text,fact,expected', [
    ('Does a trader have to notify the tax office when operations cease?', 'rule', (True, 'rule')),
    ('Who must issue an excise invoice?', 'rule', (True, 'rule')),
    ('What must be reported to the customs authority?', 'rule', (True, 'rule')),
    ('When is a shareholder loan treated as taxable income?', 'rule', (True, 'rule')),
    ('When must a trader register for sales tax?', 'rule', (True, 'rule')),
    ('When must a developer generate a software build?', 'explanation', (False, 'explanation')),
    ('When should software costs be recognised under IAS 38?', 'rule', (False, 'standard')),
])
def test_e1_negatives(text, fact, expected):
    assert final(text, fact) == expected


@pytest.mark.parametrize('text', [
    'Are professional subscriptions deductible?',
    'Is an insurance settlement taxable?',
    'Can input VAT be recoverable on equipment?',
    'Must a trader withhold tax on royalties?',
    'What records must support customs relief?',
    'Which conditions apply to an excise exemption?',
    'How should we treat a reimbursement for tax?',
    'How to account for this item for tax?',
])
def test_e2_practical_without_country(text, monkeypatch):
    monkeypatch.setenv('KRITON_COUNTRY_RESOLUTION', '1')
    assert final(text, 'explanation') == (True, 'rule')
    model = ModelPart(1, False, 'explanation', [], [], 'unspecified', 'high')
    result = shadow._final(text, text, model)
    assert result['country_resolution']['status'] == 'unknown'
    assert result['tax_countries'] == result['domains'] == []


@pytest.mark.parametrize('text', [
    'Why are taxes imposed on consumption?',
    'How does a tax affect economic incentives in general?',
    'What is the difference between direct and indirect taxes in general?',
    'What records are needed to plan a holiday?',
])
def test_e2_concepts_and_non_tax_questions_stay_explanations(text):
    assert final(text, 'explanation') == (False, 'explanation')


@pytest.mark.parametrize('text', [
    'How should a provision be recognised under IAS 37?',
    'What judgement applies to financial statements containing misstatements?',
    'Should equipment repairs be capitalised in the accounts?',
])
def test_e3_accounting_judgement(text):
    assert final(text, 'rule') == (False, 'standard')


def test_e3_tax_treatment_stays_official():
    assert final('How does IAS 12 affect the corporate tax treatment?', 'rule') == (True, 'rule')


@pytest.mark.parametrize('text', [
    'Which costs are included when computing taxable income?',
    'What deductions are allowed when working out excise duty?',
    'What items are added back when taxable income is calculated?',
])
def test_e4_included_in_official_calculation(text):
    assert final(text, 'explanation') == (True, 'rule')


def test_e4_non_tax_cost_question_stays_explanation():
    assert final('Which costs are included when computing a project budget?', 'explanation') == (False, 'explanation')


def test_user_figures_guard_still_wins():
    assert final('Calculate VAT on £8,000 at 20%.', 'rule') == (False, 'calculation')


def test_instruction_updates_in_both_variants():
    for countries in (True, False):
        system, _ = prompt('question', ['question'], countries=countries)
        for phrase in ('time-bound action', 'withholding certificate', 'sports club', 'IAS 36', 'chargeable income'):
            assert phrase in system

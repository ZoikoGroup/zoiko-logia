"""Stage E1: the rule-table part classifier (offline, shadow only). No
model, database or network. Cases come from the tuning sets only.
"""
import pytest

from app.orchestration.part_classifier import classify_part


@pytest.mark.parametrize("text, fact", [
    ("What is the current UK VAT registration threshold?", "threshold"),
    ("What percentage VAT do UK restaurants charge on hot food?", "rate"),
    ("How long must I keep VAT records in the UK?", "deadline"),
    ("What is the late fee for GSTR-1 in India?", "rule"),
    ("What is the current RBA cash rate?", "rate"),
])
def test_official_parts(text, fact):
    result = classify_part(text, text)
    assert result.needs_official and result.fact_type == fact


@pytest.mark.parametrize("text, fact, source", [
    ("Convert $2,500 to pounds at an exchange rate of £1 = $1.25.", "calculation", "guard:fx_rate_given"),
    ("Calculate the VAT payable: UK company, sales £100,000, purchases £50,000, VAT 20%.", "calculation", "guard:user_figures"),
    ("Why do tax authorities set VAT registration thresholds?", "explanation", "guard:conceptual"),
    ("Explain the difference between a filing deadline and a filing extension.", "explanation", "guard:conceptual"),
])
def test_guards_decide_the_clear_cases(text, fact, source):
    result = classify_part(text, text)
    assert not result.needs_official and result.fact_type == fact and result.source == source
    assert result.confidence["fact_type"] == "high"


@pytest.mark.parametrize("text, guarded", [
    ("A company charges S$10,000 before GST. Calculate the total invoice amount.", False),   # rate not given
    ("Calculate the stamp duty on a £400,000 house purchase in England.", False),
    ("Calculate employer NI on a £40,000 salary.", False),
    ("Calculate VAT at 20% on £1,000.", True),
    ("Calculate net profit: revenue £100,000, expenses £60,000, tax £8,000.", True),          # tax amount given
    ("Calculate profit before tax from sales of £50,000 and costs of £30,000.", True),
    ("Prepare the journal entry for paying £3,000 of VAT to HMRC.", True),
    ("Prepare the journal for £600 PAYE deducted from £3,000 salary.", True),
    ("Calculate annual depreciation on £12,000 over 4 years.", True),
])
def test_the_user_figures_guard_needs_every_input_including_the_rate(text, guarded):
    assert (classify_part(text, text).source == "guard:user_figures") is guarded


def test_a_current_exchange_rate_is_official():
    result = classify_part("Convert £10,000 to euros at today's exchange rate.")
    assert result.needs_official and result.source == "guard:fx_current"


def test_the_other_partys_country_is_a_counterparty():
    result = classify_part("I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. "
                           "Do I need GST registration and do I charge GST?")
    assert result.tax_countries == ["INDIA"]
    assert [c.country for c in result.countries if c.role == "counterparty"] == ["US"]


def test_every_field_has_a_confidence():
    result = classify_part("What is the standard GST rate in Singapore?")
    assert set(result.confidence) == {"needs_official", "fact_type", "countries", "period"}
    assert result.as_record()["version"] == "rule-table-e1"

"""Statutory calculations from verified, effective-dated parameters
(registry/tax_parameters.json) and investment appraisal from stated cash
flows (3 Nov 2026). Expected figures are worked by hand from the official
rates quoted in the parameter file."""
from datetime import date
from decimal import Decimal

import pytest

from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.statutory import select


def _values(query):
    result = calculate_from_query(query)
    return result, {o.name: o.display_value for o in result.outputs}


@pytest.mark.parametrize("query, expected", [
    ("Calculate income tax on a salary of £40,000.", {"income_tax": "£5,486.00"}),
    ("What is the take-home pay on a salary of £40,000?",
     {"income_tax": "£5,486.00", "employee_national_insurance": "£2,194.40", "annual_take_home_pay": "£32,319.60"}),
    ("Calculate the employer National Insurance on a UK salary of £40,000 for 2026 to 2027.",
     {"employer_national_insurance": "£5,250.00"}),
    ("Calculate employee national insurance on £60,000.", {"employee_national_insurance": "£3,210.60"}),
    ("Calculate income tax on £150,000 for 2025/26.", {"income_tax": "£53,703.00"}),     # allowance fully tapered
    ("What is the take-home pay on £3,000 a month?", {"monthly_take_home_pay": "£2,453.30"}),
    ("Calculate income tax on ₹15,00,000 under the new regime for FY 2025-26.", {"slab_tax": "₹105,000.00"}),
    ("Calculate income tax on ₹30 lakh for AY 2026-27.", {"slab_tax": "₹480,000.00"}),
])
def test_statutory(query, expected):
    result, values = _values(query)
    assert result.status == "success", result
    for name, shown in expected.items():
        assert values[name] == shown
    assert any("read 2026-11-03" in note for note in result.notes)


@pytest.mark.parametrize("query", [
    "Calculate income tax on £40,000 for 2023 to 2024.",              # no verified parameters for that year
    "Calculate income tax for a Scottish taxpayer on £40,000.",       # Scottish bands not in the tables
    "Calculate income tax on ₹15,00,000 under the new regime.",       # FY 2026-27 slabs not verified
    "Calculate income tax on ₹15,00,000 under the old regime for FY 2025-26.",
])
def test_not_calculated_without_verified_parameters(query):
    result = calculate_from_query(query)
    assert "uk_statutory_pay" not in result.formula_ids and "india_income_tax_new_regime" not in result.formula_ids


def test_the_entry_in_force_is_chosen_by_date():
    assert select("UK", "ni_employer", "", today=date(2026, 1, 10))["period"]["label"] == "2025 to 2026"
    assert select("UK", "ni_employer", "", today=date(2026, 11, 3))["period"]["label"] == "2026 to 2027"
    assert select("UK", "ni_employer", "", today=date(2024, 6, 1)) is None


def test_a_supplied_rate_stays_arithmetic_on_the_users_figures():
    _, values = _values("Calculate income tax on £30,000 at 20% after a £12,570 allowance.")
    assert values["tax"] == "£3,486.00"


@pytest.mark.parametrize("query, expected", [
    ("A project has an initial investment of £100,000 and cash flows of £30,000, £40,000 and £50,000 over three years. "
     "Calculate the NPV at 8%.", {"npv": "£1,762.94"}),
    ("Initial investment £100,000; annual cash inflows £30,000 for 5 years. Calculate the IRR and payback period.",
     {"irr": "15.24%", "payback_years": "3.33 years"}),
    ("Year 0: -£50,000; Year 1: £20,000; Year 2: £25,000; Year 3: £15,000. What is the NPV at 10% and the IRR?",
     {"npv": "£112.70", "irr": "10.13%"}),
    ("Net profit is £1,000,000 and there are 2,000,000 shares. Calculate EPS.", {"basic_eps": "£0.50"}),
    ("Profit after tax of £5m, preference dividends of £500,000 and 10 million ordinary shares. What is the earnings per share?",
     {"basic_eps": "£0.45"}),
])
def test_investment_and_eps(query, expected):
    result, values = _values(query)
    assert result.status == "success"
    assert {k: values[k] for k in expected} == expected


def test_an_npv_without_a_rate_is_asked_for_not_assumed():
    from app.orchestration.clarification_requirements import clarification
    from app.orchestration.task_contract import build_task_contract
    query = "Calculate the NPV of an initial investment of £100,000 with cash flows of £30,000 and £80,000."
    assert not calculate_from_query(query).matched
    assert "discount rate" in clarification(build_task_contract(query), task_query=query)


def test_every_parameter_quotes_its_source():
    import json
    from app.orchestration.calculations.statutory import PARAMETERS
    for entry in json.loads(PARAMETERS.read_text())["entries"]:
        assert entry["period"]["from"] < entry["period"]["to"]
        assert all(src["url"].startswith("https://") and src["quotes"] and len(src["content_sha256"]) == 64
                   for src in entry["source"])

"""Global Source Registry, Stage S4 (shadow): selection from registry metadata,
the comparison with today's selection, and that the shadow is off by default
and never raises."""
import json

from app.orchestration import registry_shadow
from app.orchestration.task_contract import build_task_contract


def _official(query):
    return [r for r in build_task_contract(query).retrieval if r.needs_official]


def test_registry_file_loads():
    assert len(registry_shadow.entries()) > 100


def test_uk_vat_threshold_selects_the_hmrc_registration_page():
    [selection] = registry_shadow.selections(build_task_contract("What is the current UK VAT registration threshold?"))
    assert selection.tier == "fixed_page"
    assert "https://www.gov.uk/register-for-vat" in selection.fixed_pages
    assert selection.today_connector == "hmrc_vat_registration" and selection.connector_agrees


def test_singapore_gst_rate_agrees_on_the_iras_page():
    [selection] = registry_shadow.selections(build_task_contract("What is the current GST rate in Singapore?"))
    assert any("iras.gov.sg" in url for url in selection.fixed_pages)
    assert not selection.pages_today_only


def test_isle_of_man_has_no_registered_source():
    selections = registry_shadow.selections(build_task_contract("What is the VAT registration threshold in the Isle of Man?"))
    assert all(s.tier in {"search_only", "none"} and not s.fixed_pages for s in selections)


def test_a_historical_year_is_not_served_by_a_current_page():
    [requirement] = _official("What was the UK corporation tax main rate in 2015?")
    selection = registry_shadow.select(requirement)
    assert requirement.period.kind == "year"
    assert not selection.fixed_pages and selection.period_unconfirmed


def test_calculation_on_given_figures_selects_nothing():
    assert registry_shadow.selections(build_task_contract(
        "Equipment costs £95,000, residual value £11,000, useful life 7 years. Calculate annual straight-line depreciation.")) == []


def test_record_is_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("KRITON_REGISTRY_SHADOW", raising=False)
    monkeypatch.setattr(registry_shadow, "_LOG_FILE", tmp_path / "r.jsonl")
    registry_shadow.record(build_task_contract("What is the current UK VAT registration threshold?"), query_id="q")
    assert not (tmp_path / "r.jsonl").exists()


def test_record_writes_when_on_and_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("KRITON_REGISTRY_SHADOW", "true")
    monkeypatch.setattr(registry_shadow, "_LOG_FILE", tmp_path / "r.jsonl")
    registry_shadow.record(build_task_contract("What is the current UK VAT registration threshold?"), query_id="q")
    line = json.loads((tmp_path / "r.jsonl").read_text().splitlines()[0])
    assert line["stage"] == "registry" and line["selections"][0]["tier"] == "fixed_page"
    registry_shadow.record(object(), query_id="bad")  # not a contract: logged, not raised


# S4b: subjects and payroll (the gaps the first shadow report found).
def test_uk_vat_rate_does_not_select_corporation_or_income_tax_pages():
    [selection] = registry_shadow.selections(build_task_contract("What is the current VAT rate in the UK?"))
    assert not any("corporation-tax" in url or "income-tax" in url for url in selection.fixed_pages)


def test_australian_gst_rate_is_not_served_by_the_cash_rate_connector():
    [selection] = registry_shadow.selections(build_task_contract("What is the GST rate in Australia?"))
    assert "connector:find_cash_rate" not in selection.connectors
    assert selection.tier == "search_only" and "ato.gov.au" in selection.search_domains


def test_payroll_questions_reach_the_country_search_scope():
    [selection] = registry_shadow.selections(build_task_contract(
        "What is the current rate of employer national insurance contributions in the UK?"))
    assert selection.tier != "none" and "gov.uk" in selection.search_domains


def test_conversion_at_todays_rate_selects_the_exchange_rate_connector():
    [selection] = registry_shadow.selections(build_task_contract("Convert £10,000 to euros at today's exchange rate."))
    assert "connector:find_rate" in selection.connectors

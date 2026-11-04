"""Task Contract, Stage C-2a (shadow): the official pages each part would use,
and a record of what the final answer cites for each official part. Recorded
only: retrieval, answers and verification are unchanged. No model, database
or network.
"""
import logging
from types import SimpleNamespace

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import task_contract
from app.orchestration.task_contract import build_task_contract, record_retrieved, served_by
from tests.test_answer_status_pipeline import pipeline  # noqa: F401


def _only(query):
    requirements = [r for r in build_task_contract(query).retrieval if r.needs_official]
    assert len(requirements) == 1, requirements
    return requirements[0]


def _cite(url, authority=None, provider=None, title="Source"):
    return SimpleNamespace(url=url, authority=authority, provider=provider, title=title)


def test_the_existing_official_pages_are_recorded():
    singapore = _only("What is the standard GST rate in Singapore?")
    assert [title for title, _ in singapore.official_pages] == ["IRAS: Current GST rates"]
    corporation_tax = _only("What is the main rate of corporation tax in the UK for 2026?")
    assert any("Corporation Tax" in title for title, _ in corporation_tax.official_pages)
    assert _only("What is the GST registration turnover threshold in Australia?").official_pages == []


def test_a_conceptual_part_records_no_pages():
    requirement = build_task_contract("Why do tax authorities set VAT registration thresholds?").retrieval[0]
    assert not requirement.needs_official and requirement.official_pages == []


def test_what_served_an_official_part():
    singapore = _only("What is the standard GST rate in Singapore?")
    iras = _cite("https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/basics-of-gst/current-gst-rates")
    assert served_by(singapore, [iras]) == ["official_page"]
    threshold = _only("What is the current UK VAT registration threshold?")
    assert served_by(threshold, [_cite("https://www.gov.uk/register-for-vat")]) == ["connector"]
    rate = _only("What is the standard rate of VAT in the UK?")
    assert served_by(rate, [_cite("https://www.gov.uk/vat-rates")]) == ["publisher"]
    assert served_by(rate, [_cite("https://www.legislation.gov.uk/ukpga/1994/23", authority="official")]) == ["publisher"]
    assert served_by(rate, [_cite("https://accountingweb.co.uk/vat", authority="web")]) == []
    assert served_by(rate, []) == []


def test_another_countrys_authority_is_not_the_publisher():
    singapore = _only("What is the standard GST rate in Singapore?")
    assert served_by(singapore, [_cite("https://cbic-gst.gov.in/gst-rates")]) == []
    assert served_by(singapore, [_cite("https://cbic-gst.gov.in/gst-rates", authority="official")]) == ["other_official"]


def test_a_domain_retrieval_trusts_for_the_country_is_recorded_as_such():
    australia = _only("What is the GST registration turnover threshold in Australia?")
    assert "ato.gov.au" in australia.official_domains
    assert served_by(australia, [_cite("https://www.ato.gov.au/businesses/gst/registering")]) == ["allowlisted"]
    assert served_by(australia, [_cite("https://www.gov.uk/vat-registration")]) == []


def test_the_record_never_raises(caplog):
    contract = build_task_contract("What is the current UK VAT registration threshold?")
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    record_retrieved(contract, object(), query_id="q1")
    record_retrieved(contract, SimpleNamespace(answer=SimpleNamespace(citations=[1, None])), query_id="q2")
    record_retrieved(None, None, query_id="q3")
    assert sum("stage=retrieved" in r.getMessage() for r in caplog.records) == 2


def test_nothing_is_recorded_without_an_official_part(caplog):
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    record_retrieved(build_task_contract("Explain how VAT works as a tax on consumption."),
                     SimpleNamespace(answer=None), query_id="q")
    assert not [r for r in caplog.records if "stage=retrieved" in r.getMessage()]


async def test_the_pipeline_records_what_the_answer_cites(pipeline, caplog):
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    pipeline.answers(AgentOutcome(text="The VAT registration threshold is set by HMRC."))
    await pipeline.ask("What is the current UK VAT registration threshold?")
    retrieved = [r.getMessage() for r in caplog.records if "stage=retrieved" in r.getMessage()]
    assert len(retrieved) == 1 and '"fact": "threshold"' in retrieved[0]


async def test_a_failing_record_does_not_reach_the_answer(pipeline, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("boom")
    monkeypatch.setattr(task_contract, "served_by", broken)
    pipeline.answers(AgentOutcome(text="The VAT registration threshold is set by HMRC."))
    response, _ = await pipeline.ask("What is the current UK VAT registration threshold?")
    assert response.outcome



async def test_the_record_names_the_retrieval_path(pipeline, caplog):
    import json
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    pipeline.answers(AgentOutcome(text="The VAT registration threshold is set by HMRC."))
    await pipeline.ask("What is the current UK VAT registration threshold?")
    message = next(r.getMessage() for r in caplog.records if "stage=retrieved" in r.getMessage())
    summary = json.loads(message.split("stage=retrieved ", 1)[1])
    assert summary["retrieval"]["path"] == "agent" and summary["retrieval"]["official_prefetch"] is True
    assert summary["route"]


def test_a_response_before_retrieval_is_recorded_as_such(caplog):
    caplog.set_level(logging.INFO, logger="kriton.task_contract")
    record_retrieved(build_task_contract("What is the current UK VAT registration threshold?"),
                     SimpleNamespace(answer=None, outcome="clarification_required", route="CLARIFICATION"), query_id="q")
    assert '"path": "before_retrieval"' in next(r.getMessage() for r in caplog.records if "stage=retrieved" in r.getMessage())

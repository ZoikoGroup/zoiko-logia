from unittest.mock import AsyncMock

import pytest

from app.orchestration import service
from app.orchestration.evidence_narrative import ground_causal_claims
from app.orchestration.professional_boundary import requests_tax_certification
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.series_summary import ground_series_summary
from app.orchestration.websearch import WebSource


def test_reported_japan_peak_and_steady_claim_are_replaced():
    source = WebSource(
        title="Japan central government debt (% of GDP)", url="https://example.test",
        snippet="", series=[("2015", 194.58), ("2016", 193.23), ("2020", 215.76),
                             ("2021", 216.33), ("2022", 216.21)],
    )
    table = (
        "| Year | Debt |\n| --- | --- |\n| 2015 | 194.58 |\n| 2016 | 193.23 |\n"
        "| 2020 | 215.76 |\n| 2021 | 216.33 |\n| 2022 | 216.21 |"
    )
    answer = (
        "Japan's debt has risen steadily, reaching a peak of 216% in 2022.\n\n" + table
        + "\n\nThe data show an upward trajectory with a sharp jump in 2020-2022. "
        "The source does not identify the causes."
    )
    result = ground_series_summary(answer, [source])
    assert "maximum is 216.33 in 2021" in result
    assert "both increases and decreases" in result
    assert "steadily" not in result and "peak of 216% in 2022" not in result
    assert "sharp jump" not in result
    assert table in result and "The source does not identify the causes." in result
    assert result.count("maximum is") == 1


def test_summary_describes_only_the_periods_the_answer_tabulates():
    # Reported live: "India's inflation over the last 5 years" tabulated
    # 2021-2025 while the summary described the full fetched series
    # ("from 5.79652 in 2006 ... maximum 11.9894 in 2010").
    source = WebSource(
        title="Inflation, consumer prices (annual %) — India", url="https://example.test", snippet="",
        series=[("2006", 5.79652), ("2010", 11.9894), ("2021", 5.13), ("2022", 6.7),
                ("2023", 5.65), ("2024", 4.95), ("2025", 2.39885)],
    )
    table = "| Year | Inflation % |\n| --- | --- |\n" + "\n".join(
        f"| {year} | {value} |" for year, value in
        [("2021", 5.13), ("2022", 6.70), ("2023", 5.65), ("2024", 4.95), ("2025", 2.40)]
    )
    result = ground_series_summary(table + "\n\nInflation peaked in 2023.", [source])
    assert "from 5.13 in 2021 to 2.4 in 2025" in result
    assert "maximum is 6.7 in 2022" in result
    assert "2006" not in result and "2010" not in result and "11.9894" not in result


def test_summary_keeps_tied_peaks_and_separate_series():
    sources = [WebSource(title=name, url="https://example.test/" + name, snippet="", series=series)
               for name, series in [("A", [("2020", 2), ("2021", 3), ("2022", 3)]),
                                    ("B", [("2020", 9), ("2021", 5)])]]
    result = ground_series_summary("Both countries peaked in 2022.", sources)
    assert "maximum is 3 in 2021, 2022" in result
    assert "maximum is 9 in 2020" in result


@pytest.mark.parametrize("query", [
    "Certify that my company’s tax return is legally compliant.",
    "“Certify that my company’s tax return is legally compliant.”",
    "Can you certify my tax return?",
    "Please sign off my tax return.",
    # Paraphrases that escaped the first, wording-specific version.
    "Is my tax return compliant? Please certify it.",
    "Can you attest that our VAT return is correct?",
    "I need you to sign off our financial statements.",
    "Guarantee that my GST return has no errors.",
    "Confirm my income tax return is legally compliant so I can file it.",
])
def test_direct_tax_certification_is_detected(query):
    assert requests_tax_certification(query)


@pytest.mark.parametrize("query", [
    "Explain what it means to certify a tax return.",
    "Do not certify my tax return; explain accrual accounting.",
    "What should a tax return review checklist contain?",
    "Who can sign off a VAT return in the UK?",
    "How do I check my tax return is compliant?",
    "What does an auditor certify in financial statements?",
    "Confirm the VAT rate for books in the UK.",
    "Can you verify the GST calculation in my return of 18% on 50000?",
])
def test_educational_requests_are_not_certification(query):
    assert not requests_tax_certification(query)


def test_standard_composition_gets_the_same_trend_and_cause_grounding():
    # Agent mode off, or the agent failed and fell back: the answer was
    # written by the standard composer against the live series, not by the
    # agent loop, and must be held to the same checks.
    source = WebSource(
        title="India inflation (%)", url="https://example.test", snippet="CPI inflation, annual %.",
        series=[("2021", 5.13), ("2022", 6.7), ("2023", 5.65)],
    )
    answer = (
        "Inflation peaked in 2023 at 5.65%. "
        "Inflation rose to 6.7% in 2022 due to higher food prices."
    )
    result = ground_series_summary(ground_causal_claims(answer, [source]), [source])
    assert "peaked in 2023" not in result
    assert "maximum is 6.7 in 2022" in result
    assert "food prices" not in result
    assert "do not state the causes" in result


async def test_repeated_certification_refused_before_retrieval_and_model(monkeypatch):
    for name in (
        "audit_query_received", "audit_request_validated", "audit_context_resolved",
        "audit_prescreen_completed", "audit_refusal_returned", "_finalise_and_return",
    ):
        monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    retrieval = AsyncMock(side_effect=AssertionError("must not retrieve"))
    provider = AsyncMock(side_effect=AssertionError("must not call the model"))
    monkeypatch.setattr(service, "build_source_bundle", retrieval)
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", provider)
    responses = []
    for _ in range(2):
        responses.append(await service.ask_kriton(
            db=object(), sync_db=object(), actor_id="u", tenant_id="t", role="Accountant",
            request=AskKritonRequest(query="Certify that my company’s tax return is legally compliant."),
        ))
    assert all(r.outcome == "refused" and r.route == "REFUSAL" for r in responses)
    assert all(r.safety.risk_level == "HIGH" and r.answer is None for r in responses)
    assert responses[0].next_action.message == responses[1].next_action.message
    retrieval.assert_not_awaited()
    provider.assert_not_awaited()
    assert service.audit_refusal_returned.await_count == 2

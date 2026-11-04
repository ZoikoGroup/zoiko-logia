"""The search planner may not add a year the request does not name (3 Nov
2026): "What is the current UK employer National Insurance contribution
rate?" was searched as "… rate 2024", retrieved the 2024 to 2025 rates page
(13.8%), and the claim judge rejected the correct 15% as contradicted."""
import json
from types import SimpleNamespace

import pytest

from app.orchestration import evidence_planning
from app.orchestration.evidence_planning import without_introduced_years

NI = "What is the current UK employer National Insurance contribution rate?"


@pytest.mark.parametrize("phrase, expected", [
    ("uk employer national insurance contribution rate 2024", "uk employer national insurance contribution rate"),
    ("UK employer NIC rates 2024 to 2025", "UK employer NIC rates"),
    ("HMRC rates 2024/25", "HMRC rates"),
    ("employer rate FY 2024-25 HMRC", "employer rate HMRC"),
])
def test_a_year_the_request_does_not_name_is_removed(phrase, expected):
    assert without_introduced_years(phrase, NI) == expected


@pytest.mark.parametrize("request_text, phrase", [
    ("What was the UK corporation tax rate in 2022?", "UK corporation tax main rate 2022 HMRC"),
    ("What was the UK corporation tax rate in 2022?", "corporation tax rate 2022 to 2023"),
    ("Explain ASU 2016-02 on leases", "ASU 2016-02 lease accounting"),
])
def test_a_year_the_request_names_is_kept(request_text, phrase):
    assert without_introduced_years(phrase, request_text) == phrase


@pytest.mark.parametrize("phrase", ["IAS 16 property plant and equipment", "section 194J TDS rate", "Form 2024A filing"])
def test_numbers_that_are_not_years_are_kept(phrase):
    assert without_introduced_years(phrase, NI) == phrase


async def test_the_semantic_plan_is_kept_without_the_added_year(monkeypatch):
    plan = {"subjects": [{"subject": "UK employer NIC rate", "query": "uk employer national insurance contribution rate 2024",
                          "alternative": "HMRC employer Class 1 secondary rate 2024 to 2025"}]}

    async def complete(**kwargs):
        return SimpleNamespace(text=json.dumps(plan))

    monkeypatch.setenv("EVIDENCE_PLANNING", "on")
    monkeypatch.setattr(evidence_planning.gateway, "may_use", lambda *args: True)
    monkeypatch.setattr(evidence_planning.gateway, "complete_auxiliary", complete)
    result = await evidence_planning.plan_evidence_search(NI, [NI])
    assert result.method == "semantic"
    [subject] = result.subjects
    assert subject.query == "uk employer national insurance contribution rate"
    assert subject.alternative == "HMRC employer Class 1 secondary rate"

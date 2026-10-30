"""Evidence validation (reliability plan phase 4): a citation is not proof.

Every released answer is checked against the full text of the sources it
cites, deterministically: the figure must be in the very source cited for it;
the source must be of the jurisdiction asked about, in force for the period,
not withdrawn, not contradicted by another cited source, and of a kind that
can state a rule. Findings are disclosed and audited with each source's
provenance; nothing is rewritten to look supported. Missing evidence keeps
its existing disclosure (uncited statements are labelled general explanation;
strict answers without evidence are withheld). No model, database or network.
"""
import inspect
from datetime import date

import pytest

from app.orchestration import audit_events, service
from app.orchestration.schemas import SourceCitation, SourceSummary
from app.orchestration.source_taxonomy import source_authority
from app.orchestration.verification_service import (
    AUTHORITY_NOTE_PREFIX, EVIDENCE_NOTE_PREFIX, evidence_findings, evidence_notes, verify_for_release,
)
from app.orchestration.websearch import WebSource

HMRC = SourceCitation(ref_id="REF-1", source_id="s1", title="VAT rates", url="https://www.gov.uk/guidance/rates-of-vat",
                      authority="official", jurisdiction="UK")
OLD_NOTICE = SourceCitation(ref_id="REF-2", source_id="s2", title="VAT Notice 700/1 (2011)", authority="official",
                            jurisdiction="UK", effective_from=date(2011, 1, 4), effective_to=date(2017, 3, 31),
                            source_version_id="ver-old")
BLOG = SourceCitation(ref_id="REF-3", source_id="s3", title="Tax blog", url="https://www.example-tax-blog.com/vat",
                      authority="web")
CBIC = SourceCitation(ref_id="REF-4", source_id="s4", title="GST registration", url="https://cbic-gst.gov.in/reg",
                      authority="official", jurisdiction="INDIA")
CITATIONS = [HMRC, OLD_NOTICE, BLOG, CBIC]
EVIDENCE = {
    "REF-1": "The standard rate of VAT is 20%. The reduced rate is 5%.",
    "REF-2": "The VAT registration threshold is £85,000.",
    "REF-3": "The standard rate of VAT is 17.5% for most goods and services.",
    "REF-4": "A supplier must register for GST within 30 days of becoming liable.",
}


def codes(answer, question, **kwargs):
    kwargs.setdefault("evidence_by_ref", EVIDENCE)
    kwargs.setdefault("citations", CITATIONS)
    return sorted(f.code for f in evidence_findings(answer, question=question, **kwargs))


# ── Valid citations pass ─────────────────────────────────────────────────

@pytest.mark.parametrize("answer", [
    "The standard rate of VAT is 20% [REF-1].",
    "The reduced rate is 5% [REF-1].",
    "A VAT-registered business charges VAT on its taxable supplies [REF-1].",
])
def test_a_claim_its_official_source_states_passes(answer):
    assert codes(answer, "What are the UK VAT rates?") == []


def test_the_users_own_figures_and_calculator_results_need_no_source():
    question = "I sold goods for £12,000. What VAT is due?"
    assert codes("On your £12,000 sale VAT at 20% applies [REF-1].", question, facts=question) == []
    assert codes("VAT due is £2,400 [REF-1].", question, facts=question, derived=[2400.0]) == []


def test_an_illustrative_examples_rule_lines_are_checked_and_its_scenario_is_not():
    example = ("### Illustrative example (hypothetical figures)\n"
               "- **Turnover**: £950,000 (assumed for illustration).\n"
               "- Output VAT is charged at the standard rate of 20% [REF-1].")
    assert codes(example, "Explain with a worked example") == []
    # A cited line claims its source's support, in an example or not.
    assert codes(example.replace("20% [REF-1]", "25% [REF-1]"), "Explain with a worked example") \
        == ["figure_not_in_cited_source"]


# ── Unsupported claims: the citation is not the proof ───────────────────

def test_a_figure_its_cited_source_does_not_state_is_found():
    found = evidence_findings("The standard rate of VAT is 25% [REF-1].", question="UK VAT rate?",
                              evidence_by_ref=EVIDENCE, citations=CITATIONS)
    assert [f.code for f in found] == ["figure_not_in_cited_source"]
    assert found[0].message == "25% is not stated in the source cited for it"


def test_a_figure_cited_to_the_wrong_source_says_another_states_it():
    found = evidence_findings("The VAT registration threshold is £85,000 [REF-1].", question="UK VAT threshold?",
                              evidence_by_ref=EVIDENCE, citations=CITATIONS)
    assert found[0].code == "figure_not_in_cited_source" and "another retrieved source states it" in found[0].message


def test_a_rule_supported_only_by_web_sources_is_disclosed():
    assert codes("The standard rate of VAT is 17.5% [REF-3].", "UK VAT rate?") == ["no_authoritative_source"]


@pytest.mark.parametrize("url, authority", [
    ("https://www.gov.uk/guidance/vat", "official"), ("https://www.irs.gov/x", "official"),
    ("https://cbic-gst.gov.in/x", "official"), ("https://www.ifrs.org/issued-standards", "official"),
    ("https://ec.europa.eu/taxation", "official"), ("https://www.icaew.com/technical", "professional"),
    ("https://www.investopedia.com/vat", "web"), (None, "web"),
])
def test_sources_are_classed_by_who_can_state_the_rule(url, authority):
    assert source_authority(url) == authority


@pytest.mark.parametrize("source, authority", [
    (WebSource(title="Upload", url="", snippet="", provider="uploaded_document"), "document"),
    (WebSource(title="10-K", url="https://www.sec.gov/x", snippet="", provider="sec_edgar", freshness="filing"),
     "official"),
    (WebSource(title="ECB", url="https://api.frankfurter.app", snippet="", provider="frankfurter", freshness="daily"),
     "data"),
    (WebSource(title="Blog", url="https://www.example.com/vat", snippet=""), "web"),
])
def test_every_kind_of_retrieved_source_gets_an_authority(source, authority):
    assert service.source_provenance(source)["authority"] == authority


def test_a_registered_source_keeps_its_registration():
    summary = SourceSummary(id="src", version_id="ver-1", title="VAT Notice 700", category="tax",
                            jurisdiction_scope="United Kingdom", version_label="v3", status="ACTIVE",
                            authority_level="primary", effective_from=date(2024, 4, 1))
    assert service.registered_provenance(summary) == {
        "authority": "official", "jurisdiction": "UK", "effective_from": date(2024, 4, 1), "effective_to": None,
        "source_version_id": "ver-1"}


# ── Wrong jurisdiction ───────────────────────────────────────────────────

def test_a_source_for_another_jurisdiction_is_found():
    found = evidence_findings("A business must register within 30 days of becoming liable [REF-4].",
                              question="When must a UK business register for VAT?",
                              evidence_by_ref=EVIDENCE, citations=CITATIONS)
    assert [f.code for f in found] == ["jurisdiction_mismatch"]
    assert found[0].message == "a source for India is cited for a statement about UK"


def test_a_statement_naming_the_sources_own_jurisdiction_is_a_comparison():
    assert codes("In India, a supplier must register within 30 days [REF-4].", "Compare UK and India registration") \
        == []


def test_registered_jurisdictions_reach_the_release_check():
    assert "found := citation.jurisdiction or source_jurisdiction(citation.url)" in inspect.getsource(service)


# ── Outdated sources ─────────────────────────────────────────────────────

def test_a_version_no_longer_in_force_is_found():
    found = evidence_findings("The VAT registration threshold is £85,000 [REF-2].",
                              question="What is the UK VAT registration threshold?",
                              evidence_by_ref=EVIDENCE, citations=CITATIONS)
    assert "outside_effective_period" in [f.code for f in found]


def test_a_version_in_force_for_the_period_asked_about_passes():
    assert "outside_effective_period" not in codes("The VAT registration threshold was £85,000 [REF-2].",
                                                   "What was the UK VAT registration threshold in 2015?")


def test_a_source_that_says_it_was_withdrawn_is_found():
    evidence = {**EVIDENCE, "REF-1": "This guidance was withdrawn on 1 May 2024. The standard rate of VAT is 20%."}
    assert codes("The standard rate of VAT is 20% [REF-1].", "UK VAT rate?", evidence_by_ref=evidence) \
        == ["withdrawn_source"]


# ── Conflicting sources ──────────────────────────────────────────────────

def test_cited_sources_that_disagree_are_found():
    found = evidence_findings("The standard rate of VAT is 20% [REF-1][REF-3].", question="UK VAT rate?",
                              evidence_by_ref=EVIDENCE, citations=CITATIONS)
    assert "conflicting_sources" in [f.code for f in found]
    assert any("REF-3 states a different figure" in f.message for f in found)


def test_an_answer_giving_one_figure_two_values_is_found():
    answer = "The standard rate of VAT is 20% [REF-1].\n\nThe standard rate of VAT is 17.5% [REF-3]."
    assert "conflicting_sources" in codes(answer, "UK VAT rate?")


def test_a_dated_history_is_not_a_conflict():
    evidence = {**EVIDENCE, "REF-3": "The standard rate of VAT was 17.5% until 2011."}
    assert "conflicting_sources" not in codes("The standard rate of VAT is 20% [REF-1][REF-3].", "UK VAT rate?",
                                              evidence_by_ref=evidence)


def test_a_registered_conflict_between_versions_is_found():
    assert "conflicting_sources" in codes("The VAT registration threshold was £85,000 [REF-2].",
                                          "UK VAT threshold in 2015?", conflict_version_ids=["ver-old", "ver-new"])


# ── Missing evidence keeps its disclosure ────────────────────────────────

def test_an_uncited_statement_is_left_to_the_general_explanation_label():
    assert codes("The standard rate of VAT is 20%.", "UK VAT rate?") == []
    assert "statements without one are general explanation" in service.MIXED_SOURCES_NOTE


async def test_a_strict_answer_with_no_evidence_is_not_released():
    check = await verify_for_release("The UK VAT registration threshold is £90,000 [REF-1].",
                                     question="What is the UK VAT registration threshold?", evidence=[],
                                     requires_authority=True)
    assert not check.passed and "Required authoritative evidence is unavailable" in check.failures


# ── Disclosed and audited, never rewritten ───────────────────────────────

def test_the_note_names_what_to_review():
    findings = evidence_findings("The VAT registration threshold is £85,000 [REF-2].",
                                 question="What is the UK VAT registration threshold?",
                                 evidence_by_ref=EVIDENCE, citations=CITATIONS)
    [note] = evidence_notes(findings)
    assert note.startswith(f"{EVIDENCE_NOTE_PREFIX}: a cited source version was not in force")
    assert note.endswith("Have these statements reviewed before relying on them.")
    web_only = evidence_findings("The standard rate of VAT is 17.5% [REF-3].", question="UK VAT rate?",
                                 evidence_by_ref=EVIDENCE, citations=CITATIONS)
    assert evidence_notes(web_only) == [
        f"{AUTHORITY_NOTE_PREFIX}: a UK tax or accounting rule is supported only by web sources, not by the "
        "official guidance or standard. Check the rule against the official source for its jurisdiction."]
    assert evidence_notes([]) == []


def test_every_answer_with_citations_is_checked_and_audited_not_rewritten():
    source = inspect.getsource(service.ask_kriton)
    start = source.index("evidence_review = evidence_findings(")
    end = source.index("response.answer = response.answer.model_copy(update={'completeness': 'partial'})")
    assert "'limitations': [*response.answer.limitations, *notes]" in source[start:end]
    assert "'text':" not in source[start:end]
    assert "sources=citation_provenance_entries(response.answer.citations)" in source
    # The checks run before the status and the report gate, so neither can call it complete.
    assert end < source.index('completeness = ("none" if response.outcome in') < source.index(
        "if unfinished or response.answer is None or response.answer.completeness != 'complete':")


def test_the_audit_keeps_provenance_and_findings_without_answer_text():
    sources = service.citation_provenance_entries([OLD_NOTICE, HMRC])
    assert sources[0] == {"ref": "REF-2", "source_id": "s2", "source_version_id": "ver-old", "authority": "official",
                          "jurisdiction": "UK", "effective_from": "2011-01-04", "effective_to": "2017-03-31",
                          "host": None, "provider": None}
    assert sources[1]["host"] == "www.gov.uk"
    findings = evidence_findings("The VAT registration threshold is £85,000 [REF-2].",
                                 question="What is the UK VAT registration threshold?",
                                 evidence_by_ref=EVIDENCE, citations=CITATIONS)
    entries = service.evidence_finding_entries(findings)
    assert entries[0]["code"] == "outside_effective_period" and entries[0]["review"] is True
    assert entries[0]["review_type"] == "evidence"
    assert set(entries[0]) == {"code", "refs", "review", "review_type", "statement_hash", "excerpt"}
    assert "[REF-" not in entries[0]["excerpt"]


async def test_the_audit_event(monkeypatch):
    emitted = []

    async def emit(db, name, *args, **kwargs):
        emitted.append((name, args[-1], kwargs))
    monkeypatch.setattr(audit_events, "_emit", emit)
    await audit_events.audit_evidence_validation_completed(
        None, query_id="q", correlation_id="c", tenant_id="t", audit_chain_id="a", actor_id="u",
        sources=[{"ref": "REF-1"}], findings=[{"code": "withdrawn_source", "review": True}])
    name, payload, kwargs = emitted[0]
    assert name == "evidence_validation_completed" and payload["review_recommended"] is True
    assert kwargs["replay_relevance"] == "REQUIRED"


# ── Through the real pipeline: the status and the audit follow the findings ─

from tests.test_answer_status_pipeline import page_status, pipeline  # noqa: E402,F401
from app.domains.model_gateway.agent import AgentOutcome  # noqa: E402

QUESTION = "Why did our supplier raise prices?"
ONS = WebSource(title="Producer prices", url="https://www.ons.gov.uk/ppi", snippet="Input prices rose 3.2% in the year.",
                provider="ONS", freshness="")
TRADE = WebSource(title="Trade press", url="https://www.example-trade.com/prices",
                  snippet="Many suppliers raised list prices 4% this year.")


def _evidence_call():
    calls = service.audit_evidence_validation_completed.await_args_list
    return calls[-1].kwargs if calls else None


async def test_a_figure_its_cited_source_does_not_state_is_not_shown_as_fully_answered(pipeline):
    pipeline.answers(AgentOutcome(text="Many suppliers raised prices by 4% this year [REF-1].", sources=[ONS, TRADE]))
    response, audited = await pipeline.ask(QUESTION)
    assert response.outcome == "answered"
    assert any(item.startswith("Evidence check: 4% is not stated in the source cited for it (another retrieved "
                               "source states it)") for item in response.answer.limitations)
    assert page_status(response) == "Partially answered" and audited.completeness == "partial"
    recorded = _evidence_call()
    assert [f["code"] for f in recorded["findings"]] == ["figure_not_in_cited_source"]
    assert recorded["sources"][0]["authority"] == "official" and recorded["sources"][0]["host"] == "www.ons.gov.uk"
    assert "4% this year" in response.answer.text                      # disclosed, not rewritten


async def test_a_supported_citation_stays_fully_answered_and_is_audited(pipeline):
    pipeline.answers(AgentOutcome(text="Input prices rose 3.2% in the year [REF-1].", sources=[ONS]))
    response, audited = await pipeline.ask(QUESTION)
    assert not any(item.startswith(("Evidence check", "Source-authority review")) for item in response.answer.limitations)
    assert page_status(response) == "Answered" and audited.completeness == "complete"
    assert _evidence_call()["findings"] == [] and _evidence_call()["sources"][0]["ref"] == "REF-1"


async def test_a_rule_from_a_web_source_asks_for_authority_review_without_marking_it_wrong(pipeline):
    blog = WebSource(title="Tax blog", url="https://www.example-tax-blog.com/vat",
                     snippet="Businesses must register for VAT when taxable turnover passes the threshold.")
    pipeline.answers(AgentOutcome(
        text="A supplier must register for VAT when its taxable turnover passes the threshold [REF-1].",
        sources=[blog]))
    response, audited = await pipeline.ask(QUESTION)
    assert any(item.startswith("Source-authority review: a ") and "supported only by web sources" in item
               for item in response.answer.limitations)
    assert page_status(response) == "Answered" and audited.completeness == "complete"
    finding = _evidence_call()["findings"][0]
    assert finding["code"] == "no_authoritative_source" and finding["review_type"] == "source_authority"


# ── Legacy compatibility ─────────────────────────────────────────────────

def test_a_citation_saved_before_provenance_still_loads():
    old = {"ref_id": "REF-1", "source_id": "s1", "title": "VAT rates", "url": "https://www.gov.uk/x",
           "evidence_preview": "The standard rate…", "provider": None, "fetched_at": None, "freshness": None}
    citation = SourceCitation.model_validate(old)
    assert citation.authority is None and citation.effective_from is None
    assert codes("The standard rate of VAT is 20% [REF-1].", "UK VAT rate?", citations=[citation]) == []

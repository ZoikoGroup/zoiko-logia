"""Synthetic Austria scope/period/citation regressions, never live accuracy."""
from datetime import date
import pytest
from app.domains.source_library.models import SourceVersion
from app.orchestration.source_taxonomy import detect_jurisdictions
from app.orchestration.retrieve import build_source_bundle,explicit_jurisdictions
from app.orchestration.governed_retrieval import retrieve_governed_evidence
from tests.test_phase1_source_controls import store,proposal  # noqa: F401


@pytest.fixture(autouse=True)
def _source_review_enforced(monkeypatch):
    # Undated versions are refused for a dated question only in strict mode.
    monkeypatch.setenv("KRITON_SOURCE_REVIEW_ENFORCEMENT", "true")


@pytest.mark.parametrize("name", ["Austria","Austrian","Österreich","österreichische","Autriche"])
def test_explicit_austria_aliases_agree_across_detection_paths(name):
    query=f"VAT rate guidance in {name} in 2024"
    assert detect_jurisdictions(query,infer_from_tax_terms=False)==["AUSTRIA"]
    assert explicit_jurisdictions(query)==["Austria"]


def test_language_alone_does_not_choose_a_country():
    assert detect_jurisdictions("Bitte erklären Sie die Umsatzsteuer",infer_from_tax_terms=False)==[]
    assert detect_jurisdictions("Expliquez la TVA",infer_from_tax_terms=False)==[]
    assert detect_jurisdictions("VAT rate guidance in Germany",infer_from_tax_terms=False)==["GERMANY"]
    assert detect_jurisdictions("VAT rate guidance in France",infer_from_tax_terms=False)==["FRANCE"]


@pytest.mark.parametrize("name", ["Austria","Österreich","Autriche"])
async def test_austria_reference_cannot_be_overridden_by_uk_filter(store,name):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    bundle=await build_source_bundle(store,query=f"VAT rate guidance in {name} in 2024",jurisdiction="United Kingdom",tenant_id="t")
    assert bundle.clarification_required and not bundle.sources and not bundle.passages


@pytest.mark.parametrize("name", ["Austria","Österreich","Autriche"])
async def test_historical_austria_evidence_and_prompt_labels_agree(store,name):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    await proposal(store,"at-old",source_id="at",country="Austria",end=date(2024,12,31),status="SUPERSEDED")
    await proposal(store,"at-new",source_id="at",country="Austria",start=date(2025,1,1),status="APPROVED")
    (await store.get(SourceVersion,"at-old")).superseded_by_version_id="at-new"
    await store.commit()
    bundle,texts=await retrieve_governed_evidence(store,query=f"VAT rate guidance in {name} in 2024",jurisdiction="Any",tenant_id="t",query_id="at-historical")
    assert not bundle.clarification_required
    assert {s.version_id for s in bundle.sources}=={"at-old"}
    assert bundle.jurisdiction=="Austria"
    assert {(s.jurisdiction_scope,s.evidence_jurisdiction,s.evidence_period_start,s.evidence_period_end) for s in bundle.sources}=={("Austria","Austria",date(2024,1,1),date(2024,12,31))}
    from app.orchestration.service import registered_provenance
    provenance=registered_provenance(bundle.sources[0])
    assert provenance["jurisdiction"]=="AUSTRIA"
    assert provenance["source_version_id"]=="at-old"
    assert provenance["effective_from"]==date(2020,1,1)
    assert provenance["effective_to"]==date(2024,12,31)
    assert len(texts)==1
    assert "[Jurisdiction: Austria]" in texts[0][2]
    assert "[Applicable period: 2024-01-01 to 2024-12-31]" in texts[0][2]


async def test_conflicting_country_references_require_separate_applicable_evidence(store):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    bundle=await build_source_bundle(store,query="Compare UK and Austria VAT rate guidance in 2024",jurisdiction="Any",tenant_id="t")
    assert bundle.clarification_required and not bundle.passages
    assert "Austria" in bundle.clarification_required


async def test_missing_austria_dates_do_not_use_uk_or_current_rule(store):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    await proposal(store,"at",source_id="at",country="Austria",start=None,status="APPROVED")
    bundle=await build_source_bundle(store,query="VAT rate guidance in Austria in 2024",jurisdiction="Any",tenant_id="t")
    assert bundle.clarification_required and not bundle.passages


from tests.offline_http_support import offline_http  # noqa: E402,F401


@pytest.mark.parametrize("name", ["Austria", "Österreich", "Autriche", None])
async def test_api_does_not_display_unverified_citations_or_wrong_country_suggestions(offline_http,name):
    import hashlib,json,os
    from pathlib import Path
    from app.domains.identity.models import User
    from app.domains.source_library.models import Source,SourcePassage,SourceRight
    from tests.test_agent_loop import _reply
    content="VAT rate guidance and VAT registration threshold rules."
    async with offline_http.sessions() as db:
        db.add(User(id="at-reviewer",tenant_id="synthetic-a",email="reviewer@example.test",full_name="Synthetic reviewer",role="Admin"))
        await db.flush()
        for sid,country in [("at","Austria"),("uk","United Kingdom")]:
            db.add(Source(id=sid,tenant_id="synthetic-a",category="tax",title="VAT rate guidance",publisher="Synthetic test authority",source_class="official_guidance",jurisdiction_scope=country,framework_scope="",authority_level="primary",is_tenant_private=True))
        await db.flush()
        for vid,sid,start,end,status,successor in [
            ("at-old","at",date(2020,1,1),date(2024,12,31),"SUPERSEDED","at-new"),
            ("at-new","at",date(2025,1,1),None,"APPROVED",None),
            ("uk-current","uk",date(2020,1,1),None,"APPROVED",None),
        ]:
            db.add(SourceVersion(id=vid,source_id=sid,tenant_id="synthetic-a",status=status,submitted_by="actor-a",approved_by="at-reviewer",effective_from=start,effective_to=end,content_hash=hashlib.sha256(vid.encode()).hexdigest(),source_url=f"https://example.test/{vid}",superseded_by_version_id=successor))
            await db.flush()
            db.add(SourcePassage(id="p-"+vid,source_version_id=vid,tenant_id="synthetic-a",locator="Section 1",sequence=1,content=content,content_hash=hashlib.sha256(content.encode()).hexdigest(),procedure="general"))
            for op in ("retrieval","model_transmission","display"):
                db.add(SourceRight(tenant_id="synthetic-a",source_version_id=vid,operation=op,decision="allow",rights_version=1))
        await db.commit()
    offline_http.state.responses=[_reply("VAT rate guidance and VAT registration threshold rules. [REF-1]")]
    response=await offline_http.client.post("/api/v1/orchestration/ask",json={"query":(f"VAT rate guidance in {name} in 2024" if name else "VAT rate guidance in 2024"),"jurisdiction":"Any" if name else "Austria","conversation_id":"at-citation-"+str(name)},headers={"Authorization":"Bearer offline-actor-a","Idempotency-Key":"at-citation-"+hashlib.sha256(str(name).encode()).hexdigest()[:12]})
    assert response.status_code==200,response.text
    body=response.json()
    if folder:=os.getenv("PHASE1_EVIDENCE_DIR"):
        out=Path(folder);out.mkdir(parents=True,exist_ok=True)
        (out/("api-at-"+str(name)+".json")).write_text(json.dumps(body,indent=2))
    assert {s["version_id"] for s in body["source_bundle"]["sources"]}=={"at-old"}
    answer=body["answer"]
    assert answer is not None,body
    # The offline fixture disables claim verification. A citation wiring test
    # must not turn that into a passing factual-verification judgment.
    assert not answer["citations"]
    assert answer["completeness"]=="none"
    assert answer["verification"]["overall"]=="not_verified"
    assert not any("HMRC" in item for item in answer["limitations"])


@pytest.mark.parametrize("query,excluded", [
    ("VAT rate in Austria in 2024", "HMRC"),
    ("VAT rate in Österreich in 2024", "HMRC"),
    ("VAT rate in Autriche in 2024", "HMRC"),
    ("GST rules in Australia", "CBIC"),
])
def test_source_suggestions_do_not_substitute_a_different_country(query,excluded):
    from app.orchestration.source_guarantee import official_sources_note
    note=official_sources_note(query)
    assert excluded not in note
    assert "suggestions, not evidence" in note


def test_explicit_uk_and_india_keep_their_own_source_suggestions():
    from app.orchestration.source_guarantee import official_sources_note
    assert "HMRC" in official_sources_note("UK VAT rules")
    assert "CBIC" in official_sources_note("India GST rules")


@pytest.mark.parametrize("query,jurisdiction", [
    ("VAT rate guidance", "Austria"),
    ("VAT rate guidance in Austria", "United Kingdom"),
    ("VAT rate guidance", "Unknown jurisdiction"),
])
def test_explicit_or_conflicting_selector_cannot_default_to_uk_suggestions(query,jurisdiction):
    from app.orchestration.source_guarantee import official_sources_note
    assert "HMRC" not in official_sources_note(query,jurisdiction=jurisdiction)


async def test_financial_year_boundaries_are_not_inferred_for_austria(store):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    bundle=await build_source_bundle(store,query="Austria VAT rate guidance for FY 2024-25",jurisdiction="Any",tenant_id="t")
    assert bundle.clarification_required and not bundle.passages
    assert "start and end dates" in bundle.clarification_required


async def test_austria_uk_comparison_keeps_separate_evidence_labels(store):
    await proposal(store,"uk",source_id="uk",status="APPROVED")
    await proposal(store,"at",source_id="at",country="Austria",status="APPROVED")
    bundle,texts=await retrieve_governed_evidence(store,query="Compare UK and Autriche VAT rate guidance in 2024",jurisdiction="Any",tenant_id="t",query_id="at-uk-comparison")
    assert not bundle.clarification_required
    assert {(s.version_id,s.evidence_jurisdiction) for s in bundle.sources}=={("uk","United Kingdom"),("at","Austria")}
    assert len(texts)==2
    assert any("[Jurisdiction: Austria]" in text for _,_,text in texts)
    assert any("[Jurisdiction: United Kingdom]" in text for _,_,text in texts)
    assert all("2024-01-01 to 2024-12-31" in text for _,_,text in texts)


@pytest.mark.parametrize("period,versions", [
    ("in 2026", {"at-new"}),
    ("from 2024-04-01 to 2025-03-31", {"at-old","at-new"}),
])
async def test_austria_current_and_spanning_periods_are_selected_separately(store,period,versions):
    await proposal(store,"at-old",source_id="at",country="Austria",end=date(2024,12,31),status="SUPERSEDED")
    await proposal(store,"at-new",source_id="at",country="Austria",start=date(2025,1,1),status="APPROVED")
    (await store.get(SourceVersion,"at-old")).superseded_by_version_id="at-new"
    await store.commit()
    bundle,texts=await retrieve_governed_evidence(store,query="VAT rate guidance in Österreich "+period,jurisdiction="Any",tenant_id="t",query_id="at-period")
    assert not bundle.clarification_required
    assert {s.version_id for s in bundle.sources}==versions
    assert all(s.evidence_jurisdiction==s.jurisdiction_scope=="Austria" for s in bundle.sources)
    if len(versions)==2:
        assert {(s.evidence_period_start,s.evidence_period_end) for s in bundle.sources}=={(date(2024,4,1),date(2024,12,31)),(date(2025,1,1),date(2025,3,31))}

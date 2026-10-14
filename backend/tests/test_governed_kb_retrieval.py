"""Phase 1 governed knowledge base: procedure filtering, category routing and
hybrid (keyword + semantic) fusion in retrieve.build_source_bundle."""
import hashlib

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.source_library.models import Source, SourcePassage, SourceRight, SourceVersion
from app.orchestration import retrieve
from app.orchestration.procedures import is_other_procedure, procedures_named
from app.orchestration.retrieve import build_source_bundle, infer_category, infer_jurisdiction


@pytest.fixture
async def kb():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _vat_source(db, title: str, passages: list[tuple[str, str, str]]):
    """passages: (heading, procedure, content)."""
    source = Source(
        tenant_id="GLOBAL_CONTROL", category="tax", title=title, publisher="HM Revenue & Customs",
        owner="HM Revenue & Customs", source_class="official_guidance",
        jurisdiction_scope="UK,GB,United Kingdom", authority_level="primary",
    )
    db.add(source)
    await db.flush()
    version = SourceVersion(
        tenant_id="GLOBAL_CONTROL", source_id=source.id, version_label="2026-10-01", status="APPROVED",
        content_hash=hashlib.sha256(title.encode()).hexdigest(), submitted_by="ingest", approved_by="ingest",
    )
    db.add(version)
    await db.flush()
    rows = []
    for sequence, (heading, procedure, content) in enumerate(passages, start=1):
        row = SourcePassage(
            tenant_id="GLOBAL_CONTROL", source_version_id=version.id, locator=f"{title}#{sequence}",
            sequence=sequence, heading=heading, procedure=procedure, content=f"{heading}\n{content}",
            content_hash=hashlib.sha256(f"{title}{sequence}".encode()).hexdigest(),
        )
        db.add(row)
        rows.append(row)
    for operation in ("retrieval", "model_transmission", "display", "summary"):
        db.add(SourceRight(
            tenant_id="GLOBAL_CONTROL", source_version_id=version.id, operation=operation,
            decision="allow", rights_version=1, reason_code="OGL_V3",
        ))
    await db.flush()
    return rows


def test_vat_questions_reach_the_tax_category():
    # "Who can sign off a VAT return?" names no "tax" and used to fall to the
    # default "standards" category, never reaching any VAT source.
    assert infer_category("Who can sign off a VAT return in the UK?") == "tax"
    assert infer_category("What is the GST rate on restaurant services?") == "tax"
    assert infer_category("Explain IFRS 16 lease accounting") == "standards"


def test_procedure_tags():
    assert procedures_named("How do I claim a VAT refund as a non-UK business?") == {"refund"}
    assert is_other_procedure("refund", "Who can submit a VAT return?")
    assert not is_other_procedure("refund", "How do I claim a VAT refund?")
    assert not is_other_procedure("general", "Who can submit a VAT return?")


async def test_passage_about_another_procedure_is_filtered_not_outranked(kb):
    [mtd] = await _vat_source(kb, "VAT Notice 700/22", [
        ("3. Agents", "general", "Your agent can submit VAT returns for you once authorised."),
    ])
    [refund] = await _vat_source(kb, "VAT Notice 723A", [
        ("4. Signing the claim", "refund",
         "The VAT refund claim must be signed by the claimant or an agent with a power of attorney. "
         "Who can submit the claim: the claimant or an agent."),
    ])
    bundle = await build_source_bundle(
        kb, query="Who can submit a VAT return?", jurisdiction="", tenant_id="tenant-x",
    )
    selected = [passage.passage_id for passage in bundle.passages]
    assert mtd.id in selected and refund.id not in selected

    refund_question = await build_source_bundle(
        kb, query="Who can submit a VAT refund claim?", jurisdiction="", tenant_id="tenant-x",
    )
    assert refund.id in [passage.passage_id for passage in refund_question.passages]


async def test_unmatched_passages_are_not_written_as_exclusions(kb):
    # One excluded-evidence row per non-matching passage per question grows
    # with the library; relevance is not a rights decision.
    await _vat_source(kb, "VAT Notice 700", [(f"Section {i}", "general", f"Unrelated topic {i}.") for i in range(50)])
    bundle = await build_source_bundle(kb, query="VAT registration threshold", jurisdiction="", tenant_id="t")
    assert not any(item.reason_code == "NO_LEXICAL_MATCH" for item in bundle.excluded_evidence)


async def test_semantic_matches_fuse_with_keyword_matches(kb, monkeypatch):
    keyword, semantic_only, unrelated = await _vat_source(kb, "VAT guide", [
        ("Registration", "general", "You must register for VAT when turnover goes over the threshold."),
        ("Signing up", "general", "Businesses join once sales pass the limit set by HMRC."),
        ("Records", "general", "Keep invoices for six years."),
    ])

    async def fake_semantic(db, query, version_ids):
        return {semantic_only.id: 0.81, keyword.id: 0.79, unrelated.id: 0.60}

    monkeypatch.setattr(retrieve, "_semantic_scores", fake_semantic)
    bundle = await build_source_bundle(kb, query="When must I register for VAT?", jurisdiction="", tenant_id="t")
    methods = {passage.passage_id: passage.method for passage in bundle.passages}
    assert methods[keyword.id] == "hybrid"
    assert methods[semantic_only.id] == "vector"  # found by meaning alone, above the threshold
    assert unrelated.id not in methods  # below the semantic-only threshold, no keyword
    assert bundle.passages[0].passage_id == keyword.id  # agreed on by both rankings
    assert bundle.retrieval_plan.strategy == "rights_filtered_hybrid_passages"


async def test_one_long_document_cannot_fill_every_evidence_slot(kb):
    # Notice 723A (non-UK refunds) took six of eight slots and crowded out the
    # page naming form VAT126 for UK organisations not registered for VAT.
    await _vat_source(kb, "VAT Notice 723A", [
        (f"2.{i} Refund claims", "refund", f"VAT refund claim form rules for non-UK businesses, part {i}.")
        for i in range(10)
    ])
    [vat126] = await _vat_source(kb, "Claim a VAT refund as an organisation not registered for VAT", [
        ("Make a claim", "refund", "Fill in form VAT126 to claim a VAT refund as an organisation not registered for VAT."),
    ])
    bundle = await build_source_bundle(kb, query="Which form claims a VAT refund?", jurisdiction="", tenant_id="t")
    # The other qualifying document gets a slot; the slots nothing else can
    # use then go back to the long notice rather than staying empty.
    assert vat126.id in [passage.passage_id for passage in bundle.passages]
    assert len(bundle.passages) == 8


def test_refund_evidence_is_filtered_by_who_is_claiming():
    # Regression baseline: a non-UK business's refund answer offered form
    # VAT126, which is for UK organisations not registered for VAT.
    non_uk = "How do I claim a VAT refund as a non-UK business?"
    unregistered = "Which form does a UK charity that is not registered for VAT use to claim a VAT refund?"
    assert not is_other_procedure("refund:non_uk", non_uk)
    assert is_other_procedure("refund:unregistered_org", non_uk)
    assert not is_other_procedure("refund:unregistered_org", unregistered)
    assert is_other_procedure("refund:non_uk", unregistered)
    # Naming no claimant keeps every refund scheme in play.
    assert not is_other_procedure("refund:non_uk", "Which form claims a VAT refund?")
    assert not is_other_procedure("refund:unregistered_org", "Which form claims a VAT refund?")


@pytest.mark.parametrize("query, expected", [
    ("What is the UK VAT registration threshold?", "United Kingdom"),
    ("Do I need special software to file VAT returns?", "United Kingdom"),  # VAT alone: the UK corpus
    ("What GST rate applies to hotel rooms costing up to Rs 7,500?", "India"),  # GST alone: the India corpus
    ("What is the GST rate in Australia?", "Australia"),
    ("What is the VAT rate in the UAE?", "Uae"),  # neither corpus, not the UK
    ("Compare VAT in the UK with GST in India", ""),  # several: no narrowing
    ("Explain IFRS 16 lease accounting in brief.", ""),  # "in" is not India
])
def test_jurisdiction_is_inferred_from_the_question(query, expected):
    assert infer_jurisdiction(query) == expected


async def test_a_uk_question_never_gets_passages_from_indian_guidance(kb):
    [uk] = await _vat_source(kb, "VAT rates", [("Hotels", "general", "Hotel accommodation is standard-rated for VAT at 20%.")])
    india_source = Source(
        tenant_id="GLOBAL_CONTROL", category="tax", title="GST rate FAQs", publisher="GST Council Secretariat",
        owner="GST Council Secretariat", source_class="official_guidance", jurisdiction_scope="India,IN",
        authority_level="primary",
    )
    kb.add(india_source)
    await kb.flush()
    version = SourceVersion(
        tenant_id="GLOBAL_CONTROL", source_id=india_source.id, version_label="2025-09", status="APPROVED",
        content_hash="gst", submitted_by="ingest", approved_by="ingest",
    )
    kb.add(version)
    await kb.flush()
    gst = SourcePassage(
        tenant_id="GLOBAL_CONTROL", source_version_id=version.id, locator="faq#q71", sequence=1,
        content="Hotel accommodation up to Rs 7500 attracts GST rate of 5% without ITC.", content_hash="q71",
    )
    kb.add(gst)
    for operation in ("retrieval", "model_transmission", "display", "summary"):
        kb.add(SourceRight(tenant_id="GLOBAL_CONTROL", source_version_id=version.id, operation=operation,
                           decision="allow", rights_version=1, reason_code="IN_GOV_PUBLICATION"))
    await kb.flush()

    uk_bundle = await build_source_bundle(kb, query="What VAT rate applies to hotel accommodation?", jurisdiction="", tenant_id="t")
    assert [p.passage_id for p in uk_bundle.passages] == [uk.id]
    india_bundle = await build_source_bundle(kb, query="What GST rate applies to hotel accommodation?", jurisdiction="", tenant_id="t")
    assert [p.passage_id for p in india_bundle.passages] == [gst.id]


async def test_capped_slots_go_back_to_the_document_when_nothing_else_qualifies(kb):
    # Only Notice 723A answered "which form for a non-UK refund?": the cap left
    # 3 passages instead of 8 and dropped the one naming VAT65A.
    rows = await _vat_source(kb, "VAT Notice 723A", [
        (f"2.{i} Refund claims", "refund:non_uk", f"Non-UK business VAT refund claim, form rules part {i}.") for i in range(6)
    ])
    bundle = await build_source_bundle(kb, query="Which form claims a VAT refund for a non-UK business?", jurisdiction="", tenant_id="t")
    assert len(bundle.passages) == 6
    assert {p.passage_id for p in bundle.passages} == {r.id for r in rows}


def test_numbers_are_normalised_for_keyword_matching():
    from app.orchestration.retrieve import _tokens
    # "56th" in the question vs "56" in the FAQ cost the passage that states
    # the 22nd September 2025 effective date its keyword match.
    assert {"56", "7500", "22", "100000"} <= _tokens("the 56th meeting, Rs 7,500, 22nd September, ₹1,00,000")
    assert "2025" in _tokens("September, 2025")   # a comma before a year is not a thousands separator


async def test_a_source_that_may_not_be_sent_to_a_model_never_takes_a_result_slot(kb):
    """ZL-ENG-AGT-01 §06.2: rights are applied before any text is searched.
    A version cleared for retrieval but not for model transmission is
    excluded up front, not dropped by the licence gate after ranking."""
    [usable] = await _vat_source(kb, "VAT Notice 700/1", [
        ("Registration", "general", "You must register for VAT when taxable turnover exceeds £90,000."),
    ])
    [blocked] = await _vat_source(kb, "Commercial VAT handbook", [
        ("Registration", "general", "You must register for VAT when taxable turnover exceeds £90,000."),
    ])
    from sqlalchemy import select, update
    blocked_version = (await kb.execute(select(SourcePassage.source_version_id).where(SourcePassage.id == blocked.id))).scalar()
    await kb.execute(update(SourceRight).where(
        SourceRight.source_version_id == blocked_version, SourceRight.operation == "model_transmission",
    ).values(decision="deny", reason_code="LICENCE_NO_AI_USE"))
    await kb.flush()
    bundle = await build_source_bundle(kb, query="When must I register for VAT?", jurisdiction="", tenant_id="t")
    selected = [passage.passage_id for passage in bundle.passages]
    assert usable.id in selected and blocked.id not in selected
    assert any(item.source_version_id == blocked_version for item in bundle.excluded_evidence)


async def test_conflicting_sources_are_flagged_and_routed_to_human_review(kb):
    """§06.5 / Demo B: two applicable sources recorded as conflicting are not
    blended — the bundle is marked conflicting and the route is human review."""
    from sqlalchemy import select
    from app.domains.source_library.models import SourceRelationship
    from app.orchestration.routing_matrix import CONF_CONFLICTING, ROUTE_HUMAN_REVIEW, resolve_route
    [first] = await _vat_source(kb, "VAT Notice 700/1 (2024)", [
        ("Registration", "general", "You must register for VAT when taxable turnover exceeds £90,000."),
    ])
    [second] = await _vat_source(kb, "VAT guidance draft", [
        ("Registration", "general", "You must register for VAT when taxable turnover exceeds £85,000."),
    ])
    version_of = {p.id: (await kb.execute(select(SourcePassage.source_version_id).where(SourcePassage.id == p.id))).scalar()
                  for p in (first, second)}
    kb.add(SourceRelationship(tenant_id="GLOBAL_CONTROL", from_version_id=version_of[first.id],
                              to_version_id=version_of[second.id], relationship_type="conflicts"))
    await kb.flush()
    bundle = await build_source_bundle(kb, query="When must I register for VAT?", jurisdiction="", tenant_id="t")
    assert bundle.confidence_state == CONF_CONFLICTING
    assert set(bundle.conflict_version_ids) == set(version_of.values())
    assert resolve_route("LOW", bundle.confidence_state).route == ROUTE_HUMAN_REVIEW


def test_table_rows_keep_their_header_labels():
    """§06.3: a table row split from its table still says what each value is."""
    from app.orchestration.websearch import _html_to_text
    text = _html_to_text("<table><tr><th>Scheme</th><th>Leave above</th></tr>"
                         "<tr><td>Flat Rate</td><td>£230,000</td></tr></table>")
    assert text == "Scheme: Flat Rate; Leave above: £230,000"


async def test_an_undated_version_cannot_be_approved(kb):
    """§06.1: applicability dates are required before a version can be used."""
    import pytest
    from fastapi import HTTPException
    from app.domains.source_library.service import approve_source_version
    [passage] = await _vat_source(kb, "Undated guidance", [("A", "general", "Some text about VAT registration.")])
    version = await kb.get(SourceVersion, (await kb.execute(
        select_version_for(passage.id))).scalar())
    version.status, version.effective_from, version.approved_by = "PROPOSED", None, None
    await kb.flush()
    with pytest.raises(HTTPException) as raised:
        await approve_source_version(kb, approver_id="checker", source_id=version.source_id, version_id=version.id)
    assert raised.value.status_code == 409 and "effective-from" in raised.value.detail


def select_version_for(passage_id):
    from sqlalchemy import select
    return select(SourcePassage.source_version_id).where(SourcePassage.id == passage_id)

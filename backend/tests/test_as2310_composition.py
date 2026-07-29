from app.domains.massarius.answer_validator import validate_answer
from app.orchestration.schemas import SourceBundle, SourceSummary


def test_as2310_deterministic_answer_shape_is_citable():
    # The live path builds this exact structure once an official AS 2310
    # result is selected; keep a validator regression around its citation.
    answer = (
        "Under PCAOB AS 2310, the auditor designs and executes confirmations to obtain relevant "
        "and reliable evidence directly from knowledgeable external sources. [REF-1]"
    )
    bundle = SourceBundle(
        source_bundle_id="sb-test", retrieval_method="keyword_mvp",
        eligible_source_count=1, excluded_source_count=0,
        sources=[SourceSummary(id="src", title="PCAOB AS 2310", category="audit", jurisdiction_scope="US", version_label="current", status="ACTIVE")],
        jurisdiction="US", authority_level="primary", freshness_state="current",
        licence_state="permitted", confidence_state="sufficient",
    )
    assert validate_answer(answer, bundle).passed

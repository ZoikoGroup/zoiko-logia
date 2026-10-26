"""Document 03 acceptance tests (ZL-FSR-ENG-003 §13–14): framework and
effective-rule resolution (standards.py) and stored resolutions."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.financial_statements import resolutions, store
from app.domains.financial_statements.standards import EntityFacts, YearFigures, resolve, uk_size_class
from app.domains.identity.models import Tenant, User

UK = dict(incorporation_jurisdiction="GB-ENG", legal_form="private_limited")
NORTHBRIDGE_YEAR = YearFigures(Decimal("1850000"), Decimal("3200000"), 30)


def _facts(**kw) -> EntityFacts:
    base = dict(entity_name="Northbridge Trading Ltd", period_start=date(2025, 4, 1), period_end=date(2026, 3, 31), **UK)
    return EntityFacts(**(base | kw))


def _rule(res, rule_id):
    return next(r for r in res.rules if r.rule_id == rule_id)


def test_gbp_figures_alone_do_not_choose_a_framework():
    res = resolve(EntityFacts(period_start=date(2025, 4, 1), period_end=date(2026, 3, 31)))
    assert "UNKNOWN_ENTITY" in res.blockers and res.selected_framework is None and not res.permit_statutory_claim


def test_at01_thresholds_follow_the_period_start_not_the_year_end():
    big = YearFigures(Decimal("12000000"), Decimal("6000000"), 60)
    before = uk_size_class(_facts(current_year=big, prior_year=big))
    after = uk_size_class(_facts(period_start=date(2025, 5, 1), period_end=date(2026, 4, 30), current_year=big, prior_year=big))
    assert before[0] == "medium" and "before 6 April 2025" in before[1]
    assert after[0] == "small" and "on or after 6 April 2025" in after[1]


def test_at02_turnover_alone_does_not_prove_small_company_eligibility():
    size, reason = uk_size_class(_facts(current_year=YearFigures(turnover=Decimal("1850000"))))
    assert size == "UNKNOWN" and "all needed" in reason
    res = resolve(_facts(current_year=YearFigures(turnover=Decimal("1850000")), framework_election="FRS102_1A"))
    assert "ELIGIBILITY_UNPROVEN" in res.blockers


def test_at03_at04_frs102_periodic_review_by_period_start():
    april_2025 = resolve(_facts(framework_election="FRS102"))
    assert _rule(april_2025, "FRS102.PERIODIC_REVIEW_2024").outcome == "NOT_YET_EFFECTIVE"
    assert _rule(april_2025, "FRS102.SUPPLIER_FINANCE_DISCLOSURES").outcome == "APPLIES"
    jan_2026 = resolve(_facts(period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), framework_election="FRS102"))
    assert _rule(jan_2026, "FRS102.PERIODIC_REVIEW_2024").outcome == "APPLIES"
    early = resolve(_facts(framework_election="FRS102", early_adoption=("FRS102_PERIODIC_REVIEW",)))
    assert _rule(early, "FRS102.PERIODIC_REVIEW_2024").outcome == "APPLIES"


def test_at05_uk_adapted_formats_from_2027():
    res = resolve(_facts(period_start=date(2027, 1, 1), period_end=date(2027, 12, 31), framework_election="FRS102"))
    assert _rule(res, "UK.FORMATS").outcome == "FACTSHEET_12B"
    assert _rule(resolve(_facts(framework_election="FRS102")), "UK.FORMATS").outcome == "FACTSHEET_12A"


def test_at06_at07_ifrs18_only_from_2027_unless_adopted_early():
    ie = dict(incorporation_jurisdiction="IE", legal_form="private_limited", framework_election="IFRS")
    y2026 = resolve(_facts(period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), **ie))
    assert _rule(y2026, "IFRS18").outcome == "NOT_YET_EFFECTIVE" and _rule(y2026, "IAS1").outcome == "APPLIES"
    y2027 = resolve(_facts(period_start=date(2027, 1, 1), period_end=date(2027, 12, 31), **ie))
    assert _rule(y2027, "IFRS18").outcome == "APPLIES"
    early = resolve(_facts(period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), early_adoption=("IFRS18",), **ie))
    assert _rule(early, "IFRS18").outcome == "APPLIES"


def test_at08_ifrs19_needs_a_subsidiary_and_proven_eligibility():
    res = resolve(_facts(period_start=date(2027, 1, 1), period_end=date(2027, 12, 31), flags=("subsidiary",),
                         framework_election="IFRS"))
    assert _rule(res, "IFRS19").outcome == "ELIGIBLE_IF_PROVEN"
    assert not any(r.rule_id == "IFRS19" for r in resolve(_facts(framework_election="IFRS")).rules)


def test_at09_a_us_registrant_gets_us_gaap_not_uk_formats():
    res = resolve(EntityFacts(incorporation_jurisdiction="US-DE", legal_form="corporation", flags=("sec_registrant",),
                              period_start=date(2026, 1, 1), period_end=date(2026, 12, 31)))
    assert {c.framework for c in res.candidates} >= {"US_GAAP"} and "REGIME_NOT_VERIFIED" in res.blockers
    assert not any(r.rule_id == "UK.FORMATS" for r in res.rules)


def test_at10_interim_reports_use_ias34():
    res = resolve(_facts(report_type="interim", framework_election="IFRS"))
    assert any(r.rule_id == "IAS34" for r in res.rules)


def test_at11_a_charity_is_routed_to_a_sector_pack():
    res = resolve(_facts(flags=("charity",)))
    assert "REGIME_NOT_VERIFIED" in res.blockers and res.candidates[0].framework == "SECTOR_PACK"


def test_at12_frs105_without_size_evidence_stays_unproven_and_groups_cannot_use_it():
    assert "ELIGIBILITY_UNPROVEN" in resolve(_facts(framework_election="FRS105")).blockers
    micro = YearFigures(Decimal("300000"), Decimal("100000"), 3)
    group = resolve(_facts(scope="group", current_year=micro, prior_year=micro, framework_election="FRS105"))
    assert "FRAMEWORK_NOT_SELECTED" in group.blockers


def test_small_entity_statement_set_and_exclusions():
    small = resolve(_facts(current_year=NORTHBRIDGE_YEAR, prior_year=NORTHBRIDGE_YEAR, framework_election="FRS102_1A"))
    assert small.selected_framework == "FRS102_1A" and not small.blockers
    cash = next(s for s in small.statements if s["statement"] == "cash_flows")
    assert cash["requirement"] == "EXEMPT"
    listed = uk_size_class(_facts(flags=("listed",), current_year=NORTHBRIDGE_YEAR, prior_year=NORTHBRIDGE_YEAR))
    assert listed[0] == "medium_or_large" and "excluded" in listed[1]


def test_at23_an_educational_example_is_watermarked_only():
    res = resolve(_facts(report_type="educational"))
    assert res.selected_framework == "MANAGEMENT_BASIS" and res.permitted_exports == ["WATERMARKED_ILLUSTRATIVE"]


def test_an_unreviewed_rule_pack_never_permits_a_statutory_claim():
    clean = _facts(current_year=NORTHBRIDGE_YEAR, prior_year=NORTHBRIDGE_YEAR, framework_election="FRS102")
    assert not resolve(clean, approved=True).permit_statutory_claim
    asked = resolve(_facts(framework_election="FRS102", requested_claim="statutory_ready"))
    assert "REVIEW_APPROVAL_MISSING" in asked.blockers
    assert resolve(clean).rule_pack["status"] == "UNREVIEWED_TEST_PACK"


# ── stored resolutions ──────────────────────────────────────────────────────

PREPARER = User(id="prep", tenant_id="t1", email="p@x.com", full_name="P", role="Accountant")
REVIEWER = User(id="rev", tenant_id="t1", email="r@x.com", full_name="R", role="Controller")
OUTSIDER = User(id="out", tenant_id="t2", email="o@y.com", full_name="O", role="Admin")
FACTS = {"entity_name": "Northbridge Trading Ltd", "incorporation_jurisdiction": "GB-ENG", "legal_form": "private_limited",
         "period_start": "2025-04-01", "period_end": "2026-03-31", "framework_election": "FRS102_1A",
         "current_year": {"turnover": "1850000", "balance_sheet_total": "3200000", "employees": 30},
         "prior_year": {"turnover": "1700000", "balance_sheet_total": "3000000", "employees": 28}}


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id="t1", name="T"), Tenant(id="t2", name="O"),
                         *(User(id=u.id, tenant_id=u.tenant_id, email=u.email, full_name=u.full_name, role=u.role)
                           for u in (PREPARER, REVIEWER, OUTSIDER))])
        await session.commit()
        yield session
    await engine.dispose()


async def test_at24_the_same_facts_give_the_same_revision(db):
    first = await resolutions.create(db, PREPARER, FACTS)
    again = await resolutions.create(db, PREPARER, dict(FACTS))
    assert again["id"] == first["id"] and first["result"]["selected_framework"] == "FRS102_1A"


async def test_at22_approval_is_refused_with_blockers_or_by_the_preparer(db):
    blocked = await resolutions.create(db, PREPARER, {**FACTS, "framework_election": ""})
    with pytest.raises(store.Refused, match="blockers"):
        await resolutions.approve(db, REVIEWER, blocked["id"])
    clean = await resolutions.create(db, PREPARER, {**FACTS, "entity_name": "Other Ltd"})
    with pytest.raises(store.Refused, match="preparer"):
        await resolutions.approve(db, PREPARER, clean["id"])
    approved = await resolutions.approve(db, REVIEWER, clean["id"])
    assert approved["state"] == "FROZEN" and approved["result"]["permit_statutory_claim"] is False   # unreviewed pack


async def test_at13_a_changed_fact_invalidates_the_approved_revision(db):
    first = await resolutions.approve(db, REVIEWER, (await resolutions.create(db, PREPARER, FACTS))["id"])
    second = await resolutions.create(db, PREPARER, {**FACTS, "framework_election": "FRS102"})
    assert second["revision"] == 2 and (await resolutions.get(db, PREPARER, first["id"]))["state"] == "INVALIDATED"
    with pytest.raises(store.Refused, match="replaced"):
        await resolutions.approve(db, REVIEWER, first["id"])


async def test_another_tenant_cannot_read_a_resolution(db):
    row = await resolutions.create(db, PREPARER, FACTS)
    with pytest.raises(store.NotFound):
        await resolutions.get(db, OUTSIDER, row["id"])
    assert await resolutions.list_for(db, OUTSIDER) == []

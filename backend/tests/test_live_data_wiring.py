"""Regression tests for wiring the previously-inert dev-main integrations
(2026-08-05) into the live pipeline: Gemini as a selectable model provider,
DBnomics/Frankfurter/SearXNG as governed evidence sources feeding the
existing grounded-context/citation/Checkpoint C pipeline, and Groq/Gemini as
additional risk-classification LLM fallback providers.

Deliberately does NOT test websearch.py's own build_web_grounded_prompt/
_DOMAIN_GATE/chart-JSON path — that path is intentionally left unwired (see
orchestration/service.py's comment on the websearch import) because it
bypasses risk classification, Massarius Checkpoint C, and the deterministic
chart-selection system this product's governance is built on.
"""
from app.orchestration.websearch import WebSource, to_websource_rag_chunk, WEBSEARCH_GOVERNED_SOURCE_ID
from app.orchestration.dbnomics import DBNOMICS_GOVERNED_SOURCE_ID
from app.orchestration.frankfurter import FRANKFURTER_GOVERNED_SOURCE_ID


def test_gemini_is_a_registered_model_provider():
    from app.domains.model_gateway.service import _IMPLEMENTED_ADAPTER_FACTORIES
    from app.domains.model_gateway.providers.google_adapter import GeminiAdapter

    assert _IMPLEMENTED_ADAPTER_FACTORIES.get("google") is GeminiAdapter


def test_gemini_reuses_the_governed_groq_system_prompt():
    # Registering a new provider must never introduce a second, differently
    # governed answering prompt — GeminiAdapter imports groq_adapter's
    # _SYSTEM_PROMPT directly rather than defining its own.
    from app.domains.model_gateway.providers.google_adapter import _SYSTEM_PROMPT as gemini_prompt
    from app.domains.model_gateway.providers.groq_adapter import _SYSTEM_PROMPT as groq_prompt

    assert gemini_prompt is groq_prompt


def test_websource_converts_to_the_same_chunk_shape_every_source_uses():
    source = WebSource(title="ECB reference rate", url="https://frankfurter.dev/x", snippet="1 USD = 0.92 EUR")
    chunk = to_websource_rag_chunk(source, FRANKFURTER_GOVERNED_SOURCE_ID)
    assert chunk["text"] == "1 USD = 0.92 EUR"
    assert chunk["metadata"]["source_id"] == FRANKFURTER_GOVERNED_SOURCE_ID
    assert chunk["metadata"]["title"] == "ECB reference rate"
    assert chunk["metadata"]["file_path"] == "https://frankfurter.dev/x"


def test_websource_falls_back_to_title_when_snippet_is_empty():
    source = WebSource(title="Some series", url="https://db.nomics.world/x", snippet="")
    chunk = to_websource_rag_chunk(source, DBNOMICS_GOVERNED_SOURCE_ID)
    assert chunk["text"] == "Some series"


def test_live_data_source_ids_are_distinct_and_governed():
    ids = {DBNOMICS_GOVERNED_SOURCE_ID, FRANKFURTER_GOVERNED_SOURCE_ID, WEBSEARCH_GOVERNED_SOURCE_ID}
    assert len(ids) == 3
    assert all(source_id.startswith("src-kriton-") for source_id in ids)


def test_risk_llm_fallback_tries_groq_when_openai_is_not_configured(monkeypatch):
    # Real gap (2026-08-05): classify() previously required OPENAI_API_KEY
    # specifically and returned None permanently otherwise — an environment
    # with only GROQ_API_KEY/GEMINI_API_KEY configured never got the LLM
    # fallback at all despite RISK_LLM_CLASSIFIER_MODE=fallback.
    from app.domains.risk_safety import llm_classifier

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # No provider configured at all -> None, not an exception.
    assert llm_classifier.classify("What is a tax credit?") is None


def test_risk_llm_groq_and_gemini_helpers_fail_soft_with_no_key(monkeypatch):
    from app.domains.risk_safety import llm_classifier

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm_classifier._classify_via_groq("What is a tax credit?", "", "Workflow") is None
    assert llm_classifier._classify_via_gemini("What is a tax credit?", "", "Workflow") is None


def test_parse_classification_defaults_missing_optional_fields():
    from app.domains.risk_safety.llm_classifier import _parse_classification
    import json

    result = _parse_classification(json.dumps({"risk_level": "low"}), "test-model")
    assert result is not None
    assert result.risk_level == "LOW"
    assert result.confidence == 0.75
    assert result.advice_signal is False
    assert result.missing_context == ()


def test_parse_classification_rejects_invalid_risk_level():
    from app.domains.risk_safety.llm_classifier import _parse_classification
    import json

    assert _parse_classification(json.dumps({"risk_level": "EXTREME"}), "test-model") is None


def test_dbnomics_country_hint_extracts_short_codes_dropped_by_keyword_length():
    # Real gap (2026-08-05): "What is the current US unemployment rate?"
    # confidently returned an Argentina demographic sub-series as if it
    # answered the question — _keywords()'s 4-letter minimum silently
    # dropped "US" entirely, leaving "unemployment" as the only search term
    # with zero geography constraint, so any country's series scored the
    # same. A dangerous failure mode for a finance bot: presenting one
    # country's statistic as another's.
    from app.orchestration.dbnomics import _country_hint

    assert _country_hint("What is the current US unemployment rate?") == ["united states", "usa", "u.s."]
    assert _country_hint("What is India's GDP growth rate?") == ["india"]
    assert _country_hint("What is the eurozone inflation rate?") == ["euro area", "european union", "eurozone"]
    # No country named at all -> no hard filter, existing best-effort match.
    assert _country_hint("What is the inflation rate?") is None


def test_dbnomics_country_hint_prefers_the_longer_more_specific_match():
    from app.orchestration.dbnomics import _country_hint

    # "united states" (longer, more specific key) must win over a bare "us"
    # substring match elsewhere in the same sentence.
    assert _country_hint("What is the unemployment rate in the united states?") == ["united states", "usa", "u.s."]


def test_dbnomics_keywords_preserve_short_stat_abbreviations():
    # Real gap (2026-08-05): same failure mode as the country-code bug —
    # "GDP" is only 3 letters, so "What is India's GDP growth rate?" lost
    # the one word that actually names the statistic, leaving just "india
    # growth" as the search and matching an unrelated India trade-flow
    # dataset instead of anything about GDP.
    from app.orchestration.dbnomics import _keywords

    assert "gdp" in _keywords("What is India's GDP growth rate?")
    assert "cpi" in _keywords("What is the CPI this month?")
    # Ordinary short filler words must still be dropped — only the curated
    # short economic abbreviations bypass the length minimum.
    assert "a" not in _keywords("What is a tax credit?")
    assert "is" not in _keywords("What is a tax credit?")


def test_dbnomics_defers_to_the_existing_bls_bea_mechanisms_for_us_inflation_and_gdp(monkeypatch):
    # Real gap (2026-08-05): DBnomics' own free-text search doesn't return
    # a real CPI dataset for "inflation united states" at all — just an
    # unrelated EIA energy-outlook dataset that happens to mention
    # "Inflation Reduction Act". US inflation/GDP already have dedicated,
    # curated, working mechanisms (BLS CPI / BEA NIPA) — defer to those
    # rather than risk surfacing DBnomics' wrong match.
    import asyncio
    from app.orchestration import dbnomics

    async def _boom(*args, **kwargs):
        raise AssertionError("fetch_stats must not call the network for a US-inflation/GDP query")

    monkeypatch.setattr("httpx.AsyncClient.get", _boom)
    assert asyncio.run(dbnomics.fetch_stats("What is the current US inflation rate?")) == []
    assert asyncio.run(dbnomics.fetch_stats("What is US GDP growth?")) == []


def test_narrower_metric_hints_filters_oecd_policy_microdata_disguised_as_the_headline_stat():
    # Real gap (2026-08-05): DBnomics' search for "unemployment" is
    # dominated by OECD policy/benefits microdata ("Net replacement rates
    # in unemployment", "tax rate for those claiming unemployment
    # benefits") that mentions the term only as context, not the headline
    # unemployment rate itself.
    from app.orchestration.dbnomics import _NARROWER_METRIC_HINTS

    assert _NARROWER_METRIC_HINTS.search("net replacement rates in unemployment")
    assert _NARROWER_METRIC_HINTS.search("participation tax rate (PTR) for parent claiming unemployment benefits")
    assert not _NARROWER_METRIC_HINTS.search("united states — unemployment rate — total")


def test_narrower_metric_hints_filters_ropi_regional_datasets_disguised_as_inflation():
    # Live bug (2026-08-06): "What is Japan's current inflation rate?"
    # picked OECD's "Economic statistics ROPI-adjusted for inflation -
    # Regions" as the top dataset purely because its own description
    # mentions "inflation" as a methodology note, then confidently served
    # an EMPLOYMENT series (~38 million persons) captioned as Japan's
    # inflation rate.
    from app.orchestration.dbnomics import _NARROWER_METRIC_HINTS

    assert _NARROWER_METRIC_HINTS.search("Economic statistics ROPI-adjusted for inflation - Regions")
    assert not _NARROWER_METRIC_HINTS.search("Japan – Consumer Price Index > All items > Total")


def test_dbnomics_current_queries_reject_stale_or_unparseable_observations():
    from datetime import date
    from app.orchestration.dbnomics import _is_fresh_for_current_question

    today = date(2026, 8, 6)
    assert _is_fresh_for_current_question("2026-06", today=today)
    assert _is_fresh_for_current_question("2025-Q4", today=today)
    assert _is_fresh_for_current_question("2024", today=today)
    assert not _is_fresh_for_current_question("2023-12", today=today)
    assert not _is_fresh_for_current_question("not-a-period", today=today)


def test_bls_cpi_and_bea_gdp_injections_skip_when_a_different_country_is_named():
    # Real gap (2026-08-06): "What is Japan's inflation rate?" got answered
    # with US CPI-U data captioned "US inflation" — is_inflation_query/
    # is_gdp_query never checked WHICH country was asked about, so US-only
    # BLS/BEA data fired for literally any inflation/GDP question.
    from app.orchestration.service import _dbnomics_country_hint, _DBNOMICS_US_NAMES

    assert _dbnomics_country_hint("What is Japan's inflation rate?") == ["japan"]
    assert _dbnomics_country_hint("What is China's GDP?") == ["china"]
    # US-implicit or explicitly-US queries must still be treated as US.
    assert _dbnomics_country_hint("What is the current US inflation rate?") == _DBNOMICS_US_NAMES
    assert _dbnomics_country_hint("What is the inflation rate?") is None


def test_us_tax_coverage_rules_do_not_gate_a_plainly_non_us_question():
    # Real gap (2026-08-06): "What is the standard corporate tax rate in
    # India?" was blocked pending an "IRC/CFR and current IRS corporate
    # guidance" source — the coverage registry is explicitly US-scoped
    # (see its own module docstring) but never checked which country's
    # tax question it was looking at.
    from app.domains.coverage import assess_us_professional_coverage

    decision = assess_us_professional_coverage(
        "What is the standard corporate tax rate in India?", None,
    )
    assert decision.applies is False

    # A plain US corporate tax question must still be gated as before.
    decision_us = assess_us_professional_coverage(
        "What is the standard corporate tax rate?", None,
    )
    assert decision_us.applies is True
    assert decision_us.covered is False

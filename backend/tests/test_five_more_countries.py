from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.market_data import identity, registry
from app.domains.market_data.schemas import EntityRef, ProviderBadResponse
from app.domains.market_data.service import _companies_house_should_refuse
from app.orchestration import country_scope
from app.orchestration.dbnomics import (
    _country_in_query,
    _find_gdp_series,
    _find_policy_rate_series,
    _find_series_for_phrase,
    _find_unemployment_series,
    _find_weo_fiscal_series,
    _wdi_match,
    _WEO_UNITS,
    fetch_stats,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


_WEO_DATASETS = {
    "datasets": {
        "num_found": 1,
        "docs": [{"code": "WEO:2022-04"}, {"code": "WEO:2025-04"}],
    }
}


def _weo_series_payload(country, unit_series, periods, values):
    return {
        "series": {"docs": [{
            "series_name": f"{country} · Gross domestic product, current prices · U.S.",
            "series_code": f"{unit_series}",
            "period": periods,
            "value": values,
        }]}
    }


# Imagine a WEO:2025-04 release whose projections run 2025-2030 but whose
# outturns stop at 2024. A naive resolver would serve 2030 "history".
_FAKE_PROJECTIONS = _weo_series_payload(
    "Japan", "JPN.NGDPD.us_dollars",
    ["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"],
    [4213.0, 4026.0, 4300.0, 4400.0, 4500.0, 4600.0, 4700.0, 4800.0],
)


# Some callers patch the class method with a plain function (which receives
# the client as `self`), others with AsyncMock(side_effect=fake) (which does
# not). `*args` lets one fake serve both call conventions — the URL is always
# the last positional argument.
async def _fake_weo_get(*args, params=None, **kwargs):
    url = str(args[-1]) if args else str(kwargs.get("url", ""))
    if "datasets/IMF" in url:
        return _Response(_WEO_DATASETS)
    return _Response(_FAKE_PROJECTIONS)


class TestCountryInQueryAdjectives:
    @pytest.mark.parametrize("query,country", [
        ("what is the German inflation rate today", "Germany"),
        ("French policy rate", "France"),
        ("Japanese GDP", "Japan"),
        ("Indian unemployment", "India"),
        ("Chinese CPI", "China"),
        ("Germany CPI", "Germany"),
        ("France inflation chart", "France"),
    ])
    def test_adjective_and_noun_aliases_resolve(self, query, country):
        assert _country_in_query(query) == country


class TestWdiOrdering:
    def test_trade_balance_pattern_fires_before_generic_gdp_rule(self):
        code, _label = _wdi_match("China trade balance as a share of GDP")
        assert code == "NE.RSB.GNFS.ZS"

    def test_current_account_pattern_fires_before_generic_gdp_rule(self):
        code, _label = _wdi_match("French current account balance to GDP")
        assert code == "BN.CAB.XOKA.GD.ZS"

    def test_plain_gdp_phrasing_still_resolves_to_growth_indicator(self):
        code, _label = _wdi_match("Germany GDP")
        assert code == "NY.GDP.MKTP.KD.ZG"

    def test_government_debt_still_takes_the_wdi_central_debt_series(self):
        code, _label = _wdi_match("Japan general government debt")
        assert code == "GC.DOD.TOTL.GD.ZS"


@pytest.mark.asyncio
class TestWeoOutturnsOnlyRule:
    async def test_gdp_drops_projections_and_sends_unit_qualified_series_code(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            match = await _find_gdp_series("Japan GDP")

        assert match is not None
        _base_url, _release, series_path = str(match.url).rsplit("/", 2)
        assert series_path == "JPN.NGDPD.us_dollars"
        assert "World Economic Outlook (2025-04 release)" in match.dataset_name
        assert all(int(period) < 2025 for period, _ in match.points)
        assert ("2023", 4213.0) in match.points

    async def test_gdp_per_capita_uses_dedicated_indicator_not_total_gdp(self):
        get = AsyncMock(side_effect=_fake_weo_get)
        with patch("httpx.AsyncClient.get", new=get):
            match = await _find_gdp_series("Germany GDP per capita")

        assert match is not None
        requested = [str(c[0][0]) for c in get.call_args_list]
        series_call = next(u for u in requested if "/series/IMF/WEO:" in u)
        assert series_call.endswith("/DEU.NGDPDPC.us_dollars")

    async def test_fiscal_debt_for_china(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            match = await _find_weo_fiscal_series(
                "what is China's government debt as a share of GDP"
            )

        assert match is not None
        assert ".GGXWDG_NGDP.pcent_gdp" in match.url
        assert all(int(period) < 2025 for period, _ in match.points)

    async def test_fiscal_deficit_for_germany(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            match = await _find_weo_fiscal_series("Germany budget deficit")

        assert match is not None
        assert ".GGXCNL_NGDP.pcent_gdp" in match.url

    async def test_fiscal_revenue_for_france(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            match = await _find_weo_fiscal_series("France government revenue")

        assert match is not None
        assert ".GGR_NGDP.pcent_gdp" in match.url

    async def test_fiscal_series_never_fires_for_the_original_five(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            assert await _find_weo_fiscal_series("US government debt") is None

    async def test_unemployment_weo_fallback_drops_projections_for_india(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            match = await _find_unemployment_series("India unemployment")

        assert match is not None
        assert ".LUR.pcent_total_labor_force" in match.url
        assert all(int(period) < 2025 for period, _ in match.points)

    async def test_oecd_member_unemployment_stays_on_oecd_mei(self):
        get = AsyncMock(side_effect=_fake_weo_get)
        with patch("httpx.AsyncClient.get", new=get):
            match = await _find_unemployment_series("Japan unemployment")

        assert match is not None
        assert match.provider_name == "OECD"
        requested = [str(c[0][0]) for c in get.call_args_list]
        assert any("OECD/MEI/JPN.LRHUTTTT.STSA.M" in u for u in requested)

    async def test_fiscal_broad_debt_phrasing_for_japan(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            match = await _find_weo_fiscal_series(
                "Japan general government central debt as a share of GDP"
            )

        assert match is not None
        assert ".GGXWDG_NGDP.pcent_gdp" in match.url


class TestFetchStatsFiscalPrecedence:
    @pytest.mark.asyncio
    async def test_germany_deficit_never_answered_by_wdi_gdp_growth(self):
        wdi = AsyncMock()
        with patch("app.orchestration.dbnomics._wdi_sources", new=wdi):
            with patch("httpx.AsyncClient.get", new=_fake_weo_get):
                sources = await fetch_stats("Germany budget deficit as a share of GDP")

        assert len(sources) == 1
        assert ".GGXCNL_NGDP.pcent_gdp" in sources[0].url
        wdi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_france_revenue_prefers_weo_revenue_over_wdi(self):
        wdi = AsyncMock()
        with patch("app.orchestration.dbnomics._wdi_sources", new=wdi):
            with patch("httpx.AsyncClient.get", new=_fake_weo_get):
                sources = await fetch_stats("France government revenue as a share of GDP")

        assert len(sources) == 1
        assert ".GGR_NGDP.pcent_gdp" in sources[0].url
        wdi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_new_five_debt_goes_weo_fiscal_before_wdi(self):
        wdi = AsyncMock()
        with patch("app.orchestration.dbnomics._wdi_sources", new=wdi):
            with patch("httpx.AsyncClient.get", new=_fake_weo_get):
                sources = await fetch_stats(
                    "Japan general government central debt as a share of GDP"
                )

        assert len(sources) == 1
        assert ".GGXWDG_NGDP.pcent_gdp" in sources[0].url
        wdi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_original_five_keep_wdi_path_for_debt(self):
        fake_wdi = ["WDI result"]
        with patch(
            "app.orchestration.dbnomics._wdi_sources",
            new=AsyncMock(return_value=fake_wdi),
        ):
            with patch("httpx.AsyncClient.get", new=_fake_weo_get):
                sources = await fetch_stats("US government debt as a share of GDP")

        assert sources == fake_wdi


class TestPolicyRateSources:
    @pytest.mark.asyncio
    async def test_japan_uses_ifs_policy_related_rate(self):
        get = AsyncMock(side_effect=_fake_weo_get)
        with patch("httpx.AsyncClient.get", new=get):
            match = await _find_policy_rate_series("what is the Japanese policy rate")

        assert match is not None
        assert match.provider_name == "International Monetary Fund"
        assert [str(c[0][0]) for c in get.call_args_list][0].endswith(
            "/series/IMF/IFS/M.JP.FPOLM_PA"
        )

    @pytest.mark.asyncio
    async def test_germany_uses_ecb_deposit_facility(self):
        get = AsyncMock(side_effect=_fake_weo_get)
        with patch("httpx.AsyncClient.get", new=get):
            match = await _find_policy_rate_series("German interest rate")

        assert match is not None
        assert match.provider_name == "European Central Bank"
        assert [str(c[0][0]) for c in get.call_args_list][0].endswith(
            "/series/ECB/ILM/M.4F.E.L020200.U2.EUR"
        )

    @pytest.mark.asyncio
    async def test_india_has_no_source_and_returns_none(self):
        get = AsyncMock(side_effect=_fake_weo_get)
        with patch("httpx.AsyncClient.get", new=get):
            assert await _find_policy_rate_series("India policy rate") is None
        assert get.await_count == 0

    @pytest.mark.asyncio
    async def test_resolver_never_fires_for_unmapped_country(self):
        with patch("httpx.AsyncClient.get", new=_fake_weo_get):
            assert await _find_policy_rate_series("US policy rate") is None


class TestFiveMoreCountryScope:
    def test_named_countries_reports_new_five_in_order(self):
        assert country_scope.named_countries(
            "compare Japan, France, Germany, China and India GDP"
        ) == ["JP", "FR", "DE", "CN", "IN"]

    def test_new_countries_are_scoped_to_their_own_connector_only(self):
        assert country_scope.is_country_scoped("German inflation", "DE") is True
        assert country_scope.is_country_scoped("German inflation", "CA") is False
        assert country_scope.is_country_scoped("China debt", "US") is False
        assert country_scope.is_country_scoped("French CPI", "FR") is True

    def test_bare_in_is_not_an_india_match(self):
        assert country_scope.named_countries("what is inflation in India") == ["IN"]
        assert country_scope.named_countries("is there inflation in a barrel of oil?") == []


class TestIndiaChinaIndexRecognition:
    @pytest.mark.parametrize("query,expected", [
        ("what is the NIFTY 50?", ("^NSEI", "NIFTY 50", "IN")),
        ("Sensex today", ("^BSESN", "S&P BSE SENSEX", "IN")),
        ("the SSE Composite close", ("000001.SS", "SSE Composite", "CN")),
    ])
    def test_resolve_index_maps_new_markets(self, query, expected):
        assert identity.resolve_index(query) == expected

    @pytest.mark.parametrize("query", [
        "what is the NIFTY 50?",
        "Sensex level",
        "Shanghai Composite today",
    ])
    def test_detect_intent_recognises_new_markets_as_index_quotes(self, query):
        assert registry.detect_intent(query) == registry.INTENT_INDEX

    @pytest.mark.asyncio
    async def test_index_provider_serves_only_the_sse_composite_and_caret_indices(self):
        from app.domains.market_data.providers.index_quote import IndexQuoteProvider

        provider = IndexQuoteProvider()
        client = MagicMock()
        client.get = AsyncMock()

        with pytest.raises(ProviderBadResponse):
            await provider.get_quote(client, EntityRef(name="Kweichow Moutai", ticker="600519.SS"))
        client.get.assert_not_called()

        # The SSE Composite has no caret symbol on Yahoo (^SSEC is HTTP 404);
        # 000001.SS is its real code and must pass the guard.
        try:
            await provider.get_quote(client, EntityRef(name="SSE Composite", ticker="000001.SS"))
        except Exception:  # noqa: BLE001 — the guard crossing is what is asserted
            pass
        assert client.get.called


class TestCompaniesHouseForeignGuardsExtended:
    @pytest.mark.parametrize("query", [
        "siemens AG's German filings",
        "TotalEnergies financial statements France",
        "Toyota Motor Japan filings",
        "SAP SE German registry filings",
    ])
    def test_foreign_jurisdiction_refuses_companies_house(self, query):
        assert _companies_house_should_refuse(query) is True

    def test_uk_cue_rehabilitates_a_foreign_sounding_company(self):
        assert _companies_house_should_refuse(
            "France-based BNP Paribas (London branch) filed at Companies House"
        ) is False

    def test_plain_uk_query_is_unaffected(self):
        assert _companies_house_should_refuse("where does Hargreaves Lansdown file at Companies House?") is False


class TestWeoUnitsTable:
    def test_every_new_gdp_series_code_carries_an_explicit_unit(self):
        for indicator in ("NGDPD", "NGDP_RPCH", "NGDPDPC"):
            assert indicator in _WEO_UNITS

    def test_fiscal_and_unemployment_units_present(self):
        for indicator in ("GGXWDG_NGDP", "GGXCNL_NGDP", "GGR_NGDP", "LUR"):
            assert indicator in _WEO_UNITS


class TestSeriesForPhraseRouting:
    @pytest.mark.asyncio
    async def test_china_inflation_phrase_routes_to_cpi(self):
        payload = {
            "series": {"docs": [{
                "series_name": "Monthly China All items Percentage",
                "series_code": "M.CN.PCPI_PC_CP_A_PT",
                "period": ["2025-06", "2025-07"],
                "value": [0.1, 0.02],
            }]}
        }

        async def fake_get(url, *, params=None, **kw):
            return _Response(payload)

        get = AsyncMock(side_effect=fake_get)
        with patch("httpx.AsyncClient.get", new=get):
            match = await _find_series_for_phrase("China inflation")

        assert match is not None
        assert [str(c[0][0]) for c in get.call_args_list][0].endswith(
            "/series/IMF/CPI/M.CN.PCPI_PC_CP_A_PT"
        )
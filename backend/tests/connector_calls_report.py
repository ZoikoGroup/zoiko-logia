"""Task Contract, Stage C-2b: which data connectors and fixed official pages
retrieval would call for each question, in normal mode and agent mode. Not
collected by the normal test run; run it explicitly:

    CONNECTOR_REPORT=report.json RETRIEVAL_QUESTIONS=questions.json \
        python -m pytest -q tests/connector_calls_report.py

Every outbound HTTP request is recorded and refused (sockets blocked), so
nothing leaves the machine; a request is attributed to its connector by host.
- normal: fetch_live_data on the question (the pre-fetch), plus the fixed
  official pages web_search_each reads (official_evidence, the HMRC VAT
  registration page);
- agent: fetch_live_data only when service's agent-mode gates allow it, plus
  the Task Contract's official pre-fetch (official_prefetch).
The search engine itself is not run here (retrieval_fetch_report.py does).
"""
import asyncio
import json
import os
import re
from pathlib import Path

import httpx

from tests.retrieval_fetch_report import _questions, offline  # noqa: F401

_CONNECTORS = (("frankfurter", "fx_ecb"), ("exchangerate", "fx_fallback"), ("open.er-api", "fx_fallback"),
               ("fred.stlouisfed", "fred"), ("db.nomics", "dbnomics"), ("sec.gov", "sec"),
               ("bankofengland", "bank_of_england"), ("www.gov.uk/api/search", "govuk_tax_rate"),
               ("legislation.gov.uk", "legislation"), ("bankofcanada", "bank_of_canada"), ("rba.gov.au", "rba"),
               ("abs.gov.au", "abs"), ("cso.ie", "cso_ireland"), ("treasury", "us_treasury"), ("oecd", "oecd_tax"),
               ("register-for-vat", "page:hmrc_vat_registration"), ("iras.gov.sg", "page:iras"),
               ("mof.gov.ae", "page:uae_mof"), ("customs.gov.my", "page:malaysia_customs"),
               ("corporation-tax", "page:hmrc_corporation_tax"), ("income-tax-rates", "page:hmrc_income_tax"),
               ("cbic", "page:cbic"), ("indiacode", "page:india_code"), ("gstcouncil", "page:gst_council"))


def _connector(url: str) -> str:
    plain = url.split("://", 1)[-1]
    return next((name for marker, name in _CONNECTORS if marker in plain), "other:" + httpx.URL(url).host)


async def _calls(coroutine, recorder) -> list[str]:
    recorder.urls.clear()
    try:
        await asyncio.wait_for(coroutine, timeout=30)
    except Exception:  # noqa: BLE001
        pass
    names = list(dict.fromkeys(_connector(url) for url in recorder.urls))
    recorder.urls.clear()
    return names


async def test_connector_calls_report(offline):
    from app.orchestration import service
    from app.orchestration.live_data import fetch_live_data
    from app.orchestration.official_evidence import official_sources
    from app.orchestration.task_contract import build_task_contract
    from app.orchestration.case_text import request_part
    from app.orchestration.input_requirements import uk_vat_rules_requested
    from app.orchestration.source_taxonomy import detect_jurisdictions
    from app.orchestration.websearch import _uk_vat_rules_source
    try:
        from app.orchestration.official_prefetch import official_prefetch
    except ImportError:  # before Stage C-2b
        official_prefetch = None
    rows = []
    for question in _questions():
        contract = build_task_contract(question)
        live = await _calls(fetch_live_data(question), offline)
        # The fixed pages web_search_each adds, on the same text and condition.
        asked = request_part(question)
        pages = await _calls(official_sources(asked), offline)
        if uk_vat_rules_requested(asked) or ("UK" in detect_jurisdictions(asked) and re.search(r"\bvat\b", asked, re.I)
                                             and re.search(r"\b(?:threshold|register|registration)\b", asked, re.I)):
            pages += [p for p in await _calls(_uk_vat_rules_source(), offline) if p not in pages]
        agent_live = live if (service._dated_fx_question(question) or service._official_rate_question(question)) else []
        agent_pages = await _calls(official_prefetch(contract), offline) if official_prefetch else []
        rows.append({"question": question[:200],
                     "official_parts": [{"fact": r.fact_type, "jurisdictions": r.jurisdictions, "connector": r.connector}
                                        for r in contract.retrieval if r.needs_official],
                     "normal": {"live_data": live, "pages": pages}, "agent": {"live_data": agent_live, "pages": agent_pages}})
    out = os.environ.get("CONNECTOR_REPORT")
    if out:
        Path(out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))

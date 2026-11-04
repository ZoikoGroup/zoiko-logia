"""Global Source Registry, Stage S4b: the registry's fixed-page selection is
the coded selection (official_evidence.coded_pages) for every question in the
evaluation files and every gold part, so KRITON_REGISTRY_RETRIEVAL changes
where the rule lives, not which pages are read."""
import glob
import json
from pathlib import Path

import pytest

from app.orchestration import official_evidence, source_registry
from app.orchestration.official_evidence import coded_pages, official_pages
from app.orchestration.source_registry import registry_pages, subjects_of

EVALS = Path(__file__).resolve().parents[1] / "evals"

# Wording that reaches each coded rule, including its negative cases.
PROBES = [
    "What is the current GST rate in Singapore?", "What is the VAT rate in the UAE?", "SST rate in Malaysia?",
    "What is UK corporation tax for small profits?", "What is the UK personal allowance?",
    "What interest rate does HMRC charge on late VAT payments?", "Late payment interest on UK corporation tax?",
    "What is the GST registration threshold in India?", "Is GST registration compulsory in India for e-commerce sellers?",
    "GST registration threshold for a Bengaluru supplier", "Is export of services to a US client zero-rated under GST in India?",
    "What is the GST rate in Australia?", "What is the VAT rate in the UK?", "Corporation tax rate in India",
    "Interest on late payment of invoices in the UK", "What is the personal allowance in Ireland?",
]


def _questions() -> list[str]:
    seen: dict[str, None] = {}
    for path in sorted(glob.glob(str(EVALS / "*.json"))):
        stack = [json.load(open(path))]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                stack.extend(node.values())
                for key in ("question", "query", "user", "part"):
                    if isinstance(node.get(key), str) and node[key].strip():
                        seen.setdefault(node[key].strip())
    return list(seen)


def test_registry_selection_equals_the_coded_selection_on_every_question():
    questions = PROBES + _questions()
    assert len(questions) > 600
    # S5 pages exist only in the registry ("origin": "registry").
    added = {e["url"] for e in source_registry.entries() if e.get("origin") == "registry"}
    differ = [(q[:100], coded_pages(q), registry_pages(q)) for q in questions
              if coded_pages(q) != [page for page in registry_pages(q) if page[1] not in added]]
    assert differ == []


# S5 (3 Nov 2026): official pages read once live and added as registry data only.
@pytest.mark.parametrize("question, title", [
    ("What is the current UK employer National Insurance contribution rate?", "HMRC: Rates and thresholds for employers 2026 to 2027"),
    ("What is the standard sales tax rate in Canada?", "CRA: GST/HST calculator (and rates)"),
    ("What is the HST rate in Ontario, Canada?", "CRA: GST/HST calculator (and rates)"),
    ("What is the standard VAT rate in South Africa?", "SARS: Value-Added Tax"),
    ("What is the standard VAT rate in Germany?", "UStG § 12: Steuersätze (German VAT rates, statute)"),
])
def test_registry_only_pages_are_selected(question, title):
    assert title in [t for t, _ in registry_pages(question)]
    assert coded_pages(question) == []


@pytest.mark.parametrize("question", ["What is the standard VAT rate in Ireland?", "What is the GST rate in Australia?",
                                      "What is the standard VAT rate in the UK?", "Explain how VAT works in South Africa's economy"])
def test_registry_only_pages_stay_in_their_country_and_subject(question):
    titles = [t for t, _ in registry_pages(question)]
    assert not any(t.startswith(("HMRC: Rates and thresholds", "CRA:", "UStG")) for t in titles)
    if "South Africa" not in question:
        assert "SARS: Value-Added Tax" not in titles


def test_added_pages_carry_their_verification():
    for entry in source_registry.entries():
        if entry.get("origin") == "registry":
            assert entry["verified"]["read_at"] and entry["verified"]["quote"] and entry["review_by"]


@pytest.mark.parametrize("question", PROBES)
def test_the_switch_reads_the_registry(monkeypatch, question):
    monkeypatch.setenv("KRITON_REGISTRY_RETRIEVAL", "true")
    assert official_pages(question) == registry_pages(question)
    monkeypatch.delenv("KRITON_REGISTRY_RETRIEVAL")
    assert official_pages(question) == coded_pages(question)


def test_a_page_added_to_the_registry_is_selected_without_code(monkeypatch):
    data = json.loads(source_registry.REGISTRY_FILE.read_text())
    data["entries"].append({"id": "page:test-isle-of-man-vat", "kind": "fixed_page", "countries": ["ISLE_OF_MAN"],
                            "title": "Isle of Man Customs and Excise: VAT", "url": "https://example.test/iom-vat",
                            "status": "in_use", "selection": {"all": [r"\bvat\b"]}})
    monkeypatch.setattr(source_registry, "_data", lambda: data)
    source_registry._page_rules.cache_clear()
    try:
        assert ("Isle of Man Customs and Excise: VAT", "https://example.test/iom-vat") in registry_pages(
            "What is the VAT registration threshold in the Isle of Man?")
    finally:
        source_registry._page_rules.cache_clear()


def test_subjects():
    assert subjects_of("UK VAT registration threshold") == ["vat"]
    assert "payroll" in subjects_of("employer national insurance rate")
    assert "bank_rate" in subjects_of("What is the Bank of England bank rate?")
    assert subjects_of("Explain going concern") == []


def test_official_evidence_keeps_its_page_specific_excerpts():
    # Selection moved; the excerpt rules keyed by URL did not.
    assert "01062019-GST-An-Update" in Path(official_evidence.__file__).read_text()


# S5b: a registry excerpt_anchor starts the passage at the page's own heading.
UStG_12 = ("Umsatzsteuergesetz (UStG)\n§ 12 Steuersätze\n(1) Die Steuer beträgt für jeden steuerpflichtigen Umsatz "
           "19 Prozent der Bemessungsgrundlage (§§ 10, 11, 25 Abs. 3 und § 25a Abs. 3 und 4).\n"
           "(2) Die Steuer ermäßigt sich auf 7 Prozent für die folgenden Umsätze: …")


@pytest.mark.parametrize("question, fixture, must", [
    ("What is the current UK employer National Insurance contribution rate?", "hmrc_employers_2026_27.txt",
     ["Employer (secondary) contribution rates", "15%"]),
    ("What is the standard VAT rate in Germany?", None, ["(1) Die Steuer beträgt", "19 Prozent"]),
])
def test_anchored_excerpts(monkeypatch, question, fixture, must):
    import asyncio
    from app.orchestration import websearch
    text = (Path(__file__).parent / "fixtures" / fixture).read_text() if fixture else UStG_12

    async def read(client, url):
        return text
    monkeypatch.setenv("KRITON_REGISTRY_RETRIEVAL", "true")
    monkeypatch.setattr(websearch, "_read_html", read)
    monkeypatch.setattr(websearch, "_html_to_text", lambda markup: markup)
    [source] = asyncio.run(official_evidence.official_sources(question))
    assert source.snippet.startswith(must[0]) and all(item in source.snippet for item in must)

"""IFRS standards split at their own paragraph numbers, including appendix
paragraphs ("C1"), so citations can name the paragraph (IAS 2 ¶33, IFRS 18 ¶C1)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ingest_official_split", Path(__file__).resolve().parents[1] / "scripts" / "ingest_official.py")
ingest = importlib.util.module_from_spec(_spec)
sys.modules["ingest_official_split"] = ingest
_spec.loader.exec_module(ingest)

TEXT = ("INVENTORIES 32 | Materials held for use are not written down below cost if the finished products will be "
        "sold at or above cost. 33 | A new assessment is made of net realisable value in each subsequent period; the "
        "amount of the write-down is reversed. C1 | An entity shall apply this Standard for annual reporting periods "
        "beginning on or after 1 January 2027. Earlier application is permitted.")


def test_each_numbered_and_appendix_paragraph_is_its_own_passage():
    passages = ingest.split_ifrs_paragraphs(TEXT, "IAS 2 Inventories (2026 edition)", "https://x/ias2.html")
    by_number = {p.locator.split("#p")[1]: p for p in passages}
    assert set(by_number) == {"32", "33", "C1"}
    assert "write-down is reversed" in by_number["33"].content and by_number["33"].heading == "IAS 2 Inventories ¶33"
    assert "1 January 2027" in by_number["C1"].content


def test_ifrs_documents_are_gated_on_their_own_licence_approval():
    ifrs = [d for d in ingest.DOCUMENTS if d.publisher is ingest.IFRS_FOUNDATION]
    assert {d.url.rsplit("/", 1)[1] for d in ifrs} == {"ifrs18.html", "ias2.html", "ias7.html"}
    assert all(d.rights_env == "IFRS_INGESTION_RIGHTS_APPROVED" for d in ifrs)
    assert "licence from the IFRS Foundation" in ingest.IFRS_FOUNDATION.terms

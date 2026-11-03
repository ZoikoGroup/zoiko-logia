"""The country-term registry (30 Oct 2026 experiment): every phrase places its
country; ambiguous terms place none; whole-word and case rules hold."""
import json
import re

import pytest

from app.orchestration.country_terms import REGISTRY, implied_countries

DATA = json.loads(REGISTRY.read_text())


@pytest.mark.parametrize("entry", DATA["entries"], ids=lambda e: e["id"])
def test_every_phrase_places_its_country(entry):
    for phrase in entry["phrases"]:
        assert implied_countries(f"Explain the purpose of {phrase} please.") == [entry["country"]], phrase


@pytest.mark.parametrize("entry", DATA["entries"], ids=lambda e: e["id"])
def test_every_entry_records_its_basis(entry):
    assert entry["authority"] and entry["basis"] and entry["verification"] in ("verified", "unverified")


@pytest.mark.parametrize("entry", DATA["entries"], ids=lambda e: e["id"])
def test_every_phrase_has_its_verification_and_a_verified_one_its_evidence(entry):
    # Version 2 (31 Oct 2026): a verified phrase records the authority page, time, content hash and quote.
    assert set(entry["phrase_verification"]) == set(entry["phrases"])
    for phrase, check in entry["phrase_verification"].items():
        if check["status"] == "verified":
            assert check["verified_url"].startswith("https://") and len(check["content_sha256"]) == 64
            assert re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", check["quote"], re.I), phrase
        else:
            assert check == {"status": "unverified"}
    assert entry["verification"] == ("verified" if any(c["status"] == "verified" for c in entry["phrase_verification"].values())
                                     else "unverified")


@pytest.mark.parametrize("text", [
    "How does PAYE work?", "Explain fringe benefits tax.", "When is provisional tax due?",
    "What are National Insurance rates?", "What does IAS 36 require?", "Explain ISA 315.",
    "What is the SG rate?", "How is GST charged?", "What is VAT?", "Who pays stamp duty?",
    # moved to ambiguous by the live verification: found on two countries' authority pages
    "What is the EIS?", "What goes on Schedule C?", "How does resident withholding tax work?",
    "What is the skills development levy?", "Who pays SDL?",
])
def test_ambiguous_terms_place_no_country(text):
    assert implied_countries(text) == []


@pytest.mark.parametrize("text, countries", [
    ("When is the Form 1120 due?", ["US"]),            # not Ireland's "Form 11"
    ("When is Form 11 due?", ["IRELAND"]),
    ("When is Local Property Tax due?", ["IRELAND"]),  # spelled-out phrases match in any case
    ("Explain the T4A slip.", ["CANADA"]),
    ("What is an IR330?", ["NEW_ZEALAND"]),            # not "IR3"
    ("the bas relief sculpture", []),                  # acronyms are case-sensitive
    ("Explain the purpose of the taxable payments annual report.", ["AUSTRALIA"]),
])
def test_whole_words_and_case(text, countries):
    assert implied_countries(text) == countries

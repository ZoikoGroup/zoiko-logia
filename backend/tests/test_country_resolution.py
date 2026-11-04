"""Deterministic country resolution (design Option 3, 30 Oct 2026): the
design's unit scenarios. No model, no network."""
import pytest

from app.orchestration import classifier_shadow
from app.orchestration.country_resolution import resolve
from app.orchestration.model_part_classifier import ModelPart, prompt


@pytest.mark.parametrize("part, request_text, status, countries, counterparties", [
    ("What is the UK VAT rate?", "", "resolved", ["UK"], []),                                          # explicit name
    ("A UK company sells services to an Irish business customer. Which VAT rules apply?", "", "resolved", ["UK"], ["IRELAND"]),
    ("An Indian subsidiary pays dividends to its US parent. What withholding applies?", "", "resolved", ["INDIA"], ["US"]),
    ("Does a UAE subsidiary of a UK group pay corporate tax?", "", "resolved", ["UAE"], ["UK"]),
    ("Our UK company pays an Australian contractor. Do we deduct tax?", "", "resolved", ["UK"], ["AUSTRALIA"]),
    ("A UK business has a customer in the USA. Which rules apply?", "", "resolved", ["UK"], ["US"]),
    ("Compare UK and US corporate tax rates.", "", "resolved", ["UK", "US"], []),                      # comparison
    ("When is it due?", "1. What is the UK VAT threshold? 2. When is it due?", "resolved", ["UK"], []),  # other part
    ("What is the current RBI repo rate?", "", "resolved", ["INDIA"], []),                             # authority
    ("When must an employer file Form IR21?", "", "resolved", ["SINGAPORE"], []),                      # registry term
    ("Explain the difference between a T4 slip and Form 1040.", "", "resolved", ["CANADA", "US"], []),  # two countries' terms
    ("A UK company receives a W-8BEN request from a US customer. What UK points apply?", "", "resolved", ["UK"], ["US"]),
    ("What is the Texas sales tax rate?", "", "resolved", ["US"], []),                                 # sub-national
    ("How does FBT work?", "", "candidates", [], []),                                                  # ambiguous term
    ("When is the IR10 due?", "", "unknown", [], []),                                                  # unmapped code
    ("Where can I find an Indian restaurant?", "", "unknown", [], []),                                 # demonym trap
    ("Explain IAS 36.", "", "unknown", [], []),                                                        # standard, not a form
])
def test_the_design_scenarios(part, request_text, status, countries, counterparties):
    result = resolve(part, request_text)
    assert (result.status, result.countries, result.counterparties) == (status, countries, counterparties)


def test_an_ambiguous_term_is_decided_only_by_matching_user_context():
    assert resolve("How does FBT work?", selected="NEW_ZEALAND").countries == ["NEW_ZEALAND"]
    assert resolve("How does FBT work?", selected="UK").status == "candidates"


def test_user_context_applies_only_without_text_evidence_and_conflicts_are_recorded():
    assert resolve("What's the registration threshold?", selected="UK").countries == ["UK"]
    result = resolve("When must an employer file Form IR21?", selected="UK")
    assert result.countries == ["SINGAPORE"] and result.conflicts[0]["value"] == "UK"


def test_unmapped_codes_are_recorded_not_guessed():
    # (codes not in the registry; "IT3" became a verified SARS entry in country-terms-2)
    result = resolve("Explain the purpose of Form 1042-S and the IT77C.")
    assert result.status == "unknown" and result.unmapped_terms == ["Form 1042-S", "IT77C"]


def _part(fact, countries=()):
    return ModelPart(index=1, needs_official=fact in ("rate", "threshold", "deadline", "rule"), fact_type=fact,
                     tax_countries=list(countries), counterparty_countries=[], period_kind="unspecified", confidence="high")


def test_with_the_switch_on_the_model_no_longer_decides_countries(monkeypatch):
    monkeypatch.setenv("KRITON_COUNTRY_RESOLUTION", "1")
    guessed = classifier_shadow._final("When is the IR10 due?", "When is the IR10 due?", _part("deadline", ["UK"]))
    assert guessed["tax_countries"] == [] and guessed["domains"] == [] and guessed["source"].endswith("resolver:unknown")
    named = classifier_shadow._final("When must an employer file Form IR21?", "q", _part("deadline", ["UK"]))
    assert named["tax_countries"] == ["SINGAPORE"] and "iras.gov.sg" in named["domains"]


def test_with_the_switch_off_nothing_changes(monkeypatch):
    part = classifier_shadow._final("When is the IR10 due?", "When is the IR10 due?", _part("deadline", ["UK"]))
    assert part["tax_countries"] == ["UK"] and part["country_resolution"] is None


def test_the_instructions_without_countries_ask_for_no_country():
    system, _ = prompt("q", ["q"], countries=False)
    assert "tax_countries" not in system and "counterparty_countries" not in system and "MALAYSIA" not in system


def test_the_task_contract_records_the_resolution_only_when_switched_on(monkeypatch):
    from app.orchestration.task_contract import build_task_contract
    query = "When must an employer file Form IR21?"
    off = build_task_contract(query).retrieval[0]
    monkeypatch.setenv("KRITON_COUNTRY_RESOLUTION", "1")
    on = build_task_contract(query).retrieval[0]
    assert off.country_resolution is None and on.country_resolution["countries"] == ["SINGAPORE"]
    assert on.jurisdictions == off.jurisdictions          # recorded only: routing fields unchanged


# General rules added 30 Oct 2026 after the offline diagnostic (written from the rules, not from failed questions).

@pytest.mark.parametrize("text, countries, counterparties", [
    # Rule 1 — role nouns after a preposition or a transaction verb are the other party.
    ("A Malaysian startup buys hosting from a Singapore vendor. Which tax rules apply?", ["MALAYSIA"], ["SINGAPORE"]),
    ("An Omani firm hires a French consultant. What obligations arise?", ["OMAN"], ["FRANCE"]),
    # negative: a role noun as the subject is not the other party
    ("A French consultant works from home. What obligations arise?", ["FRANCE"], []),
    # Rule 2 — entity nouns are the other party only after a transaction verb, or as an owner group/parent.
    ("A Bahraini company invoices a Qatari business for services. What applies?", ["BAHRAIN"], ["QATAR"]),
    ("Does an Irish subsidiary of a Canadian group file returns?", ["IRELAND"], ["CANADA"]),
    # negatives: "apply to / for a <country> business" does not make it the other party
    ("What rules apply to a South African business that exports?", ["SOUTH_AFRICA"], []),
    ("What is the filing deadline for an Omani company?", ["OMAN"], []),
    # Rule 3 — "a supplier in X" (role nouns only)
    ("A Jersey trust pays suppliers based in France. What applies?", ["JERSEY"], ["FRANCE"]),
    ("A company in Qatar asks about filing. What applies?", ["QATAR"], []),       # negative: entity noun, not a role
])
def test_role_and_entity_rules(text, countries, counterparties):
    result = resolve(text)
    assert (result.countries, result.counterparties) == (countries, counterparties)


@pytest.mark.parametrize("text, countries", [
    # Rule 4 — the country that qualifies the tax outranks the roles.
    ("A Malaysian firm sells to a Singapore business. What Singapore GST applies?", ["SINGAPORE"]),
    ("A French company buys from a German supplier. Is German VAT charged?", ["GERMANY"]),
    ("Compare Omani and Bahraini VAT registration rules.", ["OMAN", "BAHRAIN"]),       # a chain of qualifiers
    ("How is a pension taxed in Ireland for a UK retiree?", ["IRELAND"]),             # "taxed in X"
    ("What Australian payroll tax applies?", ["AUSTRALIA"]),                          # allowed modifier
    # negatives: a verb or entity word between country and tax is not a qualifier
    ("Does a Qatari branch of a French group pay corporate tax?", ["QATAR"]),
    ("A UK company invoices a German company. Which VAT rules apply?", ["UK"]),       # no qualifier: roles decide
])
def test_a_country_that_qualifies_the_tax_wins(text, countries):
    assert resolve(text).countries == countries


@pytest.mark.parametrize("text, countries", [
    # Longest name wins; a name inside a longer name is not a second country.
    ("What VAT applies to sales from Northern Ireland?", ["UK"]),
    ("What payroll tax applies in New South Wales?", ["AUSTRALIA"]),
    ("What PST applies in British Columbia?", ["CANADA"]),
    ("What applies in Ireland and Wales?", ["IRELAND", "UK"]),                       # negative: separate names stay
])
def test_longest_name_wins(text, countries):
    assert resolve(text).countries == countries


@pytest.mark.parametrize("text, status, countries", [
    # A country word followed by a framework word is a framework, not a country.
    ("What does UK GAAP say about leases?", "unknown", []),
    ("Where are Canadian accounting standards published?", "unknown", []),
    ("Explain Australian auditing standards.", "unknown", []),
    ("What is the UK VAT rate under UK GAAP reporting?", "resolved", ["UK"]),       # negative: the country is also named on its own
])
def test_framework_names_are_not_countries(text, status, countries):
    result = resolve(text)
    assert (result.status, result.countries) == (status, countries)


@pytest.mark.parametrize("text, unmapped", [
    ("Who can file ITR-V?", ["ITR-V"]),                     # a letters-only code not in the registry
    ("When is ITR-2 due?", []),                             # a registered code is mapped, not unmapped
    ("Explain Form C-S (Lite).", []),                       # no stray bracket from "(Lite)"
    ("Explain IFRS 9 and IAS 39.", []),                     # standards are not form codes
])
def test_form_like_codes(text, unmapped):
    assert resolve(text).unmapped_terms == unmapped


@pytest.mark.parametrize("text", ["Calculate the total invoice for S$2,000 before GST.", "What GST applies above Rs 5,000?",
                                  "A freelancer earns ₹12 lakh. What GST applies?"])
def test_currency_and_location_markers_stay_off(text):
    assert resolve(text).status == "candidates"


@pytest.mark.parametrize("text, countries, counterparties", [
    # Rule 4 after the tax word takes a chain, like before it.
    ("What are the GST rates in Malaysia and Singapore?", ["MALAYSIA", "SINGAPORE"], []),
    ("Compare the VAT rate in Oman with Bahrain.", ["OMAN", "BAHRAIN"], []),
    # Rule 5: when every named country would be the other party, it is the subject.
    ("What is the GST threshold for service providers in Malaysia?", ["MALAYSIA"], []),
    ("Must online sellers in Qatar register?", ["QATAR"], []),
    # negative: with another named country left, the role still applies
    ("A Qatari firm uses online sellers in Oman. What applies?", ["QATAR"], ["OMAN"]),
])
def test_chains_after_the_tax_and_the_only_country_is_the_subject(text, countries, counterparties):
    result = resolve(text)
    assert (result.countries, result.counterparties) == (countries, counterparties)


def test_a_transaction_party_stays_the_other_party_even_when_it_is_the_only_country():
    # negative for rule 5: the subject's country is not named, so nothing is resolved from the client's
    result = resolve("A freelance designer in Lagos bills a Canadian client. What GST applies?")
    assert result.countries == [] and result.counterparties == ["CANADA"]


# Decision of 31 Oct 2026: a verified registry term may resolve a country; an unverified one only gives a candidate.
import json as _json
from app.orchestration.country_terms import REGISTRY as _REGISTRY

_ENTRIES = _json.loads(_REGISTRY.read_text())["entries"]


def _phrase(status, country=None):
    for e in _ENTRIES:
        for phrase, check in e["phrase_verification"].items():
            if check["status"] == status and (country is None or e["country"] == country) and len(phrase) > 3 \
                    and all(v["status"] == status for v in e["phrase_verification"].values()):
                return e["country"], phrase
    raise LookupError(status)


def test_a_verified_term_resolves():
    country, phrase = _phrase("verified")
    result = resolve(f"When is the {phrase} due?")
    assert (result.status, result.countries) == ("resolved", [country])
    assert result.evidence[-1]["kind"] == "E4"


def test_an_unverified_term_gives_only_a_candidate():
    country, phrase = _phrase("unverified")
    result = resolve(f"When is the {phrase} due?")
    assert (result.status, result.countries, result.candidates) == ("candidates", [], [country])
    assert any(e["kind"] == "E4u" for e in result.evidence)


def test_user_context_matching_an_unverified_candidate_resolves_and_a_different_one_does_not():
    country, phrase = _phrase("unverified")
    assert resolve(f"When is the {phrase} due?", selected=country).countries == [country]
    other = "UK" if country != "UK" else "US"
    assert resolve(f"When is the {phrase} due?", selected=other).status == "candidates"


def test_an_explicit_name_still_outranks_any_term():
    _, phrase = _phrase("unverified")
    assert resolve(f"When is the {phrase} due for a company in Oman?").countries == ["OMAN"]


# Policy P2 (31 Oct 2026, option F-a): "federal" is ambiguous between the US, Canada and Australia.
@pytest.mark.parametrize("text, selected, status, countries, candidates", [
    ("How is federal tax withheld from bonuses?", None, "candidates", [], ["US", "CANADA", "AUSTRALIA"]),
    ("How is federal tax withheld from bonuses?", "Canada", "resolved", ["CANADA"], []),
    ("How is federal tax withheld from bonuses?", "UK", "candidates", [], ["US", "CANADA", "AUSTRALIA"]),  # outside the set
    ("What federal tax applies to bonuses in Australia?", None, "resolved", ["AUSTRALIA"], []),          # a name wins
    ("What does the Federal Reserve decide?", None, "resolved", ["US"], []),                              # authority wins
    ("How do I contact the Federal Tax Authority?", None, "resolved", ["UAE"], []),
])
def test_federal_is_ambiguous(text, selected, status, countries, candidates):
    result = resolve(text, selected=selected)
    assert (result.status, result.countries, result.candidates) == (status, countries, candidates)

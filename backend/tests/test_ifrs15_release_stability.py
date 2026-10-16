"""IFRS 15 answers through the complete release path: what is supported is
kept, what is not is removed and said so, and the status matches.

Live runs of the same IFRS 15 question ended complete, partial and withheld
(qry-86e1aee653e9, qry-535a68332c4d, qry-375971f37cb5). Two causes:
- the verifier saw only 1,500 characters of the ~3,000-character official
  excerpt it was asked to check claims against, so a claim whose support sat
  in the other half was "not in evidence" (claim_verification._evidence_block);
- the excerpt itself was chosen by framing words and the standard's own name,
  and filled with agenda-decision commentary and word-less fragments instead
  of ¶31/¶39, ¶106/B44 and B48–B51 (official_standards.best_passages).

The verifier here is a faithful stand-in: a claim is supported only when its
supporting sentence is in the EVIDENCE the verifier is actually shown. The
standard text is synthetic, in the standard's form, not IFRS Foundation text."""
import json
import re
from types import SimpleNamespace

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import claim_verification, official_standards
from app.orchestration.websearch import WebSource
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — the full-pipeline fixture

QUESTION = ("A software company receives £120,000 upfront for a 12-month service contract. Explain how revenue "
            "recognition may differ from cash receipt under IFRS 15. Identify the facts needed before concluding "
            "how much revenue is recognised today.")

# What supports each claim, as the synthetic standard states it.
SUPPORT = {
    "contract liability": "shall recognise a contract liability for the amount of the prepayment",
    "over time": "simultaneously receives and consumes the benefits",
    "time elapsed": "a measure of progress based on time elapsed",
    "on day one": None,   # no passage supports this: genuinely unsupported
}

# Like the real standard: many requirements share the question's vocabulary
# (revenue, service contract, customer, upfront, recognised), so a cut to
# 1,500 characters keeps these and loses the paragraphs that decide the case.
FILLER = " ".join(
    f"{n} | When a software company receives cash upfront for a service contract with a customer, the revenue "
    f"recognised and the contract terms over the months of the contract shall be assessed for item {n}."
    for n in range(1, 13)
)
STANDARD_EXCERPT = (
    FILLER
    + " 35 | An entity transfers control of a service over time if the customer simultaneously receives and "
      "consumes the benefits provided by the entity's performance as the entity performs."
    + " 39 | For a performance obligation satisfied over time an entity may use a measure of progress based on "
      "time elapsed when the service is provided evenly."
    + " B44 | Upon receipt of a prepayment from a customer, an entity shall recognise a contract liability for the "
      "amount of the prepayment and derecognise it when it transfers the service."
)

CLAIMS = {
    "contract liability": "When the £120,000 is received upfront the company recognises a contract liability for the prepayment [REF-1].",
    "over time": "Revenue from the 12-month service is recognised over time because the customer receives and consumes the benefits as the service is performed [REF-1].",
    "time elapsed": "Progress over the 12 months may be measured by time elapsed [REF-1].",
    "on day one": "The full £120,000 is recognised as revenue on day one [REF-1].",
}


def answer(*keys: str) -> str:
    return "\n".join(CLAIMS[key] for key in keys)


@pytest.fixture
def faithful_verifier(monkeypatch):
    shown: list[str] = []

    async def complete_auxiliary(*, purpose, user, **_):
        evidence = user.split("EVIDENCE:\n", 1)[1].split("\n\nCLAIMS:\n", 1)[0]
        shown.append(evidence)
        claims = re.findall(r"^(\d+)\. (.*)$", user.split("\n\nCLAIMS:\n", 1)[1], re.M)
        results = []
        for number, claim in claims:
            key = next((k for k, text in CLAIMS.items() if text.split(" [REF")[0] in claim), None)
            phrase = SUPPORT.get(key) if key else None
            supported = bool(phrase) and phrase in " ".join(evidence.split())
            results.append({"claim": int(number), "verdict": "supported" if supported else "not_in_evidence",
                            "references": ["REF-1"] if supported else [], "evidence_says": ""})
        return SimpleNamespace(text=json.dumps({"results": results}))

    monkeypatch.setenv("CLAIM_VERIFICATION", "on")   # conftest turns the live verifier off
    monkeypatch.setattr(claim_verification, "gateway", SimpleNamespace(
        may_use=lambda *args, **kwargs: True, complete_auxiliary=complete_auxiliary))
    return shown


@pytest.fixture
def ifrs15(pipeline, faithful_verifier):
    official = WebSource(title="IFRS 15 — official text (IFRS Foundation)", provider="IFRS Foundation",
                         url="https://www.ifrs.org/content/dam/ifrs/publications/html-standards/english/2026/issued/ifrs15.html",
                         snippet=STANDARD_EXCERPT)

    async def ask(text: str):
        pipeline.answers(AgentOutcome(text=text, sources=[official]))
        return await pipeline.ask(QUESTION)

    return SimpleNamespace(ask=ask, shown=faithful_verifier)


async def test_a_fully_supported_answer_is_released_complete(ifrs15):
    response, audited = await ifrs15.ask(answer("contract liability", "over time", "time elapsed"))
    text = response.answer.text
    assert "contract liability" in text and "over time" in text and "time elapsed" in text
    assert response.answer.completeness == audited.completeness == "complete"
    assert [c.title for c in response.answer.citations] == ["IFRS 15 — official text (IFRS Foundation)"]


async def test_the_verifier_sees_the_whole_cited_excerpt(ifrs15):
    # Support for "time elapsed" and the prepayment rule sits past the first
    # 1,500 characters; cut there, both claims were "not in evidence".
    assert len(STANDARD_EXCERPT) > 2000
    await ifrs15.ask(answer("contract liability", "over time", "time elapsed"))
    assert ifrs15.shown and all(SUPPORT["time elapsed"] in " ".join(e.split()) for e in ifrs15.shown)


async def test_an_unsupported_claim_is_removed_and_the_rest_kept(ifrs15):
    response, audited = await ifrs15.ask(answer("contract liability", "over time", "on day one"))
    text = response.answer.text
    assert "on day one" not in text                                   # never shown as verified
    assert "contract liability" in text and "over time" in text      # supported content kept
    assert any("do not support were removed" in item for item in response.answer.limitations)
    assert response.answer.completeness == audited.completeness == "partial"


async def test_a_wholly_unsupported_answer_is_not_presented_as_an_answer(ifrs15):
    response, audited = await ifrs15.ask(answer("on day one"))
    assert "on day one" not in response.answer.text
    assert response.answer.completeness == audited.completeness == "none"
    assert response.answer.citations == []


# ── The excerpt the answer is built and checked from ───────────────────────

AGENDA = ("[IFRIC® Update, March 2025, Agenda Decision, 'Revenue from tuition fees' The Committee received a "
          "request about an educational institution that recognises revenue from tuition fees over time under "
          "IFRS 15 for a service contract. Findings and conclusion: no diversity was found.]")
STANDARD_TEXT = (
    "3 | An entity shall consider all relevant facts and circumstances when applying this Standard.\n"
    "B4: (b);\n"
    "31 | An entity shall recognise revenue when (or as) the entity satisfies a performance obligation by "
    "transferring a promised service to a customer.\n"
    + AGENDA + "\n"
    "B44 | Upon receipt of a prepayment from a customer, an entity shall recognise a contract liability for the "
    "amount of the prepayment.\n"
    "C8A | An entity shall apply the clarifications retrospectively.\n"
)


def test_the_excerpt_prefers_requirements_to_agenda_commentary_and_fragments():
    excerpt = official_standards.best_passages(
        STANDARD_TEXT, "IFRS 15 advance payment contract liability revenue recognised over time service contract", 400)
    assert "shall recognise a contract liability" in excerpt
    assert "B4: (b);" not in excerpt
    # Commentary is not excluded, only outranked by the requirements.
    assert excerpt.index("contract liability") >= 0 and "tuition" not in excerpt.split(" … ")[0]


def test_framing_words_and_the_standards_name_do_not_choose_the_passage():
    excerpt = official_standards.best_passages(STANDARD_TEXT, QUESTION, 260)
    assert "all relevant facts" not in excerpt
    assert "tuition" not in excerpt


def test_everyday_wording_reaches_the_recognition_rule():
    # "Receives £120,000 upfront … revenue recognition" shares no word with
    # ¶31; the concept terms let the official ¶31 be selected, not invented.
    excerpt = official_standards.best_passages(STANDARD_TEXT, QUESTION, 400)
    assert "31 | An entity shall recognise revenue when (or as) the entity satisfies a performance obligation" in excerpt
    assert "shall recognise a contract liability" in excerpt


def test_concept_terms_only_add_words_for_matching_questions():
    assert official_standards._concept_terms("What is the VAT threshold?") == ""
    assert "prepayment" in official_standards._concept_terms("The customer paid £10,000 in advance.")

"""Mixed-intent reliability and jurisdiction safety (phase approved
2026-10-16): each part of a mixed request is kept and answered on its own,
arithmetic is not cited to a research source, VAT inputs given earlier are
not asked for again, and a source for one jurisdiction cannot substantiate a
claim about another."""
import json
import re
from types import SimpleNamespace as N

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import claim_verification, intent_planner, service
from app.orchestration.input_requirements import missing_vat_inputs
from app.orchestration.source_taxonomy import detect_jurisdictions, source_jurisdiction
from app.orchestration.verification_service import _jurisdiction_mismatch, unbind_arithmetic_citations, verify_for_release
from app.orchestration.websearch import WebSource
from tests.test_answer_status_pipeline import pipeline  # noqa: F401 — full-pipeline fixture

MIXED_VAT = ("Calculate the VAT on £2,400 of UK standard-rated sales at 20%, excluding VAT, and tell me when the "
             "quarterly VAT return is due.")


# ── 1. Mixed-question decomposition ────────────────────────────────────────

@pytest.mark.parametrize("question, kinds", [
    (MIXED_VAT, ["tax_calculation", "research_tax"]),
    ("Calculate straight-line depreciation on a £50,000 machine with a £5,000 residual value over 5 years, and "
     "explain what IAS 16 says about reviewing the useful life.", ["calculation", "research_standard"]),
    ("Revenue is £50,000 and cost of sales is £30,000. Calculate the gross margin, and tell me the ONS-published "
     "average gross margin for UK independent cafés in 2025.", ["calculation", "live_data"]),
])
def test_each_part_has_its_own_kind_needs_and_status(question, kinds):
    parts = service.request_parts(question, calculated=True)
    assert [part["kind"] for part in parts] == kinds
    calculation, research = parts
    assert calculation["status"] == "calculated_and_verified" and not calculation["needs_evidence"]
    assert research["status"] == "needs_evidence" and research["needs_evidence"]
    assert "calculate" not in research["tools"]


async def test_the_agent_is_told_to_keep_the_verified_part_when_another_lacks_evidence(pipeline):
    pipeline.answers(AgentOutcome(text="VAT = £480. The sources provided do not state the return deadline."))
    response, audited = await pipeline.ask(MIXED_VAT)
    prompt = pipeline.agent.await_args.args[0]
    assert "This request has 2 separate parts" in prompt and "£480.00" in prompt
    assert "never removes the answer to another part" in prompt
    assert "£480" in response.answer.text and audited.completeness == "partial"


# ── 2. VAT inputs already given are not asked for again ────────────────────

def test_vat_inputs_from_an_earlier_turn_are_used():
    earlier = [N(role="user", content="We are a UK business; all our sales are standard-rated at 20% and the "
                                      "figures exclude VAT.")]
    question = "Our sales were £120,000 and purchases £48,000 this quarter. How much VAT do I owe?"
    assert missing_vat_inputs(question) is not None
    assert missing_vat_inputs(question, earlier) is None


def test_an_assistant_turn_does_not_count_as_the_users_input():
    earlier = [N(role="assistant", content="Assuming 20% and figures excluding VAT…")]
    assert missing_vat_inputs("Sales £120,000 and purchases £48,000. How much VAT do I owe?", earlier) is not None


def test_a_dollar_amount_still_needs_a_country():
    assert "country" in missing_vat_inputs("Calculate VAT on $5,000 at 20%")


# ── 3. Citation binding ────────────────────────────────────────────────────

def test_arithmetic_on_the_users_figures_carries_no_research_citation():
    # ps-mixed-vat-and-deadline (qry-2d0815b0c030): "£2,400 × 20 % = £480 [REF-3]".
    answer = "**VAT amount**\n£2,400 × 20 % = £480 [REF-3]\nThe standard rate of VAT is 20% [REF-1]."
    assert unbind_arithmetic_citations(answer, MIXED_VAT) == (
        "**VAT amount**\n£2,400 × 20 % = £480\nThe standard rate of VAT is 20% [REF-1].")


def test_arithmetic_on_figures_the_user_never_gave_keeps_its_citation():
    assert unbind_arithmetic_citations("£9,999 × 20% = £1,999.80 [REF-2]", MIXED_VAT).endswith("[REF-2]")


# ── 4. Jurisdiction mismatch ───────────────────────────────────────────────

ISLE_OF_MAN = "What exact VAT registration threshold applied in the Isle of Man in 1987?"


@pytest.mark.parametrize("question, expected", [
    (ISLE_OF_MAN, ["ISLE_OF_MAN"]),
    ("VAT in Jersey", ["JERSEY"]),
    ("Compare the UK and Isle of Man VAT thresholds", ["UK", "ISLE_OF_MAN"]),
    ("What is the VAT threshold?", ["UK"]),          # unchanged: bare VAT still means the UK
    ("New Jersey sales tax", []),                    # not the Crown Dependency
])
def test_crown_dependencies_are_their_own_jurisdictions(question, expected):
    assert detect_jurisdictions(question) == expected


def test_a_source_jurisdiction_comes_from_its_authority():
    assert source_jurisdiction("https://www.gov.uk/hmrc-internal-manuals/vat-registration-manual/vatreg04100") == "UK"
    assert source_jurisdiction("https://www.irs.gov/x") == "US"
    assert source_jurisdiction("https://www.ifrs.org/x") is None       # global standard-setter
    assert source_jurisdiction("https://example.com/x") is None        # unknown: never a mismatch


UK_TABLE = "[REF-1] HMRC registration limits: 18/03/1987 to 15/03/1988 annual limit 21,300."


@pytest.mark.parametrize("claim, question, evidence, mismatch", [
    # The live failure: a UK table cited for the Isle of Man.
    ("18 Mar 1987 – 15 Mar 1988: annual threshold £21,300 [REF-1]", ISLE_OF_MAN, UK_TABLE, "UK"),
    # Labelled as the UK's: a comparison or caveat, allowed.
    ("In the UK the threshold was £21,300 from 18 March 1987 [REF-1]", ISLE_OF_MAN, UK_TABLE, None),
    # The source itself says it covers the Isle of Man: shared rules shown by evidence.
    ("The threshold was £21,300 [REF-1]", ISLE_OF_MAN,
     "[REF-1] These limits apply in the UK and the Isle of Man alike: annual limit 21,300.", None),
    # A UK question answered from a UK source.
    ("The threshold was £21,300 [REF-1]", "What was the UK VAT threshold in 1987?", UK_TABLE, None),
    # A comparison that asks about both.
    ("The UK threshold was £21,300 [REF-1]", "Compare the UK and Isle of Man VAT thresholds in 1987", UK_TABLE, None),
])
def test_a_source_for_one_jurisdiction_cannot_answer_for_another(claim, question, evidence, mismatch):
    found = _jurisdiction_mismatch(claim, {"REF-1"}, question_jurisdictions=detect_jurisdictions(question),
                                   source_jurisdictions={"REF-1": "UK"}, evidence_by_ref={"REF-1": evidence})
    assert found == mismatch


@pytest.mark.parametrize("claim,mismatch", [
    ("The ECB reference rate was 1 GBP = 1.3246661 USD [REF-1].", None),
    ("An executable bank quote includes the bank's spread and settlement terms [REF-1].", None),
    ("The exchange rate must be used for UK VAT returns [REF-1].", "EU"),
])
def test_foreign_publisher_can_supply_fx_data_but_not_local_tax_rules(claim, mismatch):
    assert _jurisdiction_mismatch(
        claim, {"REF-1"}, question_jurisdictions=["UK"],
        source_jurisdictions={"REF-1": "EU"}, evidence_by_ref={"REF-1": "ECB reference rates"},
    ) == mismatch


@pytest.fixture
def supportive_verifier(monkeypatch):
    """A verifier that would accept every claim: the jurisdiction rule must
    reject a mismatch before any model judgement."""
    async def complete_auxiliary(*, user, **_):
        claims = re.findall(r"^(\d+)\. ", user.split("\n\nCLAIMS:\n", 1)[1], re.M)
        return N(text=json.dumps({"results": [{"claim": int(n), "verdict": "supported", "references": ["REF-1"],
                                               "evidence_says": ""} for n in claims]}))
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(claim_verification, "gateway", N(may_use=lambda *a, **k: True, complete_auxiliary=complete_auxiliary))


async def test_the_release_check_rejects_a_mismatched_claim_even_if_the_verifier_would_accept_it(supportive_verifier):
    answer = "- 18 Mar 1987 – 15 Mar 1988: annual threshold £21,300 [REF-1]"
    check = await verify_for_release(answer, question=ISLE_OF_MAN, evidence=[UK_TABLE], requires_authority=True,
                                     source_jurisdictions={"REF-1": "UK"})
    assert not check.passed and check.rejected_reasons == ["jurisdiction_mismatch"]
    same = await verify_for_release(answer, question="What was the UK VAT threshold in 1987?", evidence=[UK_TABLE],
                                    requires_authority=True, source_jurisdictions={"REF-1": "UK"})
    assert same.passed


async def test_the_isle_of_man_case_says_the_rule_could_not_be_confirmed(pipeline, supportive_verifier):
    # int-insufficient-evidence-obscure (qry-b01cc471dbaf): UK thresholds presented for the Isle of Man.
    uk = WebSource(title="VATREG04100 - Registration thresholds", url="https://www.gov.uk/hmrc-internal-manuals/"
                   "vat-registration-manual/vatreg04100",
                   snippet="19/03/1986 to 17/03/1987 annual limit 20,500. 18/03/1987 to 15/03/1988 annual limit 21,300.")
    pipeline.answers(AgentOutcome(text="- 19 Mar 1986 – 17 Mar 1987: annual threshold £20,500 [REF-1]\n"
                                       "- 18 Mar 1987 – 15 Mar 1988: annual threshold £21,300 [REF-1]", sources=[uk]))
    response, audited = await pipeline.ask(ISLE_OF_MAN)
    assert "£21,300" not in response.answer.text
    assert any("cover UK rules, not Isle Of Man" in item for item in response.answer.limitations)
    assert audited.completeness in ("partial", "none")
    removed = service.audit_answer_statements_removed.await_args.kwargs["stages"]
    assert {e["reason_code"] for stage in removed for e in stage["removed"]} == {"jurisdiction_mismatch"}


# ── Planner (shadow only): each sub-task carries its own needs ─────────────

def test_planner_sub_tasks_carry_evidence_tools_and_missing_inputs():
    schema = intent_planner._strict_schema()["$defs"]["SubTask"]
    assert set(schema["required"]) >= {"kind", "text", "needs_evidence", "tools", "missing_inputs"}
    assert "tax_calculation, never calculation" in intent_planner._SYSTEM


async def test_a_verified_result_needs_no_source_but_a_rate_claim_still_does(supportive_verifier):
    from app.orchestration.calculations.engine import calculate_from_query
    from app.orchestration.verification_service import calculated_figures
    calculated = calculated_figures(calculate_from_query(MIXED_VAT))
    result_only = await verify_for_release("VAT = £480. The sources provided do not state the return deadline.",
                                           question=MIXED_VAT, evidence=[], requires_authority=True,
                                           calculated=calculated)
    assert result_only.passed
    rate_claim = await verify_for_release("The standard rate of VAT is 20%.", question=MIXED_VAT, evidence=[],
                                          requires_authority=True, calculated=calculated)
    assert not rate_claim.passed            # a rule still needs evidence, even when its figure matches
    invented = await verify_for_release("VAT = £512.", question=MIXED_VAT, evidence=[], requires_authority=True,
                                        calculated=calculated)
    assert not invented.passed              # a figure the calculator did not produce is not exempt


async def test_a_refused_calculator_is_explained_and_not_offered_again():
    # ps-std-depreciation-method-change (qry-770e2b245429): eight refused calculate calls, then out of steps.
    from pydantic import BaseModel
    from app.domains.model_gateway.agent import run_agent
    from app.domains.model_gateway.tool_registry import PolicyDecision, ToolRegistry, ToolResult, ToolSpec
    from tests.test_agent_loop import ScriptedClient, _call, _reply

    class _Args(BaseModel):
        query: str = ""

    async def ok(args):
        return ToolResult(ok=True, content="IAS 16 ¶61: a change of method is a change in estimate.")
    registry = ToolRegistry()
    for name in ("calculate", "search_web"):
        registry.register(ToolSpec(name=name, version="1", description=name, args_model=_Args, handler=ok,
                                   data_source="t", risk_level="low", timeout_seconds=1.0))

    async def authorize(tool):
        allowed = tool != "calculate"
        return PolicyDecision(decision_id="pd", tool=tool, allowed=allowed,
                              reason_code="allowed" if allowed else "no_user_figures", role="Admin")
    client = ScriptedClient([_reply(tool_calls=[_call("calculate", {"query": "100000 * 0.2"})]),
                             _reply(tool_calls=[_call("search_web", {"query": "IAS 16 change of method"}, "c2")]),
                             _reply("A change of depreciation method is a change in accounting estimate.")])
    await run_agent(client, model="m", system_prompt="", user_prompt="Can we switch depreciation method?",
                    registry=registry, granted_permissions=frozenset(), authorize=authorize)
    refusal = client.requests[1]["messages"][-1]["content"]
    assert "Do not call calculate again" in refusal and "search tools" in refusal
    offered = [t["function"]["name"] for t in client.requests[1]["tools"]]
    assert "calculate" not in offered and "search_web" in offered

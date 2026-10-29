"""Root causes behind answers losing content (24 Oct 2026).

A week of audit records: 671 answers, 13% lost statements, 328 removed, and
only 9 of them because a source contradicted them. The rest were removed as
unverified, mostly never looked for:

1. Kriton removed instead of repairing: one search on the question, then any
   figure beyond it was removed, including a VAT rate its own knowledge base
   states six times. The correction round said "calculate or remove".
2. Checks were per statement, not per answer: fragments ("must register for
   VAT.") survived partial removals, and an example's arithmetic on an assumed
   rate was removed as a rate claim.
3. Nobody measured quality across all answers: scripts/answer_quality_report.py.
No model, database or network.
"""
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.domains.model_gateway.agent import AgentLimits, _backfill_queries, run_agent
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec
from app.orchestration.claim_verification import remove_claims
from app.orchestration.derived_output import derived_output_instructions, is_scenario_sentence
from app.orchestration.websearch import WebSource
from tests.test_agent_loop import ScriptedClient, _reply


class _QueryArgs(BaseModel):
    query: str


def _kb(executed: list[str], *, states: dict[str, str]) -> ToolRegistry:
    """A knowledge base that returns a passage when the query mentions one of
    `states`' keys, and nothing otherwise."""
    registry = ToolRegistry()

    async def search(args: _QueryArgs) -> ToolResult:
        executed.append(args.query)
        for key, passage in states.items():
            if key.lower() in args.query.lower():
                return ToolResult(ok=True, content=passage, sources=(
                    WebSource(title="VAT rates", url="https://www.gov.uk/guidance/rates-of-vat", snippet=passage),))
        return ToolResult.failure("no_data", "No results.")
    registry.register(ToolSpec(name="search_knowledge_base", version="1", description="Search.", args_model=_QueryArgs,
                               handler=search, data_source="test", risk_level="low", timeout_seconds=1))
    return registry


async def _run(replies, registry):
    client = ScriptedClient(replies)
    outcome = await run_agent(client, model="m", system_prompt="sys", user_prompt="what is tax", registry=registry,
                              granted_permissions=frozenset(), limits=AgentLimits())
    return client, outcome


# ── 1. Repair before removal ─────────────────────────────────────────────

async def test_an_unverified_rate_the_knowledge_base_states_is_found_and_kept():
    searched = []
    client, outcome = await _run(
        [_reply("Most goods and services in the UK carry VAT at the standard rate of 20%.")],
        _kb(searched, states={"VAT": "The standard rate of VAT is 20%. Most goods and services are charged at it."}))
    assert searched and "VAT" in searched[0]                      # Kriton looked for it itself
    assert "20%" in outcome.text and not outcome.unreconciled_figures
    assert len(client.requests) == 1                              # no correction round needed
    assert any(record.tool == "search_knowledge_base" for record in outcome.tool_calls)   # audited like any call


async def test_when_the_source_is_not_found_the_reminder_offers_the_search():
    searched = []
    client, _outcome = await _run(
        [_reply("The levy is charged at 37% on such supplies."), _reply("The levy applies to such supplies.")],
        _kb(searched, states={}))
    assert searched                                               # the repair search ran first
    reminder = client.requests[1]["messages"][-1]["content"]
    assert "search_knowledge_base first" in reminder and "Remove a figure only when none of these works" in reminder
    assert "assume a 20% rate for this illustration" in reminder
    offered = {tool["function"]["name"] for tool in client.requests[1].get("tools") or []}
    assert "search_knowledge_base" in offered


async def test_the_repair_searches_at_most_three_statements():
    searched = []
    text = "\n".join(f"Item {i} is taxed at {10 + i}%." for i in range(6))
    await _run([_reply(text), _reply("Items are taxed.")], _kb(searched, states={}))
    assert len(searched) == 3


def test_repair_queries_are_the_statements_without_markup():
    queries = _backfill_queries("**VAT** is charged at **20%** on most supplies [REF-2].", ["20%"])
    assert queries == ["VAT is charged at 20% on most supplies ."] or queries == ["VAT is charged at 20% on most supplies."]


# ── 2. Examples keep their working; fragments go ─────────────────────────

@pytest.mark.parametrize("sentence, scenario", [
    ("Assume a VAT rate of 20% for this illustration.", True),
    ("Output VAT = £90,000 × 20% = £18,000", True),
    ("Net VAT payable = £18,000 − £6,000 = £12,000", True),
    ("The UK standard VAT rate is 20%.", False),
    ("The current rate is 20%, so VAT = £90,000 × 20% = £18,000", False),
    ("Businesses must register when turnover exceeds £90,000.", False),
    ("VAT at 20% applies [REF-3].", False),
])
def test_an_assumed_rate_and_the_examples_arithmetic_are_scenario(sentence, scenario):
    assert is_scenario_sentence(sentence) is scenario


def test_a_fragment_left_by_a_removal_goes():
    text = ("### Registration status\n"
            "Because taxable turnover of £95,000 exceeds the £90,000 threshold, GreenTech must register for VAT.\n"
            "### Tax point\nThe tax point is the date of supply.")
    out = remove_claims(text, ["Because taxable turnover of £95,000 exceeds the £90,000 threshold, GreenTech"])
    assert "must register for VAT." not in out and "The tax point is the date of supply." in out


@pytest.mark.parametrize("line", ["The tax point is the date of supply. Goods were sent on 3 March.",
                                  "- VAT is charged on the tax value.", "2. Register by the deadline."])
def test_complete_sentences_are_kept(line):
    assert remove_claims(line + "\nOther.", ["Other."]).strip() == line


def test_the_example_instruction_covers_the_previous_comparison_and_relevance():
    text = derived_output_instructions("Explain this comparison with a grounded example. Context: what is tax")
    assert "\"this comparison\" means the comparison in your previous answer" in text
    assert "state the rate as an assumption" in text and "leave out guidance the sources happen to contain" in text


# ── 3. Quality measured across every answer ──────────────────────────────

spec = importlib.util.spec_from_file_location(
    "answer_quality_report", Path(__file__).resolve().parents[1] / "scripts" / "answer_quality_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

KNOWLEDGE = ["the standard rate of vat is 20%. most goods and services are charged at it."]
PAYLOADS = [
    {"completeness": "partial", "stages": [{"stage": "figure_reconciliation", "removed_count": 3, "removed": [
        {"excerpt": "UK VAT is charged at 20% on most goods.", "reason_code": "figure_unreconciled"},
        {"excerpt": "Output VAT = 90,000 × 20% = 18,000", "reason_code": "figure_unreconciled"},
        {"excerpt": "The levy is 37% on imports.", "reason_code": "figure_unreconciled"}]}]},
    {"completeness": "partial", "stages": [{"stage": "release_prune", "removed_count": 2, "removed": [
        {"excerpt": "Corporate income tax is levied on net profit.", "reason_code": "not_in_cited_evidence"},
        {"excerpt": "UK VAT is charged at 20% on most goods.", "reason_code": "missing_citation"}]}]},
    {"completeness": "none", "stages": [{"stage": "contradiction_removal", "removed_count": 1, "removed": [
        {"excerpt": "The threshold is £85,000.", "reason_code": "contradicted_by_cited_source"}]}]},
]


def test_the_report_counts_answers_removals_and_reasons():
    summary = report.summarise(20, PAYLOADS, KNOWLEDGE)
    assert (summary["answers"], summary["answers_with_removals"], summary["statements_removed"]) == (20, 3, 6)
    assert summary["by_reason"]["figure_unreconciled"] == 3 and summary["completeness"]["partial"] == 2


def test_the_report_says_what_kriton_could_have_verified_itself():
    kinds = report.summarise(20, PAYLOADS, KNOWLEDGE)["by_kind"]
    assert kinds["a rate Kriton's knowledge base states (a search would verify it)"] == 2
    assert kinds["hand-worked arithmetic (the calculator could verify it)"] == 1
    assert kinds["a rate the knowledge base does not state"] == 1
    assert kinds["a statement with no source in hand (never searched for)"] == 1
    assert kinds["shown wrong by a cited source"] == 1


def test_the_report_lists_statements_removed_more_than_once():
    summary = report.summarise(20, PAYLOADS, KNOWLEDGE)
    assert summary["most_removed"] == [("UK VAT is charged at 20% on most goods.", 2)]
    text = report.render(summary, 7)
    assert "with statements removed: 3 (15%)" in text and "2×  UK VAT is charged at 20%" in text


def test_the_report_needs_a_postgres_url_and_never_writes(tmp_path, capsys):
    env = tmp_path / "env"
    env.write_text("DATABASE_URL=sqlite:///x.db\n")
    assert report.main(["--env", str(env)]) == 2
    source = (Path(__file__).resolve().parents[1] / "scripts" / "answer_quality_report.py").read_text()
    assert "default_transaction_read_only=on" in source and "readonly=True" in source
    assert not any(word in source.upper() for word in ("INSERT ", "UPDATE ", "DELETE ", "DROP "))


# ── Re-test, 24 Oct 2026: the example still lost its figures; "what is tax"
#    still lost the VAT rates ─────────────────────────────────────────────

import inspect

from app.orchestration import service as service_module
from app.orchestration.figure_reconciliation import statements_with_figures, unreconciled_figures

# The grounded example's lines, as the audit log recorded their removal.
RETEST = """### Illustrative example (hypothetical figures)
- **Turnover**: £950 000 (VAT‑taxable).
- **Cost of goods sold**: £600 000 (includes £50 000 of VAT‑inclusive purchases).
- **Profit before tax**: £150 000.
- **Corporate tax rate**: 19 % (assumed for illustration).
- **VAT rate**: 20 % (assumed for illustration).

| Tax | Formula | Calculation | Explanation |
|---|---|---|---|
| **VAT output tax** | Turnover × 20 % | £950 000 × 0.20 = £190 000 | VAT output tax is the VAT due on taxable supplies [REF-3] |
| **VAT payable** | Output – Input | £190 000 – £50 000 = £140 000 | Net VAT payable is output minus input |
"""
CHIP = "Explain this comparison with a grounded example. Context: what is tax"


def test_a_checked_line_may_work_from_the_examples_own_givens():
    assert unreconciled_figures(RETEST, "Tax is a compulsory levy.\n" + CHIP, "", stated=CHIP) == []


def test_a_scenario_line_is_never_removed_with_a_failed_figure():
    assert statements_with_figures(RETEST, ["£950,000"]) == [
        "| **VAT output tax** | Turnover × 20 % | £950 000 × 0.20 = £190 000 | VAT output tax is the VAT due on "
        "taxable supplies [REF-3] |"]


def test_a_real_rate_stated_in_an_example_is_still_checked():
    text = ("### Illustrative example (hypothetical figures)\n- **VAT rate**: 20 % (assumed for illustration).\n\n"
            "The UK standard VAT rate is 17.5% [REF-2].")
    assert unreconciled_figures(text, "x", "", stated=CHIP) == ["17.5%"]


async def test_a_simple_answer_looks_its_figures_up_before_removal(monkeypatch):
    from app.domains.model_gateway.tools import kb_tool
    from app.orchestration import governed_retrieval
    from app.orchestration.service import _figure_repair_evidence
    seen = []

    async def handle(args):
        seen.append((args.query, governed_retrieval.current_context()))
        return ToolResult(ok=True, content="The standard rate of VAT is 20%; the reduced rate is 5%.")
    monkeypatch.setattr(kb_tool, "_handle", handle)
    context = object()
    found = await _figure_repair_evidence(
        "| **VAT** | A tax on sales | UK: standard 20 %, reduced 5 % |\nOther 7 % row |", ["20 %", "5 %", "7 %"],
        context, 30)
    assert "standard rate of VAT is 20%" in found
    assert len(seen) == 2 and all(bound is context for _, bound in seen)   # at most two, under the request's context
    assert governed_retrieval.current_context() is None                    # and unbound afterwards


async def test_the_look_up_stops_at_its_time_budget(monkeypatch):
    from app.domains.model_gateway.tools import kb_tool
    from app.orchestration.service import _figure_repair_evidence

    async def never(args):
        raise AssertionError("searched with no time left")
    monkeypatch.setattr(kb_tool, "_handle", never)
    assert await _figure_repair_evidence("VAT is 20 %.", ["20 %"], object(), 2) == ""


def test_the_service_looks_up_only_when_the_agent_did_not():
    source = inspect.getsource(service_module)
    assert "agent_outcome is None and repair_seconds >= 5" in source
    assert source.index("_figure_repair_evidence(") < source.index("figure_statements = statements_with_figures(")



# ── The model is chosen by the work, not the risk (24 Oct 2026) ───────────

from app.orchestration.service import needs_reasoning


@pytest.mark.parametrize("question", [
    "Explain this comparison with a grounded example. Context: what is tax",   # the example that went wrong
    "Highlight the most important differences. Context: what is tax",
    "Give me an example of VAT on a £10,000 sale",
    "Calculate corporation tax on profits of 150,000",
    "What journal entries record a deferred tax asset?",
    "How do I account for a finance lease?",
    "IFRS 16 versus ASC 842",
    "What is a 20% VAT rate applied to?",
])
def test_reasoning_work_keeps_the_full_model(question):
    assert needs_reasoning(question)


@pytest.mark.parametrize("question", ["what is tax", "hello", "What does IFRS stand for?", "What is IFRS 16?",
                                      "Who issues IFRS standards?", "What is the tax point?"])
def test_plain_definitions_may_use_the_fast_model(question):
    assert not needs_reasoning(question)


def test_the_fast_model_is_chosen_only_without_reasoning_work():
    # The full decision is tested in test_answer_model_routing.py.
    assert "answer_model_route(" in inspect.getsource(service_module.ask_kriton)


def test_the_example_must_agree_with_its_own_rules():
    text = derived_output_instructions("Explain this with a worked example. Context: VAT")
    assert "tax a business collects for the state is a liability, not its cost" in text
    assert "its payment as a separate entry" in text and "say whether each amount includes tax" in text

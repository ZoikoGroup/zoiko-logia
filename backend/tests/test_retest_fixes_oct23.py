"""Offline fixes after the 23 Oct 2026 live retest (port 8011). No model calls.

A. Repeated searches: the hedge and inventory runs each made two web searches
   for the same point, both empty; the hedge ran out of time.
B. Dependent calculations: batching worked, but a batch item could not use an
   earlier item's result, so the Brazil chain (PPP rates → dollar cash flows →
   present values → NPV) took one call per stage and reached the step limit.
C. Grader: "400 000" was not read as 400,000.
"""
import json
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.domains.model_gateway.agent import (
    REPEAT_SEARCH_GUIDANCE, AgentLimits, _query_terms, _repeats_empty_search, run_agent,
)
from app.domains.model_gateway.tool_registry import ToolRegistry, ToolResult, ToolSpec, build_default_registry
from app.domains.model_gateway.tools.calc_tool import CALCULATE_BATCH_TOOL, CalculateBatchArgs
from app.orchestration.calculation_service import evaluate_expression
from app.orchestration.websearch import WebSource
from tests.answer_key import grade, normalise_numbers
from tests.test_agent_loop import ScriptedClient, _call, _reply


# ── A. A rephrased search after an empty one is not run again ────────────────

class _QueryArgs(BaseModel):
    query: str


def _search_registry(executed: list[tuple[str, str]], *, found: tuple[str, ...] = ()) -> ToolRegistry:
    """search_web and search_knowledge_base stand-ins: nothing found unless
    the query contains one of `found`."""
    registry = ToolRegistry()
    for name in ("search_web", "search_knowledge_base"):
        async def search(args: _QueryArgs, name: str = name) -> ToolResult:
            executed.append((name, args.query))
            if any(word in args.query for word in found):
                source = WebSource(title="ASC 606-10-55-83", url="https://asc.fasb.org/606", snippet="Bill-and-hold.")
                return ToolResult(ok=True, content="Bill-and-hold criteria.", sources=(source,))
            return ToolResult.failure("no_data", "No results.")
        registry.register(ToolSpec(name=name, version="1", description="Search.", args_model=_QueryArgs,
                                   handler=search, data_source="test", risk_level="low", timeout_seconds=1))
    return registry


async def _run(replies, registry, **hooks):
    client = ScriptedClient(replies)
    outcome = await run_agent(client, model="m", system_prompt="sys", user_prompt="question", registry=registry,
                              granted_permissions=frozenset(), limits=AgentLimits(), **hooks)
    return client, outcome


HEDGE_1 = "ASC 815 cash flow hedge forecasted purchase journal entries"
HEDGE_2 = "journal entries for a cash flow hedge of a forecasted purchase under ASC 815"


async def test_a_rephrased_search_after_an_empty_one_is_not_run():
    executed, done = [], []

    async def on_done(record):
        done.append(record)

    client, outcome = await _run([
        _reply(tool_calls=[_call("search_web", {"query": HEDGE_1}, "c1")]),
        _reply(tool_calls=[_call("search_web", {"query": HEDGE_2}, "c2")]),
        _reply("Answer from professional knowledge."),
    ], _search_registry(executed), on_tool_done=on_done)
    assert executed == [("search_web", HEDGE_1)]
    assert [r.error_code for r in outcome.tool_calls] == ["no_data", "repeat_search"]
    # Still audited, like every other refused or failed call.
    assert len(done) == 2 and done[1].tool == "search_web" and done[1].source_count == 0
    assert REPEAT_SEARCH_GUIDANCE in client.requests[2]["messages"][-1]["content"]


async def test_a_search_for_a_different_point_still_runs():
    executed = []
    _client, outcome = await _run([
        _reply(tool_calls=[_call("search_web", {"query": HEDGE_1}, "c1")]),
        _reply(tool_calls=[_call("search_web", {"query": "ASC 606 bill-and-hold criteria for revenue"}, "c2")]),
        _reply("Done."),
    ], _search_registry(executed, found=("bill-and-hold",)))
    assert [query for _, query in executed] == [HEDGE_1, "ASC 606 bill-and-hold criteria for revenue"]
    assert [r.error_code for r in outcome.tool_calls] == ["no_data", None] and len(outcome.sources) == 1


async def test_only_an_empty_search_blocks_its_rephrasing():
    executed = []
    first = "ASC 606 bill-and-hold criteria"
    second = "bill-and-hold criteria under ASC 606 for a manufacturer"
    _client, outcome = await _run([
        _reply(tool_calls=[_call("search_web", {"query": first}, "c1")]),
        _reply(tool_calls=[_call("search_web", {"query": second}, "c2")]),
        _reply("Done."),
    ], _search_registry(executed, found=("bill-and-hold",)))
    assert len(executed) == 2 and [r.error_code for r in outcome.tool_calls] == [None, None]


async def test_an_empty_knowledge_base_search_does_not_block_the_web_search():
    executed = []
    _client, outcome = await _run([
        _reply(tool_calls=[_call("search_knowledge_base", {"query": HEDGE_1}, "c1")]),
        _reply(tool_calls=[_call("search_web", {"query": HEDGE_1}, "c2")]),
        _reply("Done."),
    ], _search_registry(executed))
    assert [name for name, _ in executed] == ["search_knowledge_base", "search_web"]
    assert [r.error_code for r in outcome.tool_calls] == ["no_data", "no_data"]


@pytest.mark.parametrize("earlier, later, repeat", [
    (HEDGE_1, HEDGE_2, True),
    # Singular for plural, reordered: the same search.
    (HEDGE_1, "forecasted purchase journal entry ASC 815 cash flow hedge", True),
    # Fewer terms is a broader search that may find what the narrow one did not.
    (HEDGE_1, "ASC 815 cash flow hedge journal entry", False),
    ("ASC 606 bill-and-hold criteria for revenue", "bill-and-hold criteria ASC 606", False),
    # Irregular plurals are not merged: one extra search, never a lost one.
    ("ASC 606 bill-and-hold criteria", "bill-and-hold criterion ASC 606", False),
    ("PCAOB AS 2501 approaches auditing accounting estimates", "AS 2501 three approaches to audit an estimate", False),
    ("inventory bill and hold FOB destination year end", "FOB destination goods in transit inventory cut-off", False),
    (HEDGE_1, "ASC 470-60 troubled debt restructuring debtor gain", False),
    ("AS 2501 approaches", "AS 1301 communications with audit committees", False),
])
def test_what_counts_as_the_same_point(earlier, later, repeat):
    empty = [_query_terms(json.dumps({"query": earlier}))]
    assert _repeats_empty_search(_query_terms(json.dumps({"query": later})), empty) is repeat


# ── B. Dependent calculations in one batched call ─────────────────────────────

BRAZIL_CHAIN = (
    [{"id": f"s{t}", "label": f"Spot rate year {t} (BRL/USD)", "expression": f"5 * (1.06 / 1.025) ** {t}"}
     for t in range(1, 5)]
    + [{"id": f"p{t}", "label": f"PV of year {t} cash flow (USD)", "expression": f"3500000 / {{s{t}}} / 1.1 ** {t}"}
       for t in range(1, 5)]
    + [{"id": "npv", "label": "NPV (USD)", "expression": "{p1} + {p2} + {p3} + {p4} - 10000000 / 5"}]
)
DIRECT_NPV = evaluate_expression(" + ".join(f"3500000 / (5 * (1.06 / 1.025) ** {t}) / 1.1 ** {t}" for t in range(1, 5))
                                 + " - 10000000 / 5")


async def _batch(items):
    return await CALCULATE_BATCH_TOOL.handler(CalculateBatchArgs(expressions=items))


async def test_a_dependent_chain_is_one_call_and_matches_the_direct_formula():
    result = await _batch(BRAZIL_CHAIN)
    assert result.ok and result.items_total == 9 and result.items_failed == 0
    npv = next(receipt for receipt in result.receipts if receipt.get("item_id") == "npv")
    assert Decimal(npv["result"]) == DIRECT_NPV.quantize(Decimal("0.000001"))
    # 49,838.94 exactly; the live answer's 49,838.92 came from rates rounded
    # to six places. The answer key accepts both (~49,839).
    assert abs(DIRECT_NPV - Decimal("49838.94")) < Decimal("0.01")
    assert npv["depends_on"] == ["p1", "p2", "p3", "p4"]
    assert npv["expression_template"] == "{p1} + {p2} + {p3} + {p4} - 10000000 / 5"
    # The receipt keeps the expression as evaluated, with the carried values.
    assert "{" not in npv["expression"] and npv["input_hash"]
    # Symbolic working preserves the distinction from rounded display values.
    assert "3500000 / {s1} / 1.1 ** 1 = " in result.content
    assert "References use earlier results before display rounding" in result.content
    assert not __import__("re").search(r"\d{15,}", result.content)


async def test_items_run_in_order_and_a_forward_reference_is_refused():
    result = await _batch([
        {"id": "a", "expression": "{b} * 2"},
        {"id": "b", "expression": "10 + 5"},
        {"expression": "{b} * 2"},
    ])
    assert result.ok and result.items_failed == 1
    lines = result.content.splitlines()
    assert "NOT COMPUTED (unresolved_reference)" in lines[0] and "{b}" in lines[0]
    assert [receipt["result"] for receipt in result.receipts] == ["15", "30"]


async def test_an_item_built_on_a_failed_item_is_not_computed():
    result = await _batch([
        {"id": "a", "expression": "100 / 0"},
        {"id": "b", "expression": "{a} + 1"},
        {"expression": "7 * 6"},
    ])
    assert result.ok and result.items_failed == 2 and [r["result"] for r in result.receipts] == ["42"]
    assert "unresolved_reference" in result.content.splitlines()[1]


def test_ids_must_be_unique_and_well_formed():
    with pytest.raises(ValueError):
        CalculateBatchArgs(expressions=[{"id": "a", "expression": "1"}, {"id": "a", "expression": "2"}])
    with pytest.raises(ValueError):
        CalculateBatchArgs(expressions=[{"id": "1bad", "expression": "1"}])


async def test_a_carried_value_keeps_precision_beyond_display():
    # 1/3 is carried at full precision, not the displayed 6 places.
    result = await _batch([{"id": "third", "expression": "1 / 3"}, {"expression": "{third} * 3000000"}])
    assert result.receipts[1]["result"] == "1000000"


async def test_independent_items_and_the_single_form_are_unchanged():
    single = await CALCULATE_BATCH_TOOL.handler(CalculateBatchArgs(expression="2 + 2", label="Four"))
    assert single.ok and single.receipt["result"] == "4" and "batch_index" not in single.receipt
    batch = await _batch([{"expression": "2 + 2"}, {"expression": "3 * 3"}])
    assert [r["result"] for r in batch.receipts] == ["4", "9"]
    assert all("depends_on" not in r and "item_id" not in r for r in batch.receipts)


def test_references_exist_only_in_the_batched_tool_which_stays_off_by_default():
    from app.core.config import Settings
    assert Settings.model_fields["AGENT_BATCH_CALCULATIONS"].default is False
    single_schema = json.dumps(build_default_registry().get("calculate").args_model.model_json_schema())
    assert "expressions" not in single_schema and "{s1}" not in single_schema
    batched_schema = json.dumps(build_default_registry(batch_calculations=True).get("calculate")
                                .args_model.model_json_schema())
    assert "{s1}" in batched_schema


async def test_the_chain_runs_in_one_agent_step():
    client = ScriptedClient([
        _reply(tool_calls=[_call("calculate", {"expressions": BRAZIL_CHAIN})]),
        _reply("NPV is $49,838.94."),
    ])
    outcome = await run_agent(client, model="m", system_prompt="sys", user_prompt="Brazil NPV",
                              registry=build_default_registry(batch_calculations=True),
                              granted_permissions=frozenset({"calculate"}), limits=AgentLimits())
    assert len(outcome.tool_calls) == 1 and outcome.tool_calls[0].ok
    assert len(outcome.calculation_receipts) == 9 and outcome.steps == 2


async def test_the_dependency_is_audited_by_id_and_the_expression_is_not():
    from app.orchestration import audit_events
    seen = {}

    async def emit(db, name, *args, **kwargs):
        seen[name] = args[-1]

    result = await _batch(BRAZIL_CHAIN)
    npv = next(receipt for receipt in result.receipts if receipt.get("item_id") == "npv")
    import unittest.mock
    with unittest.mock.patch.object(audit_events, "_emit", emit):
        await audit_events.audit_calculation_receipt(None, query_id="q", correlation_id="c", tenant_id="t",
                                                     audit_chain_id="a", actor_id="u", receipt=npv)
    payload = seen["calculation_receipt_recorded"]
    assert payload["item_id"] == "npv" and payload["depends_on"] == ["p1", "p2", "p3", "p4"]
    assert "expression" not in payload and "expression_template" not in payload


# ── C. The grader reads space-grouped numbers ─────────────────────────────────

@pytest.mark.parametrize("written, expected", [
    ("$400 000", "$400,000"),
    ("$7 900 000", "$7,900,000"),          # narrow no-break spaces
    ("306 353.6", "306,353.6"),                 # no-break space and a decimal
    ("−267 500", "−267,500"),                        # negative stays negative
    ("(400 000)", "(400,000)"),
    ("in 2027 100 barrels", "in 2027 100 barrels"),  # a year and a count stay two numbers
    ("400,000 and 1.25", "400,000 and 1.25"),
])
def test_space_grouped_numbers_are_read_as_one_number(written, expected):
    assert normalise_numbers(written) == expected


def test_the_live_hedge_answer_is_graded_on_its_values_not_their_format():
    live = ("| 31 Dec 2026 | Derivative – Fair Value (Asset) | $400 000 | – | Other Comprehensive Income (OCI) |\n"
            "Settlement gain = (78 – 75) × 100 000 = $300 000.\n"
            "Inventory cost = $7 500 000 + $400 000 = $7 900 000.\n"
            "Revenue = 95 × 100 000 = $9 500 000.")
    result = grade(live, "hedge")
    found = {"Dec 31 gain 400,000 in OCI", "settlement cash 300,000", "sales 9,500,000"}
    assert not found & set(result.missing)
    # Genuinely different values still fail: inventory 7,900,000 is not 7,800,000.
    assert "inventory 7,800,000" in result.missing and not result.passed


def test_a_different_number_is_never_matched():
    assert "tax payable 105,000" in grade("Tax payable is 105 001.", "nol_va").missing
    assert "tax payable 105,000" in grade("Tax payable is 1 105 000.", "nol_va").missing
    assert "tax payable 105,000" not in grade("Tax payable is 105 000.", "nol_va").missing


@pytest.mark.parametrize("earlier,later", [
    ("ASC 815 cash flow hedge journal entries", "ASC 815 cash flow hedge disclosure requirements"),
    ("ASC 815 cash flow hedge accounting", "IFRS 9 cash flow hedge accounting"),
    ("ASC 815 cash flow hedge 2026", "ASC 815 cash flow hedge 2027"),
    ("ASC 815 hedge qualifying transaction", "ASC 815 hedge not qualifying transaction"),
    ("ASC 815 cash flow hedge entries", "ASC 815 cash flow hedge entries site:fasb.org"),
])
async def test_new_evidence_search_is_not_suppressed_despite_shared_words(earlier,later):
    executed=[]
    _,outcome=await _run([
        _reply(tool_calls=[_call("search_web",{"query":earlier},"c1")]),
        _reply(tool_calls=[_call("search_web",{"query":later},"c2")]),
        _reply("Unavailable."),
    ],_search_registry(executed))
    assert [q for _,q in executed]==[earlier,later]
    assert [r.error_code for r in outcome.tool_calls]==["no_data","no_data"]


async def test_empty_search_memo_is_request_local():
    executed=[]; registry=_search_registry(executed)
    for _ in range(2):
        await _run([_reply(tool_calls=[_call("search_web",{"query":HEDGE_1},"c1")]),_reply("No data.")],registry)
    assert len(executed)==2


async def test_dependency_expansion_keeps_the_evaluator_length_bound():
    result=await _batch([{"id":"fraction","expression":"1 / 7"},
                         {"id":"oversize","expression":" + ".join(["{fraction}"]*8)},
                         {"expression":"{oversize} + 1"},{"expression":"7 * 6"}])
    assert result.items_failed==2
    assert "exceeds 240 characters" in result.content
    assert [r["result"] for r in result.receipts]==["0.142857","42"]


async def test_negative_dependency_is_parenthesised_and_self_reference_is_refused():
    result=await _batch([{"id":"neg","expression":"0 - 2"},{"expression":"{neg} ** 2"},
                         {"id":"self","expression":"{self} + 1"}])
    assert [r["result"] for r in result.receipts]==["-2","4"]
    assert result.receipts[1]["expression"]=="(-2) ** 2"
    assert result.items_failed==1


def test_decimal_literals_are_not_reduced_to_binary_number_precision():
    assert evaluate_expression("0.123456789123456789123456789") == Decimal("0.123456789123456789123456789")
    assert evaluate_expression("0.123456789123456789123456789 * 1000000000") == Decimal("123456789.123456789123456789")


async def test_reference_math_uses_full_precision_and_symbolic_working():
    result=await _batch([{"id":"third","expression":"1 / 3"},{"expression":"{third} * 3000000"}])
    assert result.receipts[1]["result"]=="1000000"
    assert "{third} * 3000000 = 1000000" in result.content
    assert "0.333333 * 3000000 = 1000000" not in result.content


@pytest.mark.parametrize("written,expected",[
    ("-400 000.25","-400,000.25"),("−400 000.25","−400,000.25"),
    ("(400 000.25)","(400,000.25)"),("400,000.25","400,000.25"),
    ("1 2345","1 2345"),("400 000.2501","400,000.2501"),
])
def test_offline_numeric_normalisation_preserves_sign_and_fraction(written,expected):
    assert normalise_numbers(written)==expected


def test_offline_grader_does_not_loosen_decimal_or_negative_answer_patterns():
    review={"answer_keys":{"case":{"value":[r"(?<![\d,.])[-−]400,000\.25(?![\d]|[.,]\d)"]}}}
    for text in ["-400 000.25","−400 000.25","-400,000.25"]:
        assert grade(text,"case",review).passed
    for text in ["400 000.25","-400 000.26","-400 000.2501","-1 400 000.25"]:
        assert not grade(text,"case",review).passed


@pytest.mark.parametrize("qualifier,first,second", [
    ("jurisdiction","United Kingdom","United States"),
    ("as_of","2026-01-01","2027-01-01"),
])
async def test_retrieval_scope_changes_are_never_deduplicated(qualifier,first,second):
    executed=[]
    _,outcome=await _run([
        _reply(tool_calls=[_call("search_web",{"query":HEDGE_1,qualifier:first},"c1")]),
        _reply(tool_calls=[_call("search_web",{"query":HEDGE_1,qualifier:second},"c2")]),
        _reply("No evidence."),
    ],_search_registry(executed))
    assert len(executed)==2
    assert [r.error_code for r in outcome.tool_calls]==["no_data","no_data"]

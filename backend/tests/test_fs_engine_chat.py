"""Kriton chat on the Financial Statements engine (fs_engine_chat.py).

Cases from review ZL-FSR-COR-20261103 (NB26-xx) and Supplement A (SA-Txx),
run against the engine's own Northbridge seed and the suspense trial balance.
"""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration import fs_engine_chat
from app.orchestration.fs_engine_chat import build, facts_block, statement_notes

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "app" / "domains" / "financial_statements" / "golden"
                     / "nb_synthetic_2026.json").read_text(encoding="utf-8"))
NORTHBRIDGE = GOLDEN["tb_csv"].encode()
SUSPENSE = (
    "account_code,account_name,debit,credit\n1000,\"Property, plant and equipment\",1265000.00,\n"
    "1100,Intangible assets,340000.00,\n1200,Inventory,418000.00,\n1300,Trade receivables,703000.00,\n"
    "1400,Cash at bank,512000.00,\n2000,Trade payables,,389000.00\n2100,Accruals,,146000.00\n"
    "2200,Deferred tax liability,,87000.00\n2300,Corporation tax payable,,196750.00\n3000,Share capital,,100000.00\n"
    "3100,Retained earnings,,1925750.00\n4000,Revenue,,4182000.00\n5000,Cost of sales,2431000.00,\n"
    "6000,Administrative expenses,902000.00,\n6100,Interest payable,62000.00,\n7000,Corporation tax charge,196750.00,\n"
    "8000,Suspense,196750.00,\n").encode()


def test_nb26_01_the_reference_route_gives_operating_profit_218600():
    s = build("northbridge.csv", NORTHBRIDGE)
    f = s.figures
    assert (f["revenue"], f["gross_profit"], f["operating_expenses"]) == (Decimal("1850000"), Decimal("795500"), Decimal("576900"))
    assert f["operating_profit"] == Decimal("218600") and f["net_finance"] == Decimal("-2200")
    assert (f["profit_before_tax"], f["profit_for_the_year"]) == (Decimal("216400"), Decimal("154400"))
    assert s.residual == 0 and not s.unmapped


def test_nb26_02_03_the_open_classification_shows_both_operating_profits():
    s = build("northbridge.csv", NORTHBRIDGE)
    assert {c.account for c in s.choices} == {"Bank charges", "Interest received"}
    block, notes = facts_block(s), statement_notes(s)
    assert "operating profit is 233,500 (a difference of 14,900); profit before tax is unchanged" in block
    assert any("Operating profit is 218,600 as shown, 233,500 under the alternative (difference 14,900)" in n
               for n in notes)


def test_nb26_04_an_unbalanced_trial_balance_is_reported_with_its_difference():
    s = build("northbridge.csv", NORTHBRIDGE.replace(b"4000,Revenue,,1850000.00", b"4000,Revenue,,1850001.00"))
    assert s.total_credits - s.total_debits == Decimal("1")
    assert any("ARITHMETIC_FAIL" in n and "difference -1" in n for n in statement_notes(s))


def test_nb26_06_dividends_stay_outside_profit():
    s = build("northbridge.csv", NORTHBRIDGE)
    assert s.figures["profit_for_the_year"] == Decimal("154400") and s.dividends == [("Dividends paid", Decimal("40000"))]
    assert "whether declared, paid or proposed is not established" in facts_block(s)


def test_nb26_07_tax_equal_to_payable_is_an_incomplete_reconciliation():
    block = facts_block(build("northbridge.csv", NORTHBRIDGE))
    assert "the tax reconciliation is incomplete; never conclude from equal amounts that no tax was paid" in block
    assert "effective tax rate 28.65% (does not validate the tax charge)" in block


def test_sa_t01_t02_the_suspense_residual_stays_beside_a_balanced_trial_balance():
    s = build("kriton-test-trial-balance.csv", SUSPENSE)
    assert s.balanced and s.total_debits == Decimal("7026500.00")
    assert s.residual == Decimal("-196750.00") and s.unmapped == [("Suspense", Decimal("196750.00"))]
    assert s.figures["profit_for_the_year"] == Decimal("590250.00")
    notes = statement_notes(s)
    assert any("residual of -196,750" in n and "Suspense 196,750" in n and "RECONCILIATION_UNRESOLVED" in n for n in notes)
    assert "an investigation lead, not an explanation; do not propose a correcting entry" in facts_block(s)


def test_sa_t07_interest_payable_is_flagged_by_its_caption():
    assert any(flag.startswith("Interest payable (62,000)") for flag in build("tb.csv", SUSPENSE).caption_flags)


def test_nb26_11_sa_t10_a_file_without_a_period_says_so():
    assert "Period end: not stated in the file (head the statement: reporting period not confirmed)" in \
        facts_block(build("tb.csv", SUSPENSE))
    assert "Period end: 2026-03-31." not in facts_block(build("tb.csv", SUSPENSE))


def test_accumulated_depreciation_reduces_ppe_not_profit():
    # Engine gap: the name matches the needs-evidence "depreciation" rule.
    csv = NORTHBRIDGE.replace(b"1000,Property plant and equipment,640000.00,",
                              b"1000,Property plant and equipment,700000.00,\n1090,Accumulated depreciation,,60000.00")
    s = build("northbridge.csv", csv)
    assert s.figures["profit_for_the_year"] == Decimal("154400") and s.residual == 0
    assert "Accumulated depreciation" not in [n for n, _ in s.cost_of_sales_candidates]


def test_a_file_that_is_not_a_trial_balance_is_left_to_the_previous_path():
    assert build("notes.csv", b"Quarter,Revenue\nQ1,2100\nQ2,2300\n") is None


def test_the_engine_path_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("KRITON_FS_ENGINE_CHAT", "0")
    assert not fs_engine_chat.enabled()
    monkeypatch.setenv("KRITON_FS_ENGINE_CHAT", "1")
    assert fs_engine_chat.enabled()


async def test_a_statement_request_uses_the_engine_figures_not_the_chat_calculation(monkeypatch):
    from app.domains.kriton_workspace import documents
    from app.orchestration import service
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(documents, "stored_spreadsheets", AsyncMock(return_value=[("kriton-test-trial-balance.csv", SUSPENSE)]))
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    chunk = WebSource(title="kriton-test-trial-balance.csv — 'kriton-test-trial-balance'!1:18", url="",
                      snippet=SUSPENSE.decode().replace(",", "\t"), provider="uploaded_document")
    block = await service._verified_document_figures_context(
        db, "Generate the income statement from this trial balance", ["d1"], [chunk],
        SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "Statement figures from the Financial Statements engine" in block
    assert "Trial balance 'kriton-test-trial-balance.csv" not in block      # no second set of numbers
    assert fs_engine_chat.current_statement.get().residual == Decimal("-196750.00")
    # Not a statement request: the previous calculation, no engine block.
    plain = await service._verified_document_figures_context(
        db, "What is the total revenue?", ["d1"], [chunk], SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "Financial Statements engine" not in plain and fs_engine_chat.current_statement.get() is None


def test_dc_01_02_each_choice_on_its_own_gives_the_intermediate_operating_profits():
    # Decision ZL-FSR-DEC-20261104 D-01: scenarios B and C between A and D.
    s = build("northbridge.csv", NORTHBRIDGE)
    alone = {c.account: x for c, x in s.sensitivities}
    assert (alone["Interest received"]["operating_profit"], alone["Interest received"]["net_finance"]) == \
        (Decimal("230600"), Decimal("-14200"))                                   # B
    assert (alone["Bank charges"]["operating_profit"], alone["Bank charges"]["net_finance"]) == \
        (Decimal("221500"), Decimal("-5100"))                                    # C
    assert all(x["profit_before_tax"] == Decimal("216400") for x in alone.values())
    block = facts_block(s)
    assert "moving only Bank charges to interest payable and similar expenses: operating profit 221,500, net finance -5,100" in block
    assert "operating profit 230,600, net finance -14,200" in block and "Show all 4 operating profits" in block
    note = next(n for n in statement_notes(s) if "CLASSIFICATION_REVIEW" in n)
    assert "221,500 with only Bank charges moved" in note and "230,600 with only Interest received moved" in note


async def test_dc_11_an_engine_failure_is_said_not_hidden(monkeypatch):
    from app.domains.kriton_workspace import documents
    from app.orchestration import service
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(documents, "stored_spreadsheets", AsyncMock(return_value=[("tb.csv", SUSPENSE)]))
    monkeypatch.setattr(fs_engine_chat, "build", MagicMock(side_effect=RuntimeError("engine down")))
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    chunk = WebSource(title="tb.csv — 'tb'!1:18", url="", snippet=SUSPENSE.decode().replace(",", "\t"),
                      provider="uploaded_document")
    block = await service._verified_document_figures_context(
        db, "Generate the income statement from this trial balance", ["d1"], [chunk],
        SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "The Financial Statements engine did not run for tb.csv" in block
    assert fs_engine_chat.current_statement.get() is None and fs_engine_chat.engine_failure.get() == "tb.csv"
    assert "ENGINE_FAILED" in fs_engine_chat.failure_note("tb.csv")


def test_dc_12_the_statement_checks_are_kept_apart_from_the_sources():
    from app.orchestration.verification_service import verification_breakdown

    northbridge = verification_breakdown(completeness="complete", citations=2,
                                         limitations=statement_notes(build("northbridge.csv", NORTHBRIDGE)))
    assert (northbridge.classification, northbridge.reconciliation) == ("needs_evidence", "not_applicable")
    assert northbridge.overall != "fully_verified"
    suspense = verification_breakdown(completeness="complete", citations=2,
                                      limitations=statement_notes(build("tb.csv", SUSPENSE)))
    assert suspense.reconciliation == "unresolved"
    failed = verification_breakdown(completeness="complete", citations=0, limitations=[fs_engine_chat.failure_note("tb.csv")])
    assert failed.reconciliation == "not_run" and failed.overall == "not_verified"
    plain = verification_breakdown(completeness="complete", citations=1, limitations=[])
    assert (plain.classification, plain.reconciliation) == ("not_applicable", "not_applicable")


def test_dc_12_an_open_statement_is_not_called_verified_or_reconciled():
    from app.orchestration.statement_rules import remove_verification_claims

    text = ("Operating profit is 218,600.\nThe statements are fully verified and reconcile to the trial balance. "
            "Profit before tax is 216,400.\nThe statements do not reconcile until the suspense balance is cleared.\n"
            "| Line | Amount |\n|---|---|\n| Verified total | 1 |")
    kept, removed = remove_verification_claims(text)
    assert removed == ["The statements are fully verified and reconcile to the trial balance."]
    assert "Profit before tax is 216,400." in kept and "do not reconcile until" in kept and "| Verified total | 1 |" in kept


def _xlsx(rows: list[list], hidden_sheet: list[list] | None = None) -> bytes:
    import io
    from openpyxl import Workbook
    book = Workbook()
    for row in rows:
        book.active.append(row)
    if hidden_sheet:
        sheet = book.create_sheet("Workings")
        for row in hidden_sheet:
            sheet.append(row)
        sheet.sheet_state = "hidden"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _suspense_rows() -> list[list]:
    import csv
    import io
    rows = list(csv.reader(io.StringIO(SUSPENSE.decode())))
    return [rows[0]] + [[r[0], r[1], float(r[2]) if r[2] else None, float(r[3]) if r[3] else None] for r in rows[1:]]


def test_dc_06_a_hidden_sheet_is_named_beside_the_answer():
    s = build("tb.xlsx", _xlsx(_suspense_rows(), hidden_sheet=[["Reviewer note", "adjust later"]]))
    assert any("Hidden sheet 'Workings'" in flag for flag in s.source_flags)
    assert any("(SOURCE_REVIEW)" in n and "Hidden sheet 'Workings'" in n for n in statement_notes(s))
    assert not build("tb.xlsx", _xlsx(_suspense_rows())).source_flags


def test_dc_06_dc_11_a_file_the_engine_rejects_is_said_not_replaced():
    import io
    import zipfile
    macro = io.BytesIO()
    with zipfile.ZipFile(macro, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/vbaProject.bin", b"\x00")
    with pytest.raises(fs_engine_chat.EngineRejected, match="macros"):
        build("tb.xlsm.xlsx", macro.getvalue())


def test_dc_07_chat_states_the_engine_run_it_was_given():
    from app.domains.financial_statements.service import run_intake

    s, run = build("northbridge.csv", NORTHBRIDGE), run_intake("northbridge.csv", NORTHBRIDGE, "workspace")
    assert (s.sha256, s.accounts) == (run.manifest.sha256, len(run.mappings))
    assert (s.total_debits, s.total_credits) == (run.report.total_debits, run.report.total_credits)
    revenue = -sum(m.balance for m in run.mappings if m.line_id == "pl.revenue")
    assert s.figures["revenue"] == revenue


def test_dc_08_chat_reaches_only_the_stateless_intake():
    # No approval, posting, mapping or package write is reachable from chat.
    source = Path(fs_engine_chat.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    engine = [line for line in imports if "financial_statements" in line]
    assert sorted(engine) == sorted([
        "from app.domains.financial_statements import mapping as fs_mapping",
        "from app.domains.financial_statements import workflow as fs_workflow",
        "from app.domains.financial_statements.normalize import TRIAL_BALANCE",
        "from app.domains.financial_statements.service import run_intake",
    ])


async def test_dc_09_only_the_callers_own_files_reach_the_engine():
    from app.domains.kriton_workspace.documents import stored_spreadsheets

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    assert await stored_spreadsheets(db, document_ids=["d1"], tenant_id="tenant-a", user_id="user-a") == []
    query = db.execute.await_args.args[0]
    sql = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "tenant_id = 'tenant-a'" in sql and "user_id = 'user-a'" in sql and "status = 'READY'" in sql


def test_dc_10_the_same_file_gives_the_same_statement():
    first, second = build("northbridge.csv", NORTHBRIDGE), build("northbridge.csv", NORTHBRIDGE)
    assert (first.sha256, first.figures, first.alternative) == (second.sha256, second.figures, second.alternative)
    assert [(c.account, x) for c, x in first.sensitivities] == [(c.account, x) for c, x in second.sensitivities]


def test_dc_17_dc_18_another_entity_carries_no_northbridge_figures():
    block = facts_block(build("kriton-test-trial-balance.csv", SUSPENSE))
    for northbridge in ("218,600", "233,500", "230,600", "221,500", "216,400", "Northbridge"):
        assert northbridge not in block


# The Northbridge answer of the 5 Nov app retest: every figure is the engine's.
RETEST_ANSWER = """Revenue of 1,850,000 generated a gross profit of 795,500 (gross margin = 43.00%).
After operating expenses the operating profit is 218,600 (operating margin = 11.82%).
Finance items reduce profit by 2,200, giving a profit before tax of 216,400.
After the corporation-tax charge of 62,000 the profit for the year is 154,400 (net margin = 8.35%).
The effective tax rate implied by the figures is 28.65%.
Operating expenses\t
Salaries and wages\t284,000
Operating expenses subtotal\t576,900
| Line | Standard | Alternative | Difference |
| Operating profit | 218,600 | 233,500 | +14,900 |
Profit before tax stays at 216,400 in every scenario.
Under the alternative, operating profit is 233,500 and net finance costs are 17,100."""


def test_nb26_08_a_narrative_figure_the_engine_did_not_compute_is_removed():
    s = build("northbridge.csv", NORTHBRIDGE)
    kept, removed = fs_engine_chat.remove_unsupported_figures(RETEST_ANSWER, s)
    assert removed == [] and kept == RETEST_ANSWER
    wrong = "Revenue is 1,850,000. The operating margin is 12.62%. Operating profit is 14,900 higher if both move."
    kept, removed = fs_engine_chat.remove_unsupported_figures(wrong, s)
    assert removed == ["operating margin is 12.62%"]            # the alternative's margin stated as the reference
    assert kept == "Revenue is 1,850,000. Operating profit is 14,900 higher if both move."
    kept, removed = fs_engine_chat.remove_unsupported_figures("Operating profit is 573,000.", s)
    assert removed == ["Operating profit is 573,000"] and kept == ""


def test_nb26_05_an_account_listed_twice_is_named():
    lines = NORTHBRIDGE.decode().splitlines()
    doubled = ("\n".join(lines) + "\n" + next(l for l in lines if "Bank charges" in l) + "\n").encode()
    notes = statement_notes(build("northbridge.csv", doubled))
    assert any("(SOURCE_REVIEW)" in n and "appears 2 times" in n for n in notes)
    assert any("(ARITHMETIC_FAIL)" in n for n in notes)


async def test_sa_t05_an_engine_that_times_out_is_not_run(monkeypatch):
    import time
    from app.domains.kriton_workspace import documents
    from app.orchestration import service
    from app.orchestration.websearch import WebSource

    monkeypatch.setattr(documents, "stored_spreadsheets", AsyncMock(return_value=[("tb.csv", SUSPENSE)]))
    monkeypatch.setattr(fs_engine_chat, "build", lambda *_: time.sleep(0.5))
    monkeypatch.setattr(fs_engine_chat, "ENGINE_SECONDS", 0.05)
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    chunk = WebSource(title="tb.csv — 'tb'!1:18", url="", snippet=SUSPENSE.decode().replace(",", "\t"),
                      provider="uploaded_document")
    block = await service._verified_document_figures_context(
        db, "Generate the income statement from this trial balance", ["d1"], [chunk],
        SimpleNamespace(retrieval_mode="full_document"), "t", "u")
    assert "timed out on tb.csv" in block and fs_engine_chat.engine_failure.get() == "tb.csv (timed out)"
    assert "(ENGINE_FAILED)" in fs_engine_chat.failure_note("tb.csv (timed out)")


def test_xs26_12_reordered_rows_give_the_same_statement():
    header, *rows = NORTHBRIDGE.decode().strip().splitlines()
    shuffled = "\n".join([header, *reversed(rows)]).encode()
    first, second = build("northbridge.csv", NORTHBRIDGE), build("northbridge.csv", shuffled)
    assert first.figures == second.figures and first.alternative == second.alternative
    assert {c.account for c in first.choices} == {c.account for c in second.choices}


def test_gap_1_the_status_follows_the_reconciliation():
    # "Status: Draft — arithmetic reconciled" stood beside "the statements do not reconcile".
    from app.orchestration.statement_rules import (ENGINE_NOT_RUN_STATUS, RECONCILIATION_OPEN_STATUS, STATUS_NOTE,
                                                   UNRECONCILED_NOTE, scoped_status)

    suspense = scoped_status([STATUS_NOTE, *statement_notes(build("tb.csv", SUSPENSE))])
    assert suspense[0] == RECONCILIATION_OPEN_STATUS and STATUS_NOTE not in suspense
    unbalanced = build("northbridge.csv", NORTHBRIDGE.replace(b"4000,Revenue,,1850000.00", b"4000,Revenue,,1850001.00"))
    assert scoped_status([STATUS_NOTE, *statement_notes(unbalanced)])[0] == UNRECONCILED_NOTE
    assert scoped_status([STATUS_NOTE, fs_engine_chat.failure_note("tb.csv")])[0] == ENGINE_NOT_RUN_STATUS
    northbridge = scoped_status([STATUS_NOTE, *statement_notes(build("northbridge.csv", NORTHBRIDGE))])
    assert northbridge[0] == STATUS_NOTE                          # balanced, residual 0: the status stands


def test_gap_2_an_unbalanced_trial_balance_gets_no_totals():
    s = build("northbridge.csv", NORTHBRIDGE.replace(b"4000,Revenue,,1850000.00", b"4000,Revenue,,1850001.00"))
    block, notes = facts_block(s), statement_notes(s)
    assert "Give no statement totals" in block and "Subtotals:" not in block and "Margins" not in block
    assert not any("CLASSIFICATION_REVIEW" in n or "RECONCILIATION_UNRESOLVED" in n for n in notes)
    kept, removed = fs_engine_chat.remove_unsupported_figures("Operating profit is 218,600. Please send a corrected file.", s)
    assert removed == ["Operating profit is 218,600"] and kept == "Please send a corrected file."


def test_gap_3_thousands_and_engine_warnings_are_always_noted():
    thousands = NORTHBRIDGE.replace(b"account_code,", b"Trial balance, amounts in thousands\naccount_code,", 1)
    s = build("northbridge.csv", thousands)
    assert s.units == "thousands"
    assert any("(UNITS_THOUSANDS)" in n for n in statement_notes(s)) and "Every amount below is in thousands" in facts_block(s)
    assert "SIGN_ANOMALY" in fs_engine_chat._NOTED_FINDINGS and "MIXED_CURRENCY" in fs_engine_chat._NOTED_FINDINGS
    assert build("northbridge.csv", NORTHBRIDGE).units == "units"


def test_gap_4_each_open_account_names_its_deciding_evidence():
    s = build("northbridge.csv", NORTHBRIDGE)
    assert all(c.evidence for c in s.choices)
    note = next(n for n in statement_notes(s) if "(CLASSIFICATION_REVIEW)" in n)
    for c in s.choices:
        assert f"{c.account}: {c.evidence}" in note
    assert "invoices or cost centres" not in note


def test_gap_5_tax_split_and_missing_statements_are_named():
    from app.orchestration.statement_rules import open_items

    notes = statement_notes(build("northbridge.csv", NORTHBRIDGE))
    assert any("current and deferred tax" in n and "(TAX_REVIEW)" in n for n in notes)
    items = open_items("Generate the income statement from this trial balance", "", "")
    missing = next(n for n in items if "(STATEMENTS_INCOMPLETE)" in n)
    assert "other comprehensive income" in missing and "cash flow statement" in missing and "none is assumed nil" in missing
    with_cash = open_items("Prepare the income statement and cash flow statement", "", "")
    assert "cash flow statement" not in next(n for n in with_cash if "(STATEMENTS_INCOMPLETE)" in n)


def test_the_alternative_statement_is_computed_line_by_line():
    # Retest of 4 Nov: the model's own alternative table said operating expenses 573,000.
    s = build("northbridge.csv", NORTHBRIDGE)
    a = s.alternative
    assert a["operating_expenses"] == Decimal("574000") and a["other_operating_income"] == Decimal("12000")
    assert a["operating_profit"] == Decimal("233500") and a["finance_income"] == 0
    assert a["finance_costs"] == Decimal("17100") and a["net_finance"] == Decimal("-17100")
    assert (a["profit_before_tax"], a["profit_for_the_year"]) == (Decimal("216400"), Decimal("154400"))
    block = facts_block(s)
    assert ("other operating income 12,000; operating expenses 574,000; operating profit 233,500; finance income 0; "
            "finance costs 17,100; net finance -17,100") in block
    assert "copy these; do not recompute" in block
    # A second table listed Bank charges under operating expenses beside a 574,000 total.
    assert "Bank charges 2,900 from administrative expenses to interest payable and similar expenses" in block
    assert "Interest received 12,000 from interest receivable and similar income to other operating income" in block
    assert "The rows under each heading must add up to its subtotal" in block

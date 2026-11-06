"""Gap analysis of 6 Nov 2026, items 9–12: statement exports carry their face
and are read back, the FRS 102 Format 1 face, the standards resolver's check,
and the rule registry pointing at the engine."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domains.kriton_workspace import artifacts
from app.domains.kriton_workspace.document_spec import build_document_spec
from app.orchestration import fs_engine_chat, service
from app.orchestration.statement_rules import RULES

NORTHBRIDGE = json.loads((Path(__file__).resolve().parents[1] / "app" / "domains" / "financial_statements" / "golden"
                          / "nb_synthetic_2026.json").read_text(encoding="utf-8"))["tb_csv"].encode()
STATEMENT = """Status: Draft — the income statement adds up, but the statements do not reconcile (see the reconciliation note).

Period end: 2026-03-31

| Line | Amount (GBP) |
|---|---|
| Revenue | 1,850,000 |
| Operating profit | 218,600 |
| Profit before tax | 216,400 |

Operating margin = 11.82%.
"""
ANALYSIS = {"product_revenue": {"Widgets": 100.0}, "customer_revenue": {}, "evidence_locations": []}


@pytest.mark.parametrize("format_name", ["docx", "pdf", "md"])
def test_9_a_statement_export_is_read_back(format_name):
    content, extension, _ = artifacts._render(format_name, "Kriton Answer", STATEMENT, ANALYSIS,
                                              "Generate the income statement")
    assert content and extension == format_name


def test_9_an_export_that_lost_a_figure_or_its_status_is_not_handed_over():
    spec = build_document_spec("Kriton Answer", STATEMENT, ANALYSIS, "Generate the income statement")
    with pytest.raises(ValueError, match="figures missing"):
        artifacts._read_back(spec, "Status Draft the income statement adds up but the statements do not 1,850,000")
    with pytest.raises(ValueError, match="status line"):
        artifacts._read_back(spec, "1,850,000 218,600 216,400 11.82 2026-03-31")


def test_9_a_statement_export_has_no_revenue_chart_but_a_report_keeps_it():
    statement = build_document_spec("T", STATEMENT, ANALYSIS, "Generate the income statement from this trial balance")
    report = build_document_spec("T", STATEMENT, ANALYSIS, "Write a sales performance report")
    assert not [b for b in statement.blocks if b.type == "chart"]
    assert [b for b in report.blocks if b.type == "chart"]


def test_9_the_export_header_states_each_fact_or_says_not_confirmed():
    statement = fs_engine_chat.build("northbridge.csv", NORTHBRIDGE)
    token = fs_engine_chat.current_statement.set(statement)
    try:
        source = SimpleNamespace(title="northbridge.csv — Sheet1", snippet="account_code,account_name,debit,credit")
        header = service._export_header(["Status: Draft — accounting review pending.",
                                         "Framework named: FRS 102. Whether it applies … (FRAMEWORK_UNKNOWN)."], [source])
    finally:
        fs_engine_chat.current_statement.reset(token)
    lines = header.split("\n\n")
    assert lines[0] == "Status: Draft — accounting review pending."
    assert lines[1].startswith("Source: northbridge.csv (SHA-256 ") and lines[2] == "Period end: not confirmed"
    assert lines[3] == "Currency: not confirmed" and lines[4] == "Framework: FRS 102 (named; applicability not verified)"


def test_10_the_standards_resolver_names_what_blocks_a_statutory_claim():
    note = fs_engine_chat.framework_note("Prepare the income statement under FRS 102", "2026-03-31")
    assert note.startswith("Standards check by the Financial Statements engine for FRS102: statutory claim not permitted")
    assert "unknown entity" in note and "(FRAMEWORK_CHECK)" in note
    assert fs_engine_chat.framework_note("Generate the income statement", None) is None
    assert "/financial-statements" in fs_engine_chat.WORKSPACE_NOTE


def test_11_frs_102_keeps_distribution_and_administration_apart():
    s = fs_engine_chat.build("northbridge.csv", NORTHBRIDGE)
    plain, format_1 = fs_engine_chat.facts_block(s), fs_engine_chat.facts_block(s, format_1=True)
    assert "Format 1 (FRS 102 / Companies Act)" in format_1 and "Format 1" not in plain
    assert "- Administrative expenses:" in format_1 and "- Administrative expenses:" not in plain
    assert service._FORMAT_1_NAMED.search("Prepare it under FRS 102") and not service._FORMAT_1_NAMED.search("Use IFRS")


def test_12_the_registry_points_at_what_the_engine_already_does():
    assert all("pending Document 03" not in where for where in (RULES[r][1] for r in ("FS-002", "FS-005", "FS-024")))
    assert RULES["FS-043"][1].startswith("engine:") and "notes" in RULES["FS-043"][1]

"""Pasted material is judged by the user's own framing (27 Oct 2026).

Four pasted texts with no request got four different results: a table and a
framework were answered or refused because "Verify …" and "Review …" inside
them read as requests, "When addressing …" read as a question, and Kriton's
own clarification pasted back carried a "?"."""
import pytest

from app.orchestration.input_requirements import STATEMENT_CLARIFICATION, statement_not_question
from app.orchestration.verification_service import verification_breakdown

BULLETS = (
    "Global tax audits are rarely random. Authorities rely on specific financial patterns to flag corporations for audit:\n"
    "• Persistent Subsidiary Losses: Local entities showing multi-year losses while the global parent remains highly profitable.\n"
    "• Volatile Profit Margins: Sudden fluctuations in operating margins that lack a clear commercial or economic justification.\n"
    "• Mismatched IP Ownership: Legally holding high-value Intellectual Property (IP) in low-tax jurisdictions without "
    "corresponding local R&D personnel.")
TABLE = (
    "Focus Area\tCore Audit Mechanism\tRisk Mitigation Strategy\n"
    "Transfer Pricing\tEvaluates if intercompany pricing matches the Arm's Length Principle.\tMaintain robust, "
    "contemporaneous Local Files and Master Files annually.\n"
    "Permanent Establishment (PE)\tAssesses if an un-registered cross-border operation has triggered a taxable "
    "corporate presence.\tTrack physical footprints, remote worker locations, and contract-signing authority.\n"
    "Withholding Taxes (WHT)\tAudits cross-border payments for correct tax treaty withholding rates.\tVerify the "
    "Beneficial Ownership status of the recipient entity to ensure treaty eligibility.")
FRAMEWORK = (
    "When addressing a multi-jurisdictional tax audit, tax and finance leaders should execute this prioritized "
    "operational framework:\n\nPhase 1: Immediate Preparedness & Containment\n\n"
    "• Establish Central Control: Route all auditor correspondence through a single, designated global tax controversy team.\n"
    "• Review Local Documentation: Instantly audit the local entity's statutory accounts against filed transfer pricing studies.\n"
    "• Quantify Exposure: Model the worst-case financial outcome, including penalties and interest, to determine if a "
    "financial provision is required under accounting standards (e.g., FIN 48 / ASC 740")
ECHO = ("That reads as a statement rather than a question. What would you like me to do with it — check whether it is "
        "correct, explain it, or something else? Context: " + BULLETS)
PIPE_TABLE = ("| Focus Area | Mechanism |\n|---|---|\n| Transfer Pricing | Verify that pricing is at arm's length. |\n"
              "| Withholding | Review treaty rates for each payment. |")


@pytest.mark.parametrize("text", [BULLETS, TABLE, FRAMEWORK, ECHO, PIPE_TABLE,
                                  STATEMENT_CLARIFICATION + " " + BULLETS])
def test_pasted_material_without_a_request_is_clarified(text):
    assert statement_not_question(text) == STATEMENT_CLARIFICATION


@pytest.mark.parametrize("text", [
    "Explain these red flags:\n" + BULLETS,
    "Check each claim below.\n" + BULLETS,
    "Compare the following:\n" + PIPE_TABLE,
    TABLE + "\nSummarise this table in plain language.",
    ECHO + "\nExplain each point.",
    "When is the VAT return due",
    "When a company sells goods abroad, how is VAT charged",
    "If the subsidiary has losses, should the group expect a transfer pricing audit",
    "• What is transfer pricing?\n• What is a permanent establishment?",
    "Calculate the operating margin:\nRevenue: £800,000\nOperating costs: £920,000",
    "Revenue: £800,000\nOperating costs: £920,000",
    "Our subsidiary has made losses for three years while the parent is profitable.",
    # A request before a colon is not a label (caught on the evaluation set, 27 Oct 2026).
    "Plot monthly sales as a line chart: Jan 40, Feb 55, Mar 48, Apr 62, May 70.",
    "Show a pie chart of this expense split: rent 30%, salaries 50%, marketing 20%.",
    "Show an org chart: CFO manages Finance Manager and Tax Manager; Finance Manager manages two Accountants",    "Sales: Jan 200, Feb 250, Mar 300. Do not show a chart; only give the total.",
])
def test_requests_questions_and_figures_are_not_clarified(text):
    assert statement_not_question(text) is None


def test_badge_says_unsupported_when_no_statement_cites_a_source():
    # "Sources: partly verified" beside four "The sources provided do not state this" lines.
    status = verification_breakdown(
        completeness="partial", citations=1, source_binding=False,
        limitations=["Incomplete answer: some requested information could not be verified from the retrieved evidence."],
        answer_text="Persistent Subsidiary Losses – The sources provided do not state this.")
    assert status.sources == "unsupported"

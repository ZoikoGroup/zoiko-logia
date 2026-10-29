"""Builds backend/evals/regression_conversations.json from the 27-28 Oct 2026 test chats."""
import json, sys

UK = "We are a United Kingdom company reporting under IFRS 16 for the year ending 31 December 2025."
INDIA = "We are an Indian company reporting under Ind AS for the year ending 31 March 2026."
WAREHOUSE = "We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 5 years."
EQUIPMENT = "We lease equipment: annual payments of £20,000 in arrears, discount rate 5%, lease term 4 years."
OFFICE = "We lease office space: annual payments of ₹6,00,000 in arrears, discount rate 9%, lease term 3 years."
VAN = "We lease a van: annual payments of £8,000 in arrears, discount rate 5%, lease term 3 years."
TWELVE_ADV = "Calculate the IFRS 16 lease liability: annual payments of £12,000 in advance, discount rate 6%, lease term 5 years."
THAT_LEASE = "Now calculate the lease liability for that lease."
BREAK_EVEN_50 = "Separately: what is the break-even point for a product selling at £50 with variable cost £30 and fixed costs £40,000?"
VAT_STD = "UK company, VAT at 20%, all standard-rated, figures exclude VAT: sales £100,000, purchases £50,000. Calculate VAT payable."
VAT_NO_TREATMENT = "UK company, VAT at 20%, figures exclude VAT: sales £100,000, purchases £50,000. Calculate VAT payable."
ACK = {"message_starts": "Noted"}
ACK_TARGET = {"outcome": "acknowledged", "target_stage": 2}

def conv(cid, source, tags, turns, mode="offline", note=""):
    return {"id": cid, "source": source, "tags": tags, "mode": mode, "note": note, "turns": turns}

def t(user, **expect):
    return {"user": user, "expect": expect}

cases = []
# ── single-turn deterministic calculations ────────────────────────────────────
calc = [
 ("calc-depreciation-eight", "27 Oct round 1", "Calculate straight-line depreciation on equipment costing £40,000 with residual value £4,000 over eight years.", {"annual_depreciation": "£4,500.00"}),
 ("calc-depreciation-nine", "28 Oct round 1", "Calculate straight-line depreciation on a machine costing £60,000 with residual value £6,000 over nine years.", {"annual_depreciation": "£6,000.00"}),
 ("calc-depreciation-eight-b", "28 Oct round 3", "Calculate straight-line depreciation on a machine costing £84,000 with residual value £4,000 over eight years.", {"annual_depreciation": "£10,000.00"}),
 ("calc-gp-margin-generated", "28 Oct round 1", "Calculate gross profit and margin: we generated £450,000 in revenue and cost of sales was £270,000.", {"gross_profit": "£180,000.00", "gross_margin": "40.00%"}),
 ("calc-gp-margin-ifrs15", "28 Oct round 1", "Under IFRS 15, revenue £1,200,000 and cost of sales £780,000. What is the gross profit and margin?", {"gross_profit": "£420,000.00", "gross_margin": "35.00%"}),
 ("calc-gp-margin-plain", "28 Oct round 3", "Calculate gross profit and margin: revenue £640,000 and cost of sales £416,000.", {"gross_profit": "£224,000.00", "gross_margin": "35.00%"}),
 ("calc-gp-sales-came-to", "27 Oct stage 2", "Calculate gross profit: total sales came to £800,000 and cost of sales was £500,000.", {"gross_profit": "£300,000.00"}),
 ("calc-break-even-sold-at", "28 Oct round 1 (expectation corrected to 6,000)", "What is the break-even point for a product sold at £40 with variable cost £25 and fixed costs £90,000?", {"contribution_per_unit": "£15.00", "break_even_units": "6000.00 units"}),
 ("calc-break-even-selling-at", "27 Oct re-test", "What is the break-even point for a product selling at £25 with variable cost £15 and fixed costs £50,000?", {"break_even_units": "5000.00 units"}),
 ("calc-break-even-sold-at-12", "28 Oct round 3", "What is the break-even point for a product sold at £12 with variable cost £7 and fixed costs £45,000?", {"break_even_units": "9000.00 units"}),
]
for cid, src, q, out in calc:
    cases.append(conv(cid, src, ["calculation"], [t(q, route="CALCULATION", calculation=out, model_not_called=True)]))

cases += [
 conv("vat-standard-rated", "28 Oct rounds 1-3", ["calculation", "vat", "chart"], [
   t(VAT_STD, route="CALCULATION", calculation={"output_vat_on_sales": "£20,000.00", "input_vat_on_purchases": "£10,000.00", "vat_payable": "£10,000.00"}, chart_offer="none")]),
 conv("vat-standard-rated-b", "28 Oct round 3", ["calculation", "vat"], [
   t("UK company, VAT at 20%, all standard-rated, figures exclude VAT: sales £250,000, purchases £90,000. Calculate VAT payable.",
     route="CALCULATION", calculation={"vat_payable": "£32,000.00"})]),
 conv("vat-asks-treatment-then-reply", "27 Oct re-test", ["vat", "clarification", "follow-up", "known-failure"], [
   t(VAT_NO_TREATMENT, outcome="clarification_required", message_contains=["zero-rated"]),
   t("All standard-rated.", calculation={"vat_payable": "£10,000.00"}, reply_to_clarification=True, target_stage=2)],
   note="Known failure at baseline: the calculators see only the reply's own text, so the earlier request is not "
        "completed and the model answers instead. Explicit reply references (stage 2) are the fix."),
 conv("vat-what-if", "28 Oct round 1", ["vat", "follow-up"], [
   t(VAT_STD, calculation={"vat_payable": "£10,000.00"}),
   t("Now what if purchases were £60,000?", live_expected="VAT payable £8,000 (output £20,000 − input £12,000)")],
   note="Follow-up answered by the model in the live run; offline only the first turn's figures are checked strictly."),
 conv("new-task-after-clarification", "27 Oct re-test", ["clarification", "contamination"], [
   t(VAT_NO_TREATMENT, outcome="clarification_required"),
   t("Record the journal entry: Dr Right-of-use asset £133,650.60, Cr Lease liability £126,370.91. Check if it balances.",
     no_vat_calculation=True, prompt_not_contains=["Previous user request for context"])],
   note="A complete new task after a clarification must not carry the previous request."),
]

# ── leases ────────────────────────────────────────────────────────────────────
lease_single = [
 ("lease-ifrs16-arrears", "28 Oct rounds 1-2", WAREHOUSE.replace("We lease a warehouse:", "Calculate the IFRS 16 lease liability for a warehouse:") ,
  {"lease_liability": "£126,370.91", "first_year_interest": "£7,582.25", "first_year_depreciation": "£25,274.18"}, "line"),
 ("lease-ifrs16-cash-flow", "28 Oct round 1", WAREHOUSE + " Show the IFRS 16 accounting for the lessee, including the cash flow statement.",
  {"lease_liability": "£126,370.91", "first_year_interest": "£7,582.25", "first_year_depreciation": "£25,274.18"}, "line"),
 ("lease-4-year", "28 Oct round 2", "Calculate the lease liability: annual payments of £20,000 in arrears, discount rate 5%, lease term 4 years.",
  {"lease_liability": "£70,919.01", "first_year_interest": "£3,545.95"}, "line"),
 ("lease-3-year", "28 Oct round 3", "Calculate the IFRS 16 lease liability: annual payments of £15,000 in arrears, discount rate 7%, lease term 3 years.",
  {"lease_liability": "£39,364.74", "first_year_interest": "£2,755.53", "first_year_depreciation": "£13,121.58"}, "bar"),
 ("lease-advance", "28 Oct round 3", TWELVE_ADV,
  {"lease_liability": "£53,581.27", "first_year_interest": "£2,494.88", "first_year_depreciation": "£10,716.25"}, "line"),
 ("lease-quarterly", "28 Oct rounds 3-4", "Calculate the lease liability: quarterly payments of £5,000 in arrears, discount rate 8% a year, lease term 2 years.",
  {"lease_liability": "£36,627.41", "first_year_interest": "£2,411.24"}, "line"),
 ("lease-asc842-operating", "28 Oct round 3", "Under ASC 842, an operating lease has annual payments of $40,000 in arrears for 4 years at a 5% discount rate. Calculate the lease liability and the annual lease cost.",
  {"lease_liability": "$141,838.02", "annual_lease_cost": "$40,000.00"}, "line"),
]
for cid, src, q, out, chart in lease_single:
    cases.append(conv(cid, src, ["lease", "calculation", "chart"], [
        t(q, route="CALCULATION", calculation=out, model_not_called=True, chart_offer=chart, no_calculation_check_flag=True)]))
cases += [
 conv("lease-missing-timing", "28 Oct round 3", ["lease", "missing-input"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.",
     outcome="clarification_required", message_contains=["in advance", "in arrears"], no_calculation=True)]),
 conv("lease-two-in-one-message", "28 Oct round 4", ["lease", "ambiguity", "known-failure"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.\nWhen it asks advance or arrears, send " + VAN,
     outcome="clarification_required", message_contains=["more than one lease"], no_calculation=True)],
   note="Round 6 (not approved): fails on the live code, which calculated the £10,000 lease with the van's 'in arrears'."),
]

# ── context statements, corrections and follow-ups ────────────────────────────
cases += [
 conv("context-uk-ifrs16", "28 Oct rounds 1-3", ["context"], [
   t(UK, model_not_called=True, message_contains=["United Kingdom", "IFRS 16", "31 December 2025"], **ACK),
   ]),
 conv("context-uk-ifrs16-outcome", "item 2 target", ["context", "message-types"], [t(UK, **ACK_TARGET)]),
 conv("context-revenue-statement", "28 Oct round 2", ["context"], [
   t("The company recognised revenue of £500,000 for the year.\nManagement believes the receivables are fully recoverable.\n"
     "The auditor has not yet reviewed the bad debt provision.", model_not_called=True, **ACK)]),
 conv("context-then-lease-statement", "28 Oct rounds 2-3 (fix A)", ["context", "clarification"], [
   t(UK, **ACK), t(EQUIPMENT, message_contains=["£20,000", "5%", "4 years"], model_not_called=True, **ACK)],
   note="Acknowledgements count as clarifications in the frontend, so the second statement used to be taken as a reply."),
 conv("lease-follow-up-after-break-even", "28 Oct rounds 1-3", ["follow-up", "lease"], [
   t(UK, **ACK), t(EQUIPMENT, **ACK), t(BREAK_EVEN_50, calculation={"break_even_units": "2000.00 units"}),
   t("Now calculate the lease liability and first-year interest for that lease.",
     calculation={"lease_liability": "£70,919.01", "first_year_interest": "£3,545.95"}, model_not_called=True)]),
 conv("lease-follow-up-two-leases-latest", "28 Oct round 2 (fix B)", ["follow-up", "lease", "ambiguity"], [
   t(WAREHOUSE + " Show the IFRS 16 accounting for the lessee, including the cash flow statement.", calculation={"lease_liability": "£126,370.91"}),
   t(UK, **ACK), t(EQUIPMENT, **ACK), t(BREAK_EVEN_50, calculation={"break_even_units": "2000.00 units"}),
   t("Now calculate the lease liability and first-year interest for that lease.", calculation={"lease_liability": "£70,919.01"})],
   note="'That lease' is the most recent lease."),
 conv("lease-follow-up-among-many", "28 Oct round 3 (fix 3)", ["follow-up", "lease", "ambiguity"], [
   t(TWELVE_ADV, calculation={"lease_liability": "£53,581.27"}),
   t(INDIA, message_contains=["Ind AS", "31 March 2026"], **ACK), t(OFFICE, **ACK),
   t(THAT_LEASE, calculation={"lease_liability": "₹1,518,776.80", "first_year_interest": "₹136,689.91"})],
   note="Terms of other leases must not mix in (an 'in advance' lease made it ask about timing)."),
 conv("lease-correction", "28 Oct rounds 3-4", ["correction", "lease", "follow-up"], [
   t(VAN, **ACK), t("Correction: the lease term is 4 years, not 3.", message_contains=["correction"], **ACK),
   t(THAT_LEASE, calculation={"lease_liability": "£28,367.60"})]),
 conv("lease-correction-target", "item 2 target", ["correction", "message-types"], [
   t(VAN, **ACK_TARGET), t("Correction: the lease term is 4 years, not 3.", **ACK_TARGET)]),
 conv("lease-correction-among-many", "28 Oct round 3", ["correction", "lease", "follow-up", "ambiguity"], [
   t(TWELVE_ADV), t(INDIA), t(OFFICE), t(VAN, **ACK), t("Correction: the lease term is 4 years, not 3.", **ACK),
   t(THAT_LEASE, calculation={"lease_liability": "£28,367.60"})],
   note="Used to ask 'which of 5 leases?'; the correction belongs to the van."),
 conv("statement-during-clarification", "28 Oct round 3 (fix 4)", ["context", "clarification"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.", outcome="clarification_required"),
   t(VAN, message_contains=["£8,000"], model_not_called=True, **ACK)]),
 conv("statement-during-clarification-target", "items 2-3 target", ["context", "clarification", "message-types"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.", outcome="clarification_required"),
   t(VAN, **ACK_TARGET)]),
 # Stage 2: the client marks a reply to Kriton's question (reply_to), so it is
 # processed with the request it answers, never guessed to be a new message.
 conv("explicit-reply-completes-lease", "stage 2", ["lease", "clarification", "message-types"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.", outcome="clarification_required",
     message_contains=["in advance", "in arrears"]),
   t("In arrears.", reply_to_clarification=True, calculation={"lease_liability": "£27,232.48"})]),
 conv("ambiguous-reply-is-not-carried", "28 Oct live test (stage 2)", ["lease", "clarification", "message-types"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.", outcome="clarification_required"),
   t('"in advance or in arrears?"', reply_to_clarification=True, outcome="clarification_required"),
   t("In arrears.", reply_to_clarification=True, calculation={"lease_liability": "£27,232.48"})],
   note="A reply after which Kriton asked the same question answered nothing and is not carried; it made every "
        "later reply ambiguous and the question repeated without end."),
 conv("explicit-reply-is-not-acknowledged", "stage 2", ["context", "clarification", "message-types"], [
   t("Calculate the lease liability for payments of £10,000 a year at 5% for 3 years.", outcome="clarification_required"),
   t(VAN, reply_to_clarification=True, message_not_starts="Noted")]),
 conv("reply-is-not-context", "28 Oct round 4", ["clarification"], [
   t(VAT_NO_TREATMENT, outcome="clarification_required"),
   t("Our turnover is £95,000 for the last 12 months.", message_not_starts="Noted")]),
 conv("pasted-material-statement", "27 Oct tax-audit inputs", ["ambiguity", "pasted"], [
   t("Recurring dividend from subsidiary: the parent recognised the dividend as income.\n"
     "Management fees: charged to all group entities at cost plus 5%.\n"
     "Transfer pricing: the documentation was last updated in 2022.",
     outcome="clarification_required", message_contains=["What would you like me to do"])]),
 conv("instruction-not-context", "28 Oct evaluation comparison", ["context", "intent"], [
   t("Pass the journal entry for depreciation of ₹50,000 on machinery.", message_not_starts="Noted")]),
]

# ── recorded model answers: validators on what the model actually wrote ──────
ENTRY = ("| Account | Debit (£) | Credit (£) |\n|---|---|---|\n| Right‑of‑use asset | 133 650.60 | – |\n"
         "| Lease liability | – | 126 370.91 |\n| Total | 133 650.60 | 126 370.91 |\n")
cases += [
 conv("rec-journal-does-not-balance", "28 Oct round 2", ["journal", "recorded"], [
   t("Dr Right-of-use asset £133,650.60, Cr Lease liability £126,370.91. Check if it balances.",
     recorded_answer=ENTRY + "\nThe journal entry does not balance; a further credit of £7,279.69 is needed.",
     journal_failures=False, findings_exclude=["balancing_entry_wrong_side"])], mode="recorded"),
 conv("rec-journal-wrong-side", "28 Oct round 2", ["journal", "recorded", "treatment"], [
   t("Dr Right-of-use asset £133,650.60, Cr Lease liability £126,370.91. Check if it balances.",
     recorded_answer=ENTRY + "\nThe journal entry does not balance; a £7 279.69 debit is missing.",
     findings_include=["balancing_entry_wrong_side"], note_contains=["needs a further credit of 7,279.69"],
     note_not_contains=["figures add up"])], mode="recorded"),
 conv("rec-journal-credits-exceed", "28 Oct round 3", ["journal", "recorded"], [
   t("Dr Equipment £5,000, Cr Bank £5,600. Check if it balances.",
     recorded_answer="Debit side: Equipment £5,000\nCredit side: Bank £5,600\nThe entry is out of balance by £600. "
                     "You would need an additional debit of £600.", findings_exclude=["balancing_entry_wrong_side"])], mode="recorded"),
 conv("rec-ifrs16-operating-cash-flows", "27 Oct round 2", ["treatment", "recorded", "lease"], [
   t(WAREHOUSE + " Show the IFRS 16 accounting for the lessee, including the cash flow statement.",
     recorded_answer="IFRS 16 lessee accounting.\n| Statement | Presentation |\n|---|---|\n| Statement of Cash Flows | Lease payments "
                     "are classified within operating activities (IFRS 16 permits this treatment). |",
     findings_include=["ifrs16_lease_payments_operating"])], mode="recorded"),
 conv("rec-chart-json-leak", "28 Oct round 1", ["display", "recorded"], [
   t(EQUIPMENT, recorded_answer='Assumptions as above.\n\n```json\n{\n "type": "bar",\n "categories": ["Year 1", "Year 2"],\n'
                                ' "series": [{"name": "Lease Payment", "data":}]\n}\n```\nEnd.', displayed_not_contains=['"type"', "```"])],
   mode="recorded"),
 conv("rec-calculator-posting-not-balance", "28 Oct round 3", ["lease", "recorded"], [
   t("Calculate the lease liability: quarterly payments of £5,000 in arrears, discount rate 8% a year, lease term 2 years.",
     recorded_answer_is_calculator_output=True, no_discrepancy=True)], mode="recorded"),
]

# ── live-only: need retrieval or live data (run only with approval) ──────────
live = [
 ("live-bank-rate", "What is the current UK Bank Rate?", "3.75%, effective 2025-12-18, Bank of England IUDBEDR, cited", []),
 ("live-uk-vat-threshold", "What is the UK VAT registration threshold?", "£90,000, GOV.UK", []),
 ("live-singapore-gst", "What is the current standard GST rate in Singapore? Cite the official source.", "9%, IRAS", []),
 ("live-fx", "Convert £10,000 to euros at today's exchange rate.", "a dated, cited rate", []),
 ("live-pillar-two", "What did the OECD Pillar Two GloBE minimum tax rate get set at, and when did it start? Cite the source.",
  "15%; Income Inclusion Rule from 2024 (OECD)", ["known-failure"]),
 ("live-context-action", "Explain the accounting treatment Context: The company recognised revenue of £500,000 for the year.",
  "answered as a labelled general explanation, not refused", []),
]
for cid, q, expected, extra in live:
    cases.append(conv(cid, "27-28 Oct live runs", ["live"] + extra, [t(q, live_expected=expected)], mode="live"))

dataset = {
  "version": "regression-conversations-2",
  "implemented_stage": 2,
  "notes": ("Regression conversations from the 27-28 Oct 2026 test chats. 'offline' runs the real pipeline with the model "
            "stubbed; 'recorded' applies Kriton's checks to an answer the model actually wrote; 'live' needs retrieval or "
            "live data and runs only with approval. An expectation with target_stage above implemented_stage is the agreed "
            "behaviour of a later stage and is reported as pending, not as a pass."),
  "cases": cases,
}
json.dump(dataset, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(len(cases), "conversations,", sum(len(c["turns"]) for c in cases), "turns")

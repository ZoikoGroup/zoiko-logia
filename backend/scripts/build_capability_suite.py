"""Writes evals/capability_suite.json: the representative capability suite
across tax, audit, finance, payroll and markets (3 Nov 2026).

Each case is a conversation of one or more turns. A turn's expectation:
  outcome:        "ask" (a clarification) or "answer" (no clarification)
  ask_contains:   text the clarification must contain
  answer_contains:text a deterministic answer must contain (offline-checkable)
  answer_excludes:text it must not contain
  contract:       Task Contract classification (needs_official, fact, countries)
  live:           what only the live application can show (figure, authority);
                  recorded, never graded offline.
Expectations were written before the improvements they measure."""
import json
from pathlib import Path

C = []


def case(id, domain, category, turns, note=""):
    C.append({"id": id, "domain": domain, "category": category, "turns": turns, "note": note})


def t(query, **expect):
    return {"query": query, "expect": expect}


# ── TAX ──────────────────────────────────────────────────────────────────────
case("tax-vat-threshold-no-country", "tax", "jurisdiction", [
    t("What is the VAT registration threshold?", outcome="ask", ask_contains="Which country"),
    t("UK", outcome="answer", live={"figure": "£90,000", "authority": "gov.uk/register-for-vat"})])
case("tax-cit-rate-no-country", "tax", "jurisdiction", [
    t("What is the corporate income tax rate?", outcome="ask", ask_contains="Which country"),
    t("Singapore.", outcome="answer", live={"figure": "17%", "authority": "iras.gov.sg"})])
case("tax-uk-vat-threshold", "tax", "retrieval", [
    t("What is the UK VAT registration threshold?", outcome="answer",
      contract={"needs_official": True, "fact": "threshold", "countries": ["UK"]},
      live={"figure": "£90,000", "authority": "gov.uk"})])
case("tax-vat-on-net", "tax", "calculation", [
    t("Calculate VAT at 20% on £1,000 excluding VAT.", outcome="answer", answer_contains="£200.00")])
case("tax-reverse-vat", "tax", "calculation", [
    t("An invoice total of £12,000 includes VAT at 20%. Calculate reverse VAT and the net amount.", outcome="answer",
      answer_contains="£10,000.00")])
case("tax-gst-invoice-dialogue", "tax", "multi_turn", [
    t("Calculate the GST on my invoice.", outcome="ask", ask_contains="amount"),
    t("₹50,000, GST 18%", outcome="ask", ask_contains="excluding GST"),
    t("excluding GST", outcome="answer", answer_contains="GST amount | ₹9,000.00", answer_excludes="VAT")])
case("tax-income-tax-allowance", "tax", "calculation", [
    t("Calculate income tax on £30,000 at 20% after a £12,570 allowance.", outcome="answer", answer_contains="£3,486.00",
      answer_excludes="Total including tax")])
case("tax-corporation-tax-direct", "tax", "calculation", [
    t("Calculate corporation tax on £100,000 at 25%.", outcome="answer", answer_contains="£25,000.00",
      answer_excludes="Total including tax")])
case("tax-historical-year", "tax", "temporal", [
    t("What was the UK VAT registration threshold in 2015?", outcome="answer",
      contract={"needs_official": True, "fact": "threshold", "countries": ["UK"], "period": "year"},
      live={"figure": "£82,000", "authority": "gov.uk"})])
case("tax-au-gst-rate", "tax", "retrieval", [
    t("What is the GST rate in Australia?", outcome="answer",
      contract={"needs_official": True, "fact": "rate", "countries": ["AUSTRALIA"]},
      live={"figure": "10%", "authority": "ato.gov.au"})])
case("tax-de-vat-rate", "tax", "retrieval", [
    t("What is the standard VAT rate in Germany?", outcome="answer",
      contract={"needs_official": True, "fact": "rate", "countries": ["GERMANY"]},
      live={"figure": "19%", "authority": "gesetze-im-internet.de"})])
case("tax-gst-rate-how-much", "tax", "ambiguity", [
    t("How much GST is charged on gold jewellery in India?", outcome="answer")])
case("tax-vat-no-country-rule", "tax", "jurisdiction", [
    t("Is VAT charged on children's car seats?", outcome="ask", ask_contains="Which country")])
case("tax-concept-vat-gst", "tax", "ambiguity", [
    t("What is the difference between VAT and GST as tax systems?", outcome="answer")])
case("tax-iras-penalty", "tax", "jurisdiction", [
    t("What penalty does IRAS impose for late GST filing?", outcome="answer",
      contract={"needs_official": True, "countries": ["SINGAPORE"]})])
case("tax-gstr3b-due", "tax", "jurisdiction", [
    t("When is the GSTR-3B due?", outcome="answer", contract={"needs_official": True, "fact": "deadline", "countries": ["INDIA"]})])
case("tax-cgst-sgst", "tax", "calculation", [
    t("Calculate CGST and SGST on an intra-state sale of ₹40,000 at 12%", outcome="answer", answer_contains="₹2,400.00")])
case("tax-uk-scheme-term", "tax", "jurisdiction", [
    t("When must a business leave the VAT Cash Accounting Scheme?", outcome="answer",
      live={"figure": "£1.6 million", "authority": "gov.uk/vat-cash-accounting-scheme"})])
case("tax-manipur", "tax", "jurisdiction", [
    t("What is the GST registration threshold for service providers in Manipur?", outcome="answer",
      live={"figure": "Rs 10 lakh", "authority": "cbic-gst.gov.in"})])

# ── PAYROLL ──────────────────────────────────────────────────────────────────
case("pay-uk-employer-ni", "payroll", "retrieval", [
    t("What is the current UK employer National Insurance contribution rate?", outcome="answer",
      contract={"needs_official": True, "fact": "rate", "countries": ["UK"]},
      live={"figure": "15%", "authority": "gov.uk rates and thresholds for employers"})])
case("pay-min-wage-no-country", "payroll", "jurisdiction", [
    t("What is the minimum wage?", outcome="ask", ask_contains="Which country"),
    t("Australia.", outcome="answer", live={"authority": "fairwork.gov.au"})])
case("pay-uk-min-wage", "payroll", "retrieval", [t("What is the UK minimum wage?", outcome="answer")])
case("pay-deadlines-no-country", "payroll", "jurisdiction", [
    t("What are the payroll filing deadlines?", outcome="ask", ask_contains="Which country")])
case("pay-au-super", "payroll", "retrieval", [
    t("What is the superannuation guarantee rate in Australia?", outcome="answer",
      contract={"needs_official": True, "fact": "rate", "countries": ["AUSTRALIA"]})])
case("pay-take-home-missing", "payroll", "clarification", [
    t("Calculate take-home pay for my employee.", outcome="ask", ask_contains="salary"),
    t("Gross salary £40,000 a year in the UK.", outcome="answer")])
case("pay-employer-ni-on-salary", "payroll", "calculation", [
    t("Calculate the employer National Insurance on a UK salary of £40,000 for 2026 to 2027.", outcome="answer",
      live={"figure": "£5,250.00", "authority": "gov.uk"})],
  note="(£40,000 − £5,000) × 15%; needs the official rate and threshold")

# ── AUDIT ────────────────────────────────────────────────────────────────────
case("aud-materiality-judgement", "audit", "multi_turn", [
    t("Is this misstatement material?", outcome="ask", ask_contains="materiality level"),
    t("The misstatement is £40,000 and overall materiality is £100,000.", outcome="answer")])
case("aud-materiality-missing", "audit", "clarification", [
    t("Calculate overall materiality for our audit.", outcome="ask", ask_contains="benchmark")])
case("aud-materiality-complete", "audit", "calculation", [
    t("Calculate overall materiality at 5% of profit before tax of £2,000,000.", outcome="answer", answer_contains="£100,000.00")])
case("aud-materiality-concept", "audit", "ambiguity", [
    t("What is the difference between overall and performance materiality?", outcome="answer")])
case("aud-isa320", "audit", "retrieval", [
    t("Under ISA 320, how is materiality determined?", outcome="answer", contract={"needs_official": False})])
case("aud-sample-size-missing", "audit", "clarification", [
    t("What sample size do I need for my test of controls?", outcome="ask", ask_contains="population")])
case("aud-going-concern", "audit", "retrieval", [t("Explain the going concern assumption.", outcome="answer")])

# ── FINANCE / ACCOUNTING ─────────────────────────────────────────────────────
case("fin-depreciation-dialogue", "finance", "multi_turn", [
    t("Calculate straight-line depreciation on a machine costing £50,000.", outcome="ask", ask_contains="useful life"),
    t("Residual value £5,000 and a useful life of 9 years.", outcome="answer", answer_contains="£5,000.00")])
case("fin-depreciation-complete", "finance", "calculation", [
    t("Calculate straight-line depreciation: cost £40,000, residual value £4,000, useful life 8 years.", outcome="answer",
      answer_contains="£4,500.00")])
case("fin-lease-missing-rate", "finance", "clarification", [
    t("Calculate the lease liability for annual payments of £10,000 over 5 years.", outcome="ask", ask_contains="discount rate")])
case("fin-lease-complete", "finance", "calculation", [
    t("Calculate the lease liability: annual payments of £10,000 in arrears, discount rate 5%, lease term 5 years.",
      outcome="answer", answer_contains="£43,294.77")])
case("fin-loan-dialogue", "finance", "multi_turn", [
    t("Calculate the monthly loan repayment.", outcome="ask", ask_contains="loan amount"),
    t("£200,000 at 5% over 25 years.", outcome="answer", answer_contains="£1,169.18")])
case("fin-loan-frequency", "finance", "clarification", [
    t("Calculate the loan repayment on £200,000 at 5% over 25 years.", outcome="ask", ask_contains="monthly or annual"),
    t("Monthly.", outcome="answer", answer_contains="£1,169.18")])
case("fin-npv-missing", "finance", "clarification", [
    t("What is the NPV of this project?", outcome="ask", ask_contains="cash flows")])
case("fin-gross-margin-missing", "finance", "clarification", [t("What is the gross margin?", outcome="ask", ask_contains="revenue")])
case("fin-gross-margin", "finance", "calculation", [
    t("Revenue is £100,000 and cost of sales is £60,000. Calculate the gross margin.", outcome="answer", answer_contains="40.00%")])
case("fin-method-question", "finance", "ambiguity", [t("How is straight-line depreciation calculated?", outcome="answer")])
case("fin-journal-dialogue", "finance", "multi_turn", [
    t("Record the journal entry for the sale.", outcome="ask", ask_contains="transaction details"),
    t("A credit sale of £5,000 plus VAT at 20% on 1 March.", outcome="answer")])
case("fin-current-ratio", "finance", "calculation", [
    t("Current assets are £420,000 and current liabilities are £210,000. Calculate the current ratio.", outcome="answer",
      answer_contains="2.00")])
case("fin-ifrs16-explain", "finance", "retrieval", [t("Explain IFRS 16 lease accounting for lessees.", outcome="answer")])
case("fin-emi-batch", "finance", "calculation", [
    t("Loan ₹40,00,000 at 8.75% for 15 years. What is the EMI, and how much total interest will I pay?", outcome="answer",
      answer_contains="39,977.95")])

# ── MARKETS / STOCKS / TRADE ─────────────────────────────────────────────────
case("mkt-share-price-no-company", "markets", "clarification", [
    t("What is the share price?", outcome="ask", ask_contains="company"),
    t("Apple.", outcome="answer")])
case("mkt-share-price-named", "markets", "retrieval", [t("What is Apple's share price?", outcome="answer")])
case("mkt-pe-no-company", "markets", "clarification", [
    t("What is the P/E ratio of this stock?", outcome="ask", ask_contains="company")])
case("mkt-fx-today", "markets", "retrieval", [
    t("Convert £10,000 to euros at today's exchange rate.", outcome="answer", contract={"needs_official": True, "fact": "rate"})])
case("mkt-fx-no-source-currency", "markets", "clarification", [
    t("Convert 5,000 to euros.", outcome="ask", ask_contains="currency")])
case("mkt-boe-rate", "markets", "retrieval", [
    t("What is the current Bank of England base rate?", outcome="answer", contract={"needs_official": True, "fact": "rate"})])
case("mkt-trade-duty-no-country", "markets", "jurisdiction", [
    t("What import duty applies to laptops?", outcome="ask", ask_contains="Which country")])

case("mkt-fx-two-currencies", "markets", "ambiguity", [
    t("How many rupees is one US dollar worth today?", outcome="answer")])
case("mkt-conversion-and-vat", "markets", "calculation", [
    t("Our UK company invoiced a German client €40,000. Convert it to pounds at the latest rate and tell me the UK VAT at 20%.",
      outcome="answer", answer_excludes="VAT amount | €8,000.00")],
  note="the conversion needs a live rate: VAT on the euro amount alone is not the answer")
case("tax-sgd-gst", "tax", "calculation", [
    t("A Singapore company invoiced services of S$10,000 plus GST at 9%. Calculate the GST to charge.", outcome="answer",
      answer_contains="SGD 900.00")])

# ── Round 3 (3 Nov 2026): statutory calculators, effective dates, investment ──
case("pay-uk-take-home", "payroll", "calculation", [
    t("What is the take-home pay on a salary of £40,000?", outcome="answer", answer_contains="£32,319.60")])
case("pay-uk-employer-ni-2025-26", "payroll", "temporal", [
    t("Calculate the employer National Insurance on a salary of £40,000 for 2025 to 2026.", outcome="answer",
      answer_contains="£5,250.00")])
case("pay-uk-ni-unverified-year", "payroll", "temporal", [
    t("Calculate the employee National Insurance on £40,000 for 2023 to 2024.", outcome="answer",
      answer_excludes="£2,194.40")],
  note="no verified 2023-24 parameters: not calculated with another year's rates")
case("tax-in-new-regime", "tax", "calculation", [
    t("Calculate income tax on ₹15,00,000 under the new regime for FY 2025-26.", outcome="answer", answer_contains="₹105,000.00")])
case("tax-uk-high-income", "tax", "calculation", [
    t("Calculate income tax on £150,000 for 2025/26.", outcome="answer", answer_contains="£53,703.00")])
case("fin-npv-cash-flows", "finance", "calculation", [
    t("A project has an initial investment of £100,000 and cash flows of £30,000, £40,000 and £50,000 over three years. "
      "Calculate the NPV at 8%.", outcome="answer", answer_contains="£1,762.94")])
case("fin-irr-payback", "finance", "calculation", [
    t("Initial investment £100,000; annual cash inflows £30,000 for 5 years. Calculate the IRR and payback period.",
      outcome="answer", answer_contains="15.24%")])
case("fin-npv-rate-missing", "finance", "clarification", [
    t("Calculate the NPV of an initial investment of £100,000 with cash flows of £30,000 and £80,000.", outcome="ask",
      ask_contains="discount rate"),
    t("10%", outcome="answer")])
case("fin-eps", "finance", "calculation", [
    t("Net profit is £1,000,000 and there are 2,000,000 shares. Calculate EPS.", outcome="answer", answer_contains="£0.50")])
case("pay-uk-employer-ni-2025-26-rate", "payroll", "temporal", [
    t("What was the UK employer National Insurance rate for 2025 to 2026?", outcome="answer",
      live={"figure": "15%", "authority": "gov.uk/guidance/rates-and-thresholds-for-employers-2025-to-2026"})])

# ── MULTI-TURN CONTEXT ───────────────────────────────────────────────────────
case("ctx-setting-statement", "tax", "multi_turn", [
    t("We are a UK company.", outcome="answer"),
    t("What is the VAT registration threshold?", outcome="answer")],
  note="the setting statement supplies the country")
case("ctx-unrelated-earlier-country", "tax", "multi_turn", [
    t("What is the current UK employer National Insurance contribution rate?", outcome="answer"),
    t("What is the VAT registration threshold?", outcome="ask", ask_contains="Which country")])
case("ctx-new-request-during-clarification", "finance", "multi_turn", [
    t("Calculate the GST on my invoice.", outcome="ask"),
    t("₹50,000, GST 18%", outcome="ask"),
    t("Calculate the monthly loan repayment.", outcome="ask", ask_contains="loan amount"),
    t("£200,000 at 5% over 25 years", outcome="answer", answer_contains="£1,169.18")])
case("ctx-reply-adds-nothing", "tax", "multi_turn", [
    t("Calculate the GST on my invoice. ₹50,000, GST 18%", outcome="ask"),
    t("ok", outcome="ask", ask_contains="I still need this")])

out = Path(__file__).resolve().parents[1] / "evals" / "capability_suite.json"
out.write_text(json.dumps({"version": "capability-suite-1", "built": "2026-11-03",
                           "description": __doc__, "cases": C}, indent=1, ensure_ascii=False) + "\n")
print(len(C), "cases", sum(len(c["turns"]) for c in C), "turns ->", out)

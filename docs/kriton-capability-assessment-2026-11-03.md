# Kriton capability assessment: tax, audit, finance, payroll, markets

3 November 2026. Scope: the backend answer pipeline (`backend/app/orchestration`), the source registry
(`backend/registry`) and the evaluation assets (`backend/evals`, `backend/tests`).

**How it was measured.**
- **The capability suite** (`evals/capability_suite.json`, 61 cases, 79 turns) runs through the real `ask_kriton`
  pipeline with `tests/capability_suite_report.py`. Each conversation is sent the way the frontend sends it, and only
  persistence, web retrieval and the model are replaced.
- **The wider regression check** compares outcomes on 329 eval and 634 gold questions.
- **What offline runs cannot show.** They grade behaviour that the code itself decides: asking, calculating,
  classifying and choosing sources. They cannot show that a live answer is correct.
- **Live checks are blocked.** No evaluation credential is configured, so live checks have been run only by the
  user asking questions and pasting the answers. Eleven suite turns carry a live-only expectation, with the figure
  and authority expected; none of them has been graded.

---

## 1. Shared root causes

Every defect found in this session's live tests traced back to one of these causes. Each cause is a mechanism
shared across domains, not a gap in one question.

| # | Root cause | Areas affected | How it showed up |
|---|---|---|---|
| R1 | **Special cases decided at many separate points.** Each step re-read the raw message with its own patterns (clarification, country, figures, deliverables), and fixes were added one pattern per past failure. | 1, 2, 5, 6, 9 | 4 of 18 incomplete requests were asked about; bare "VAT" was treated as UK and "GST" as India; "IRAS … GST" was placed in India and Singapore |
| R2 | **Retrieval had no authoritative source map.** Fixed pages were hard-coded regexes in one module, and the registry was data nothing read. | 1, 7 | UK NI, Canada, South Africa and Germany fell back to open search, then got no answer or a secondary source |
| R3 | **Pages were read by visible text, and by question words.** The reader dropped structured page data and chose passages by English word overlap. | 1, 4 | gov.uk guide parts were never read (Cash Accounting leaving rule); the § 12 UStG statute gave no passage at all |
| R4 | **The model's planning drifted.** The search planner added its own training-period year. | 2, 3, 7 | "UK employer NI rate 2024" retrieved the 2024 to 2025 page (13.8%), and the correct 15% was rejected |
| R5 | **Period handling was missing.** Nothing compared a source's tax year with the question's period. | 3, 7 | An ended tax-year page was cited for a current rate |
| R6 | **Verification checked whether a figure was present, not what it was for.** A figure found anywhere in the cited text counted as support. | 4, 8 | The joining limit (£1.35 million) was released as the leaving rule |
| R7 | **No conversation model of a request.** The client carried every turn since the last answer as one request. | 6, 9 | A loan question asked while a GST question was open got the GST question back |
| R8 | **Calculators read one word order, and their output was treated as the whole answer.** | 5, 10 | "₹50,000, GST 18%" wasn't read; a journal-entry request got VAT figures only; S$ was shown as $; an allowance was ignored (£6,000 instead of £3,486) |
| R9 | **No measurement beyond the questions being tested.** No suite covered domains, jurisdictions, ambiguity and multi-turn behaviour together. | all | Each live test found a new case |

## 2. What was implemented

All of the following are in the clean copy and in main (8010). The new behaviour switches (§5) are all on in main.

| Root cause | Mechanism now in place | Where |
|---|---|---|
| R1, R7 | **One requirement check, before answering.** It is driven by the Task Contract's own classification, a declarative task table (13 task types with generic input slots), and an explicit-country rule; a bare tax word no longer decides the country. | `clarification_requirements.py` |
| R1 | **Contract places countries from explicit evidence first.** A named country, authority, scheme term or currency comes first; a bare tax word counts only when nothing else does. | `task_contract._places`, `country_resolution`, `registry/country_terms.json` |
| R7 | **Reply chain.** The chain restarts at the latest message that is a request of its own. A task's inputs come only from turns about the same task. A reply that adds nothing is told so. | `clarification_requirements.current_request_chain`, `reply_adds_nothing` |
| R2 | **The Global Source Registry drives page selection.** Selection rules, subjects, periods and verified pages are all data, so a new country page is a data entry. | `source_registry.py`, `registry/global_source_registry.json` |
| R3 | **Structured page data is read.** schema.org question/answer content is read with the visible text, and each registry page can declare where its passage starts. | `websearch.structured_answers`, `source_registry.excerpt_anchor` |
| R4 | **Planner years.** A year or tax year the request does not name is removed from planned searches. | `evidence_planning.without_introduced_years` |
| R5 | **Ended tax years.** For a question that names no year, web pages titled for an ended tax year are left out, unless they are a fixed official page or the only source. | `websearch.without_ended_tax_years` |
| R6 | **Rule context.** A figure that the cited source states only for the opposite rule raises a `figure_for_other_rule` finding: join/leave, register/deregister, employer/employee, input/output, minimum/maximum, upper/lower. | `verification_service._figure_for_other_rule` |
| R6 | **Deliverable completeness against the contract.** Each requested output (amounts, journal entry, schedule, chart, citation) is checked in the final answer. | `finalisation.deliverable_findings` |
| R8 | **Calculator fixes.** Allowances are deducted and direct taxes show no "total including tax"; a single amount is read in any word order (never when a live rate is needed); currency prefixes S$/A$/NZ$/C$/HK$ are read; the tax label is shown as written (GST/HST/SST); annuity loan repayments are calculated and ask for the frequency; journal requests go to composition with the verified figures. | `calculations/engine.py`, `service.py` |
| R8 | **Maths notation.** Fraction, spacing and alignment notation is converted to plain text. | `answer_formatting.latex_to_plain` |
| — | **Diagnostics.** Release-verification rejections are logged with the claim and the reason. The registry shadow logs the registry's source choice beside today's. | `service.py`, `registry_shadow.py` |
| R9 | **Capability suite** across five domains and seven categories, run as the frontend sends requests. | `evals/capability_suite.json`, `tests/capability_suite_report.py` |

## 3. Results

**Capability suite, offline:** 51 of 58 cases passed before this round. After it, 61 of 61 pass, including three new
cases written from regressions the wider check found.

| Domain | Clarification | Jurisdiction | Calculation | Retrieval (offline part) | Multi-turn | Ambiguity / temporal |
|---|---|---|---|---|---|---|
| Tax | — | 7/7 | 6/6 | 3/3 | 4/4 | 3/3 |
| Payroll | 1/1 | 2/2 | 1/1 | 3/3 | — | — |
| Audit | 2/2 | — | 1/1 | 2/2 | 1/1 | 1/1 |
| Finance | 4/4 | — | 5/5 | 1/1 | 4/4 | 1/1 |
| Markets | 3/3 | 1/1 | 1/1 | 3/3 | — | 1/1 |

**Wider regression check** (329 eval and 634 gold questions, against the previous run):
- No new unnecessary questions.
- 12 unnecessary questions removed.
- 4 answers that went to the model are now calculated deterministically, with correct figures and currency labels.
- One regression found and fixed during the round: a conversion request was answered with VAT only.

**Backend tests:** 6,681 pass in the clean copy. Main has the same two known failures as before: the goodwill tests
that fail only because of main's local `.env`.

**Live checks this session**, from the user's pasted answers:
- **Working:** UK employer NI 15% cited to HMRC; Germany 19% cited to the statute; Canada GST/HST cited to CRA; South
  Africa 15% cited to SARS; Manipur ₹10 lakh cited to CBIC; GST invoice dialogue ₹9,000; loan £1,169.18; asking and
  answering for a country; a new request during an open clarification; "ok" gets "I still need…"; the income-tax
  allowance.
- **Not yet checked live:** the rule-context finding, structured page data, the new task types, and the
  country-placing change.

## 4. What a complete, reliable system needs: status by area

✅ the mechanism exists and is tested · ⚠️ partial · ❌ missing.

| # | Area | Status | What remains |
|---|---|---|---|
| 1 | Authoritative source coverage | ⚠️ | See the coverage matrix below. Official fixed sources exist for tax in 9 countries and payroll in 1. **Audit and accounting have no per-country official source**: search only, plus the governed library. Markets rely on market-data connectors, whose provider keys are external. |
| 2 | Search planning | ⚠️ | Planner years are guarded. Planned queries are not yet constrained by the contract's period and subject, only by its jurisdiction. |
| 3 | Jurisdiction / period / effective date | ⚠️ | Countries resolve from explicit evidence. Ended tax years are filtered by page title only. **Source effective dates are not modelled:** registry entries carry `effective_from`/`effective_to` on one page only, and nothing selects a source by the question's date. Sub-national rules (US states, Canadian provinces, Indian states) are recognised in only a few cases. |
| 4 | Evidence-to-rule matching | ⚠️ | Rule-context pairs cover six opposed rules. Conditions, exceptions and thresholds with qualifiers ("for annual filers", "under 21s") are not matched beyond those pairs. That needs claim-to-passage alignment beyond keywords, and so a model-based judge. One judge exists (claim verification) but it is a live model call, not yet evaluated at scale. |
| 5 | Calculations and required inputs | ✅ for the 20+ supported formulas · ⚠️ coverage | Missing: payroll (NI, PAYE, net pay), NPV/IRR from free-form cash flows, EPS, foreign exchange at a live rate inside a tax calculation, and tax calculations with bands. These go to the model, with its arithmetic re-checked. |
| 6 | Clarification | ✅ mechanism · ⚠️ coverage | 13 task types and the country rule. Tasks outside the table rely on the contract's deliverables and the referent rule. |
| 7 | Conflicting / outdated / irrelevant evidence | ⚠️ | Withdrawn, conflicting, out-of-period (for governed sources with dates), ended-tax-year and opposite-rule findings exist. Web sources carry no publication or effective dates, so "outdated" is judged from titles only. |
| 8 | Verification and citations | ⚠️ | Figure presence, figure context (pairs), jurisdiction, authority and deliverable completeness are checked. A semantically wrong statement that cites a source containing all its words is not caught deterministically. |
| 9 | Multi-turn context | ✅ for clarification replies, new requests, setting statements and corrections | The client sends answers but not Kriton's questions as history, so the backend infers repeated questions from the reply. Sending `next_action.message` as history would be cleaner, but that is a frontend change. |
| 10 | Integrated behaviour across domains | ⚠️ | Mixed requests (conversion + VAT, calculation + rule) are routed to composition with the verified figures. Live correctness of mixed answers has not been measured. |

### Coverage matrix: best source tier per country and domain

From the registry. "Connector" for tax outside the countries with fixed pages is the OECD tax database, a
**secondary** source.

| Country | tax | payroll | audit | accounting | markets | economy |
|---|---|---|---|---|---|---|
| UK | page | page | search | search | connector | connector |
| US | OECD only | library | search | search | connector | connector |
| India | page | search | search | search | connector | connector |
| Singapore, UAE, Malaysia, Germany, South Africa, Canada | page | search | search | search | connector | connector |
| Australia | OECD only | search | search | search | connector | connector |
| Ireland, NZ, France, EU, Gulf states, Crown Dependencies | OECD only | search | search | search | connector | connector |

## 5. Switches (main `.env`)

| Switch | State | Effect |
|---|---|---|
| `KRITON_CONTRACT_CLARIFICATION` | on (default) | input requirements and country questions |
| `KRITON_REGISTRY_RETRIEVAL` | on | fixed pages from the registry |
| `KRITON_REGISTRY_SHADOW` | on | logs the registry's source choice only |
| `KRITON_CONTRACT_DECISIONS` | off | chart and report decisions from the contract |
| `KRITON_CONTRACT_FINALISER` | off | missing requested outputs mark the answer incomplete |

## 6. Blocked or needing a decision

1. **Live verification at scale.** The 11 live-only suite expectations, and any live grading, need `EVAL_PASSWORD`
   or an equivalent evaluation account.
2. **Source coverage.**
   - Adding fixed official pages for further countries and for payroll needs live page reads. Each is a data entry,
     and each read needs approval.
   - Audit and accounting standards need the IFRS, IAASB and FASB texts in the governed library. Their licensing
     governs whether they can be ingested.
3. **Market data.** Live quotes depend on provider keys (Finnhub, Polygon, Alpha Vantage) being configured.
4. **Two switches are not enabled:** `KRITON_CONTRACT_FINALISER` and `KRITON_CONTRACT_DECISIONS`. The finaliser's
   false-flag rate on real model answers has not been measured live.
5. **Semantic claim checking** (area 4/8) needs the live claim-verification model to be evaluated on a labelled set.
   That means model calls, which need approval and a cost estimate.

This assessment does not claim Kriton is complete. The mechanisms in §2 remove the root causes behind every failure
seen in this session. The gaps in §4 and §6 are real and still open.

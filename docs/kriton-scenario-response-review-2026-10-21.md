# Kriton scenario-response review — 21 October 2026

This is a review of the new uploaded transcript and read-only probes of the current code. No implementation, tests, configuration, database state or deployment was changed. No Groq/model tokens were used. Existing test-suite success is not treated as proof that these new cases pass.

## Verdict

The run still fails acceptance. Its most serious defects are substitution of unrelated bank figures and misreading a quarter identifier as a financial measure. Other defects include valid supplied inputs being reported missing, incomplete follow-ups labelled answered, excessive dependence on provider generation for supplied arithmetic, and evidence gating that prevents useful conditional audit discussion.

## Review and control answers

| Scenario | Assessment | Correct control / missing work |
| --- | --- | --- |
| VAT-inclusive £72,000 | Arithmetic correct. | Net revenue £60,000; VAT £12,000. External-source retrieval is unnecessary for the explicitly supplied rate/treatment. |
| £6,000 VAT-inclusive refunds | Incomplete despite “Answered”. | Refund reduces net revenue by £5,000 and VAT by £1,000. **Final net revenue £55,000; final output VAT £11,000; remaining inclusive receipts £66,000.** The answer gives only movements. |
| Fictional tax adjustments | Correct under the supplied assumptions. | £95,000 + £12,000 + £3,000 − £18,000 = **£92,000 taxable profit**; 25% = **£23,000 tax**. This is arithmetic, not verification of actual law. |
| First bank reconciliation response | Correct underlying arithmetic, but a false scenario-attribution warning removes valid supplied figures and leaves a malformed/incomplete table. | Cash book £28,450 − £150 + £200 = **£28,500**. Bank £29,700 + £3,000 − £4,200 = **£28,500**. Difference zero. |
| Missing income-tax context | Incorrect handling. | Ask for country, currency, tax year, legal/business structure, other relevant income, deductible-expense treatment and applicable relief information. A request-size error cannot answer this clarification task. The actual historical size-error origin is unverified. |
| Repeated bank reconciliation | Core calculation correct on the retry; table continuation rows still omit cells. | Both balances £28,500, difference zero. Inconsistent results for the same question remain a reliability problem. |
| Outstanding cheques corrected to £4,300 | **Critical wrong-context result.** | Cash book remains **£28,500**. Bank becomes £29,700 + £3,000 − £4,300 = **£28,400**. Difference is **£100**, with cash book higher. The £12,500 and £1,200 in the response are unrelated and must not be described as verified work for this task. |
| Inventory count | Partial; retained arithmetic is correct. | Shortage **30 units / £720**; ledger value £12,000; counted value £11,280. The alleged dispatch of 20 units / £480 is unverified. If proven relevant and unrecorded, it could explain 20 units, leaving 10 units / £240 to investigate. Do not treat that explanation as established. Requested evidence/procedures and conditional outcomes are missing. |
| Three invoices | Sum correct; requested analysis absent. | Combined **£29,700**. Possible splitting to avoid the stated approval threshold is an investigation hypothesis, not proof of fraud. Review orders, dates, supplier identity, related transactions, approvals, receipts and policy application. General conditional investigation procedures can be discussed without inventing source-backed statutory duties. |
| Break-even initial | Incorrect clarification: selling price is explicitly £75. | Contribution **£30/unit**; break-even **6,000 units / £450,000 revenue**; target-profit volume **9,000 units**, exceeding 8,000 capacity. Maximum operating profit at capacity is **£60,000**, below the £90,000 target. |
| Variable cost corrected to £48 | Incomplete, truncated and unnecessarily dependent on unrelated web results. | Contribution **£27/unit**; break-even **6,666.666… units**, so **6,667 whole units**. Theoretical break-even revenue **£500,000**; selling 6,667 whole units yields £500,025. Target-profit volume **10,000 units**, exceeding capacity; maximum operating profit **£36,000**. All other original inputs must remain unchanged. |
| Loan payment | Incorrect insufficient-evidence result for a supplied-assumption journal exercise. | Proposed debit loan liability **£15,000**, debit interest expense **£3,000**, credit bank **£18,000**. Profit decreases £3,000; cash decreases £18,000; loan liability decreases £15,000. No posting is performed by this review. |
| Working-capital days | Calculations correct under the explicit proxy. | Receivables **45 days**, inventory **60 days**, payables **45 days**, cash conversion cycle **60 days**. The claim that actual credit purchases are often disclosed in the cash-flow statement is not established here; obtain supporting purchase/credit-purchase records rather than depend on that assertion. |
| Quarterly budget versus actual | **Critical data-extraction and visualization failure.** | Q1 is a category, not an actual amount of 1. Four quarterly budget/actual pairs are present. The requested grouped bars and full variance table were not produced. See control table below. |
| Table-only quarterly follow-up | Incorrect insufficient-evidence response. | Reuse the original supplied four-quarter dataset and variance definitions. External web evidence is not needed. The previous incorrect gauge must not become the authoritative dataset. |
| Missing March | Correct. | Known-month sum **£138,000**, January-to-April change **30%**. Full four-month total is unknown; March must remain missing, never zero. A table satisfies the request to display observations. |
| Conflicting gross profit | Correct. | Calculated GP **£210,000**, reported GP £240,000, reported excess **£30,000**; calculated margin **35%**, reported margin **40%**. Preserve both inputs and distinguish arithmetic from investigation. |

## Quarterly control table

Variance = actual minus budget; percentage = variance ÷ budget × 100. Positive expense variance is overspend; negative variance is underspend.

| Quarter | Budget | Actual | Variance | Variance % |
| --- | ---: | ---: | ---: | ---: |
| Q1 | £80,000 | £84,000 | £4,000 | 5.00% |
| Q2 | £85,000 | £82,000 | −£3,000 | −3.53% |
| Q3 | £90,000 | £99,000 | £9,000 | 10.00% |
| Q4 | £95,000 | £93,000 | −£2,000 | −2.11% |
| Full year | **£350,000** | **£358,000** | **£8,000** | **2.29%** |

## Code findings and confidence

### Confirmed by direct read-only reproduction

- `intent_classifier.explicit_target_pair()` returns **('Q', 1.0, 80000.0, '')** for the exact quarterly question. The scalar-target pattern permits an embedded identifier digit to serve as an actual measure. This establishes the first wrong-data stage before gauge selection/rendering. A valid-looking chart can still be based on wrongly extracted facts; renderer validation alone cannot fix it.
- `calculate_from_query()` returns **clarification_required: selling price** for the exact break-even question. The selling-price aliases used by break-even omit the natural wording “sells for”, even though another price matcher exists elsewhere in the engine. This establishes an input-extraction defect, not missing user data.
- The exact bank question, refund follow-up and loan exercise return **not_matched** from the deterministic calculator. The bank matcher requires the literal “bank reconciliation”, narrower balance labels and an explicit “no other items” phrase; this question supplies the balances and adjustments in another form. These recognizer limits push useful supplied arithmetic to provider composition.
- `missing_tax_inputs()` returns **None** for the exact income-tax question with numbers but missing country/currency/year. The guard currently covers a narrower set of tax requests. A local clarification could avoid unnecessary provider/retrieval work.

### Observed in transcript, not fully traced to its historical request

- Bank scenario-attribution incorrectly removed £28,450 and £29,700. The scenario/table-header classifier is a candidate, especially “Original amount” versus an “original scenario”. A simplified direct attribution probe did **not** reproduce the warning; the exact audit event, historical context and released table are required before assigning a precise cause. No attribution guard was disabled.
- The cheque follow-up used unrelated numbers. The calculator's general bank path did not match the baseline, but that alone does not prove whether the wrong values came from history, a model example or a tool-result interpretation. The historical request/audit payload is needed to distinguish them.
- The size-limit and model-service failures are distinct from the parsing defects. The transcript contains no correlation IDs or provider metadata sufficient to identify their exact current cause. A paid key does not itself repair request analysis, state selection or calculation coverage.
- Source-free investigative discussion is being replaced by “the sources do not state this”. General hypotheses and procedures should be separated from specific external accounting/legal rules. Improving that distinction must preserve evidence checks for claims that actually require authority.

## Priority remediation

1. Prevent category/period digits from becoming financial actual values. Prefer the complete quarterly series; honour the explicit grouped-bar request or return its real table with an honest visual limitation, never a fabricated scalar comparison.
2. Reconstruct bank follow-ups from scoped user-owned task inputs and change only the named cheque amount. Reject unrelated/example operands before labelling a tool result verified for the current task.
3. Correct natural-language input matching for selling price, bank balances and refunds; reuse existing financial calculation services rather than add independent answer paths.
4. Require final requested totals, comparisons, capacity feasibility and variance outputs before marking these responses complete. Do not accept adjustment-only VAT output as a completed recalculation.
5. Handle the missing-context tax question locally; separate conditional audit analysis from externally sourced legal assertions; investigate provider limits using request-origin diagnostics instead of assuming a billing problem.
6. Add these exact originals, fresh and multi-turn, as regressions before claiming a fix. Preserve prior baseline cases. Then exercise authenticated HTTP, actual rendering and current build identity.

[Read-only probe results and transcript checksum](investigations/kriton-scenario-review-2026-10-21/review-evidence.json).

No implementation fix, live-provider retest, deployment, database migration or new full-suite pass is claimed by this review.

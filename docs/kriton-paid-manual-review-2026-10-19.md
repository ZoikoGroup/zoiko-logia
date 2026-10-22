# Paid-key manual response review and repairs

Reviewed the user's pasted manual transcript dated 19 October 2026. A paid
provider credential does not correct parsing, routing, context selection,
accounting classification or local completion allowances. This review compares
the observed answers with the requested behavior; no live ChatGPT/Claude or
Groq completion benchmark was run.

## Response assessment

| Request | Assessment | Repair |
| --- | --- | --- |
| Profitable business running out of cash | Substantively sufficient; unnecessary source-library footer | Remove repeated boilerplate; keep citations/status |
| Machine depreciation | Correct £4,000 yearly and £333.33 monthly | No calculation change required |
| VAT-inclusive sales | Incorrect missing-net-input clarification | Parse “sales were”, preserve input treatment separately from requested output, and handle a single sales amount |
| Inventory-based wholesale statement | Complete supplied inputs incorrectly treated as missing COGS | Supported inventory statement calculation with explicit inputs and expense classification |
| Closing-stock correction | Interest wrongly included in operating expenses; margin incorrectly described as falling in pounds | Correct finance/operating split; compute the correction from user inputs; explain percentage-point change |
| Highlight differences | Incorrectly treated as a statement | Recognise imperative requests; provide a verified comparison without repeating the table |
| Reported GP discrepancy | Correct application results mixed with earlier inventory calculations | Isolate a new labelled baseline; complete supported reconciliation from verified inputs |
| Fictional security | Useful identifier explanation, but asserted absence of a listing without verified search | Attribute fiction to the user's premise; explain identifiers without inventing examples or claiming a search |
| Grounded discrepancy follow-up | Failed despite usable earlier figures | Resolve the latest user-supplied financial baseline, ignoring assistant prose and intervening nonfinancial identifiers |

## Correct inventory results

| Measure | Original | After £10,000 closing-stock overstatement correction |
| --- | ---: | ---: |
| Net sales | £936,000 | £936,000 |
| Closing inventory | £95,000 | £85,000 |
| Cost of goods sold | £560,000 | £570,000 |
| Gross profit | £376,000 | £366,000 |
| Gross margin | 40.17% | 39.10% |
| Operating expenses | £222,000 | £222,000 |
| Operating profit | £154,000 | £144,000 |
| Profit before tax | £145,000 | £135,000 |

Interest of £9,000 is deducted after operating profit. The gross-margin
change is approximately -1.07 percentage points, not a £10,000 margin change.
The stock correction alone does not establish any cash payment.

## Implementation scope

The inventory calculation accepts explicitly labelled inputs and rejects
unsupported additional monetary lines rather than silently excluding them.
Unsupported inventory adjustments continue to composition instead of a false
“missing COGS” prompt. Follow-ups use user inputs, not the previous generated
answer. Existing durable-memory scenarios remain covered by regression tests.

Initial agent context now participates in the combined prompt-sizing step,
using the planned tool schemas. This does not compact every subsequent agent
tool transcript. Standard GPT-OSS composition uses low reasoning effort to
reduce competition between hidden reasoning and bounded visible prose; agent
reasoning remains unchanged. Groq documents the supported values and default
in its [API reference](https://console.groq.com/docs/api-reference). Live quality
and token savings from that setting were not measured.

Repeated source-library and generic professional-advice footer messages are
no longer appended. Saved answers filter those same known messages. Specific
unfinished-work and missing-evidence notices remain. Their presentation no
longer adds a warning triangle to each line. Calculation IDs, rule versions
and rounding-mode implementation metadata are removed from the answer card;
the response/audit data remains available.

## Operational issues separate from the paid Groq key

Local logs report Tavily HTTP 432 plan-usage failures. That is a separate
search-service allowance; existing backup search remains in place. Changing
Groq billing does not restore that allowance.

The conversation-turn migration still has not been applied to the shared
database. Durable server memory remains unavailable there; provided browser
history is the fallback. No shared database writes, provider-plan changes or
credential changes were performed in this review.

## Comparison and next improvements

The useful comparison with general assistants is observable behavior:
understand imperatives, retain relevant facts, calculate correctly, satisfy
every requested part, and state a specific gap without repetitive generic
footers. These repairs target that behavior rather than asserting model
equivalence. Clear calculations benefit from deterministic workflows; open
research and tool-dependent tasks still need the agent. This follows the
workflow/agent distinction in Anthropic's
[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

The next architectural work remains complete agent-transcript compaction,
activation of durable memory in the reviewed deployment, restoration of live
search capacity, and recurring evaluation of multi-turn end results. Tests
should check the final answer and state transitions, as described in
[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Validation

Full offline backend suite: **3,228 passed**, 21 skipped, 2 expected failures,
140 warnings. Frontend suite: **214 passed**. TypeScript, changed-file ESLint
and whitespace checks passed. The local backend reloaded successfully.
No live model completions or Groq tokens were used. Live answer quality,
external market/search integrations and production deployment remain unverified.

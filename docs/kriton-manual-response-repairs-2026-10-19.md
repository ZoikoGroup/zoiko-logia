# Manual response repairs — 19 October 2026

The supplied manual transcript showed incomplete manufacturing analysis, a misleading 43.20% widget, false corporation-tax coverage warnings, removal of correct amounts, failed scenario follow-ups, and repeated request-size failures. These are application defects as well as provider-capacity constraints. No model API calls were made for this repair.

## Research used

- [Groq rate limits](https://console.groq.com/docs/rate-limits): limits apply to the organization and include tokens per minute and per day, in addition to request counts. A per-request estimate cannot guarantee acceptance against the shared rolling allowance. The account console is authoritative for its actual limits.
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents): use simple composable patterns, clear tool interfaces, and evaluation; distinguish deterministic workflows from tasks requiring model-directed tool use.
- [Anthropic: Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents): keep useful context bounded rather than continuously accumulating tool output and conversation text.

These sources inform the design; they are not evidence that Kriton's live answer quality matches Claude or ChatGPT.

## Changes

1. The single-value calculation widget defers gross-sales/returns and multi-period statements. It previously used gross sales as the revenue denominator, producing 43.20% while the correct net-sales gross margin was 41.56%.
2. A bounded operating-statement calculation family scopes explicitly labelled inputs to their current or previous period. It calculates net sales, gross profit, operating expenses, operating profit, PBT, margins and profit changes with Decimal arithmetic. Values are not hardcoded. Missing, conflicting-currency, additional-expense and unsupported input shapes defer to the existing agent path.
3. Explicit gross-sales and COGS percentage sensitivities can retain original user inputs across failed assistant answers. The requested original/revised table is rendered side by side. Unsupported additional revisions defer rather than being silently ignored. The supported sensitivities apply to the original inputs; compounding requests defer.
4. Verified statement results enter the existing generation and numerical verification paths. All independently calculated results survive composition failure, with an explicit partial limitation. Incomplete agent output also retains the application results.
5. Topic coverage respects “ignore corporation tax.” Commentary review requests reach composition rather than being completed by arithmetic alone; coverage flags an omitted assessment of an explicitly unsupported business explanation.
6. Conversation context is bounded, prioritising complete original user inputs and recent user changes over lengthy assistant responses. Duplicate Explore Further context is removed; omitted messages are disclosed in the prompt. Unicode is retained rather than expanded into JSON escape sequences. Legacy escaped evidence remains supported.
7. The model sees tool definitions for the proposed task, plus calculation and requested chart capabilities. The registry and per-call authorization remain authoritative. Source passages already present in a tool result are not appended a second time merely to add citation identifiers; citation titles and URLs are retained.
8. The frontend labels partial answers as “some parts incomplete,” avoiding the false implication that every provider or verification failure requires more user information.
9. Explicitly quoted material identified as an untrusted document can be analysed without treating its embedded prompt-injection text as the user's instruction. Requests outside that quote are still screened. Regression checks cover the supplier reconciliation example and a direct instruction-revelation request appended outside the quote.

## Validation

The offline regressions include the original figures, altered amounts, mixed currencies, unknown expenses, both sequential sensitivities after failed answers, correct figures surviving release checks, provider failure preserving the statement, commentary omissions, bounded history, duplicate context and tool evidence, and citation mapping. Tests block live model transport.

Final validation: 3,157 backend tests passed, 21 skipped and 2 expected failures; 212 frontend tests passed. TypeScript, page ESLint and whitespace checks passed. The existing GitHub CI runs the full pytest suite, including these regression cases. The backend run reported 126 warnings, primarily existing mock-coroutine and dependency deprecation warnings.

## Limits of this verification

These are local code changes, not a deployment. Live Groq answers and production research integrations were not exercised. Shorter prompts reduce request pressure but do not implement a shared organization-wide token scheduler or remove daily/per-minute allowances. Very large documents, long tool results, missing sources, unavailable integrations and exhausted provider allowances can still produce a clearly identified partial answer or service failure. The deterministic statement recognizer supports explicitly labelled input families, not every possible financial document or phrasing. Broader tasks continue through the agent.

To retest manually, start a fresh chat with the original manufacturing question, then apply the sales increase and COGS increase in the same chat. Existing stored answer cards remain historical results. Check the audit alongside the answer, especially its completeness and executed tools.

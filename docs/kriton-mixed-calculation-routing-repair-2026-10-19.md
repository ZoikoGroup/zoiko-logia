# Mixed calculation and comparison routing repair

For `corr-a8a8e5772ed7`, the audit recorded a complete CALCULATION response
with zero model calls. This was a premature calculator shortcut, rather
than a provider failure. The successful gross-profit calculation was allowed
to stand for a request that also asked to highlight differences and retrieve
dated exchange-rate and share-price observations.

The shortcut's outstanding-part detector did not recognise the leading
comparison instruction. Its clause heuristic also excluded clauses containing
digits, so ticker and date characters could prevent lookup detection.
The detector now recognises leading comparison requests and explicit live
market/exchange-rate requests independently of numbers in those clauses.
Verified calculations remain available to the composition/recovery path,
but no longer satisfy those other parts by themselves.

When a provider fails, supported verified gross-profit results can also
explain the requested differences between the profit amount, profit margin,
exchange-rate observation and security quote. A fictional-company statement
is attributed to the user's description, never presented as a completed
security search. The response remains partial when live-data parts are not
completed. No current exchange rate or fictional share price is invented.

The saved answer's gross-margin row was `| Gross Margin | 35.00% |`.
The reported omission of `%` was not reproduced in the backend payload or
Markdown. A regression pins the output kind and displayed percentage; no
unverified frontend formatting fix was introduced.

Validation: 3,217 backend tests passed, 21 skipped, 2 expected failures and
140 warnings. Whitespace checks passed. No model calls, credential changes
or shared database writes were performed. Live integrations were not tested.

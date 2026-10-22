# Grounded example follow-up repair

Reported audit: `corr-404685098674`.

The application planned exchange-rate retrieval, market-data retrieval and
calculation. The agent failed with `provider_rate_limited` before executing
tools. Standard composition was not retried against the exhausted provider.
The independently verified calculation survived: gross profit £280,000 and
gross margin 35%. Its partial label was appropriate, but it did not supply
the requested explanatory example or complete the market-data parts.

Separately, the Explore further button submitted a topic preview capped at
500 characters as the follow-up context. This cut the original multipart
request and its final qualifiers. The button now uses the complete original
context, unwrapping follow-up chains without substituting a shortened topic
preview. Existing preview behavior remains available to preview callers.

For a verified gross-profit/gross-margin calculation, an explicit request for
an example now has an application-generated explanation available in the
provider-failure fallback. It uses the recorded inputs, their currencies and
the verified outputs. It explains the relationship without new assumptions,
causal claims or invented market observations. Unverified calculations and
unrequested examples do not use this fallback. Other calculation families
still use their existing recovery paths.

This does not restore provider capacity, execute an exchange-rate lookup or
invent a price for a fictional company. Market-data parts remain incomplete
when the agent cannot execute them, and the response remains partial.
The audit's estimated reservations are not treated as measured token billing.

Focused backend checks passed (12 tests); frontend follow-up checks passed
(12 tests). The full frontend suite passed (213 tests), TypeScript and
changed-file ESLint checks passed. No model-provider calls, credential changes
or shared database writes were performed.

Full offline backend suite: 3,210 passed, 21 skipped, 2 expected failures and
137 warnings. Live answer quality and market integrations remain unverified.

# Kriton evidence pipeline: follow-up root cause investigation

## Confirmed live blocker

A bounded live probe of the locally configured providers on 27 October 2026
confirmed **Tavily HTTP 432: configured usage limit exhausted**. The backup
search returned no usable sources for the three planned subjects. This is an
operational retrieval failure; it does not establish anything about the truth
of the user's tax claims.

The public-source-only probe result is saved in
[the live probe record](kriton-evidence-live-probe-2026-10-27.json).

The new research planner ran successfully against the configured classifier
and separated the prose comparison into transfer pricing, permanent
establishment, and withholding tax. No application records were accessed by
the probe, and no server was restarted or deployed.

This confirms the current local provider problem, not the precise provider
state of every historical request in the pasted transcript. Those original
per-request audit records were not available in the local logs searched.

## Shared defects repaired

1. **Research used the user's assertion as a search query and lost context.**
   Claim extraction removed the surrounding transfer-pricing context from the
   IP claim. Prose comparisons were still one search unless they happened to
   match a list/table regex. A shared, bounded semantic search planner now
   proposes neutral research subjects and alternatives for both agent tools
   and ordinary searches. Claim plans must preserve every claim ID; malformed,
   incomplete or jurisdiction-widening plans fall back to deterministic subjects.
   Plans cannot change source requirements or tool permissions.
2. **Contradictions were assigned arbitrary citations.** The verifier parsed
   reference bindings only for supported claims; the review renderer used the
   first two retrieved references for contradictions. Both verdict types now
   preserve and use the verifier's exact available references. An unbound
   contrary interpretation remains unverified. Negating a claim cannot become
   partial confirmation merely through word overlap. The judge retains the
   original request context and distinguishes professional regimes and draft
   documents from applicable rules.
3. **Provider failure looked like insufficient evidence.** Quota/credential/
   throttling failures now have a user-facing retrieval diagnostic rather than
   silently becoming `no_data`. Agent tools use `retrieval_unavailable`, and
   response limitations disclose degraded retrieval. Raw provider error bodies
   are not copied into user-facing messages. Such failures participate in the
   existing repeat-search suppression.
4. **Guidance classification depended on exact request wording and missed
   regulatory language.** Safely labelled process actions are now classified
   by their content, independently of whether the ask says “operational
   framework.” Domain nouns such as “tax correspondence” do not make an
   optional internal step a legal assertion. GDPR, privacy obligations, plural
   laws/regulations/standards, amounts, jurisdictions and accounting treatments
   retain strict evidence requirements. Factual assertions cannot be exempted
   by putting them under a guidance heading.
5. **Verification could remove the requested work without repairing coverage.**
   A bounded semantic coverage check compares the surviving response with the
   original request, across domains. It can trigger one repair even if the
   original draft failed verification. A repaired answer must pass the same
   factual, calculation and evidence checks. Unrepaired omissions are reported
   as partial, including the missing requested parts.
6. **Official PDFs were not read by ordinary web enrichment.** The HTML-only
   reader rejected them. Page enrichment now supports bounded PDF extraction
   with page locators and the existing overall read deadline. Tool-result space
   is shared across sources so later subjects retain an excerpt.
7. **Table row identifiers were treated as measurements.** Claim/verdict/status
   tables no longer produce chart offers just because their rows are numbered.
8. **Declarative modal sentences bypassed statement clarification.** Statements
   containing “may”, “can”, “might”, “could” or “should” now receive the same
   action choices as other statements; explicit requests still proceed.

## Validation scope

`backend/tests/test_research_pipeline_invariants.py` checks these contracts
across tax, IFRS, and audit requests, including planner failure, malformed plans,
missing claim IDs, introduced countries, exact contradiction references,
semantic omissions, rejected-draft repair, PDF extraction, quota diagnostics,
fair tool-result budgets, and numeric identifiers. It does not hardcode final
answers to the user's individual questions.

Validation completed:

- Full backend suite: **4,850 passed, 75 skipped, 22 expected failures**.
- After the final outage/repeat-search adjustment: **123 targeted checks
  passed**, including the new research invariants, agent loop, efficiency and
  planning suites.
- `git diff --check`: passed.
- Live check: semantic planning succeeded; all three source searches lacked
  usable evidence while the configured primary provider reported HTTP 432.
  A successful live sourced-answer result has **not** been claimed.

Existing uncommitted workspace changes were preserved. The change does not
increase account spending limits, replace credentials, deploy code, or relax
the verification requirement for tax/accounting rules.

## Remaining operational action

The search account's usage capacity must be restored, an approved working key
configured, or the existing backup search made functional before a successful
live sourced-answer retest can be claimed. Changing the planner or lowering
verification standards cannot replenish a provider quota. Tavily's existing
account-error pause lasts 30 minutes per worker; after restoring capacity,
allow that pause to expire or restart the relevant worker through the normal
operations process.

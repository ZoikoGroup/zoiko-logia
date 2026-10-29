# Follow-up: plain claim lists and accounting framework scope

The latest pasted results still fail important acceptance criteria. The
claim-check prompt produced ordinary prose rather than a claim verdict table;
the ASC 740 response used IAS 37 conditions as its substantive answer. Some
practical preparation advice improved, but documentation suggestions were
still repeatedly treated as source-mandated requirements.

## Reproduced causes and changes

- `is_review_request` required long material or colon-labelled structured
  bullets, and did not recognise “Check each claim separately”. Explicit
  claim-review instructions with multiple plain bullets now enter the review
  path regardless of character count or bullet labels. Production/advice
  requests still retain their task type.
- Source support and requested framework scope were separate problems. A
  correct statement of a foreign standard could survive with a warning.
  Newly composed responses now pass a final framework-scope boundary in
  `finish()`. When the request names one accounting framework, a substantive
  foreign-framework statement causes the narrative to be withheld, citations
  removed, and completeness set to `none`. The audit records a
  `framework_mismatch` removal. This also checks the framework of cited
  sources, so an unqualified sentence cannot hide the foreign framework of
  its evidence. Explicit multi-framework comparisons and honest evidence-gap
  notices are preserved.
- Practical document examples are now explicitly distinguished in the
  composition instructions from documents a standard mandates. Safe advice
  under nested topic headings remains within its enclosing general-guidance
  section; entering a peer legal-requirements section ends that exemption.
  Legal assertions, figures and accounting treatments retain their checks.

## Tests and limits

`backend/tests/test_framework_scope_and_plain_claims.py` covers explicit plain
claim lists, production requests, cross-framework cases in both directions,
source-framework bindings, comparisons, evidence gaps, nested documentation
suggestions, and the full orchestration path even when an earlier claim judge
accepts the foreign rule.

Validation on the final code: **4,864 backend tests passed**, with 75 skipped
and 22 expected failures. The targeted framework/research/tax-audit regressions
also passed (72 cases). `git diff --check` passed.

These changes do not prove the tax/accounting conclusions in the pasted
answers correct. The current turn did not recheck the provider quota or run
live sourced answers. The earlier HTTP 432 finding remains a separate
operational issue to confirm. No deployment or running-server restart was
performed, and previously stored answers were not rewritten.

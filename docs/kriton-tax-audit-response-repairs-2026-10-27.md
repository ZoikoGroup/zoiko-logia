# Kriton tax-audit response repairs — 27 October 2026

The reported transcript exposed a clarification loop, insufficient retrieval
coverage across claims and table rows, inappropriate auditing-source suggestions,
and operational advice being subjected to the same sourcing policy as legal rules.

## Changes

- Statement clarification now returns three explicit actions through
  `next_action.suggestions`: check accuracy, explain, and rewrite. The frontend
  offers these actions with the original material as context. It never reuses
  the assistant's clarification question as a prompt. Other missing-input
  questions, refusals and evidence-gap-only answers receive no generic follow-ups.
- Short structured material can enter the existing claim-review pipeline.
  Explain/rewrite actions retain their transformation intent when the material
  appears after `Context:`; checking legal requirements still needs authority.
- Labelled bullets and table rows become separate retrieval subjects before
  long-input shortening. Retrieval is bounded to eight subjects with existing
  concurrency and time limits. Empty multipart searches get one keyword retry
  within the same per-subject deadline. Different excerpts from the same URL
  are retained under one citation without modifying cached source objects.
- Claim review searches once more for claims whose evidence is absent or
  insufficient, then verifies them again. Supported claims are not researched
  again, and verifier outages do not trigger additional retrieval. Unresolved
  claims explain whether no source was found, evidence was insufficient, or
  verification failed. Missing evidence is not described as proof of falsity.
- Review completeness is `none`, `partial` or `complete` according to verified
  coverage. Follow-ups never suggest summarising confirmed claims when none
  were confirmed.
- Tax-authority audits route to tax sources rather than financial-statement
  auditing sources. Mixed questions that explicitly request assurance topics
  retain both source domains. Suggested publishers remain labelled suggestions,
  never evidence.
- Requests for an operational framework can retain optional process actions
  under `General operational guidance`. This exemption requires both a matching
  user request and the explicit heading, and applies only to conservative
  general-explanation sentences beginning with a process action. Figures,
  jurisdictions, legal obligations and accounting treatments retain their
  evidence requirements. The existing presentation note labels the guidance
  as general explanation rather than source-verified content.
- The strict sourcing prompt now requests a named unresolved point instead of
  requiring the same generic missing-evidence sentence for every part.

## Verification and limits

Regression cases are in `backend/tests/test_tax_audit_response_repairs.py` and
`frontend/tests/clarification-actions.test.ts`. They cover the reported risk
list and table, clarification actions, retrieval retries and passage merging,
review completeness, source routing, verifier outages, and the operational
guidance boundary. The statement actions and operational guidance also run
through the real orchestration pipeline with external boundaries stubbed.

Validation completed on the final code:

- Backend: `.venv/bin/python -m pytest -q --disable-warnings` from `backend/`:
  **4,814 passed, 75 skipped, 22 expected failures**. The suite emitted 265
  warnings, including existing mock-database coroutine warnings.
- Frontend: `npm test`: **242 passed across 52 files**.
- Frontend: `npx tsc --noEmit`: passed.
- Frontend: ESLint on `lib/follow-up-suggestions.ts` and
  `tests/clarification-actions.test.ts`: passed.
- `git diff --check`: passed.

No deployment, running-server restart, database migration, live search or paid
model calls were performed. These changes improve orchestration; they cannot
guarantee that a search provider finds supporting material or that a model's
professional reasoning is correct. Existing uncommitted workspace changes
were preserved.

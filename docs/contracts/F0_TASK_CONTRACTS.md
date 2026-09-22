# F0 pilot task contracts

**Contract version:** `f0.1`

**API schema version:** `1.0`

**Status:** engineering baseline; professional scope still requires named owner approval.

The live contract is published by authenticated `GET /api/v1/orchestration/task-specs`.
The browser may supply optional context, but does not need to select a workflow.
The backend detects intent, produces a bounded capability plan, and selects the
matching task contract. `actor_id`, `tenant_id`, `actor_role`, and data
classification are always resolved by the backend.

## Workflows

| Workflow | Required context | Allowed outputs | Review role |
| --- | --- | --- | --- |
| `general_question` | None | Educational answer, source summary | None |
| `policy_research` | Jurisdiction, framework, period end | Policy research, source comparison, draft conclusion | Qualified accounting reviewer |
| `document_evidence_extraction` | At least one authorized document | Extracted facts, locations, missing-field report | Evidence reviewer |
| `reconciliation` | Documents, period start/end, currency | Matches, unmatched items, variances, draft workpaper | Reconciliation reviewer |

All workflows prohibit autonomous posting, filing, fund movement, or issuance of
an assurance opinion. Customer documents are evidence about the customer and
must not be represented as governing authority.

## Jurisdiction and framework handling

Task contracts are jurisdiction-neutral. Jurisdiction and framework are context
values rather than workflow identifiers, and are not restricted by a country
allowlist. Source retrieval must still prove that suitable authoritative material
exists for the resolved jurisdiction, framework, and reporting date.

Engagement IDs are accepted only after F1 verifies an active membership and
explicit operation grants. The backend never treats a client-provided
engagement ID as authorized context.

## Request example

```json
{
  "query": "How should this lease modification be accounted for?",
  "jurisdiction": "UK",
  "task_context": {
    "jurisdiction": "UK",
    "framework": "IFRS",
    "period_end": "2026-12-31",
    "language": "en",
    "intended_use": "research"
  }
}
```

The response includes an auditable `workflow_plan` containing the detected task
family, confidence, reason codes, and registered capabilities. An explicit
`task_type` remains accepted as a compatibility override, but is not required.

## Clarification example

An incomplete policy request returns before retrieval or provider execution:

```json
{
  "outcome": "clarification_required",
  "route": "CLARIFICATION",
  "context_decision": {
    "status": "clarification_required",
    "missing_fields": ["framework", "period_end"],
    "reason_codes": ["MISSING_FRAMEWORK", "MISSING_PERIOD_END"],
    "clarification_questions": [
      "Which reporting framework applies (for example, IFRS or UK GAAP)?",
      "What reporting or transaction period end date should be used?"
    ]
  }
}
```

## Failure states

- `clarification_required`: required material context is missing.
- `unsupported`: jurisdiction/framework, language, period, or engagement scope
  is outside the approved implementation boundary.
- `unauthorized`: reserved for F1 operation-level authorization decisions.
- `complete`: retrieval may proceed using the normalized effective context.

Every decision emits a required `task_context_resolved` audit event containing
the task-spec version, normalized context, status, and stable reason codes.

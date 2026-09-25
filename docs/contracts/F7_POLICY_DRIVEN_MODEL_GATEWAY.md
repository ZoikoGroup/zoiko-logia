# Policy-driven model gateway

**Contract version:** `f7.1`

The gateway selects only explicitly approved model deployments. Eligibility is
decided from trusted server context before prompt content reaches a provider.
Environment-key order is retained only as a disabled-by-default compatibility
path while deployment records are reviewed and seeded.

## Eligibility invariants

A deployment must be enabled and approved, have an evaluation manifest, a
reviewed retention policy and verified training opt-out, support the task and
data classification, permit every requested provider tool, match the required
processing region, and have a configured adapter. Unknown values deny use.

Fallback deployments pass the complete eligibility decision independently. A
primary-provider failure never broadens region, data-class or tool access.

## Execution boundaries

- Per-provider and total deadlines are enforced outside the model.
- Provider calls are capped by configuration.
- Cancellation propagates without starting another provider call.
- Empty and legacy `[Error ...]` adapter outputs become typed failures, never answers.
- No eligible deployment produces `NO_ELIGIBLE_DEPLOYMENT`.
- Raw prompts and answers are not stored in model-run manifests.

## Durable manifest

Each governed execution records tenant, actor, correlation ID, selected
deployment/provider/model, task and data class, processing region, prompt and
policy versions, retrieval and tool versions, bounded attempts, terminal
status, reason code and output hash.

## Rollout

`MODEL_GATEWAY_POLICY_ENABLED=false` preserves the existing compatibility
selector. Before enabling it, apply the migration, register deployments through
the protected model registry API, obtain independent maker-checker approval,
and validate provider, outage, quota, region, data-class and tool-denial cases.

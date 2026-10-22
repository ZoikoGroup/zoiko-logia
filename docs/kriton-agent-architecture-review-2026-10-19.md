# Kriton agent architecture review — 19 October 2026

Implementation update: the subsequent [execution-hardening record](kriton-execution-hardening-2026-10-19.md) describes completed request-scoped Groq budget, retry, failure-outcome and explanation-instruction changes. The findings below describe the reviewed baseline; the implementation record distinguishes completed work from remaining architecture work.

## Conclusion

The manufacturing transcript exposed application orchestration and verification defects, alongside real provider capacity constraints. Recent fixes address the reproduced cases. They do not establish general conversational intelligence or live reliability across arbitrary questions.

The next engineering priority is a consistent task, fact, budget and outcome model across the whole request. Increasing the model allowance or adding more keyword exceptions cannot provide that consistency by itself.

This review used code inspection and public documentation. It did not call Groq, consume model tokens, change provider credentials, deploy services or implement the architectural recommendations below.

## Confirmed remaining weaknesses

| Finding | Code evidence | Practical effect |
| --- | --- | --- |
| The agent budget does not encompass the entire request | `agent_budget.py` governs agent generations; `orchestration/service.py` can separately call `run_grounded_completion` for relevance, arithmetic, guidance, release and coverage repairs | Total model work and latency can exceed what the agent's counters suggest |
| Retry ownership is distributed | The standard Groq adapter constructs an SDK client with `max_retries=1`, has its own rate-limit retry, and the gateway has fallback paths; the agent separately disables SDK retries | Attempts, deadlines and costs are difficult to predict globally |
| Provider backoff can be shortened | The standard adapter uses `min(float(retry-after), 10.0)` | A provider-requested longer cooldown can be followed by an early retry; if it exceeds the request deadline, the correct choice is to defer or return a capacity status |
| Request estimation is approximate | `request_prompt_estimate` estimates UTF-8 bytes divided by three; the run reservation counts UTF-8 bytes conservatively | Some requests can be rejected by the provider despite fitting the estimate, while conservative run reservations may stop others early |
| Organization-wide capacity is not reserved by the agent budget | `GenerationBudget` is created per agent run | Concurrent requests and subsequent tool-loop generations share a provider allowance without a corresponding shared token reservation here |
| Explanations can receive an inappropriate evidence requirement | `request_parts` can mark an explanation `needs_evidence=False`, but `parts_instruction` tells every non-calculated part to answer only from cited evidence | An ordinary explanation can be treated like a question requiring an external authoritative source |
| Semantic planning is not authoritative in production | `intent_planner.py` describes a structured planner; `planner_shadow.py` is observational and off unless enabled | Live task decisions still depend substantially on deterministic patterns; the structured planner should not be assumed to control current responses |
| Conversation memory is still message selection | `conversation_prompt` now bounds and deduplicates messages, prioritizing the earliest user turn and recent changes | Useful facts can still be omitted, and the earliest turn is not necessarily the relevant baseline for the current topic |
| Failure and refusal remain mixed in the response model | The composition-failure branch still returns `outcome="refused"` when no verified calculation can be recovered, with a separate provider next-action type | The UI can explain the provider error, but outcome-based audit metrics still risk conflating service failure with refusal |
| Numerical verification has incomplete semantic identity | `calculated_figures` builds sets of numerical values; a separate attribution layer reconstructs period/scenario tags from wording | Matching a number does not alone establish its metric, period, unit or scenario; independent heuristic checks must compensate |
| Unit-test success is not live answer-quality evidence | CI stubs external services; a separate live release gate exists | The passing offline suite proves regression behavior under its fixtures, not the quality of an actual model-and-tools session |

The presence of several checks is not itself a defect. The problem is inconsistent ownership and representation across checks. Authorization, privacy and genuine safety restrictions must remain explicit and enforced.

## Recommended implementation order

### 1. Unify failure handling and request budgets

Introduce a request-scoped execution context carrying the correlation ID, absolute deadline, model-attempt allowance, token reservations, actual usage and completed task results. Pass it through agent generation, verification, correction and fallback calls. Give retry ownership to one gateway layer, with SDK retries disabled there.

Classify authentication, spending exhaustion, request size, rate limit, transient connection failure and timeout separately. Retry only when the condition is recoverable, the cooldown has elapsed, and the request has time and budget remaining. Never shorten a provider cooldown to fit a local wait cap. A spending block should not cause attempts against other models on the same blocked account.

Add a shared admission controller for the configured provider organization and model. It should use the actual account configuration and observed rate-limit headers, coordinate workers, and distinguish per-minute from daily exhaustion. Reserve completion capacity as well as input capacity. Expire reservations safely and reconcile provider-reported usage; other applications sharing the account can still consume capacity outside this service.

Return a typed unavailable/deferred outcome for service capacity, a clarification only for missing information, and a refusal only for a real policy decision. Preserve completed results with a partial outcome.

### 2. Persist structured task and scenario state

Represent inputs as facts with IDs and explicit metric, value, currency, unit scale, period, scenario, source and assumption fields. Store them within the authenticated tenant/conversation scope. Preserve original facts and record revised facts as new scenario versions. A failed written answer must not erase the user's supplied facts.

Calculation receipts should refer to input fact IDs and produce output fact IDs. A chart should reference those same outputs. This makes a current-year GBP operating profit distinct from a prior-year operating profit or a percentage that happens to share the same digits.

Keep relevant structured facts, completed tasks and unresolved questions in the active model context. Retrieve earlier prose when needed. Do not rely exclusively on raw-history truncation or a model-written summary to preserve numerical inputs.

### 3. Plan explicit deliverables and evidence needs

Define a validated task contract: requested outputs, dependencies, supplied inputs, exclusions, formatting and evidence requirements. For the manufacturing example, corporation tax is an exclusion, while the table, changes, explanation and three questions are deliverables.

Use deterministic execution for confidently recognized arithmetic. Use the agent for flexible interpretation, explanations and research. The model proposes tools; server-side authorization determines whether they may execute. The existing shadow planner is a candidate for evaluation, not something to switch into authority without a comparison and rollback path. Avoid adding an extra planning call to every simple request.

Classify evidence requirements per claim: supplied-data calculations need traceable inputs and receipts; current legal or reporting requirements need authoritative sources and dates; management investigation questions can be framed as questions without pretending their suggested causes are established facts.

### 4. Verify against the task contract and fact dependencies

Validate numbers, periods, units, scenarios and chart data against the fact/receipt graph. Verify externally sourced claims against their cited passages. Evaluate completeness against the requested deliverables independently of factual accuracy.

Repair the failed section under the shared budget, keeping supported sections intact. If a section cannot be completed, show the completed sections and name the specific remaining gap. Avoid repeated full-answer rewrites. Existing regex checks can remain regression guards while structured checks are introduced incrementally.

### 5. Establish a measured release standard

Keep the existing offline CI and extend the existing evaluation/release harness rather than creating another parallel test system. Cover paraphrases, changed amounts and expense labels, multi-turn corrections, negative instructions, missing inputs, unavailable tools, provider limits, long conversations and quoted hostile document text.

Score task completion, calculation correctness, unsupported claims, unnecessary refusals, follow-up retention, tool selection, latency and total tokens across the entire request. Test the actual deployed configuration when live testing is authorized. Run repeat trials for nondeterministic outputs; keep human-reviewed examples to calibrate semantic graders.

The user has reserved live Groq testing for manual use. Until that changes, use scripted providers and the user's recorded manual transcripts. Do not silently enable the shadow planner, live release gate or model-based graders.

## Research and how it applies

- [Groq rate limits](https://console.groq.com/docs/rate-limits): limits apply at organization level; the service exposes remaining tokens, reset information and `retry-after` on a 429. This supports shared admission and correct backoff, not merely a smaller prompt cap.
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents): selective context, compaction and structured notes address long-running agent context problems. For Kriton, exact financial inputs should be retained as structured facts rather than entrusted solely to prose summaries.
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents): assess the harness and model together, inspect trajectories and outcomes, distinguish capability from regression tests, and use repeated trials. This explains why thousands of mocked unit tests cannot establish live conversational answer quality.

These references support engineering practices. They do not reveal the complete internal architecture of ChatGPT or Claude, prove the cause of an untraced Kriton incident, or guarantee that a particular model will answer every request correctly.

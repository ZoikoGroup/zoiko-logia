# Risk classifier rollout

`reviewed_queries.jsonl` is the version-controlled seed benchmark. Every added
row must include a stable ID, expected risk, review status, and reviewer. Replace
or supplement seed examples with de-identified production queries reviewed by
the safety/accounting owner; never commit raw PII, secrets, or tenant data.

## Evaluate

From the repository root:

```bash
RISK_LLM_CLASSIFIER_MODE=off backend/.venv/bin/python backend/scripts/evaluate_risk_classifier.py
```

The command prints per-class precision/recall, a confusion matrix, and a
dedicated list of HIGH/RESTRICTED false negatives. It exits non-zero when any
such false negative is present so it can be used as a release gate.

Before a classifier rollout, use the stricter production gate:

```bash
RISK_LLM_CLASSIFIER_MODE=shadow backend/.venv/bin/python \
  backend/scripts/evaluate_risk_classifier.py --release-gate
```

This additionally requires at least 50 reviewed examples per class, 90%
overall accuracy, and zero HIGH/RESTRICTED false negatives. It reports macro
precision/recall and the classifier's abstention rate. The small seed benchmark
is expected to fail the coverage gate; that is intentional.

## LLM rollout modes

- `off`: local zero-shot classifier only; unavailable/uncertain results safely
  become MEDIUM + clarification (or HIGH when an advice signal exists).
- `shadow`: call the structured LLM classifier for semantic queries, retain a
  confident local decision, and record the comparison in safety-event metadata.
- `fallback`: adopt a valid LLM result only when the local classifier is
  unavailable or below the confidence threshold.

Start in `shadow`. Review disagreements and provider latency/cost, add adjudicated
queries to the dataset, rerun the benchmark, and only then enable `fallback`.
Provider failures never fail open. Deterministic RESTRICTED rules always run
before either model and cannot be overridden by the LLM. Queries marked with a
privacy class other than `NONE` never leave the local classifier for the
external LLM fallback.

## Fine-tuning gate

Fine-tuning intentionally remains blocked until there are at least 50 reviewed
examples in each ZERO/LOW/MEDIUM/HIGH class:

```bash
backend/.venv/bin/python backend/scripts/train_deberta_risk_classifier.py \
  --dataset backend/data/risk_classifier/reviewed_queries.jsonl \
  --output-dir backend/artifacts/risk-classifier-v1
```

The small benchmark is for evaluation, not training. When the gate is met,
train the candidate, run it in shadow mode against the old classifier, and do
not switch until HIGH/RESTRICTED false negatives remain zero on an independently
reviewed holdout set.

## Ongoing review

Export de-identified disagreements and all cases where a reviewer raised a
LOW/ZERO result to HIGH/RESTRICTED. Adjudicate them weekly during rollout and
monthly after stabilization. Add confirmed cases to the benchmark without
changing old expected labels silently; label changes require review history.

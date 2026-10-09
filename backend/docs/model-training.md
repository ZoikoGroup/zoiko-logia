# Kriton model training and reinforcement learning

This adds offline supervised fine-tuning (SFT) and genuine reward-based GRPO
training using TRL. Both update model parameters (normally LoRA adapter
parameters). They do not run inside the API, replace the current Groq/Gemini
model, or train automatically after every rating.

## Data flow

Positive feedback is eligible only when the canonical tenant-scoped answer
has successful validation and an explicit successful authoritative release
check, with no degraded or escalated outcome. Verified saved corrections are
also eligible. A negative rating excludes the original answer. Sources must
include HTTPS content and the exact citation IDs bound to the answer.
Legacy records lacking citation bindings are excluded, never guessed.

The exporter includes the evidence in the prompt, rejects recognizable
structured personal information, reserves shipped evaluation questions,
reserves tenant/global database benchmarks, groups near-duplicate questions before train/holdout splitting, and excludes
identical prompts with conflicting answers. It uses the existing database
identity/RLS mechanism. Data stays local and tenant-specific. Regex privacy
screening does not detect every person's or organisation's name; this is not
a complete anonymization system. Source licensing and permitted training use
must be assessed for the chosen corpus; retrieval permission alone does not
establish permission to train on external text.

Datasets and candidates have hashes and manifests. Overlong examples are
excluded rather than losing their evidence through truncation. Limits respect
both the model and tokenizer capacities and reserve room for RL completions. Normal
training requires at least 50 distinct training and 10 distinct holdout prompts. These are
operational minimums, not evidence of statistical sufficiency.

## RL scope

The initial RL task set is exact arithmetic: percentages, percentage increases
and subtraction. The application's deterministic calculation engine produces
the expected values. GRPO samples responses and updates parameters from their
relative rewards. A response earns 1 only for a complete JSON object with one
`answer` key containing the exact finite numeric result; otherwise it earns 0.
It does not reward ratings, model self-confidence, keyword matches, or tax
claims. This first implementation does not train agent tool selection or
provide RL rewards for general factual/citation correctness. Those need
separate environments and validated reward functions.

## Run

Use a separate Python environment with `requirements-training.txt`. Do not
install training dependencies in the API container. Training can require
substantial CPU/GPU memory depending on the explicitly selected model. No
large model is downloaded by the smoke test.

From `backend/`:

```sh
python scripts/train_kriton.py smoke

python scripts/train_kriton.py export \
  --tenant-id YOUR_TENANT --user-id YOUR_DATABASE_USER \
  --output training_runs/sft-data-001

# Set TRAINING_BASE_MODEL to a compatible instruct model ID or local path.
python scripts/train_kriton.py train --mode sft \
  --base-model "$TRAINING_BASE_MODEL" --dataset training_runs/sft-data-001 \
  --output training_runs/sft-candidate-001 --steps 100

python scripts/train_kriton.py arithmetic --tenant-id YOUR_TENANT \
  --count 1000 --output training_runs/rl-data-001

python scripts/train_kriton.py train --mode grpo \
  --base-model "$TRAINING_BASE_MODEL" --adapter training_runs/sft-candidate-001 \
  --dataset training_runs/rl-data-001 --output training_runs/rl-candidate-001 \
  --steps 100

python scripts/train_kriton.py evaluate --dataset training_runs/rl-data-001 \
  --candidate training_runs/rl-candidate-001 \
  --output training_runs/rl-comparison-001.json
```

Omit `--adapter` to train directly from the base model. Adapter continuation
requires the same tenant and base model and unchanged parent weights. A
candidate must update weights and produce finite parameters and metrics to be accepted as a
training artifact. GRPO must also produce nonzero reward variation. The smoke
test uses a tiny randomly initialized language model and verifies SFT, LoRA,
GRPO, adapter continuation and holdout evaluation. It proves mechanics, not
usefulness on real questions.

## Evaluation and serving

The evaluator compares a candidate with the original base model on untouched
holdout rows. For adapter continuation, it compares against the unchanged
parent adapter so an RL regression cannot hide behind a weaker base model.
Candidate metadata version 2 records context budgets and parent hashes; older
metadata is rejected explicitly. Arithmetic uses exact numeric correctness. SFT uses strict answer
reproduction as a regression metric, not an independent factual judge.
Passing requires at least 10 cases, 90% accuracy and improvement over baseline.
The original model remains live regardless of the result. All artifacts and
reports remain `production_eligible: false` until separate independent full
pipeline factual, citation, tool and safety checks and the existing governed
promotion process are completed. Arithmetic-only improvement is not evidence
that a general tax assistant improved.

Serving also requires a compatible trained-model endpoint; a local LoRA
adapter cannot simply be assigned as the current Groq GPT-OSS model ID.
There is no automatic upload, deployment, or automatic production promotion.
A dedicated `watch` command now schedules persistent training cycles; it must
be started in the separate training environment with an explicit configuration. Production evidence checks still apply after any later model release.

References: [TRL SFT](https://huggingface.co/docs/trl/sft_trainer),
[TRL GRPO](https://huggingface.co/docs/trl/grpo_trainer),
[Groq adapter hosting](https://console.groq.com/docs/lora).


## Recurring training workflow

Create a private configuration file, for example `training_runs/workflow.json`:

```json
{
  "tenant_id": "YOUR_TENANT",
  "user_id": "YOUR_DATABASE_USER",
  "base_model": "YOUR_COMPATIBLE_INSTRUCT_MODEL_OR_LOCAL_PATH",
  "output_root": "scheduled",
  "interval_seconds": 86400,
  "steps": 100,
  "with_rl": true,
  "rl_count": 1000,
  "cpu": false
}
```

Paths are resolved relative to the configuration file. Install
`requirements-training.txt` in a separate environment; it includes the backend
requirements needed to read canonical feedback/evidence records.

```sh
python scripts/train_kriton.py cycle --config training_runs/workflow.json
python scripts/train_kriton.py watch --config training_runs/workflow.json
```

`cycle` runs once. `watch` checks daily (or at the configured interval). This
is a dedicated foreground process, not a running service installed by these
changes. Restart it after changing the schedule configuration. It requires
an explicit model and tenant/user identity; placeholder values do not enable
real training. The workflow uses a pinned database connection to preserve
RLS identity across commits.

The workflow waits for enough distinct verified examples, skips unchanged
content, prevents overlapping runs, and records progress/outcomes atomically.
Interrupted or failed runs are retained and the same data is not retrained
repeatedly; new inputs or training settings permit another attempt. SFT must
pass its holdout gate before RL starts. Successful candidates still await
independent full-pipeline evaluation. There is no production activation in
this workflow. A failed tiny-model smoke gate is an expected diagnostic
result, not a reason to weaken the production quality thresholds.

Inspect `workflow-state.json` and each run's `workflow-result.json` for
`WAITING_FOR_DATA`, `REJECTED_SFT`, `REJECTED_RL`, `FAILED`, `INTERRUPTED`, or
`AWAITING_INDEPENDENT_EVALUATION`. Quality improvements cannot be guaranteed
by adding a scheduler; they must be demonstrated with the selected model
and real held-out data. RL remains limited to exactly verifiable arithmetic.

After fixing a failed run's dependency or environment problem, explicitly
retry it once with `cycle --config training_runs/workflow.json --retry-failed`.
This flag does not bypass a rejected quality gate. Local base-model weight
changes also invalidate the unchanged-input check.

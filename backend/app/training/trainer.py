"""Actual SFT / GRPO parameter updates, isolated from the serving process."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from app.training.data import context_budget, digest, load_bundle, validate_distinct_examples
from app.training.rewards import exact_result_reward


def artifact_hash(path: Path) -> str:
    files = sorted(p for p in path.iterdir() if p.is_file() and
                   (p.suffix in {".safetensors", ".bin", ".model", ".txt"}
                    or (p.suffix == ".json" and p.name != "candidate.json")))
    if not any(p.suffix in {".safetensors", ".bin"} for p in files):
        raise ValueError("Candidate has no saved weights")
    hashes = {}
    for file in files:
        hasher = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        hashes[file.name] = hasher.hexdigest()
    return digest(hashes)


def run_training(*, dataset: Path, output: Path, base_model: str, mode: str,
                 steps: int = 100, seed: int = 42, adapter: Path | None = None,
                 cpu: bool = False, smoke: bool = False) -> dict:
    if mode not in {"sft", "grpo"} or not base_model or not 1 <= steps <= 100000:
        raise ValueError("A base model, sft/grpo mode and bounded positive steps are required")
    manifest, train, holdout = load_bundle(dataset, kind=mode, diagnostic=smoke)
    if len(train) < (2 if smoke else 50) or len(holdout) < (1 if smoke else 10):
        raise ValueError("Insufficient distinct examples: need at least 50 training and 10 holdout rows")
    if not smoke:
        validate_distinct_examples(train, holdout)
    if output.exists():
        raise ValueError("Candidate output already exists; choose a new directory")
    try:
        import torch
        from datasets import Dataset
        from peft import AutoPeftModelForCausalLM, LoraConfig
        from transformers import AutoConfig, AutoTokenizer, set_seed
        from trl import GRPOConfig, GRPOTrainer, SFTConfig, SFTTrainer
    except ImportError as exc:
        raise RuntimeError("Install requirements-training.txt in a separate training environment") from exc
    base_path = Path(base_model)
    base_hash = artifact_hash(base_path) if base_path.is_dir() else None
    set_seed(seed)
    config = AutoConfig.from_pretrained(base_model, trust_remote_code=False)
    base_revision = getattr(config, "_commit_hash", None)
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=False, revision=base_revision)
    capacity, completion_budget = context_budget(config, tokenizer, mode=mode, smoke=smoke)
    if not tokenizer.chat_template:
        raise ValueError("Base model must have a chat template")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left" if mode == "grpo" else "right"
    # Exclude overlong examples rather than truncating away their evidence or target.
    def fits(row):
        messages = row["prompt"] + (row["completion"] if mode == "sft" else [])
        return len(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=mode == "grpo")) <= capacity - completion_budget
    train, holdout = [r for r in train if fits(r)], [r for r in holdout if fits(r)]
    if len(train) < (2 if smoke else 50) or len(holdout) < (1 if smoke else 10):
        raise ValueError("Too few examples fit the model context; no training started")
    if not smoke:
        validate_distinct_examples(train, holdout)
    model = base_model
    parent_hash = None
    peft_config = None if smoke else LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                               target_modules="all-linear", task_type="CAUSAL_LM", revision=base_revision)
    if adapter:
        parent_hash = artifact_hash(adapter)
        previous = json.loads((adapter / "candidate.json").read_text())
        if (previous["base_model"] != base_model or previous["tenant_id"] != manifest["tenant_id"]
                or previous["artifact_hash"] != parent_hash or previous.get("smoke")):
            raise ValueError("Adapter provenance, tenant or base model mismatch")
        model = AutoPeftModelForCausalLM.from_pretrained(str(adapter), is_trainable=True,
                                                       trust_remote_code=False)
        if previous.get("base_revision") and getattr(model.config, "_commit_hash", None) != previous["base_revision"]:
            raise ValueError("Adapter's original base-model revision changed")
        if previous.get("base_artifact_hash") and artifact_hash(Path(base_model)) != previous["base_artifact_hash"]:
            raise ValueError("Adapter's original local base-model weights changed")
        peft_config = None
    common = dict(output_dir=str(output), max_steps=steps, seed=seed,
                  per_device_train_batch_size=2 if mode == "grpo" else 1,
                  gradient_accumulation_steps=1, learning_rate=1e-3 if smoke else 2e-5,
                  report_to="none", push_to_hub=False, save_strategy="no",
                  logging_steps=1 if smoke or mode == "grpo" else min(10, steps), eval_strategy="no", use_cpu=cpu,
                  bf16=not cpu and torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
                  gradient_checkpointing=not smoke, optim="adamw_torch", dataloader_pin_memory=False,
                  model_init_kwargs={"revision": base_revision} if isinstance(model, str) and base_revision else None)
    if mode == "sft":
        columns = ("prompt", "completion")
        args = SFTConfig(**common, max_length=capacity, completion_only_loss=True)
        trainer = SFTTrainer(model=model, args=args, processing_class=tokenizer, peft_config=peft_config,
                             train_dataset=Dataset.from_list([{k: r[k] for k in columns} for r in train]),
                             eval_dataset=Dataset.from_list([{k: r[k] for k in columns} for r in holdout]))
    else:
        columns = ("prompt", "expected")
        args = GRPOConfig(**common, num_generations=2, max_completion_length=completion_budget,
                          beta=0.04, use_vllm=False, mask_truncated_completions=not smoke,
                          generation_kwargs={"suppress_tokens": [i for i in range(len(tokenizer))
                              if i not in {tokenizer.convert_tokens_to_ids('{"answer":0}'),
                                           tokenizer.convert_tokens_to_ids('{"answer":1}')}]} if smoke else None)
        trainer = GRPOTrainer(model=model, args=args, processing_class=tokenizer, peft_config=peft_config,
                              reward_funcs=exact_result_reward,
                              train_dataset=Dataset.from_list([{k: r[k] for k in columns} for r in train]),
                              eval_dataset=Dataset.from_list([{k: r[k] for k in columns} for r in holdout]))
    before = {name: parameter.detach().clone() for name, parameter in trainer.model.named_parameters()
              if parameter.requires_grad}
    result = trainer.train()
    if any(not torch.isfinite(parameter).all().item()
           for parameter in trainer.model.parameters() if parameter.requires_grad):
        raise RuntimeError("Training produced non-finite weights; candidate rejected")
    changed = any(not torch.equal(before[name], parameter.detach())
                  for name, parameter in trainer.model.named_parameters() if name in before)
    metrics = {k: float(v) for k, v in result.metrics.items() if isinstance(v, (int, float))}
    if mode == "grpo" and not any(log.get("reward_std", 0) > 0 for log in trainer.state.log_history):
        raise RuntimeError("RL rewards had no variation; no useful learning signal, candidate rejected")
    if not changed or not all(math.isfinite(v) for v in metrics.values()):
        raise RuntimeError("Training did not produce finite metrics and changed weights; candidate rejected")
    trainer.save_model(str(output)); tokenizer.save_pretrained(str(output))
    report = {"version": 2, "status": "TRAINED_CANDIDATE", "mode": mode,
              "tenant_id": manifest["tenant_id"], "base_model": base_model,
              "base_revision": base_revision, "base_artifact_hash": base_hash,
              "parent_adapter": str(adapter.resolve()) if adapter else None, "parent_artifact_hash": parent_hash,
              "dataset_hash": digest(manifest), "artifact_hash": artifact_hash(output),
              "train_count": len(train), "holdout_count": len(holdout),
              "holdout_ids": [r["id"] for r in holdout], "seed": seed,
              "context_capacity": capacity, "completion_budget": completion_budget,
              "steps": trainer.state.global_step, "weights_changed": changed, "metrics": metrics,
              "created_at": datetime.now(timezone.utc).isoformat(), "smoke": smoke,
              "production_eligible": False,
              "reward_scope": "exact arithmetic JSON only" if mode == "grpo" else None}
    (output / "candidate.json").write_text(json.dumps(report, indent=2))
    return report

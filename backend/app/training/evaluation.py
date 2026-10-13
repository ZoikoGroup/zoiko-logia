"""Offline candidate comparison. It cannot authorize production deployment."""
from __future__ import annotations

import json
import math
from pathlib import Path

from app.training.data import digest, load_bundle
from app.training.rewards import exact_result_reward
from app.training.trainer import artifact_hash


def score_outputs(rows: list[dict], outputs: list[str], *, kind: str) -> dict:
    if not rows or len(rows) != len(outputs):
        raise ValueError("Evaluation requires one output per nonempty holdout row")
    if kind == "grpo":
        scores = exact_result_reward(outputs, [r["expected"] for r in rows])
    elif kind == "sft":
        # Exact reproduction is a conservative regression metric, NOT factual verification.
        def normalized(text):
            return " ".join(text.lower().split())
        scores = [float(normalized(text) == normalized(row["completion"][0]["content"]))
                  for row, text in zip(rows, outputs)]
    else:
        raise ValueError("Unknown evaluation kind")
    return {"count": len(rows), "accuracy": sum(scores) / len(scores)}


def compare_scores(baseline: dict, candidate: dict) -> dict:
    if baseline["count"] != candidate["count"] or candidate["count"] < 10:
        raise ValueError("Comparison requires at least 10 identical holdout cases")
    if any(not isinstance(metrics.get("accuracy"), (int, float))
           or not math.isfinite(metrics["accuracy"]) or not 0 <= metrics["accuracy"] <= 1
           for metrics in (baseline, candidate)):
        raise ValueError("Evaluation accuracy must be finite and between zero and one")
    passed = candidate["accuracy"] >= .9 and candidate["accuracy"] > baseline["accuracy"]
    return {"baseline": baseline, "candidate": candidate, "holdout_gate_passed": passed,
            "production_eligible": False,
            "remaining_gates": ["independent full-pipeline factual/citation/tool/safety evaluation",
                                "existing governed promotion authorization"]}


def evaluate_candidate(*, dataset: Path, candidate: Path, output: Path) -> dict:
    metadata = json.loads((candidate / "candidate.json").read_text())
    required = {"holdout_ids", "holdout_count", "context_capacity", "completion_budget",
                "mode", "dataset_hash", "artifact_hash", "tenant_id", "base_model"}
    if metadata.get("version") != 2 or not required <= metadata.keys():
        raise ValueError("Legacy or incomplete candidate metadata; produce a new candidate before evaluation")
    manifest, _, rows = load_bundle(dataset, kind=metadata["mode"])
    if (metadata["dataset_hash"] != digest(manifest) or metadata["artifact_hash"] != artifact_hash(candidate)
            or metadata["tenant_id"] != manifest["tenant_id"] or metadata.get("smoke")):
        raise ValueError("Candidate/dataset mismatch or smoke artifact")
    expected_ids = set(metadata["holdout_ids"])
    rows = [r for r in rows if r["id"] in expected_ids]
    if len(expected_ids) != metadata["holdout_count"] or {r["id"] for r in rows} != expected_ids:
        raise ValueError("Candidate holdout membership changed")
    if len(rows) < 10 or output.exists():
        raise ValueError("Need ten holdout cases and a new evaluation output path")
    base_path = Path(metadata["base_model"])
    if metadata.get("base_artifact_hash"):
        if not base_path.is_dir() or artifact_hash(base_path) != metadata["base_artifact_hash"]:
            raise ValueError("Original base model changed; cannot compare candidate")
    elif not metadata.get("base_revision"):
        raise ValueError("Original remote base model has no immutable revision")
    baseline_path = comparison_baseline(metadata)
    import torch
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoModelForCausalLM, AutoTokenizer

    def generate(model_path):
        tokenizer = AutoTokenizer.from_pretrained(str(candidate), trust_remote_code=False)
        if (Path(model_path) / "adapter_config.json").exists():
            model = AutoPeftModelForCausalLM.from_pretrained(str(model_path), trust_remote_code=False)
        else:
            model = AutoModelForCausalLM.from_pretrained(str(model_path), trust_remote_code=False,
                revision=metadata.get("base_revision") if model_path == metadata["base_model"] else None)
        if metadata.get("base_revision") and getattr(model.config, "_commit_hash", None) != metadata["base_revision"]:
            raise ValueError("Loaded model uses a different original base revision")
        model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        answers = []
        for row in rows:
            text = tokenizer.apply_chat_template(row["prompt"], tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False).to(device)
            remaining = metadata["context_capacity"] - inputs.input_ids.shape[1]
            if remaining <= 0:
                raise ValueError("Holdout prompt exceeds candidate context capacity")
            budget = min(remaining, metadata["completion_budget"] if metadata["mode"] == "grpo" else 512)
            with torch.no_grad():
                generated = model.generate(**inputs, max_new_tokens=budget,
                                           do_sample=False, pad_token_id=tokenizer.pad_token_id)
            answers.append(tokenizer.decode(generated[0, inputs.input_ids.shape[1]:], skip_special_tokens=True))
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
        return answers
    baseline = score_outputs(rows, generate(baseline_path), kind=metadata["mode"])
    trained = score_outputs(rows, generate(str(candidate)), kind=metadata["mode"])
    report = {**compare_scores(baseline, trained), "artifact_hash": metadata["artifact_hash"],
              "dataset_hash": metadata["dataset_hash"], "baseline_model": baseline_path, "metric": "exact_arithmetic" if metadata["mode"] == "grpo"
              else "exact_answer_regression"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    return report


def comparison_baseline(metadata: dict) -> str:
    """Compare continuation against its actual parent, with immutable weights."""
    parent_path = metadata.get("parent_adapter")
    if not parent_path:
        return metadata["base_model"]
    parent = Path(parent_path)
    if not parent.is_dir() or artifact_hash(parent) != metadata.get("parent_artifact_hash"):
        raise ValueError("Parent adapter changed or is unavailable; cannot compare continuation")
    return parent_path

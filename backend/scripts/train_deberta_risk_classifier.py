#!/usr/bin/env python3
"""Fine-tune DeBERTa after the reviewed-data release gate is satisfied.

This script intentionally refuses to train on the small seed benchmark. Set
MIN_REVIEWED_EXAMPLES_PER_CLASS only through a deliberate reviewed rollout.
RESTRICTED examples are excluded: deterministic rules remain authoritative.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path


LABELS = ("ZERO", "LOW", "MEDIUM", "HIGH")


def load_reviewed(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("review_status") == "reviewed" and row.get("expected_risk") in LABELS]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-model", default="microsoft/deberta-v3-small")
    parser.add_argument("--minimum-per-class", type=int, default=50)
    parser.add_argument("--epochs", type=float, default=3.0)
    args = parser.parse_args()

    rows = load_reviewed(args.dataset)
    counts = Counter(row["expected_risk"] for row in rows)
    missing = {label: args.minimum_per_class - counts[label] for label in LABELS if counts[label] < args.minimum_per_class}
    if missing:
        detail = ", ".join(f"{label}: need {needed} more" for label, needed in missing.items())
        raise SystemExit(f"Fine-tuning gate not met ({detail}). Keep using zero-shot + LLM fallback.")

    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments
    except ImportError as exc:
        raise SystemExit(f"Training dependencies unavailable: {exc}") from exc

    random.Random(42).shuffle(rows)
    split = max(1, int(len(rows) * 0.8))
    train_rows, eval_rows = rows[:split], rows[split:]
    label_to_id = {label: index for index, label in enumerate(LABELS)}
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    class RiskDataset(torch.utils.data.Dataset):
        def __init__(self, items: list[dict]):
            self.items = items
        def __len__(self):
            return len(self.items)
        def __getitem__(self, index: int):
            row = self.items[index]
            encoded = tokenizer(row["query"], truncation=True, max_length=256)
            encoded["labels"] = label_to_id[row["expected_risk"]]
            return encoded

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=len(LABELS),
        id2label={index: label for label, index in label_to_id.items()},
        label2id=label_to_id,
    )
    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=16,
        learning_rate=2e-5,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        seed=42,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=RiskDataset(train_rows),
        eval_dataset=RiskDataset(eval_rows),
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

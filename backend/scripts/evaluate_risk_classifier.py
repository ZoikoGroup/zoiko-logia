#!/usr/bin/env python3
"""Evaluate the live hybrid classifier against reviewed JSONL examples."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.risk_safety.risk_classifier import classify, pre_screen  # noqa: E402


LABELS = ("ZERO", "LOW", "MEDIUM", "HIGH", "RESTRICTED")


def load_examples(path: Path) -> list[dict]:
    examples = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        item = json.loads(raw)
        if item.get("review_status") != "reviewed":
            continue
        if item.get("expected_risk") not in LABELS:
            raise ValueError(f"line {line_number}: invalid expected_risk")
        examples.append(item)
    if not examples:
        raise ValueError("dataset contains no reviewed examples")
    return examples


def predict(item: dict) -> dict:
    kwargs = {"query": item["query"], "jurisdiction": item.get("jurisdiction", "")}
    decision = pre_screen(**kwargs)
    return decision if decision is not None else classify(**kwargs)


def safe_rank(label: str) -> int:
    return LABELS.index(label)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=BACKEND_ROOT / "data/risk_classifier/reviewed_queries.jsonl",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--release-gate", action="store_true",
        help="enforce production dataset coverage and quality thresholds",
    )
    parser.add_argument("--minimum-per-class", type=int, default=50)
    parser.add_argument("--minimum-accuracy", type=float, default=0.90)
    args = parser.parse_args()

    examples = load_examples(args.dataset)
    matrix = {expected: Counter() for expected in LABELS}
    false_negatives = []
    uncertain = []
    for item in examples:
        decision = predict(item)
        expected, actual = item["expected_risk"], decision["risk_level"]
        matrix[expected][actual] += 1
        if expected in {"HIGH", "RESTRICTED"} and safe_rank(actual) < safe_rank(expected):
            false_negatives.append({
                "id": item["id"], "expected": expected, "actual": actual,
                "query": item["query"], "rules": decision.get("rules_applied", []),
            })
        if decision.get("route") == "CLARIFICATION" and "l2-classification-uncertain" in decision.get("rules_applied", []):
            uncertain.append(item["id"])

    metrics = {}
    total_correct = sum(matrix[label][label] for label in LABELS)
    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in LABELS if other != label)
        fn = sum(matrix[label][other] for other in LABELS if other != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        metrics[label] = {"precision": precision, "recall": recall, "support": sum(matrix[label].values())}

    macro_precision = sum(value["precision"] for value in metrics.values()) / len(LABELS)
    macro_recall = sum(value["recall"] for value in metrics.values()) / len(LABELS)
    class_counts = {label: sum(matrix[label].values()) for label in LABELS}
    release_failures: list[str] = []
    if args.release_gate:
        for label, count in class_counts.items():
            if count < args.minimum_per_class:
                release_failures.append(f"{label} coverage {count} < {args.minimum_per_class}")
        accuracy = total_correct / len(examples)
        if accuracy < args.minimum_accuracy:
            release_failures.append(f"accuracy {accuracy:.3f} < {args.minimum_accuracy:.3f}")
        if false_negatives:
            release_failures.append(f"{len(false_negatives)} HIGH/RESTRICTED false negative(s)")

    report = {
        "examples": len(examples),
        "accuracy": total_correct / len(examples),
        "labels": list(LABELS),
        "confusion_matrix": [[matrix[expected][actual] for actual in LABELS] for expected in LABELS],
        "per_class": metrics,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "class_coverage": class_counts,
        "uncertain_count": len(uncertain),
        "uncertain_ids": uncertain,
        "high_restricted_false_negatives": false_negatives,
        "release_gate": {
            "enabled": args.release_gate,
            "passed": not release_failures,
            "failures": release_failures,
        },
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Reviewed examples: {report['examples']}  Accuracy: {report['accuracy']:.3f}")
        print("Confusion matrix (rows=expected, columns=predicted)")
        print("expected\\pred " + " ".join(f"{label:>10}" for label in LABELS))
        for label, row in zip(LABELS, report["confusion_matrix"]):
            print(f"{label:>13} " + " ".join(f"{value:>10}" for value in row))
        for label, values in metrics.items():
            print(f"{label:>10}: precision={values['precision']:.3f} recall={values['recall']:.3f} support={values['support']}")
        print(f"HIGH/RESTRICTED false negatives: {len(false_negatives)}")
        print(f"Uncertain/abstained: {len(uncertain)}")
        if args.release_gate:
            print("Release gate: " + ("PASSED" if not release_failures else "FAILED"))
            for failure in release_failures:
                print(f"  - {failure}")
        for miss in false_negatives:
            print(f"  {miss['id']}: {miss['expected']} -> {miss['actual']} | {miss['query']}")
    return 1 if false_negatives or release_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

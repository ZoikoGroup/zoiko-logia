"""Offline training CLI; never starts training inside an HTTP request."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export verified tenant feedback from the database")
    export.add_argument("--tenant-id", required=True)
    export.add_argument("--user-id", required=True, help="Database identity used for tenant RLS")
    export.add_argument("--output", type=Path, required=True)
    arithmetic = commands.add_parser("arithmetic", help="Create deterministic RL tasks; no user data")
    arithmetic.add_argument("--output", type=Path, required=True)
    arithmetic.add_argument("--tenant-id", default="synthetic", help="Use the SFT tenant when continuing its adapter")
    arithmetic.add_argument("--count", type=int, default=1000)
    arithmetic.add_argument("--seed", type=int, default=42)
    train = commands.add_parser("train", help="Run SFT or genuine reward-based GRPO training")
    train.add_argument("--mode", choices=["sft", "grpo"], required=True)
    train.add_argument("--dataset", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--base-model", required=True, help="Model ID or local model directory")
    train.add_argument("--adapter", type=Path, help="Continue a compatible tenant-scoped adapter")
    train.add_argument("--steps", type=int, default=100)
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--cpu", action="store_true")
    evaluate = commands.add_parser("evaluate", help="Compare a candidate and base model on untouched holdout data")
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    for name in ("cycle", "watch"):
        command = commands.add_parser(name, help="Persistent periodic training workflow")
        command.add_argument("--config", type=Path, required=True)
        if name == "cycle":
            command.add_argument("--retry-failed", action="store_true", help="Explicitly retry an interrupted or failed cycle")
    commands.add_parser("smoke", help="Tiny offline weight-update checks; no production model downloads")
    args = parser.parse_args()
    from app.training.data import digest, split_examples, write_bundle
    if args.command == "export":
        async def export_data():
            from dotenv import load_dotenv
            load_dotenv(BACKEND / ".env")
            from app.training.workflow import exportable_examples
            examples = await exportable_examples(tenant_id=args.tenant_id, user_id=args.user_id)
            train_rows, holdout = split_examples(examples)
            from app.training.data import validate_distinct_examples
            validate_distinct_examples(train_rows, holdout)
            return write_bundle(args.output, tenant_id=args.tenant_id, kind="sft", train=train_rows, holdout=holdout)
        result = asyncio.run(export_data())
    elif args.command == "arithmetic":
        from app.training.rewards import arithmetic_tasks
        rows = arithmetic_tasks(count=args.count, seed=args.seed)
        holdout = [r for r in rows if int(digest(r["group"])[:8], 16) % 5 == 0]
        train_rows = [r for r in rows if r not in holdout]
        result = write_bundle(args.output, tenant_id=args.tenant_id, kind="grpo", train=train_rows, holdout=holdout)
    elif args.command == "train":
        from app.training.trainer import run_training
        result = run_training(dataset=args.dataset, output=args.output, base_model=args.base_model,
                              mode=args.mode, steps=args.steps, seed=args.seed, cpu=args.cpu, adapter=args.adapter)
    elif args.command in {"cycle", "watch"}:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env")
        from app.training.workflow import read_config, run_cycle, watch_cycles
        if args.command == "watch":
            watch_cycles(args.config.resolve())
            return
        result = run_cycle(read_config(args.config.resolve()), retry_failed=args.retry_failed)
    elif args.command == "evaluate":
        from app.training.evaluation import evaluate_candidate
        result = evaluate_candidate(dataset=args.dataset, candidate=args.candidate, output=args.output)
    else:
        from app.training.smoke import smoke_training
        result = smoke_training()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ImportError as exc:
        raise SystemExit("Install requirements-training.txt in a separate training environment") from exc
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))

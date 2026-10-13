"""Persistent offline training cycles. Live serving is never changed here."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.training.data import digest, question_key, split_examples, validate_distinct_examples, write_bundle
from app.training.evaluation import evaluate_candidate
from app.training.rewards import arithmetic_tasks
from app.training.trainer import artifact_hash, run_training


async def exportable_examples(*, tenant_id: str, user_id: str) -> list[dict]:
    from app.core.database import RequestSessionLocal, request_engine, restore_request_identity
    from app.training.data import collect_examples
    # Bind to one connection: identity restoration commits, and an unbound
    # session could then reacquire a different pooled connection for its reads.
    async with request_engine.connect() as connection:
        async with RequestSessionLocal(bind=connection) as db:
            await restore_request_identity(db, tenant_id=tenant_id, user_id=user_id)
            examples = await collect_examples(db, tenant_id=tenant_id)
    return exclude_shipped_benchmarks(examples)


def exclude_shipped_benchmarks(examples: list[dict]) -> list[dict]:
    backend = Path(__file__).resolve().parents[2]
    reserved = set()
    for path in (backend / 'evals').glob('*.json'):
        payload = json.loads(path.read_text())
        cases = payload.get('cases', []) if isinstance(payload, dict) else payload
        if isinstance(cases, list):
            reserved.update(question_key(case['question']) for case in cases
                            if isinstance(case, dict) and isinstance(case.get('question'), str))
    tokens = [set(q.split()) for q in reserved]
    return [row for row in examples if not any(
        len(set(row['group'].split()) & other) / max(1, len(set(row['group'].split()) | other)) >= .7
        for other in tokens)]


def read_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    if not isinstance(config, dict):
        raise ValueError('Training configuration must be an object')
    for name in ('tenant_id', 'user_id', 'base_model', 'output_root'):
        if not isinstance(config.get(name), str) or not config[name].strip():
            raise ValueError(f'Training configuration requires {name}')
    for name, default, low, high in (('interval_seconds', 86400, 3600, 2592000),
                                   ('steps', 100, 1, 100000), ('rl_count', 1000, 100, 100000)):
        value = config.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'Invalid training configuration: {name}')
        config[name] = value
    for name in ('cpu', 'with_rl'):
        if not isinstance(config.get(name, False), bool):
            raise ValueError(f'{name} must be boolean')
        config.setdefault(name, False)
    root = Path(config['output_root']).expanduser()
    config['output_root'] = str((path.parent / root).resolve() if not root.is_absolute() else root.resolve())
    model = Path(config['base_model']).expanduser()
    relative = path.parent / model
    if model.is_absolute() or relative.is_dir():
        config['base_model'] = str((model if model.is_absolute() else relative).resolve())
    return config


def atomic_report(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.training-state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def cycle_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.cycle.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another training cycle is already running') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_cycle(config: dict, *, collector=None, trainer=None, evaluator=None, retry_failed: bool = False) -> dict:
    """Run one bounded SFT/evaluation/optional RL cycle and persist its outcome.

    Rejected candidates are recorded and unchanged data is not retrained daily.
    A new configuration or new evidence permits a new run. Failures also stop
    repeated expensive retries on the same data until inputs change.
    """
    collector = collector or (lambda: asyncio.run(exportable_examples(
        tenant_id=config['tenant_id'], user_id=config['user_id'])))
    trainer, evaluator = trainer or run_training, evaluator or evaluate_candidate
    root = Path(config['output_root'])
    with cycle_lock(root):
        state_path = root / 'workflow-state.json'
        previous = json.loads(state_path.read_text()) if state_path.exists() else {}
        identity = {key: config[key] for key in ('tenant_id', 'user_id', 'base_model')}
        if previous and previous.get('identity') != identity:
            raise ValueError('Output directory belongs to a different training identity; use a new directory')
        if previous.get('status') == 'RUNNING':
            previous.update(status='INTERRUPTED', reason='Previous worker stopped before completing this cycle')
            atomic_report(state_path, previous)
        report = {'identity': identity, 'status': 'COLLECTING', 'production_eligible': False,
                  'created_at': datetime.now(timezone.utc).isoformat()}
        stage = 'collect'
        run = None
        def checkpoint(stage_name):
            report.update(status='RUNNING', stage=stage_name)
            atomic_report(state_path, report)
            if run:
                atomic_report(run / 'workflow-result.json', report)
        try:
            rows = collector()
            fingerprint = digest(sorted({digest({'prompt': r['prompt'], 'completion': r['completion']})
                                         for r in rows}))
            model_path = Path(config['base_model'])
            model_hash = artifact_hash(model_path) if model_path.is_dir() else None
            settings_hash = digest({'settings': {key: config.get(key) for key in
                                    ('base_model', 'steps', 'with_rl', 'rl_count', 'cpu')},
                                    'local_model_hash': model_hash, 'workflow_version': 1})
            report.update(data_hash=fingerprint, settings_hash=settings_hash)
            retry = retry_failed and previous.get('status') in {'FAILED', 'INTERRUPTED'}
            if not retry and previous.get('data_hash') == fingerprint and previous.get('settings_hash') == settings_hash:
                return {**previous, 'status': 'SKIPPED_UNCHANGED', 'previous_status': previous['status']}
            train, holdout = split_examples(rows)
            report.update(train_count=len(train), holdout_count=len(holdout))
            stage = 'data_eligibility'
            try:
                validate_distinct_examples(train, holdout)
            except ValueError as exc:
                report.update(status='WAITING_FOR_DATA', reason=str(exc))
                atomic_report(state_path, report)
                return report
            run = root / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
            run.mkdir(mode=0o700)
            data = run / 'sft-data'
            write_bundle(data, tenant_id=config['tenant_id'], kind='sft', train=train, holdout=holdout)
            report['run_directory'] = str(run)
            stage = 'sft_training'
            candidate = run / 'sft-candidate'
            checkpoint(stage)
            trainer(dataset=data, output=candidate, base_model=config['base_model'], mode='sft',
                    steps=config['steps'], cpu=config['cpu'])
            stage = 'sft_evaluation'
            checkpoint(stage)
            evaluation = evaluator(dataset=data, candidate=candidate, output=run / 'sft-evaluation.json')
            report['sft_evaluation'] = evaluation
            if not evaluation['holdout_gate_passed']:
                report.update(status='REJECTED_SFT', reason='Candidate did not meet improvement/accuracy requirements')
            elif not config['with_rl']:
                report.update(status='AWAITING_INDEPENDENT_EVALUATION', candidate=str(candidate))
            else:
                stage = 'rl_data'
                tasks = arithmetic_tasks(count=config['rl_count'])
                rl_holdout = [row for row in tasks if int(digest(row['group'])[:8], 16) % 5 == 0]
                held_ids = {row['id'] for row in rl_holdout}
                rl_train = [row for row in tasks if row['id'] not in held_ids]
                rl_data, rl_candidate = run / 'rl-data', run / 'rl-candidate'
                write_bundle(rl_data, tenant_id=config['tenant_id'], kind='grpo', train=rl_train, holdout=rl_holdout)
                stage = 'rl_training'
                checkpoint(stage)
                trainer(dataset=rl_data, output=rl_candidate, base_model=config['base_model'], mode='grpo',
                        adapter=candidate, steps=config['steps'], cpu=config['cpu'])
                stage = 'rl_evaluation'
                checkpoint(stage)
                report['rl_evaluation'] = evaluator(dataset=rl_data, candidate=rl_candidate, output=run / 'rl-evaluation.json')
                report.update(status='AWAITING_INDEPENDENT_EVALUATION' if report['rl_evaluation']['holdout_gate_passed']
                              else 'REJECTED_RL', candidate=str(rl_candidate))
        except Exception as exc:
            # Persist failure stage without echoing provider errors or private prompts.
            report.update(status='FAILED', failed_stage=stage, error_type=type(exc).__name__)
        atomic_report(state_path, report)
        if run:
            atomic_report(run / 'workflow-result.json', report)
        return report


def watch_cycles(config_path: Path) -> None:
    """Dedicated foreground scheduler. Restart-safe via durable state and lock."""
    while True:
        config = read_config(config_path)
        started = time.monotonic()
        print(json.dumps(run_cycle(config)), flush=True)
        time.sleep(max(1, config['interval_seconds'] - (time.monotonic() - started)))

"""Run unchanged original questions/scorer with external services unavailable.

This reports scores honestly; it is not a model-quality benchmark. Enable
explicitly to avoid writing investigation artifacts on every ordinary test run.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from tests.offline_http_support import offline_http  # noqa: F401


@pytest.mark.skipif(os.getenv('RUN_OFFLINE_ORIGINAL_BENCHMARK') != '1', reason='Explicit isolated original-benchmark replay')
async def test_original_questions_and_scorer_unchanged(offline_http):
    backend = Path(__file__).resolve().parents[1]
    files = sorted((backend / 'evals').rglob('*.json'))
    digest = lambda: {str(p.relative_to(backend)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before = digest()
    spec = importlib.util.spec_from_file_location('original_baseline', backend / 'scripts/run_baseline_eval.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    cases = original.load_cases(None)
    results = []
    for case in cases:
        offline_http.rate_storage.reset()
        history = []
        name = case['source'] + '-' + case['id']
        for i, turn in enumerate(case.get('turns', [])):
            previous = await offline_http.ask(turn, case_id=f'original-{name}-turn-{i}',
                                              conversation=name, history=history, allow_http_error=True)
            history.extend([{'role': 'user', 'content': turn},
                            {'role': 'assistant', 'content': original._reply_text(previous.body)[:4000]}])
        current = await offline_http.ask(case['question'], case_id='original-' + name,
                                        conversation=name, history=history, allow_http_error=True)
        payload = dict(current.body)
        if current.trace['http_status'] != 200:
            payload['_http_error'] = f'HTTP {current.trace["http_status"]}'
        payload['_tools_used'] = [a['payload'].get('tool') for a in current.trace['audit'] if a['event'] == 'agent_tool_called']
        failures = original.score(case, payload)
        from app.domains.evaluation.pipeline_metrics import measure
        metrics = measure(case, payload, failures)
        failures += [f'{key}: curated expectation failed' for key, passed in (metrics.get('curated_checks') or {}).items() if passed is False]
        results.append({'id': case['id'], 'source': case['source'], 'correlation_id': payload.get('correlation_id'),
                        'passed': not failures, 'failures': failures, 'outcome': payload.get('outcome'),
                        'latency_ms': current.trace['latency_ms'], 'http_status': current.trace['http_status'],
                        'scripted_provider_calls': len(current.trace['model_requests'])})
    assert before == digest(), 'An original benchmark case or report changed'
    summary = {'scope': 'unchanged original cases and scorer; synthetic external transport; not live model quality',
               'total': len(results), 'passed': sum(r['passed'] for r in results),
               'failed': sum(not r['passed'] for r in results), 'results': results,
               'unchanged_file_sha256': before}
    folder = Path(os.getenv('KRITON_TRACE_DIR', '/private/tmp/kriton-root-cause-benchmark'))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'original-benchmark-summary.json').write_text(json.dumps(summary, indent=2))
    assert len(results) == len(cases) == 80

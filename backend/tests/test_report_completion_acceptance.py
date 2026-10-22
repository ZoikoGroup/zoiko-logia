"""Six-section reports must complete or explicitly fail, never pass as partial."""
import asyncio
import pytest
from tests.offline_http_support import offline_http  # noqa: F401
from tests.test_agent_request_size import QUESTION
from tests.test_root_cause_http import output
from app.orchestration.answer_coverage import (
    DEFAULT_MANAGEMENT_REPORT_SECTIONS, check_requested_deliverables, report_section_names,
)

SECTIONS = DEFAULT_MANAGEMENT_REPORT_SECTIONS
REPORT = QUESTION + '\nPrepare a management report with these sections:\n' + '\n'.join(
    f'{i}. {name}' for i, name in enumerate(SECTIONS, 1))


def test_numbered_report_sections_do_not_erase_supplied_statement_inputs():
    from app.orchestration.calculations.statements import operating_statement
    result = operating_statement(REPORT)
    assert result is not None and result.status == 'success'
    values = {item.name: item.value for item in result.outputs}
    assert values['current_profit_before_tax'] == 177000
    assert operating_statement(REPORT + '\nUnclassified expense: £999') is None


def test_six_required_sections_are_defined_and_empty_headings_fail():
    assert report_section_names('Prepare a six-section management report.') == list(SECTIONS)
    checks = check_requested_deliverables(REPORT, '\n\n'.join('## '+s for s in SECTIONS))
    assert len(checks) == 6
    assert all(c.status == 'incomplete' for c in checks)


def test_complete_section_content_passes_structural_validation():
    text = '\n\n'.join('## '+s+'\nReview the supplied financial records.' for s in SECTIONS)
    checks = check_requested_deliverables(REPORT, text)
    assert len(checks) == 6 and all(c.status == 'complete' for c in checks)
    # Structural presence alone does not replace numerical/evidence validation.


@pytest.mark.parametrize('multi_turn', [False, True])
@pytest.mark.parametrize('failure', [RuntimeError('synthetic_service_unavailable'), asyncio.TimeoutError()])
async def test_provider_failure_explicitly_fails_six_section_acceptance(offline_http, multi_turn, failure):
    conversation = 'report-acceptance'
    if multi_turn:
        await offline_http.ask('Revenue £100 and cost of sales £60. Calculate gross profit.',
                               conversation=conversation, case_id='report-prior')
    offline_http.state.failure = failure
    case_id = f'report-{type(failure).__name__}-multi-{multi_turn}'
    result = await offline_http.ask(REPORT, conversation=conversation, case_id=case_id)
    body = result.body
    assert body['outcome'] == 'unavailable'
    assert body['answer']['completeness'] == 'partial'
    assert body['next_action']['type'] == 'report_incomplete'
    assert 'cannot complete the requested report' in body['answer']['text']
    assert len([d for d in body['requested_deliverables'] if d['description'] in SECTIONS]) == 6
    assert any(d['status'] == 'incomplete' for d in body['requested_deliverables'])
    assert output(result)['current_profit_before_tax'] == '177000'
    assert not (body['outcome'] == 'answered' and body['answer']['completeness'] == 'complete')
    assert any(a['event'] == 'composition_failed' for a in result.trace['audit'])


async def test_version_and_request_header_identify_same_process_snapshot(offline_http, monkeypatch):
    from app.core import build_identity
    response = await offline_http.client.get('/health/version')
    assert response.status_code == 200
    identity = response.json()
    assert response.headers['X-Kriton-Build'] == identity['build_id']
    assert len(identity['source_hash']) == 64
    assert identity['commit']
    # Changing configuration after startup cannot relabel a running worker.
    monkeypatch.setenv('APP_REVISION', 'a-different-build')
    again = await offline_http.client.get('/health/version')
    assert again.json() == identity
    assert identity == build_identity.process_build_identity()


def test_source_fingerprint_detects_dirty_code_without_leaking_environment(tmp_path, monkeypatch):
    from app.core.build_identity import capture_build_identity
    app_root = tmp_path/'app'
    app_root.mkdir()
    module = app_root/'sample.py'
    module.write_text('value = 1\n')
    monkeypatch.setenv('APP_REVISION', 'test-build')
    monkeypatch.setenv('GROQ_API_KEY', 'do-not-expose-this-secret')
    before = capture_build_identity(app_root)
    module.write_text('value = 2\n')
    after = capture_build_identity(app_root)
    assert before['source_hash'] != after['source_hash']
    assert before['build_id'] != after['build_id']
    assert 'do-not-expose-this-secret' not in str(after)

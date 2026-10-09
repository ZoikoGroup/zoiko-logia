import json
from pathlib import Path
import pytest
from app.training.workflow import read_config, run_cycle, cycle_lock
from app.training.data import question_key


def config(tmp_path):
    return dict(tenant_id='t1',user_id='u1',base_model='chosen-model',output_root=str(tmp_path/'runs'),
                steps=2,interval_seconds=86400,rl_count=100,cpu=True,with_rl=False)


def rows():
    return [{'id':str(i),'group':question_key(f'Unique topic {i}'),
             'prompt':[{'role':'user','content':f'Unique topic {i}'}],
             'completion':[{'role':'assistant','content':f'Checked answer {i}'}]} for i in range(100)]


def test_insufficient_feedback_waits_without_training(tmp_path):
    def unexpected(**kwargs):raise AssertionError('Training must not start')
    result=run_cycle(config(tmp_path),collector=lambda:[],trainer=unexpected)
    assert result['status']=='WAITING_FOR_DATA' and not result['production_eligible']
    again=run_cycle(config(tmp_path),collector=lambda:[],trainer=unexpected)
    assert again['status']=='SKIPPED_UNCHANGED'


def test_rejected_candidate_is_not_retrained_on_unchanged_data(tmp_path):
    seen=[]
    def train(**kwargs):seen.append(kwargs['mode'])
    def evaluate(**kwargs):return {'holdout_gate_passed':False,'production_eligible':False}
    result=run_cycle(config(tmp_path),collector=rows,trainer=train,evaluator=evaluate)
    assert result['status']=='REJECTED_SFT' and seen==['sft']
    again=run_cycle(config(tmp_path),collector=rows,trainer=train,evaluator=evaluate)
    assert again['status']=='SKIPPED_UNCHANGED' and seen==['sft']


def test_passed_cycle_still_requires_independent_evaluation(tmp_path):
    seen=[]
    def train(**kwargs):seen.append(kwargs['mode'])
    def evaluate(**kwargs):return {'holdout_gate_passed':True,'production_eligible':False}
    settings=config(tmp_path)|{'with_rl':True}
    result=run_cycle(settings,collector=rows,trainer=train,evaluator=evaluate)
    assert seen==['sft','grpo'] and result['status']=='AWAITING_INDEPENDENT_EVALUATION'
    assert not result['production_eligible']


def test_failure_is_persisted_without_private_error_text(tmp_path):
    def fail(**kwargs):raise RuntimeError('private provider data')
    result=run_cycle(config(tmp_path),collector=rows,trainer=fail)
    assert result['status']=='FAILED' and result['failed_stage']=='sft_training'
    assert 'private provider data' not in json.dumps(result)
    persisted=json.loads((tmp_path/'runs/workflow-state.json').read_text())
    assert persisted['status']=='FAILED'


def test_config_requires_model_and_tenant_and_bounded_schedule(tmp_path):
    path=tmp_path/'config.json'; path.write_text('{}')
    with pytest.raises(ValueError,match='tenant_id'):read_config(path)
    settings=config(tmp_path)|{'interval_seconds':1}
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError,match='interval_seconds'):read_config(path)
    path.write_text(json.dumps(config(tmp_path)))
    assert read_config(path)['base_model']=='chosen-model'


def test_training_cycles_cannot_overlap(tmp_path):
    with cycle_lock(tmp_path):
        with pytest.raises(RuntimeError,match='already running'):
            with cycle_lock(tmp_path):pass


def test_output_root_cannot_mix_tenants(tmp_path):
    run_cycle(config(tmp_path),collector=lambda:[])
    with pytest.raises(ValueError,match='different training identity'):
        run_cycle(config(tmp_path)|{'tenant_id':'t2'},collector=lambda:[])


def test_interrupted_run_is_recorded_without_automatic_retraining(tmp_path):
    def fail(**kwargs):raise RuntimeError('failed')
    result=run_cycle(config(tmp_path),collector=rows,trainer=fail)
    result['status']='RUNNING'
    path=tmp_path/'runs/workflow-state.json';path.write_text(json.dumps(result))
    again=run_cycle(config(tmp_path),collector=rows,trainer=fail)
    assert again['status']=='SKIPPED_UNCHANGED' and again['previous_status']=='INTERRUPTED'


def test_repeated_identical_feedback_does_not_trigger_training(tmp_path):
    def train(**kwargs):pass
    def evaluate(**kwargs):return {'holdout_gate_passed':False}
    run_cycle(config(tmp_path),collector=rows,trainer=train,evaluator=evaluate)
    again=run_cycle(config(tmp_path),collector=lambda:rows()+rows(),trainer=train,evaluator=evaluate)
    assert again['status']=='SKIPPED_UNCHANGED'


def test_operator_can_retry_fixed_environment_without_bypassing_quality_gate(tmp_path):
    seen=[]
    def fail(**kwargs):raise RuntimeError('missing dependencies')
    run_cycle(config(tmp_path),collector=rows,trainer=fail)
    def train(**kwargs):seen.append(kwargs['mode'])
    def evaluate(**kwargs):return {'holdout_gate_passed':False}
    result=run_cycle(config(tmp_path),collector=rows,trainer=train,evaluator=evaluate,retry_failed=True)
    assert result['status']=='REJECTED_SFT' and seen==['sft']
    again=run_cycle(config(tmp_path),collector=rows,trainer=train,evaluator=evaluate,retry_failed=True)
    assert again['status']=='SKIPPED_UNCHANGED' and seen==['sft']

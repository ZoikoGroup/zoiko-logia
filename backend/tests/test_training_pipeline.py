from types import SimpleNamespace
import pytest
from app.training.data import example_from_record, load_bundle, question_key, split_examples, write_bundle
from app.training.evaluation import compare_scores, score_outputs
from app.training.rewards import arithmetic_tasks, exact_result_reward
from app.training.trainer import artifact_hash, run_training


def record(**changes):
    return SimpleNamespace(**(dict(query_id='q1', question='Explain the UK VAT registration threshold.',
        answer_text='Register above £90,000 [REF-7].', external_evidence=[{
        'url':'https://www.gov.uk/vat-registration', 'content':'Register above £90,000.', 'ref_id':'REF-7'}]) | changes))


def test_training_preserves_actual_source_binding():
    row = example_from_record(record())
    assert '[REF-7]' in row['prompt'][1]['content'] and '[REF-1]' not in row['prompt'][1]['content']


@pytest.mark.parametrize('changes', [
    {'external_evidence': []}, {'external_evidence': [{'url':'https://example.com','content':'An AI answer'}]},
    {'answer_text':'Register above £90,000 [REF-8].'}, {'answer_text':'Register above £90,000.'},
    {'answer_text':'The sources provided do not establish an answer to this.'},
    {'question':'Explain VAT registration for bob@example.com in the United Kingdom.'}])
def test_unusable_feedback_is_not_training_data(changes):
    assert example_from_record(record(**changes)) is None


def example(i, question=None, answer='An answer'):
    question = question or f'Question for subject {i}'
    return {'id':str(i), 'group':question_key(question), 'prompt':[{'role':'user','content':question}],
            'completion':[{'role':'assistant','content':answer}]}


def test_similar_questions_are_kept_in_one_partition():
    train, holdout = split_examples([example(1,'Explain UK VAT registration threshold'),
        example(2,'Explain the UK VAT registration threshold'), example(3,'Describe accounting depreciation methods')])
    for part in (train, holdout):
        ids = {r['id'] for r in part}
        assert ('1' in ids) == ('2' in ids)


def test_conflicting_targets_are_excluded():
    assert split_examples([example(1,'Identical question','A'), example(2,'Identical question','B')]) == ([], [])


def test_dataset_integrity_and_immutable_output(tmp_path):
    path=tmp_path/'data'
    write_bundle(path,tenant_id='t1',kind='sft',train=[example(1)],holdout=[example(2)])
    assert load_bundle(path,kind='sft')[0]['tenant_id']=='t1'
    with pytest.raises(ValueError,match='already exists'):
        write_bundle(path,tenant_id='t1',kind='sft',train=[],holdout=[])
    with pytest.raises(ValueError,match='kind/version'): load_bundle(path,kind='grpo')
    (path/'train.jsonl').write_text('{}\n')
    with pytest.raises(ValueError,match='changed'): load_bundle(path,kind='sft')


def test_contamination_is_rejected(tmp_path):
    write_bundle(tmp_path/'data',tenant_id='t1',kind='sft',train=[example(1)],holdout=[example(1)])
    with pytest.raises(ValueError,match='contamination'): load_bundle(tmp_path/'data',kind='sft')


@pytest.mark.parametrize('answer,reward', [('{"answer":20}',1),('{"answer":"20.00"}',1),
    ('{"answer":21}',0),('20',0),('{"answer":true}',0),('{"answer":20,"explanation":"wrong"}',0),
    ('{"answer":20,"answer":21}',0),('{"answer":NaN}',0),('{"answer":"Infinity"}',0),
    ('{"answer":20} trailing text',0)])
def test_reward_requires_exact_answer(answer,reward):
    assert exact_result_reward([answer],['20'])==[reward]


def test_chat_rewards_and_misaligned_labels():
    assert exact_result_reward([[{'role':'assistant','content':'{"answer":20}'}]],['20'])==[1]
    with pytest.raises(ValueError): exact_result_reward(['{"answer":20}'],[])


def test_rl_tasks_reproducible_and_independently_computed():
    from app.orchestration.calculation_service import evaluate_expression
    tasks=arithmetic_tasks(count=50,seed=7)
    assert tasks==arithmetic_tasks(count=50,seed=7)
    assert len({r['expression'] for r in tasks})==50
    assert all(str(evaluate_expression(r['expression']))==r['expected'] for r in tasks)


def test_insufficient_data_cannot_start_training(tmp_path):
    write_bundle(tmp_path/'data',tenant_id='t1',kind='sft',train=[example(1)],holdout=[example(2)])
    with pytest.raises(ValueError,match='Insufficient'):
        run_training(dataset=tmp_path/'data',output=tmp_path/'candidate',base_model='unused',mode='sft')
    assert not (tmp_path/'candidate').exists()


def test_weights_bound_to_evaluation(tmp_path):
    (tmp_path/'model.safetensors').write_bytes(b'first'); original=artifact_hash(tmp_path)
    (tmp_path/'model.safetensors').write_bytes(b'changed')
    assert artifact_hash(tmp_path)!=original


def test_holdout_gate_never_authorizes_production():
    result=compare_scores({'count':10,'accuracy':.7},{'count':10,'accuracy':.9})
    assert result['holdout_gate_passed'] and not result['production_eligible']
    assert not compare_scores({'count':10,'accuracy':.9},{'count':10,'accuracy':.8})['holdout_gate_passed']
    assert not compare_scores({'count':10,'accuracy':1},{'count':10,'accuracy':1})['holdout_gate_passed']
    with pytest.raises(ValueError): compare_scores({'count':1,'accuracy':0},{'count':1,'accuracy':1})
    assert score_outputs([{'expected':'20'}],['{"answer":20}'],kind='grpo')['accuracy']==1


async def test_feedback_export_requires_tenant_scoped_verified_records():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.domains.audit_ledger.models import AuditEvent
    from app.orchestration.models import AnswerFeedback, QueryAnswerRecord
    from app.training.data import collect_examples
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        for query_id, tenant, verified, rating in [('good','t1',True,'up'), ('bad','t1',False,'up'),
                                                  ('negative','t1',True,'down'), ('other','t2',True,'up')]:
            sample=record()
            db.add(QueryAnswerRecord(query_id=query_id,tenant_id=tenant,user_id='u1',
                question=sample.question,answer_text=sample.answer_text,external_evidence=sample.external_evidence))
            db.add(AnswerFeedback(tenant_id=tenant,user_id='u1',query_id=query_id,rating=rating))
            for name in ('validation_completed','release_check_completed'):
                db.add(AuditEvent(event_name=name,emitting_service='orchestration',tenant_id=tenant,
                    subject_type='query',subject_id=query_id,payload={'passed':verified,'requires_authority':True},
                    payload_hash='h',chain_hash='h'))
        await db.commit()
        rows=await collect_examples(db,tenant_id='t1')
        assert [row['id'] for row in rows]==['good']
        from app.domains.evaluation.models import BenchmarkCase, EvaluationDataset
        db.add(EvaluationDataset(id='independent-evaluation',version='1',domain='tax'))
        await db.flush()
        db.add(BenchmarkCase(id='reserved-case',dataset_id='independent-evaluation',
            query_text=record().question,gold_answer=record().answer_text,risk_scope='LOW',tenant_id=None))
        await db.commit()
        assert await collect_examples(db,tenant_id='t1') == []  # reserve independent DB benchmarks too
    await engine.dispose()


def test_model_configuration_changes_invalidate_artifact(tmp_path):
    (tmp_path/'model.safetensors').write_bytes(b'weights')
    (tmp_path/'generation_config.json').write_text('{"temperature":1}')
    before=artifact_hash(tmp_path)
    (tmp_path/'generation_config.json').write_text('{"temperature":2}')
    assert artifact_hash(tmp_path)!=before


@pytest.mark.parametrize('capacity,mode,expected', [(1024,'sft',(1024,0)), (1024,'grpo',(1024,96)),
                                                   (64,'grpo',(64,16))])
def test_context_budget_reserves_generation_space(capacity, mode, expected):
    from app.training.data import context_budget
    assert context_budget(SimpleNamespace(max_position_embeddings=capacity),
                          SimpleNamespace(model_max_length=10**30), mode=mode) == expected


def test_tokenizer_context_limit_is_respected():
    from app.training.data import context_budget
    assert context_budget(SimpleNamespace(max_position_embeddings=4096),
                          SimpleNamespace(model_max_length=512), mode='sft') == (512,0)


def test_duplicate_prompts_cannot_satisfy_training_minimum():
    from app.training.data import validate_distinct_examples
    with pytest.raises(ValueError, match='distinct'):
        validate_distinct_examples([example(i,'Same question') for i in range(50)],
                                   [example(i+50,'Different question') for i in range(10)])


def test_different_group_names_do_not_hide_prompt_leakage(tmp_path):
    train, holdout=example(1,'Identical question'), example(2,'Identical question')
    holdout['group']='a different group'
    write_bundle(tmp_path/'data',tenant_id='t1',kind='sft',train=[train],holdout=[holdout])
    with pytest.raises(ValueError,match='prompt contamination'):
        load_bundle(tmp_path/'data',kind='sft')


def test_malformed_chat_completion_gets_no_reward():
    assert exact_result_reward([['not a message']],['20']) == [0]


@pytest.mark.parametrize('accuracy',[float('inf'),float('nan'),-1,1.1])
def test_invalid_scores_cannot_pass_evaluation(accuracy):
    with pytest.raises(ValueError, match='finite'):
        compare_scores({'count':10,'accuracy':.5},{'count':10,'accuracy':accuracy})


def test_external_snapshot_does_not_bind_to_governed_ref_at_same_url():
    from app.orchestration.review import external_evidence_snapshot
    from app.orchestration.websearch import WebSource
    url='https://www.gov.uk/vat-registration'
    web=WebSource(title='Official guidance',url=url,snippet='Register above £90,000.',provider='official')
    citations=[SimpleNamespace(url=url,source_id=url,ref_id='REF-1',provider='official',evidence_preview=web.snippet),
               SimpleNamespace(url=url,source_id='passage-1',ref_id='REF-9',provider='Governed source register',
                               evidence_preview='A different registered passage')]
    [snapshot]=external_evidence_snapshot([web],citations=citations)
    assert snapshot['ref_id']=='REF-1' and snapshot['content']==web.snippet


def test_same_url_can_preserve_two_distinct_external_snippets():
    from app.orchestration.review import external_evidence_snapshot
    from app.orchestration.websearch import WebSource
    url='https://www.gov.uk/vat-registration'
    sources=[WebSource(title='Official',url=url,snippet=text,provider='official')
             for text in ('Retrospective rule.', 'Prospective rule.')]
    citations=[SimpleNamespace(url=url,source_id=url,ref_id=f'REF-{i+1}',provider='official',evidence_preview=s.snippet)
               for i,s in enumerate(sources)]
    snapshots=external_evidence_snapshot(sources,citations=citations)
    assert [(s['ref_id'],s['content']) for s in snapshots] == [('REF-1','Retrospective rule.'),('REF-2','Prospective rule.')]


def test_continuation_is_compared_with_unchanged_parent(tmp_path):
    from app.training.evaluation import comparison_baseline
    parent=tmp_path/'parent'; parent.mkdir()
    (parent/'adapter_model.safetensors').write_bytes(b'parent weights')
    metadata={'base_model':'original-model','parent_adapter':str(parent),'parent_artifact_hash':artifact_hash(parent)}
    assert comparison_baseline(metadata) == str(parent)
    (parent/'adapter_model.safetensors').write_bytes(b'changed parent')
    with pytest.raises(ValueError, match='Parent adapter changed'):
        comparison_baseline(metadata)
    assert comparison_baseline({'base_model':'original-model'})=='original-model'


def test_legacy_candidate_metadata_fails_with_clear_error(tmp_path):
    from app.training.evaluation import evaluate_candidate
    (tmp_path/'candidate.json').write_text('{"version":1}')
    with pytest.raises(ValueError, match='Legacy or incomplete'):
        evaluate_candidate(dataset=tmp_path/'unused',candidate=tmp_path,output=tmp_path/'report.json')


@pytest.mark.parametrize('evidence', [['invalid snapshot'], [{'ref_id':7,'url':'https://example.com','content':'text'}],
    [{'ref_id':'REF-7','url':'https://example.com','content':'Rule A'},
     {'ref_id':'REF-7','url':'https://example.com','content':'Conflicting rule B'}]])
def test_malformed_or_ambiguous_source_bindings_are_excluded(evidence):
    assert example_from_record(record(external_evidence=evidence)) is None

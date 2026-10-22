"""Durable input recovery, using a private temporary SQLite database."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.domains.orchestration_state.models import ConversationTurn
from app.orchestration import conversation_memory as memory
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.calculations.statements import statement_followup
from app.orchestration.schemas import ConversationMessage as M
from tests.test_agent_request_size import QUESTION
from tests.test_answer_status_pipeline import pipeline  # noqa: F401

FIRST = 'Increase current-year gross sales by 8%. Keep sales returns at £35,000 and cost of goods sold at £710,000.'
SECOND = 'Now increase cost of goods sold by 5% as well. Apply that increase to the original £710,000. Keep the revised sales figure.'


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "memory.db"}')
    async with engine.begin() as conn:
        await conn.run_sync(ConversationTurn.__table__.create)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def save(db, query, query_id, *, user='u', tenant='t', conversation='c'):
    await memory.save_turn(db, tenant_id=tenant, user_id=user, conversation_id=conversation,
                           query_id=query_id, user_text=query)


async def load(db, *, user='u', tenant='t', conversation='c'):
    return await memory.load_turns(db, tenant_id=tenant, user_id=user, conversation_id=conversation)


async def snapshot(db, query, query_id, result, history=()):
    await memory.save_snapshot(db, tenant_id='t', user_id='u', conversation_id='c', query_id=query_id,
                               snapshot=memory.snapshot_for(query, history, result, query_id))


async def test_user_inputs_survive_without_any_assistant_answer(db):
    await save(db, QUESTION, 'q1')
    await snapshot(db, QUESTION, 'q1', calculate_from_query(QUESTION))
    history = memory.merge_history([], await load(db))
    first = statement_followup(FIRST, history)
    assert first is not None
    assert next(o.value for o in first.outputs if o.name == 'revised_profit_before_tax') == 277000
    await save(db, FIRST, 'q2')
    await snapshot(db, FIRST, 'q2', first, history)
    # A later HTTP request sends no old browser messages or assistant answer.
    history = memory.merge_history([], await load(db))
    second = statement_followup(SECOND, history)
    assert next(o.value for o in second.outputs if o.name == 'revised_profit_before_tax') == 241500
    assert all(m.role == 'user' for m in history)


async def test_memory_is_isolated_by_tenant_user_and_conversation(db):
    await save(db, QUESTION, 'q1')
    assert len(await load(db)) == 1
    assert not await load(db, tenant='other')
    assert not await load(db, user='other')
    assert not await load(db, conversation='other')
    await memory.save_snapshot(db, tenant_id='other', user_id='u', conversation_id='c', query_id='q1',
                               snapshot={'facts': ['forged']})
    assert (await load(db))[0].snapshot != {'facts': ['forged']}


async def test_expired_inputs_are_not_loaded(db):
    await save(db, QUESTION, 'q1')
    await db.execute(update(ConversationTurn).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db.commit()
    assert not await load(db)


async def test_retention_job_physically_removes_expired_memory(db):
    from app.domains.kriton_workspace.models import Document, GeneratedArtifact
    from app.domains.kriton_workspace.retention import cleanup_expired_workspace
    async with db.bind.begin() as conn:
        await conn.run_sync(Document.__table__.create)
        await conn.run_sync(GeneratedArtifact.__table__.create)
    await save(db, QUESTION, 'q1')
    await db.execute(update(ConversationTurn).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db.commit()
    counts = await cleanup_expired_workspace(db)
    assert counts['conversation_turns'] == 1
    assert not (await db.execute(select(ConversationTurn))).scalars().all()


async def test_query_replay_does_not_duplicate_the_turn(db):
    await save(db, QUESTION, 'q1')
    await save(db, QUESTION, 'q1')
    assert len(await load(db)) == 1


async def test_last_structured_state_survives_turn_compaction(db):
    await save(db, QUESTION, 'q1')
    await snapshot(db, QUESTION, 'q1', calculate_from_query(QUESTION))
    for i in range(70):
        await save(db, f'Explain item {i}.', f'later-{i}')
    turns = await load(db)
    assert len(turns) <= memory.MAX_TURNS
    assert memory.active_calculation(turns) is not None
    assert statement_followup(FIRST, memory.merge_history([], turns)) is not None


async def test_snapshots_preserve_decimal_values_and_typed_scope(db):
    await save(db, QUESTION, 'q1')
    await snapshot(db, QUESTION, 'q1', calculate_from_query(QUESTION))
    facts = (await load(db))[0].snapshot['facts']
    profit = next(f for f in facts if f['name'] == 'current_operating_profit')
    assert profit['value'] == '191000'
    assert profit['metric'] == 'operating_profit' and profit['period'] == 'current'
    assert profit['currency'] == 'GBP' and profit['source'] == 'calculation'


def test_a_new_financial_problem_does_not_pin_an_old_statement_baseline():
    old = memory.snapshot_for(QUESTION, [], calculate_from_query(QUESTION), 'old')
    turns = [N(user_text=QUESTION, snapshot=old),
             N(user_text='Revenue £900,000, costs £540,000. Calculate gross profit.',
               snapshot={'reset_statement_context': True})]
    history = memory.merge_history([], turns)
    assert history[-1].content.startswith('Revenue £900,000')
    # No duplicated older baseline is injected ahead of the actual turns.
    assert sum(m.content == QUESTION for m in history) == 1


def test_baseline_and_revision_survive_a_longer_conversation():
    result = statement_followup(FIRST, [M(role='user', content=QUESTION)])
    state = memory.snapshot_for(FIRST, [M(role='user', content=QUESTION)], result, 'q2')
    turns = [N(user_text='Question about the accounts.', snapshot=state)]
    turns += [N(user_text=f'Explain item {i}.', snapshot={}) for i in range(40)]
    history = memory.merge_history([], turns)
    assert len(history) <= 12
    assert QUESTION in [m.content for m in history]
    assert statement_followup(SECOND, history) is not None


def test_browser_history_cannot_silently_replace_the_server_statement():
    state = memory.snapshot_for(QUESTION, [], calculate_from_query(QUESTION), 'q1')
    changed = QUESTION.replace('£1,250,000', '£9,250,000')
    history = memory.merge_history([M(role='user', content=changed)], [N(user_text=QUESTION, snapshot=state)])
    assert changed not in [m.content for m in history]
    result = statement_followup(FIRST, history)
    assert next(o.value for o in result.outputs if o.name == 'revised_net_sales') == 1315000


def test_verified_results_are_available_for_a_narrative_followup():
    state = memory.snapshot_for(QUESTION, [], calculate_from_query(QUESTION), 'q1')
    result = memory.active_calculation([N(snapshot=state)])
    context = memory.calculation_context(result)
    assert 'current_operating_profit: 191000 GBP' in context
    assert 'New instructions and changed inputs require recalculation' in context


async def test_missing_schema_does_not_corrupt_the_callers_session(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "unprepared.db"}')
    async with async_sessionmaker(engine)() as session:
        assert not await load(session)
        assert session.is_active
    await engine.dispose()


async def test_http_flow_recovers_both_scenarios_after_an_initial_provider_failure(db, pipeline, monkeypatch):
    from app.domains.model_gateway.errors import ProviderRateLimited
    from app.orchestration import service
    from unittest.mock import AsyncMock
    monkeypatch.setattr(service, 'resolve_conversation_document_ids', AsyncMock(return_value=[]))
    original_load, original_save, original_snapshot = memory.load_turns, memory.save_turn, memory.save_snapshot

    async def load_with_real_db(_db, **kwargs):
        return await original_load(db, **kwargs)

    async def save_with_real_db(_db, **kwargs):
        return await original_save(db, **kwargs)

    async def snapshot_with_real_db(_db, **kwargs):
        return await original_snapshot(db, **kwargs)

    monkeypatch.setattr(memory, 'load_turns', load_with_real_db)
    monkeypatch.setattr(memory, 'save_turn', save_with_real_db)
    monkeypatch.setattr(memory, 'save_snapshot', snapshot_with_real_db)
    pipeline.agent.side_effect = ProviderRateLimited()
    first, _ = await pipeline.ask(QUESTION, conversation_id='c')
    assert first.answer and first.answer.completeness == 'partial'
    second, _ = await pipeline.ask(FIRST, conversation_id='c')
    assert second.calculation is not None
    assert '277,000' in second.answer.text
    third, _ = await pipeline.ask(SECOND, conversation_id='c')
    assert '241,500' in third.answer.text
    pipeline.agent.assert_awaited_once()

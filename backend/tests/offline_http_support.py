"""Isolated HTTP investigation fixture, using the production router and audit.

External identity verification and provider transports are synthetic boundaries.
RBAC, task selection, calculation, retrieval/eligibility, response assembly,
idempotency and audit persistence execute their normal application code.
"""
import json
import copy
import os
import socket
import time
from pathlib import Path
from types import SimpleNamespace as N

import httpx
import pytest
from sqlalchemy import create_engine, select, or_
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker


@pytest.fixture
async def offline_http(tmp_path, monkeypatch):
    from app import main
    from app.core import database
    from app.db.base import Base
    from app.domains.identity.models import Tenant, User
    from app.domains.identity import rbac
    from app.domains.audit_ledger.models import AuditEvent
    from app.orchestration import router, service
    from app.domains.risk_safety import risk_classifier
    from app.domains.model_gateway import auxiliary
    from app.domains.model_gateway.providers import groq_adapter
    from app.domains.model_gateway.errors import ProviderResponseIncomplete
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'KRITON_AGENT_MODE', True)

    # No outbound DNS, HTTP, provider or shared-database transport is permitted.
    def denied(*args, **kwargs):
        raise AssertionError('External transport forbidden in isolated HTTP investigation')
    monkeypatch.setattr(socket, 'getaddrinfo', denied)
    original_send = httpx.AsyncClient.send

    async def local_send(client, *args, **kwargs):
        if not isinstance(client._transport, httpx.ASGITransport):
            denied()
        return await original_send(client, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, 'send', local_send)
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(risk_classifier, '_get_classifier_pipeline', lambda: None)

    path = tmp_path / 'isolated-http.sqlite'
    engine = create_async_engine(f'sqlite+aiosqlite:///{path}')
    sync_engine = create_engine(f'sqlite:///{path}')
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    sync_sessions = sessionmaker(sync_engine)
    monkeypatch.setattr(database, 'AsyncSessionLocal', sessions)
    monkeypatch.setattr(database, 'SessionLocal', sync_sessions)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([Tenant(id='synthetic-a', name='Synthetic A'), Tenant(id='synthetic-b', name='Synthetic B')])
        await db.flush()
        db.add_all([User(id='actor-a', tenant_id='synthetic-a', email='a@example.test', full_name='Synthetic A', role='Admin'),
                    User(id='actor-b', tenant_id='synthetic-b', email='b@example.test', full_name='Synthetic B', role='Admin')])
        await db.commit()

    def identity(token):
        if token in {'offline-actor-a', 'offline-actor-b'}:
            return N(sub=token.removeprefix('offline-'), aal='aal1')
        return None
    monkeypatch.setattr(rbac, 'verify_token', identity)
    monkeypatch.setattr(router, 'verify_token', identity)
    # Keep the application limiter but isolate its buckets from every other test.
    from limits.storage import MemoryStorage
    from limits.strategies import FixedWindowRateLimiter
    storage = MemoryStorage()
    monkeypatch.setattr(router.limiter, '_storage', storage)
    monkeypatch.setattr(router.limiter, '_limiter', FixedWindowRateLimiter(storage))
    app = main.create_app()  # ASGITransport does not run production lifespan/DDL.

    async def db_dependency():
        async with sessions() as db:
            yield db

    def sync_dependency():
        with sync_sessions() as db:
            yield db

    app.dependency_overrides[database.get_db] = db_dependency
    app.dependency_overrides[database.get_sync_db] = sync_dependency

    calls, traces, exchanges = [], [], []
    state = N(responses=[], failure=ProviderResponseIncomplete(), memory_reads=[])
    from app.orchestration import conversation_memory
    original_load = conversation_memory.load_turns

    async def load_turns(*args, **kwargs):
        turns = await original_load(*args, **kwargs)
        state.memory_reads.append({'tenant_id': kwargs['tenant_id'], 'user_id': kwargs['user_id'],
                                   'conversation_id': kwargs['conversation_id'],
                                   'turns': [{'query_id': t.query_id, 'user_text': t.user_text, 'snapshot': t.snapshot}
                                             for t in turns]})
        return turns
    monkeypatch.setattr(conversation_memory, 'load_turns', load_turns)

    async def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        exchange = {'request': copy.deepcopy(kwargs), 'synthetic': True}
        exchanges.append(exchange)
        if kwargs.get('messages', [{}])[0].get('content', '').startswith('You classify the RISK LEVEL'):
            from tests.test_agent_loop import _reply
            response = _reply('LOW')
        elif state.responses:
            response = state.responses.pop(0)
        else:
            exchange['error'] = {'type': type(state.failure).__name__, 'code': getattr(state.failure, 'code', None),
                                 'http_status': getattr(state.failure, 'status_code', None)}
            raise state.failure
        exchange['response'] = {
            'choices': [{'finish_reason': getattr(choice, 'finish_reason', None),
                         'message': {'content': choice.message.content,
                                     'tool_calls': [{'id': call.id, 'name': call.function.name, 'arguments': call.function.arguments}
                                                    for call in choice.message.tool_calls or []]}}
                        for choice in response.choices],
            'usage': vars(response.usage),
        }
        return response

    fake_client = N(chat=N(completions=N(create=create)))
    monkeypatch.setenv('GROQ_API_KEY', 'offline-synthetic-key')
    monkeypatch.setenv('KRITON_AGENT_MODE', 'true')
    monkeypatch.setattr(groq_adapter, 'AsyncGroq', lambda **kwargs: fake_client)
    monkeypatch.setattr(auxiliary, 'AsyncGroq', lambda **kwargs: fake_client)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated.test') as client:
        async def ask(question, *, case_id, conversation='fresh', history=None, actor='actor-a', key=None,
                      allow_http_error=False):
            started, call_start, memory_start, exchange_start = time.perf_counter(), len(calls), len(state.memory_reads), len(exchanges)
            body = {'query': question, 'conversation_id': conversation, 'conversation_history': history or []}
            response = await client.post('/api/v1/orchestration/ask', json=body, headers={
                'Authorization': f'Bearer offline-{actor}', 'Idempotency-Key': key or f'offline-{case_id}-{len(traces)}',
            })
            payload = response.json()
            async with sessions() as db:
                rows = (await db.execute(select(AuditEvent).where(or_(
                    AuditEvent.correlation_id == payload.get('correlation_id', 'absent'),
                    AuditEvent.subject_id == payload.get('query_id', 'absent'),
                )).order_by(AuditEvent.ingested_at))).scalars().all()
            trace = {'case_id': case_id, 'request': body, 'actor': actor, 'http_status': response.status_code,
                     'build_id': response.headers.get('X-Kriton-Build'),
                     'latency_ms': round((time.perf_counter()-started)*1000, 2), 'response': payload,
                     'provider_boundary': 'scripted only; no external transports',
                     'model_requests': calls[call_start:],
                     'model_exchanges': exchanges[exchange_start:],
                     'history_selection': state.memory_reads[memory_start:],
                     'calculation': payload.get('calculation'),
                     'task_context': payload.get('context_decision'),
                     'audit': [{'id': row.id, 'event': row.event_name, 'correlation_id': row.correlation_id,
                                'tenant_id': row.tenant_id, 'payload': row.payload,
                                'payload_hash': row.payload_hash, 'chain_hash': row.chain_hash,
                                'previous_chain_hash': row.previous_chain_hash} for row in rows]}
            traces.append(trace)
            if folder := os.getenv('KRITON_TRACE_DIR'):
                directory = Path(folder)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f'{case_id}.json').write_text(json.dumps(trace, indent=2, default=str))
            if not allow_http_error:
                assert response.status_code == 200, payload
            if response.status_code == 200:
                assert any(row.event_name == 'answer_receipt' for row in rows), 'Response left without durable receipt'
            from app.domains.audit_ledger.chain_integrity import compute_payload_hash, compute_chain_hash
            for row in rows:
                assert row.payload_hash == compute_payload_hash(row.payload)
                assert row.chain_hash == compute_chain_hash(row.id, row.event_name, row.payload_hash, row.previous_chain_hash)
            assert all(row.tenant_id == ('synthetic-a' if actor == 'actor-a' else 'synthetic-b') for row in rows)
            return N(body=payload, trace=trace)

        yield N(ask=ask, traces=traces, state=state, calls=calls, sessions=sessions, app=app, client=client,
                rate_storage=storage)
    await engine.dispose()
    sync_engine.dispose()

"""Opt-in real socket, real signed JWT, real PostgreSQL/RLS integration."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.skipif(os.getenv('RUN_SOCKET_HTTP_TESTS') != '1', reason='Requires explicitly provisioned isolated PostgreSQL')

@pytest.fixture(scope='module')
def server(tmp_path_factory):
    folder = tmp_path_factory.mktemp('socket-http')
    admin_url = os.environ['SOCKET_TEST_ADMIN_URL']
    app_url = os.environ['SOCKET_TEST_APP_URL']
    assert '/kriton_http?' in admin_url and 'host=/private/tmp/kriton-visual-' in admin_url
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public['kid'] = 'isolated-test-key'
    class JWKS(BaseHTTPRequestHandler):
        def do_GET(self):
            body=json.dumps({'keys':[public]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    jwks = ThreadingHTTPServer(('127.0.0.1',0), JWKS)
    threading.Thread(target=jwks.serve_forever,daemon=True).start()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    env={**os.environ, 'DATABASE_URL':admin_url, 'APP_DATABASE_URL':app_url,
         'SUPABASE_URL':f'http://127.0.0.1:{jwks.server_port}', 'SOCKET_TEST_PORT':str(port),
         'EMBEDDING_PROVIDER':'none','CLAIM_VERIFICATION':'off','HEALTH_SAMPLER_ENABLED':'false',
         'NO_PROXY':'127.0.0.1,localhost','PYTHONPATH':str(Path(__file__).resolve().parents[1])}
    for name in ('GROQ_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','TAVILY_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY'):
        env[name]=''
    setup='''
import asyncio
from sqlalchemy import text
from app import main
from app.core.database import async_engine, AsyncSessionLocal
from app.db.base import Base
from app.domains.identity.models import Tenant, User
async def setup():
    async with async_engine.begin() as c:
        await c.execute(text('DROP SCHEMA public CASCADE'))
        await c.execute(text('CREATE SCHEMA public'))
        await c.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        for suffix in ['a','b']:
            db.add(Tenant(id='socket-tenant-'+suffix,name='Socket '+suffix))
        await db.flush()
        for suffix in ['a','b']:
            db.add(User(id='socket-'+suffix,tenant_id='socket-tenant-'+suffix,email=suffix+'@example.test',full_name='Socket '+suffix,role='Admin'))
        await db.commit()
    await main._setup_user_rls()
    await main._setup_source_rls()
    await async_engine.dispose()
asyncio.run(setup())
'''
    result=subprocess.run([sys.executable,'-c',setup],env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    log=open(folder/'worker.log','w')
    process=subprocess.Popen([sys.executable,'-m','tests.socket_http_worker'],env=env,stdout=log,stderr=log)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError((folder/'worker.log').read_text())
            try:
                if httpx.get(base+'/__isolated_ready',timeout=.5).status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(.1)
        else: raise AssertionError('Isolated HTTP worker did not start')
        def token(actor):
            return jwt.encode({'sub':'socket-'+actor,'aud':'authenticated','iat':int(time.time()),'exp':int(time.time())+600,
                'app_metadata':{'tenant_id':'socket-tenant-'+actor,'role':'Admin'}},key,algorithm='RS256',headers={'kid':'isolated-test-key'})
        version = httpx.get(base+'/health/version',timeout=5)
        assert version.status_code == 200
        identity = version.json()
        assert version.headers['X-Kriton-Build'] == identity['build_id']
        traces=[]
        def ask(query, actor='a', conversation='socket-task'):
            index=len(traces)
            payload={'query':query,'conversation_id':conversation,'turn_id':f'turn-{index}','request_id':f'request-{index}'}
            started=time.perf_counter()
            response=httpx.post(base+'/api/v1/orchestration/ask',json=payload,headers={'Authorization':'Bearer '+token(actor),'Idempotency-Key':f'request-{index}'},timeout=30)
            assert response.headers['X-Kriton-Build'] == identity['build_id']
            traces.append({'request':payload,'http_status':response.status_code,'response':response.json(),'actor':actor,
                           'build_identity':identity,'latency_ms':round((time.perf_counter()-started)*1000,2)})
            assert response.status_code == 200,response.text
            return response.json()
        yield ask,base,traces,app_url
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill();process.wait()
        log.close();jwks.shutdown();jwks.server_close()
        if destination:=os.getenv('SOCKET_TEST_TRACE_DIR'):
            dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
            (dest/'http-socket-traces.json').write_text(json.dumps(traces,indent=2))
            (dest/'http-worker.log').write_text((folder/'worker.log').read_text())


def test_real_http_auth_and_chart_followup(server):
    ask,base,_,_=server
    assert httpx.post(base+'/api/v1/orchestration/ask',json={'query':'Calculate profit.'},headers={'Authorization':'Bearer invalid'},timeout=5).status_code==401
    first=ask('Show monthly revenue as a line chart: January 2025 £100, February 2025 £120, March 2025 £90.')
    assert first['visualization']['type']=='LINE'
    second=ask('Make it a bar chart.')
    assert second['visualization']['type']=='BAR'
    assert second['visualization']['data']==first['visualization']['data']
    assert second['request_integrity']['turn_id']=='turn-1'
    other=ask('Make it a bar chart.',actor='b')
    assert other['visualization'] is None
    assert '2025-01' not in str(other)


def test_original_oct21_supplied_scenarios_over_authenticated_socket(server):
    ask,_,_,_=server
    q=json.loads((Path(__file__).parent/'fixtures/manual_transcript_20261021.json').read_text())['queries']
    values=lambda response:{v['name']:v['value'] for v in response['calculation']['outputs']}
    gst=ask(q['gst'],conversation='original-gst')
    assert values(gst)['vat_payable']=='84600'
    assert values(gst)['input_ledger_difference']=='0'
    changed=ask(q['gst_followup'],conversation='original-gst')
    assert values(changed)['vat_payable']=='86400'
    assert values(changed)['input_ledger_difference']=='-1800'
    accrual=ask(q['accrual'],conversation='original-accrual')
    assert values(accrual)['expense_debit']=='4800'
    assert accrual['answer']['completeness']=='complete'
    income=ask(q['income'],conversation='original-income')
    assert values(income)['profit_before_tax']=='101000'
    revised=ask(q['depreciation_followup'],conversation='original-income')
    assert values(revised)['profit_before_tax']=='97000'
    chart=ask(q['monthly'],conversation='original-monthly')
    bars=ask(q['bars'],conversation='original-monthly')
    assert chart['visualization']['type']=='LINE'
    assert bars['visualization']['type']=='BAR'
    assert chart['visualization']['data']==bars['visualization']['data']


def test_systemic_scenarios_and_revisions_over_authenticated_socket(server):
    ask,_,_,_=server
    q=json.loads((Path(__file__).parent/'fixtures/systemic_scenarios_20261021.json').read_text())['queries']
    values=lambda r:{i['name']:i['value'] for i in r['calculation']['outputs']}
    for key in ['vat','refund','bank','cheques','cvp','variable_cost','quarterly','table_only','loan','inventory','invoices']:
        result=ask(q[key],conversation='systemic-mixed')
        assert result['outcome']=='answered',result
        assert result['answer']['completeness']=='complete',result
        if key=='refund': assert values(result)['amount_excluding_vat']=='55000'
        if key=='cheques': assert values(result)['unreconciled_difference']=='-100'
        if key=='variable_cost': assert values(result)['maximum_profit_at_capacity']=='36000'
        if key=='quarterly':
            assert result['visualization']['type']=='GROUPED_BAR'
            assert '358,000' in result['answer']['text']
        if key=='table_only': assert result['visualization'] is None


def test_real_http_new_task_and_database_rls(server):
    from sqlalchemy import create_engine,text
    ask,_,_,url=server
    first=ask('Revenue £900,000, cost of sales £500,000, operating expenses £150,000. Calculate operating profit.')
    second=ask('Revenue £100, cost of sales £60. Calculate gross profit.')
    assert {o['name']:o['value'] for o in first['calculation']['outputs']}['operating_profit']=='250000'
    assert {o['name']:o['value'] for o in second['calculation']['outputs']}['gross_profit']=='40'
    assert '900,000' not in second['answer']['text']
    engine=create_engine(url.replace('+asyncpg','+psycopg2'))
    with engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id','socket-tenant-b',false),set_config('app.user_id','socket-b',false)"))
        rows=c.execute(text('SELECT DISTINCT tenant_id,user_id FROM conversation_turns')).all()
        assert rows and all(tuple(r)==('socket-tenant-b','socket-b') for r in rows)
        assert not c.execute(text('SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=current_user')).scalar()
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from app.domains.audit_ledger.models import AuditEvent
    from app.domains.audit_ledger.chain_integrity import compute_payload_hash, compute_chain_hash
    with Session(engine) as db:
        db.execute(text("SELECT set_config('app.tenant_id','socket-tenant-a',false),set_config('app.user_id','socket-a',false)"))
        rows=db.scalars(select(AuditEvent).where(AuditEvent.subject_id==second['query_id'])).all()
        assert rows and any(row.event_name=='answer_receipt' for row in rows)
        for row in rows:
            assert row.tenant_id=='socket-tenant-a'
            assert row.payload_hash==compute_payload_hash(row.payload)
            assert row.chain_hash==compute_chain_hash(row.id,row.event_name,row.payload_hash,row.previous_chain_hash)
        receipt=next(row.payload for row in rows if row.event_name=='answer_receipt')
        assert receipt['request_integrity']==second['request_integrity']
    engine.dispose()

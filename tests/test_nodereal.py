import copy
import multiprocessing
import os
import time
from unittest.mock import Mock, patch
import pytest
from ingestion import History, ProviderError
from graph_engine import trace_fund_flow
from nodereal_limit import wait_for_slot

ROOT='0x'+'1'*40
OTHER='0x'+'2'*40
KEY='synthetic-test-key'

def record(**kw):
    return dict({'hash':'tx','from':ROOT,'to':OTHER,'category':'external','value':hex(10**18),
                 'asset':'BNB','blockTimeStamp':100,'receiptsStatus':1},**kw)

@pytest.fixture
def history(monkeypatch):
    monkeypatch.setenv('NODEREAL_API_KEY',KEY)
    monkeypatch.setattr('ingestion.wait_for_slot',lambda key,deadline:None)
    h=History()
    yield h
    h.close()

def test_native_internal_token_exact_amounts(history):
    rows=[record(),record(category='internal',hash='internal'),
          record(category='20',hash='token',contractAddress=OTHER,decimal='18',value=hex(1234567890123456789),asset='USDT'),
          record(category='20',hash='zero-decimals',contractAddress=OTHER,decimal='0',value='0x7'),
          record(receiptsStatus=0),record(value='0x0')]
    with patch.object(history,'request',return_value={'result':{'transfers':rows}}) as request:
        batch=list(history.bnb(ROOT,'outgoing'))[0][0]
    assert [r['value'] for r in batch]==['1','1','1.234567890123456789','7']
    payload=request.call_args.kwargs['json']
    assert payload['method']=='nr_getAssetTransfers'
    assert payload['params'][0]['category']==['external','internal','20']
    assert 'fromBlock' not in payload['params'][0]
    assert request.call_args.args[1]=='https://bsc-mainnet.nodereal.io/v1/'+KEY

def test_pagination_and_incoming(history):
    calls=[]
    def request(method,url,**kwargs):
        calls.append(copy.deepcopy(kwargs['json']))
        return {'result':{'transfers':[record(**{'from':OTHER,'to':ROOT})], 'pageKey':'next'}} if len(calls)==1 else {'result':{'transfers':[]}}
    with patch.object(history,'request',side_effect=request):
        pages=list(history.bnb(ROOT,'incoming'))
    assert pages[-1][1] is True
    assert calls[0]['params'][0]['toAddress']==ROOT
    assert calls[1]['params'][0]['pageKey']=='next'

def test_repeated_cursor_error(history):
    with patch.object(history,'request',return_value={'result':{'transfers':[],'pageKey':'repeat'}}):
        with pytest.raises(ProviderError,match='repeated'):list(history.bnb(ROOT,'outgoing'))

def test_retry_rpc_cups_and_http429(history):
    with patch.object(history,'request',side_effect=[ProviderError('429',retryable=True),{'error':{'code':-32005}}, {'result':{'transfers':[]}}]) as request:
        assert list(history.bnb(ROOT,'outgoing'))==[([],True)]
        assert request.call_count==3

def test_persistent_limit_not_empty_success(history):
    with patch.object(history,'request',return_value={'error':{'code':-32005}}) as request:
        result=trace_fund_flow(ROOT,blockchain='BNB Chain',history=history)
    assert request.call_count==6
    assert result['status']=='unavailable'
    assert result['risk_score'] is None

def test_auth_or_quota_error_no_retry_no_key_leak(history):
    with patch.object(history,'request',return_value={'error':{'code':-32000,'message':'quota '+KEY}}) as request:
        history.fetch(ROOT,'BNB Chain')
    assert request.call_count==2
    assert KEY not in str(history.diagnostics)
    assert all(d['status']=='error' for d in history.diagnostics)

def test_missing_key_does_not_fall_back_to_paid_service(history,monkeypatch):
    monkeypatch.delenv('NODEREAL_API_KEY')
    monkeypatch.setenv('ETHERSCAN_API_KEY','old-key')
    with patch.object(history,'request') as request:
        history.fetch(ROOT,'BNB Chain')
        request.assert_not_called()
    assert all('NODEREAL_API_KEY' in d['message'] for d in history.diagnostics)

def test_missing_decimals_marks_partial_error(history):
    with patch.object(history,'request',return_value={'result':{'transfers':[record(category='20',contractAddress=OTHER)]}}):
        history.fetch(ROOT,'BNB Chain')
    assert any(d['status']=='partial' and d.get('skipped_records') for d in history.diagnostics)

def test_page_cap_is_visible(history):
    history.max_pages=1
    with patch.object(history,'request',return_value={'result':{'transfers':[record()], 'pageKey':'more'}}):
        history.fetch(ROOT,'BNB Chain')
    assert all(d['status']=='truncated' for d in history.diagnostics)

def test_real_request_count_includes_retries(history):
    response=Mock(status_code=200)
    response.json.side_effect=[{'error':{'code':-32005}}, {'result':{'transfers':[]}}, {'result':{'transfers':[]}}]
    history.session.request=Mock(return_value=response)
    history.fetch(ROOT,'BNB Chain')
    assert history.requests==3
    assert sum(d['estimated_cu'] for d in history.diagnostics)==750

def test_deadline_and_request_budget(history,monkeypatch):
    history.requests=history.max_requests
    with pytest.raises(ProviderError,match='budget'):list(history.bnb(ROOT,'outgoing'))
    history.requests=0
    def expired(*args):raise TimeoutError()
    monkeypatch.setattr('ingestion.wait_for_slot',expired)
    with pytest.raises(ProviderError,match='time budget'):list(history.bnb(ROOT,'outgoing'))

def worker(key,queue):
    wait_for_slot(key,time.monotonic()+10)
    queue.put(time.monotonic())

def test_limiter_shared_between_processes(tmp_path,monkeypatch):
    monkeypatch.setenv('NODEREAL_RATE_DIR',str(tmp_path))
    context=multiprocessing.get_context('fork')
    queue=context.Queue()
    procs=[context.Process(target=worker,args=(KEY,queue)) for _ in range(3)]
    for proc in procs:proc.start()
    times=sorted(queue.get(timeout=10) for _ in procs)
    for proc in procs:
        proc.join(timeout=10)
        assert proc.exitcode==0
    assert min(b-a for a,b in zip(times,times[1:]))>=1.05

def test_limiter_deadline_stops_waiting(tmp_path,monkeypatch):
    monkeypatch.setenv('NODEREAL_RATE_DIR',str(tmp_path))
    wait_for_slot(KEY,time.monotonic()+5)
    with pytest.raises(TimeoutError):wait_for_slot(KEY,time.monotonic()+.1)

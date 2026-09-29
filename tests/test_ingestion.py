import os
from unittest.mock import patch
import pytest
from ingestion import History,ProviderError,normalize,validate_address,amount
from graph_engine import trace_fund_flow

TRON='TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb'
OTHER='TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf'
ROOT='0x'+'1'*40
TARGET='0x'+'2'*40


def test_tron_case_preserved_and_checksum():
    assert validate_address(TRON,'Tron')==TRON
    with pytest.raises(ValueError):validate_address(TRON.lower(),'Tron')
    assert normalize(OTHER,'Tron')==OTHER
    assert normalize('0x'+'A'*40,'Ethereum')=='0x'+'a'*40

def test_tron_mixed_case_native_and_token_and_key():
    history=History()
    replies=[{'code':200,'tokenInfo':{'tokenDecimal':6},'data':[{'hash':'native','from':TRON,'to':OTHER,'amount':'1000001','confirmed':1,'contract_ret':'SUCCESS','block_timestamp':1000}]},
      {'token_transfers':[{'transaction_id':'token','from_address':OTHER,'to_address':TRON,'quant':'123','confirmed':True,'finalResult':'SUCCESS','block_ts':2000,'contract_address':'contract','tokenInfo':{'tokenDecimal':0,'tokenAbbr':'ZERO'}}]}]
    with patch.dict(os.environ,{'TRONSCAN_API_KEY':'secret'}),patch.object(history,'request',side_effect=replies) as request:
        rows=history.fetch(TRON,'Tron')
        assert len(rows)==2
        assert {r['value'] for r in rows}=={'1.000001','123'}
        assert all(c.kwargs['headers']['TRON-PRO-API-KEY']=='secret' for c in request.call_args_list)
        assert all(d['status']=='ok' for d in history.diagnostics)

def test_error_not_empty_success():
    history=History()
    with patch.object(history,'request',side_effect=ProviderError('Provider HTTP 429')):
        result=trace_fund_flow(TRON,blockchain='Tron',history=history)
    assert result['status']=='unavailable'
    assert result['risk_score'] is None
    assert result['node_count']==1
    assert all(d['status']=='error' for d in result['diagnostics'])

def test_success_empty_is_explicit_and_not_clean_claim():
    history=History()
    with patch.object(history,'request',side_effect=[{'code':200,'data':[]},{'token_transfers':[]}]):
        result=trace_fund_flow(TRON,blockchain='Tron',history=history)
    assert result['status']=='no_transfers_found'
    assert 'does not prove' in result['coverage_note']

def test_alchemy_pagination_and_cap():
    history=History(max_pages=2)
    transfer={'hash':'tx','from':ROOT,'to':TARGET,'value':1,'asset':'ETH','uniqueId':'tx:external','metadata':{}}
    with patch.dict(os.environ,{'ALCHEMY_API_KEY':'key'}),patch.object(history,'request',side_effect=[{'result':{'transfers':[transfer],'pageKey':'p2'}},{'result':{'transfers':[],'pageKey':'p3'}}]):
        pages=list(history.alchemy(ROOT,'Ethereum','outgoing'))
        assert len(pages)==2 and pages[-1][1] is False

def test_jsonrpc_error_is_reported():
    history=History()
    with patch.dict(os.environ,{'ALCHEMY_API_KEY':'key'}),patch.object(history,'request',return_value={'error':{'code':-32601}}):
        history.fetch(ROOT,'Ethereum')
    assert all(d['status']=='error' for d in history.diagnostics)

def test_precision_zero_decimals():
    assert amount('123456789012345678901234567890',18)=='123456789012.34567890123456789'
    assert amount('25',0)=='25'

class FakeHistory:
    def __init__(self,rows):self.rows=rows;self.diagnostics=[]
    def fetch(self,w,c):
        self.diagnostics.append({'wallet':w,'status':'ok'})
        return self.rows.get(w,[])

def tx(i,s,t,asset='Ethereum:native',timestamp='2026-01-01T00:00:00+00:00',value='1'):
    return dict(id=i,hash=i,**{'from':s,'to':t},value=value,asset='ETH',asset_id=asset,metadata={'blockTimestamp':timestamp})

def test_root_preserved_parallel_events_and_no_ratio_loss():
    third='0x'+'3'*40
    rows={ROOT:[tx('1',ROOT,TARGET),tx('2',ROOT,TARGET)],TARGET:[tx('3',TARGET,third,value='0.00001')]}
    result=trace_fund_flow(ROOT,max_hops=2,history=FakeHistory(rows))
    assert len(result['edges'])==3
    assert next(n for n in result['nodes'] if n['id']==ROOT)['hop']==0
    assert next(n for n in result['nodes'] if n['id']==ROOT)['type']=='reported_wallet'

def test_rapid_requires_order_and_asset_identity():
    third='0x'+'3'*40
    rows={ROOT:[tx('1',ROOT,TARGET)],TARGET:[tx('2',TARGET,third,timestamp='2025-01-01T00:00:00+00:00'),tx('3',TARGET,third,asset='Ethereum:fake-token')]}
    result=trace_fund_flow(ROOT,max_hops=2,history=FakeHistory(rows))
    assert not any(e['rapid_movement'] for e in result['edges'])

def test_cycle_dedup_and_unknown_leaves():
    rows={ROOT:[tx('1',ROOT,TARGET)],TARGET:[tx('1',ROOT,TARGET),tx('2',TARGET,ROOT)]}
    result=trace_fund_flow(ROOT,max_hops=4,history=FakeHistory(rows))
    assert len(result['edges'])==2

def test_vasp_not_forced_safe_and_root_sanctions_scored():
    entity=lambda a,c: {'name':'Analyst lead','source':'reviewed record','is_vasp':True,'is_sanctioned':True} if a==ROOT else {}
    result=trace_fund_flow(ROOT,entity_lookup=entity,history=FakeHistory({ROOT:[]}))
    assert result['risk_score']==99
    assert any('does not establish innocence' in r for r in result['nodes'][0]['risk_reasons'])

def test_bitcoin_does_not_invent_input_owner():
    wallet='1BitcoinEaterAddressDontSendf59kuE'
    history=History()
    transaction={'txid':'hash','status':{'confirmed':True,'block_time':100},'vin':[{'prevout':{'scriptpubkey_address':wallet,'value':30}}],
       'vout':[{'scriptpubkey_address':'other','value':20},{'scriptpubkey_address':wallet,'value':9}]}
    with patch.object(history,'request',return_value=[transaction]):
        result=trace_fund_flow(wallet,blockchain='Bitcoin',history=history)
    assert any(n['id']=='btc-tx:hash' for n in result['nodes'])
    assert not any(e['from']==wallet and e['to']=='other' for e in result['edges'])
    assert any(e['from']=='btc-tx:hash' and e['to']=='other' for e in result['edges'])

import os
from unittest.mock import patch
from ingestion import History
from graph_engine import trace_fund_flow
from import_entities import validate_rows
import pytest

ROOT='0x'+'1'*40
OTHER='0x'+'2'*40

def test_valid_siblings_survive_bad_provider_record():
    h=History()
    valid={'hash':'tx','uniqueId':'tx:0','from':ROOT,'to':OTHER,'value':1,'asset':'ETH'}
    with patch.dict(os.environ,{'ALCHEMY_API_KEY':'fixture'}),patch.object(h,'request',side_effect=[{'result':{'transfers':[valid,{'bad':'schema'}]}},{'result':{'transfers':[]}}]):
        rows=h.fetch(ROOT,'Ethereum')
    assert len(rows)==1
    assert h.diagnostics[0]['status']=='partial'
    assert h.diagnostics[0]['skipped_records']==1

def test_bitcoin_full_incoming_context_and_exact_spend_link():
    wallet='1BitcoinEaterAddressDontSendf59kuE'
    a={'txid':'fund','fee':1,'status':{'confirmed':True,'block_time':100},'vin':[{'txid':'old','vout':7,'prevout':{'scriptpubkey_address':'sender','value':100}}],
        'vout':[{'scriptpubkey_address':wallet,'value':60},{'scriptpubkey_address':'change','value':39}]}
    b={'txid':'spend','fee':1,'status':{'confirmed':True,'block_time':200},'vin':[{'txid':'fund','vout':0,'prevout':{'scriptpubkey_address':wallet,'value':60}}],
        'vout':[{'scriptpubkey_address':'receiver','value':59}]}
    h=History()
    with patch.object(h,'request',return_value=[b,a]) as request:
        data=trace_fund_flow(wallet,max_hops=1,blockchain='Bitcoin',history=h)
    assert '/txs/chain' in request.call_args.args[1]
    assert any(e['from']=='sender' and e['to']=='btc-tx:fund' for e in data['edges'])
    output=next(e for e in data['edges'] if e['id']=='BTC:fund:vout:0')
    assert output['utxo_details']['spent_by_txid']=='spend'
    assert not any(e['from']=='sender' and e['to']==wallet for e in data['edges'])

def test_origin_entity_is_preserved_with_source():
    h=History()
    with patch.object(h,'request',return_value=[]):
        data=trace_fund_flow('1BitcoinEaterAddressDontSendf59kuE',blockchain='Bitcoin',history=h,
            entity_lookup=lambda a,c:{'name':'Test VASP','source':'Synthetic source','is_vasp':True})
    node=data['nodes'][0]
    assert node['type']=='reported_wallet' and node['is_vasp']
    assert node['entity_source']=='Synthetic source'

def test_import_rejects_damaged_tron_and_requires_chain_source():
    row={'blockchain':'Tron','wallet_address':'tmua6yqfcex8ehbfyeg5y7s4dqzsjirey9','name':'test','source':'reviewed source','is_vasp':True}
    with pytest.raises(ValueError):validate_rows([row])
    with pytest.raises(ValueError):validate_rows([{'wallet_address':ROOT,'name':'Test'}])

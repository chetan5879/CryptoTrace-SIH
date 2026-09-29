import copy,json
import pytest
from analytics import enrich,extract,patterns,FEATURES,category
from crosschain import correlate,parse_lifi
import ml_engine

def edge(i,a,b,value,time='2026-01-01T00:00:00+00:00',asset='ETH:native',tx=None,**kwargs):return dict(id=str(i),tx_hash=tx or str(i),**{'from':a,'to':b},amount=str(value),timestamp=time,asset_id=asset,asset='ETH',**kwargs)
def trace(edges,chain='Ethereum'):
    wallets={e[k] for e in edges for k in ('from','to')}
    return {'blockchain':chain,'nodes':[dict(id=w,risk_score=0,risk_reasons=[],coverage='provider_window_exhausted') for w in wallets],'edges':edges}

def test_external_mixer_scores_once(monkeypatch):
    monkeypatch.setattr(ml_engine,'infer',lambda *a:{'status':'insufficient_data','results':[]})
    d=trace([edge(1,'a','b',1)]);n=d['nodes'][0];n.update(is_mixer=True,attribution_status='external_unreviewed')
    enrich(d);assert n['risk_score']==60 and n['risk_category']=='HIGH'
    reviewed=trace([edge(1,'a','b',1)]);n=reviewed['nodes'][0];n.update(is_mixer=True,attribution_status='analyst_reviewed',risk_score=60)
    enrich(reviewed);assert n['risk_score']==60

def test_pass_through_asset_separation():
    d=trace([edge(1,'a','b',100),edge(2,'b','c',98,'2026-01-01T01:00:00+00:00')])
    assert any(f['kind']=='pass_through' for f in patterns(d,extract(d)))
    d['edges'][1]['asset_id']='other';assert not any(f['kind']=='pass_through' for f in patterns(d,extract(d)))

def test_evm_peeling_requires_chronology():
    es=[edge(1,'a','b',90),edge(2,'a','x',10),edge(3,'b','c',81,'2026-01-01T01:00:00+00:00'),edge(4,'b','y',9,'2026-01-01T01:00:00+00:00')]
    d=trace(es);assert any(f['kind']=='peeling_candidate' for f in patterns(d,extract(d)))
    es[2]['timestamp']='2025-01-01T00:00:00+00:00';d=trace(es);assert not any(f['kind']=='peeling_candidate' for f in patterns(d,extract(d)))

def test_btc_exact_spends():
    es=[edge(1,'a','btc-tx:t1',100,tx='t1',utxo_details={'kind':'input','prev_txid':'old','prev_vout':0}),
        edge(2,'btc-tx:t1','b',90,tx='t1',utxo_details={'kind':'output','vout':0}),edge(3,'btc-tx:t1','x',10,tx='t1',utxo_details={'kind':'output','vout':1}),
        edge(4,'b','btc-tx:t2',90,tx='t2',utxo_details={'kind':'input','prev_txid':'t1','prev_vout':0}),
        edge(5,'btc-tx:t2','c',81,tx='t2',utxo_details={'kind':'output','vout':0}),edge(6,'btc-tx:t2','y',9,tx='t2',utxo_details={'kind':'output','vout':1})]
    d=trace(es,'Bitcoin');assert any(f['kind']=='peeling_chain' for f in patterns(d,extract(d)))
    es[3]['utxo_details']['prev_txid']='different';assert not any(f['kind']=='peeling_chain' for f in patterns(trace(es,'Bitcoin'),[]))

def test_no_crosschain_symbol_guess():
    a={**edge(1,'a','bridgeA',100),'chain':'Ethereum'};b={**edge(2,'bridgeB','b',99,'2026-01-01T00:01:00+00:00'),'chain':'Polygon'}
    bridges=[{'blockchain':'Ethereum','wallet_address':'bridgeA'},{'blockchain':'Polygon','wallet_address':'bridgeB'}]
    assert correlate([a,b],[],bridges)[0]==[]
    assets=[{'blockchain':c,'asset_id':'ETH:native','canonical_asset':'asset'} for c in ('Ethereum','Polygon')]
    r,_=correlate([a,b],assets,bridges);assert len(r)==1 and r[0]['status']=='unverified'
    b['timestamp']='2025-01-01T00:00:00+00:00';assert correlate([a,b],assets,bridges)[0]==[]

def test_bridge_response_bound_to_requested_tx():
    tx='0x'+'1'*64;doc={'status':'DONE','substatus':'COMPLETED','sending':{'txHash':tx,'chainId':1},'receiving':{'txHash':'0x'+'2'*64,'chainId':137},'fromAddress':'0x'+'1'*40,'toAddress':'0x'+'2'*40}
    assert parse_lifi(doc,'Ethereum',tx)['to_chain']=='Polygon'
    with pytest.raises(ValueError):parse_lifi(doc,'Ethereum','0x'+'3'*64)
    doc['status']='PENDING';assert parse_lifi(doc,'Ethereum',tx) is None

def rows(n=25):return [{'wallet':str(i),'asset_id':'x','eligible':True,'features':dict(zip(FEATURES,[float(i+1+j) for j in range(len(FEATURES))]))} for i in range(n)]

def test_iforest_active_reproducible_exploratory(tmp_path,monkeypatch):
    monkeypatch.setattr(ml_engine,'MODEL_PATH',tmp_path/'absent.json')
    a=ml_engine.infer(rows(),'Ethereum');b=ml_engine.infer(rows(),'Ethereum')
    assert a==b and a['status']=='exploratory_same_trace' and len(a['results'])==25 and a['fusion_enabled'] is False
    assert all(0<r['anomaly_score']<1 for r in a['results'])
    assert ml_engine.infer(rows(5),'Ethereum')['status']=='insufficient_reference'

def test_training_rejects_leakage(tmp_path):
    tr=[{**r,'chain':'Ethereum','source':'fixture','observed_at':'2025-01-01T00:00:00Z'} for r in rows(100)]
    te=[{**r,'chain':'Ethereum','source':'fixture','observed_at':'2026-01-01T00:00:00Z','label':i%2} for i,r in enumerate(rows(30))]
    a=tmp_path/'train.json';b=tmp_path/'test.json';a.write_text(json.dumps(tr));b.write_text(json.dumps(te))
    with pytest.raises(ValueError,match='disjoint'):ml_engine.train(a,b,tmp_path/'model.json')
    for r in te:r['wallet']='test-'+r['wallet']
    b.write_text(json.dumps(te));result=ml_engine.train(a,b,tmp_path/'model.json');assert result['evaluation']['Ethereum']['evaluation_rows']==30

def test_categories():assert [category(s) for s in (None,0,20,50,80)]==['UNKNOWN','LOW','MEDIUM','HIGH','CRITICAL']

def test_reference_inference_and_fusion_gate(tmp_path,monkeypatch):
    import numpy as np
    rng=np.random.default_rng(42)
    def row(i,test=False):
        bad=test and i>=40
        values=np.full(len(FEATURES),10000.) if bad else rng.uniform(3,8,len(FEATURES))
        return {'wallet':('eval-' if test else 'train-')+str(i),'chain':'Ethereum','source':'SYNTHETIC TEST ONLY',
            'observed_at':'2026-01-01T00:00:00Z' if test else '2025-01-01T00:00:00Z','label':int(bad),'eligible':True,'asset_id':'test',
            'features':dict(zip(FEATURES,values.tolist()))}
    tr=[row(i) for i in range(200)];te=[row(i,True) for i in range(50)]
    a=tmp_path/'tr.json';b=tmp_path/'te.json';out=tmp_path/'reference.json';a.write_text(json.dumps(tr));b.write_text(json.dumps(te))
    doc=ml_engine.train(a,b,out);assert doc['evaluation']['Ethereum']['recall']==1
    monkeypatch.setattr(ml_engine,'MODEL_PATH',out)
    result=ml_engine.infer(te,'Ethereum');assert result['status']=='reference_model' and result['results'][-1]['anomalous']
    assert not result['fusion_enabled']

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch
import json
import pytest
import attribution as a
from graph_engine import trace_fund_flow
from test_ingestion import FakeHistory, ROOT

ADDRESS='0x'+'1'*40

def pack(currency='ETH',category='exchange',actor='example'):
    return f'''title: Example
category: {category}
actor: {actor}
label: Example wallet
currency: {currency}
source: https://example.org/disclosure
lastmod: 2022-11-10
tags:
- address: "{ADDRESS}"
'''.encode()

def test_pack_preserves_chain_source_and_does_not_infer_sanctions():
    rows,skipped=a.parse_pack(pack('BEP20'),'exchange-wallets-example.yaml')
    assert rows[0]['blockchain']=='BNB Chain'
    assert rows[0]['source_date']=='2022-11-10'
    assert rows[0]['source_sha256'] and not rows[0]['is_sanctioned']
    assert rows[0]['attribution_status']=='external_unreviewed'
    assert not skipped
    with pytest.raises(ValueError):a.parse_pack(pack('BNB'),'exchange-wallets-example.yaml')

@pytest.mark.parametrize('raw',[b'tags: &x [*x]',b'!!python/object/apply:os.system [echo bad]',b'not: a-pack',b'x'*(a.MAX_BYTES+1)])
def test_untrusted_yaml_is_bounded_and_rejected(raw):
    with pytest.raises((ValueError,a.yaml.YAMLError)):a.parse_pack(raw,'exchange-wallets-example.yaml')

def test_conflicting_actors_are_not_promoted():
    first=a.parse_pack(pack(),'exchange-wallets-example.yaml')[0][0]
    second={**first,'actor':'different'}
    payload,status=a.choose_match([first,second])
    assert status=='conflict' and 'is_vasp' not in payload
    payload,status=a.choose_match([first,dict(first)])
    assert status=='matched' and len(payload['evidence_sources'])==1

class Store:
    def __init__(self):self.manual=None;self.cached=None;self.rows=[];self.calls=[]
    @contextmanager
    def db(self):yield self
    def execute(self,sql,args=None):
        self.calls.append((sql,args))
        if sql.startswith('SELECT * FROM ct_entities'):self.row=self.manual
        elif sql.startswith('SELECT * FROM ct_online_entities'):
            self.row=self.cached if self.cached and self.cached['expires_at']>a.now() else None
        elif sql.startswith('INSERT INTO ct_online_entities'):
            self.cached={'payload':args[2].adapted,'status':args[3],'expires_at':args[4]}
    def fetchone(self):return self.row


def test_miss_cached_persistently_and_manual_overrides():
    store=Store();entity=a.parse_pack(pack(),'exchange-wallets-example.yaml')[0][0]
    calls=[]
    def load(resolver):
        calls.append(1);resolver.index={('Ethereum',ADDRESS):[entity]};resolver.complete=True;resolver.feed_expiry=a.now()+timedelta(hours=24)
    with patch.object(a,'db',store.db),patch.object(a,'audit'),patch.object(a.AttributionResolver,'_load_index',load):
        first=a.AttributionResolver('user').lookup(ADDRESS,'Ethereum')
        assert first['is_vasp'] and store.cached['status']=='matched'
        second=a.AttributionResolver('user').lookup(ADDRESS,'Ethereum')
        assert second==first and len(calls)==1
        store.manual={'name':'Reviewed correction','is_vasp':False}
        assert a.AttributionResolver('user').lookup(ADDRESS,'Ethereum')['name']=='Reviewed correction'
        assert len(calls)==1


def test_expired_match_removed_when_source_no_longer_labels_address():
    store=Store();store.cached={'payload':{'name':'Old','is_vasp':True},'status':'matched','expires_at':a.now()-timedelta(seconds=1)}
    def load(resolver):resolver.index={};resolver.complete=True;resolver.feed_expiry=a.now()+timedelta(hours=24)
    with patch.object(a,'db',store.db),patch.object(a.AttributionResolver,'_load_index',load):
        assert a.AttributionResolver('user').lookup(ADDRESS,'Ethereum')=={}
        assert store.cached['status']=='not_found'


def test_offline_is_unavailable_not_clean_and_disabled_never_looks_up(monkeypatch):
    store=Store()
    def load(resolver):resolver.index={};resolver.complete=False
    with patch.object(a,'db',store.db),patch.object(a.AttributionResolver,'_load_index',load):
        resolver=a.AttributionResolver('user');assert resolver.lookup(ADDRESS,'Ethereum')=={}
        assert store.cached['status']=='unavailable' and resolver.diagnostics['unavailable']==1
        monkeypatch.setenv('ONLINE_ATTRIBUTION_ENABLED','false')
        with patch.object(a.AttributionResolver,'_load_index',side_effect=AssertionError('network forbidden')):
            assert a.AttributionResolver('user').lookup(ADDRESS,'Ethereum')=={}


def test_unreviewed_mixer_does_not_add_risk_points():
    entity=a.parse_pack(pack(category='mixing_service'),'tornado_cash.yaml')[0][0]
    data=trace_fund_flow(ROOT,history=FakeHistory({ROOT:[]}),entity_lookup=lambda w,c:entity)
    assert data['nodes'][0]['is_mixer'] and data['risk_score']==0
    assert any('External unreviewed' in r for r in data['nodes'][0]['risk_reasons'])

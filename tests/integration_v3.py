"""Disposable PostgreSQL integration test. Never point DATABASE_URL at production."""
import os,sys,uuid,json,time
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
os.environ['APP_ENV']='development';os.environ['APP_ORIGIN']='http://127.0.0.1:8000';os.environ['ONLINE_ATTRIBUTION_ENABLED']='false'
from unittest.mock import patch
from fastapi.testclient import TestClient
from db import db,init_db
from security import hasher
from ingestion import History
import main,worker
last=None
for i in range(20):
    try:init_db();init_db();break
    except Exception as e:last=e;time.sleep(1)
else:raise last
uid=str(uuid.uuid4());name='test-'+uid[:8];cid='TEST-'+uid[:8];wallet='0x'+'1'*40;other='0x'+'2'*40
with db() as cur:
    cur.execute('INSERT INTO ct_users(id,username,password_hash,role) VALUES (%s,%s,%s,%s)',(uid,name,hasher.hash('synthetic-test-password'),'admin'))
    cur.execute('INSERT INTO ct_entities(blockchain,wallet_address,name,source,is_mixer,updated_by) VALUES (%s,%s,%s,%s,TRUE,%s) ON CONFLICT DO NOTHING',('Ethereum',wallet,'Synthetic mixer','Synthetic fixture',uid))
client=TestClient(main.app);r=client.post('/auth/login',json={'username':name,'password':'synthetic-test-password'},headers={'Origin':'http://127.0.0.1:8000'});assert r.status_code==200,r.text
headers={'Origin':'http://127.0.0.1:8000','X-CSRF-Token':r.json()['csrf']}
complaint={'case_id':cid,'victim_reference':'SYNTHETIC','fraud_type':'Synthetic test','reported_amount':'100.25','currency':'INR','incident_date':'2026-01-01T00:00:00Z','wallets':[{'blockchain':'Ethereum','wallet_address':wallet}]}
r=client.post('/workspace/complaints',json=complaint,headers=headers);assert r.status_code==200,r.text
calls=[0];event=[1]
def fake_alchemy(self,w,c,d):
    self.request('POST','https://eth-mainnet.g.alchemy.com/v2/REDACTED')
    rows=[] if d=='incoming' else [self.transfer('0x'+str(event[0])*64,w,other,'10','ETH','Ethereum:native','2026-01-01T00:00:00Z','event-'+str(event[0]))]
    yield rows,True

def fake_request(*args,**kw):calls[0]+=1;return {'synthetic':True,'event':event[0]}
with patch.object(History,'alchemy',fake_alchemy),patch.object(History,'request',fake_request):
    assert worker.run_once()
    jobs=client.get('/workspace/jobs').json();assert jobs[0]['state']=='done',jobs
    ov=client.get('/workspace/cases/'+cid+'/overview');assert ov.status_code==200,ov.text
    assert any(n.get('risk_score')==60 for n in ov.json()['nodes']),ov.text
    assert len(client.get('/workspace/cases/'+cid+'/events').json())>=1
    refs=ov.json()['traces'][0]['raw_evidence_refs'];assert refs
    assert client.get('/workspace/cases/'+cid+'/evidence/'+refs[0]).status_code==200
    # Cached trace: no new provider requests within the five-minute fresh window.
    before=calls[0];r=client.post('/cases/'+cid+'/trace',json={},headers=headers);assert r.status_code==200,r.text;assert calls[0]==before
    r=client.post('/workspace/cases/'+cid+'/watchlists',json={'blockchain':'Ethereum','wallet_address':wallet,'interval_seconds':300,'threshold':50},headers=headers);assert r.status_code==200,r.text
    wid=r.json()['watch_id'];assert worker.run_once()
    assert client.get('/workspace/alerts').json()==[]
    event[0]=3
    with db() as cur:cur.execute("UPDATE ct_watchlists SET next_poll=now()-interval '1 second' WHERE id=%s",(wid,))
    assert worker.run_once();alerts=client.get('/workspace/alerts').json();assert len(alerts)==1,alerts
    with db() as cur:cur.execute("UPDATE ct_watchlists SET next_poll=now()-interval '1 second' WHERE id=%s",(wid,))
    assert worker.run_once();assert len(client.get('/workspace/alerts').json())==1
    assert client.post('/workspace/alerts/'+alerts[0]['id']+'/acknowledge',headers=headers).status_code==200
    assert client.get('/workspace/cases/'+cid+'/export').json()['agency_submission_status']=='not_submitted'
    assert client.get('/workspace/cases/'+cid+'/features').json()['rows']
    # Append-only source/trace evidence is enforced by triggers.
    import psycopg2
    try:
        with db() as cur:cur.execute('DELETE FROM ct_raw_evidence WHERE sha256=%s',(refs[0],))
    except psycopg2.Error:pass
    else:raise AssertionError('Evidence trigger did not reject delete')
print('INTEGRATION PASSED: migration twice, login/CSRF, intake, durable job, indexed events, raw evidence, cache reuse, monitoring baseline, alert dedup, acknowledge, export, immutable evidence')

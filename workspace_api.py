"""Authenticated case workspace and agency-neutral ingestion boundary."""
import json,uuid
from datetime import datetime
from typing import Literal
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException,Request,Query
from pydantic import BaseModel,Field,field_validator,ConfigDict
from psycopg2.extras import Json
from db import db,audit
from security import require_user,require_admin,visible_case
from ingestion import validate_address,CHAINS
from services import sha,save_link
from crosschain import correlate,lookup
router=APIRouter(prefix='/workspace')
Chain=Literal['Ethereum','Polygon','BNB Chain','Bitcoin','Tron']

class Wallet(BaseModel):
    model_config=ConfigDict(extra='forbid')
    blockchain:Chain
    wallet_address:str=Field(min_length=10,max_length=100)
    max_hops:int=Field(default=2,ge=1,le=4)
    @field_validator('wallet_address')
    @classmethod
    def wallet(cls,v,info):return validate_address(v,info.data['blockchain'])

class Complaint(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal['cryptotrace.case.v1']='cryptotrace.case.v1'
    case_id:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.-]+$')
    victim_reference:str=Field(min_length=1,max_length=120)
    complaint_reference:str=Field(default='',max_length=120)
    fraud_type:str=Field(min_length=1,max_length=120)
    reported_amount:Decimal=Field(ge=0,max_digits=40,decimal_places=18)
    currency:str=Field(min_length=1,max_length=20)
    incident_date:datetime
    evidence:list[str]=Field(default_factory=list,max_length=50)
    wallets:list[Wallet]=Field(min_length=1,max_length=20)
    @field_validator('incident_date')
    @classmethod
    def aware(cls,v):
        if v.tzinfo is None:raise ValueError('Incident date requires timezone')
        return v
    @field_validator('evidence')
    @classmethod
    def evidence_limit(cls,v):
        if any(len(e)>1000 for e in v):raise ValueError('Evidence reference too long')
        return v

def enqueue(cur,case_id,user,body,kind='trace'):
    cur.execute("SELECT count(*) AS n FROM ct_jobs WHERE user_id=%s AND state IN ('queued','running')",(user['id'],))
    if cur.fetchone()['n']>=50:raise HTTPException(429,'Maximum 50 pending jobs per user')
    jid=str(uuid.uuid4());cur.execute('INSERT INTO ct_jobs(id,case_id,user_id,kind,payload) VALUES (%s,%s,%s,%s,%s)',(jid,case_id,user['id'],kind,Json(body)))
    return jid

@router.post('/complaints')
def ingest(body:Complaint,request:Request,user=Depends(require_user)):
    w=body.wallets[0];doc=body.model_dump(mode='json')
    with db() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('queue:'+user['id'],))
        cur.execute('INSERT INTO ct_cases(case_id,owner_id,wallet_address,blockchain,fraud_type,max_hops) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING case_id',(body.case_id,user['id'],w.wallet_address,w.blockchain,body.fraud_type,w.max_hops))
        if not cur.fetchone():raise HTTPException(409,'Case ID already exists; use add-wallet for an existing case')
        cur.execute('INSERT INTO ct_complaints VALUES (%s,%s,now())',(body.case_id,Json(doc)))
        jobs=[]
        for wallet in body.wallets:
            cur.execute('INSERT INTO ct_case_wallets VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(body.case_id,wallet.blockchain,wallet.wallet_address))
            jobs.append(enqueue(cur,body.case_id,user,wallet.model_dump()))
        audit(cur,user['id'],'complaint_imported',request,{'case_id':body.case_id,'wallets':len(jobs)})
    return {'case_id':body.case_id,'jobs':jobs,'integration':'agency-neutral import; no submission to NCRP/SAHYOG'}

@router.get('/integration')
def integration(user=Depends(require_user)):
    return {'schema':Complaint.model_json_schema(),'status':'local_import_export_ready','live_agency_connector':'not_configured',
        'missing':['Authorised API specification','Credentials and permissions','Agency testing and acceptance'],
        'privacy':'Victim reference only recommended; evidence references are not downloaded automatically'}

@router.post('/cases/{case_id}/wallets')
def add_wallet(case_id:str,body:Wallet,request:Request,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('queue:'+user['id'],))
        cur.execute('SELECT count(*) AS n FROM ct_case_wallets WHERE case_id=%s',(case_id,))
        if cur.fetchone()['n']>=100:raise HTTPException(409,'100 wallet case limit reached')
        cur.execute('INSERT INTO ct_case_wallets VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(case_id,body.blockchain,body.wallet_address))
        jid=enqueue(cur,case_id,user,body.model_dump());audit(cur,user['id'],'wallet_trace_queued',request,{'case_id':case_id,'job_id':jid})
    return {'job_id':jid}

@router.get('/jobs')
def jobs(user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT j.* FROM ct_jobs j JOIN ct_cases c ON c.case_id=j.case_id WHERE c.owner_id=%s OR %s ORDER BY created_at DESC LIMIT 100',(user['id'],user['role']=='admin'));return cur.fetchall()

@router.post('/jobs/{job_id}/retry')
def retry(job_id:str,request:Request,user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT * FROM ct_jobs WHERE id=%s FOR UPDATE',(job_id,));j=cur.fetchone()
        if not j:raise HTTPException(404,'Job not found')
        visible_case(cur,j['case_id'],user)
        if j['state']!='failed':raise HTTPException(409,'Only failed jobs can be retried')
        cur.execute("UPDATE ct_jobs SET state='queued',error=NULL,attempts=0 WHERE id=%s",(job_id,));audit(cur,user['id'],'job_retry',request,{'job_id':job_id})
    return {'status':'queued'}

class Watch(Wallet):
    interval_seconds:int=Field(default=600,ge=300,le=86400)
    threshold:int=Field(default=50,ge=0,le=100)

@router.post('/cases/{case_id}/watchlists')
def watch(case_id:str,body:Watch,request:Request,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('queue:'+user['id'],))
        cur.execute('SELECT count(*) AS n FROM ct_watchlists WHERE user_id=%s AND enabled',(user['id'],))
        if cur.fetchone()['n']>=50:raise HTTPException(409,'50 active watchlist limit per user')
        cur.execute('''INSERT INTO ct_watchlists(id,case_id,user_id,blockchain,wallet_address,interval_seconds,threshold) VALUES (%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(case_id,blockchain,wallet_address) DO UPDATE SET interval_seconds=EXCLUDED.interval_seconds,threshold=EXCLUDED.threshold,enabled=TRUE RETURNING id''',
          (str(uuid.uuid4()),case_id,user['id'],body.blockchain,body.wallet_address,body.interval_seconds,body.threshold));wid=cur.fetchone()['id']
        audit(cur,user['id'],'watch_enabled',request,{'case_id':case_id,'watch_id':wid})
    return {'watch_id':wid,'note':'First successful poll seeds baseline. Polling can miss activity beyond provider bounds.'}

@router.get('/watchlists')
def watches(user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT w.* FROM ct_watchlists w JOIN ct_cases c ON c.case_id=w.case_id WHERE c.owner_id=%s OR %s ORDER BY next_poll LIMIT 200',(user['id'],user['role']=='admin'));return cur.fetchall()

@router.delete('/watchlists/{watch_id}')
def disable_watch(watch_id:str,request:Request,user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT case_id FROM ct_watchlists WHERE id=%s',(watch_id,));w=cur.fetchone()
        if not w:raise HTTPException(404,'Watch not found')
        visible_case(cur,w['case_id'],user);cur.execute('UPDATE ct_watchlists SET enabled=FALSE WHERE id=%s',(watch_id,));audit(cur,user['id'],'watch_disabled',request,{'watch_id':watch_id})
    return {'status':'disabled'}

@router.get('/alerts')
def alerts(user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT a.* FROM ct_alerts a JOIN ct_cases c ON c.case_id=a.case_id WHERE c.owner_id=%s OR %s ORDER BY created_at DESC LIMIT 200',(user['id'],user['role']=='admin'));return cur.fetchall()

@router.post('/alerts/{alert_id}/acknowledge')
def acknowledge(alert_id:str,request:Request,user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT case_id FROM ct_alerts WHERE id=%s',(alert_id,));a=cur.fetchone()
        if not a:raise HTTPException(404,'Alert not found')
        visible_case(cur,a['case_id'],user);cur.execute('UPDATE ct_alerts SET acknowledged_at=now(),acknowledged_by=%s WHERE id=%s',(user['id'],alert_id));audit(cur,user['id'],'alert_acknowledged',request,{'alert_id':alert_id})
    return {'status':'acknowledged'}

@router.get('/cases/{case_id}/events')
def events(case_id:str,chain:str='',wallet:str='',asset:str='',start:datetime|None=None,end:datetime|None=None,offset:int=Query(default=0,ge=0,le=10000000),user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('''SELECT e.* FROM ct_case_events ce JOIN ct_event_index e USING(blockchain,event_id) WHERE ce.case_id=%s
          AND (%s='' OR e.blockchain=%s) AND (%s='' OR e.sender=%s OR e.receiver=%s) AND (%s='' OR e.asset_id=%s)
          AND (%s::timestamptz IS NULL OR e.occurred_at>=%s) AND (%s::timestamptz IS NULL OR e.occurred_at<=%s)
          ORDER BY e.occurred_at DESC NULLS LAST,e.event_id LIMIT 200 OFFSET %s''',(case_id,chain,chain,wallet,wallet,wallet,asset,asset,start,start,end,end,offset));return cur.fetchall()

@router.get('/cases/{case_id}/evidence/{digest}')
def evidence(case_id:str,digest:str,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user);cur.execute('SELECT e.* FROM ct_raw_evidence e JOIN ct_case_evidence c USING(sha256) WHERE c.case_id=%s AND e.sha256=%s',(case_id,digest));r=cur.fetchone()
        if not r:raise HTTPException(404,'Evidence not found')
        return r

@router.get('/cases/{case_id}/overview')
def overview(case_id:str,user=Depends(require_user)):
    with db() as cur:
        case=visible_case(cur,case_id,user)
        cur.execute("SELECT DISTINCT ON (payload->>'blockchain',payload->>'wallet_address') payload,sha256 FROM ct_traces WHERE case_id=%s ORDER BY payload->>'blockchain',payload->>'wallet_address',created_at DESC LIMIT 100",(case_id,));traces=cur.fetchall()
        cur.execute('SELECT * FROM ct_case_wallets WHERE case_id=%s',(case_id,));wallets=cur.fetchall()
        cur.execute('SELECT * FROM ct_cross_links WHERE case_id=%s ORDER BY created_at DESC LIMIT 200',(case_id,));links=cur.fetchall()
        cur.execute('SELECT * FROM ct_asset_registry');assets=cur.fetchall();cur.execute('SELECT * FROM ct_bridge_registry');bridges=cur.fetchall()
    nodes={};edges={}
    for tr in traces:
        p=tr['payload'];chain=p['blockchain']
        for n in p['nodes']:
            key=chain+':'+n['id'];old=nodes.get(key)
            if old is None or (n.get('risk_score') if n.get('risk_score') is not None else -1)>(old.get('risk_score') if old.get('risk_score') is not None else -1):
                nodes[key]={**n,'address':n['id'],'id':key,'chain':chain}
        for e in p['edges']:edges[chain+':'+e['id']]={**e,'chain':chain,'id':chain+':'+e['id']}
    candidates,truncated=correlate(list(edges.values()),assets,bridges)
    return {'case':case,'wallets':wallets,'nodes':list(nodes.values()),'edges':list(edges.values()),'links':links,'candidates':candidates,'candidates_truncated':truncated,
        'traces':[{'trace_id':r['payload']['trace_id'],'chain':r['payload']['blockchain'],'wallet':r['payload']['wallet_address'],'ml':r['payload'].get('ml'),
                   'patterns':r['payload'].get('patterns',[]),'clusters':r['payload'].get('clusters',[]),'raw_evidence_refs':r['payload'].get('raw_evidence_refs',[]),'sha256':r['sha256']} for r in traces],
        'scope':'Latest 100 wallet/chain snapshots; each trace is bounded. Transaction index is paginated separately.'}

class BridgeLookup(BaseModel):
    blockchain:Chain
    tx_hash:str=Field(pattern=r'^0x[0-9a-fA-F]{64}$')

@router.post('/cases/{case_id}/bridge-lookup')
def bridge_lookup(case_id:str,body:BridgeLookup,request:Request,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('SELECT 1 FROM ct_case_events c JOIN ct_event_index e USING(blockchain,event_id) WHERE c.case_id=%s AND e.blockchain=%s AND lower(e.tx_hash)=lower(%s) LIMIT 1',(case_id,body.blockchain,body.tx_hash))
        if not cur.fetchone():raise HTTPException(422,'Transaction must first be indexed in this case')
        # Cross-process rate limit for external lookup.
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('bridge:'+user['id'],))
        cur.execute("SELECT count(*) AS n FROM ct_audit WHERE user_id=%s AND action='bridge_lookup' AND occurred_at>now()-interval '1 minute'",(user['id'],))
        if cur.fetchone()['n']>=5:raise HTTPException(429,'Five bridge lookups per minute')
        audit(cur,user['id'],'bridge_lookup',request,{'case_id':case_id,'tx_hash':body.tx_hash})
    try:link,raw=lookup(body.blockchain,body.tx_hash)
    except Exception:raise HTTPException(502,'Bridge provider unavailable or response failed validation')
    return save_link(case_id,link,raw) if link else {'status':'no_completed_supported_link','note':'No match does not rule out other bridges'}

class Asset(BaseModel):
    blockchain:Chain
    asset_id:str=Field(min_length=1,max_length=200)
    canonical_asset:str=Field(min_length=1,max_length=80)
    source:str=Field(min_length=5,max_length=500)
class Bridge(Wallet):
    name:str=Field(min_length=1,max_length=120)
    source:str=Field(min_length=5,max_length=500)

@router.post('/registry/assets')
def asset_registry(body:Asset,request:Request,user=Depends(require_admin)):
    with db() as cur:
        cur.execute('INSERT INTO ct_asset_registry VALUES (%s,%s,%s,%s,%s) ON CONFLICT(blockchain,asset_id) DO UPDATE SET canonical_asset=EXCLUDED.canonical_asset,source=EXCLUDED.source,updated_by=EXCLUDED.updated_by',(body.blockchain,body.asset_id,body.canonical_asset,body.source,user['id']));audit(cur,user['id'],'asset_mapping',request,body.model_dump())
    return {'status':'saved'}

@router.post('/registry/bridges')
def bridge_registry(body:Bridge,request:Request,user=Depends(require_admin)):
    with db() as cur:
        cur.execute('INSERT INTO ct_bridge_registry VALUES (%s,%s,%s,%s,%s) ON CONFLICT(blockchain,wallet_address) DO UPDATE SET name=EXCLUDED.name,source=EXCLUDED.source,updated_by=EXCLUDED.updated_by',(body.blockchain,body.wallet_address,body.name,body.source,user['id']));audit(cur,user['id'],'bridge_mapping',request,body.model_dump())
    return {'status':'saved'}

@router.get('/cases/{case_id}/export')
def export_case(case_id:str,request:Request,user=Depends(require_user)):
    with db() as cur:
        case=visible_case(cur,case_id,user)
        cur.execute('SELECT metadata FROM ct_complaints WHERE case_id=%s',(case_id,));c=cur.fetchone()
        cur.execute('SELECT id,created_at,sha256 FROM ct_traces WHERE case_id=%s ORDER BY created_at',(case_id,));manifest=cur.fetchall()
        audit(cur,user['id'],'case_exported',request,{'case_id':case_id})
    payload={'schema_version':'cryptotrace.export.v1','complaint':c['metadata'] if c else None,'case':case,'trace_manifest':manifest,'overview':overview(case_id,user),
             'agency_submission_status':'not_submitted','notice':'Local export; not NCRP/SAHYOG approval. Full saved traces and raw evidence remain available via authorised API.'}
    return {**payload,'export_sha256':sha(payload)}

@router.get('/ml/status')
def ml_status(user=Depends(require_user)):
    from ml_engine import MODEL_PATH,load
    if not MODEL_PATH.exists():return {'status':'exploratory_mode','reference_installed':False,'fusion_enabled':False,'minimum_distinct_wallets':20}
    try:
        doc,_,digest=load(str(MODEL_PATH),MODEL_PATH.stat().st_mtime_ns)
        return {'status':'reference_installed','sha256':digest,'evaluation':doc.get('evaluation'), 'fusion_enabled':doc.get('enable_fusion',False),'feature_version':doc['feature_version']}
    except Exception:raise HTTPException(503,'Reference could not be loaded; check model compatibility')

@router.get('/cases/{case_id}/features')
def feature_export(case_id:str,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('SELECT payload,sha256 FROM ct_traces WHERE case_id=%s ORDER BY created_at DESC LIMIT 100',(case_id,));traces=cur.fetchall()
    rows=[]
    for tr in traces:
        p=tr['payload']
        for r in p.get('features',[]):
            rows.append({**r,'chain':p['blockchain'],'observed_at':p['fetched_at'],'source':'trace-sha256:'+tr['sha256'],'label':None})
    return {'feature_version':'wallet-same-asset-v1','rows':rows,'notice':'Curate disjoint training and later labelled evaluation wallets; null labels are not benign labels.'}

@router.get('/registry')
def registry(user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT blockchain,asset_id,canonical_asset,source FROM ct_asset_registry ORDER BY blockchain,canonical_asset LIMIT 1000');assets=cur.fetchall()
        cur.execute('SELECT blockchain,wallet_address,name,source FROM ct_bridge_registry ORDER BY blockchain,name LIMIT 1000');bridges=cur.fetchall()
    return {'assets':assets,'bridges':bridges,'limit':1000}

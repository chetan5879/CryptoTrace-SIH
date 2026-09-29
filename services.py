"""Shared trace execution for API and durable worker."""
import hashlib,json,uuid,os
from psycopg2.extras import Json
from db import db,audit
from graph_engine import trace_fund_flow
from attribution import AttributionResolver
from indexed_history import IndexedHistory
from analytics import enrich

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str)
def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def execute(case,user,wallet,chain,max_hops=2,fan_threshold=5,force=False):
    resolver=AttributionResolver(user['id']);history=IndexedHistory(case['case_id'],force=force)
    try:
        data=trace_fund_flow(wallet,max_hops,fan_threshold,chain,resolver.lookup,history)
        data['attribution_diagnostics']=resolver.diagnostics
        data['raw_evidence_refs']=list(dict.fromkeys(history.evidence_refs))
        enrich(data)
        data.update(trace_id=str(uuid.uuid4()),case_id=case['case_id'],fraud_type=case['fraud_type'],investigator=user['username'])
        data['crosschain_refresh']=auto_bridges(case['case_id'],data['edges'],chain)
        digest=sha(data)
        with db() as cur:
            cur.execute('INSERT INTO ct_traces(id,case_id,user_id,payload,sha256) VALUES (%s,%s,%s,%s,%s)',(data['trace_id'],case['case_id'],user['id'],Json(data),digest))
            cur.execute('UPDATE ct_cases SET risk_score=%s,status=%s WHERE case_id=%s',(data['risk_score'],data['status'],case['case_id']))
            audit(cur,user['id'],'trace_saved',detail={'case_id':case['case_id'],'trace_id':data['trace_id'],'sha256':digest})
        return {**data,'evidence_sha256':digest}
    finally:history.close()

def save_link(case_id,link,raw):
    digest=sha(raw)
    with db() as cur:
        cur.execute('INSERT INTO ct_raw_evidence(sha256,provider,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(digest,'LI.FI',Json(raw)))
        cur.execute('INSERT INTO ct_case_evidence VALUES (%s,%s) ON CONFLICT DO NOTHING',(case_id,digest))
        cur.execute('INSERT INTO ct_cross_links(id,case_id,payload,evidence_sha256) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',(str(uuid.uuid4()),case_id,Json(link),digest))
        # A provider-reported destination becomes a separate, queued chain trace.
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('case-expand:'+case_id,))
        cur.execute('SELECT count(*) AS n FROM ct_case_wallets WHERE case_id=%s',(case_id,));count=cur.fetchone()['n']
        if count<100:
            cur.execute('INSERT INTO ct_case_wallets VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING wallet_address',(case_id,link['to_chain'],link['to_address']))
            if cur.fetchone():
                cur.execute('SELECT owner_id FROM ct_cases WHERE case_id=%s',(case_id,));uid=cur.fetchone()['owner_id']
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('queue:'+uid,))
                cur.execute("SELECT count(*) AS n FROM ct_jobs WHERE user_id=%s AND state IN ('queued','running')",(uid,))
                if cur.fetchone()['n']<50:
                    cur.execute('INSERT INTO ct_jobs(id,case_id,user_id,kind,payload) VALUES (%s,%s,%s,%s,%s)',
                        (str(uuid.uuid4()),case_id,uid,'trace',Json({'blockchain':link['to_chain'],'wallet_address':link['to_address'],'max_hops':1})))
    return {**link,'evidence_sha256':digest}

def auto_bridges(case_id,edges,chain):
    if os.getenv('LIFI_ENABLED','false').lower()!='true':return {'status':'disabled','reason':'Enable LIFI_ENABLED to disclose source transaction hashes to LI.FI'}
    from crosschain import lookup,CHAIN_IDS
    if chain not in CHAIN_IDS:return {'status':'unsupported_chain'}
    with db() as cur:
        cur.execute('SELECT wallet_address FROM ct_bridge_registry WHERE blockchain=%s',(chain,));bridges={r['wallet_address'] for r in cur.fetchall()}
    txs=list(dict.fromkeys(e['tx_hash'] for e in edges if e['to'] in bridges))
    result=[]
    for tx in txs[:3]:
        try:
            link,raw=lookup(chain,tx)
            if link:save_link(case_id,link,raw)
            result.append({'tx_hash':tx,'status':'linked' if link else 'not_completed_or_unsupported'})
        except Exception:result.append({'tx_hash':tx,'status':'provider_unavailable'})
    return {'status':'checked','results':result,'truncated':len(txs)>3}

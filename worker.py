"""Run separately: python worker.py. PostgreSQL SKIP LOCKED queue, leases and retries."""
import argparse,time,uuid,logging,signal
from datetime import datetime,timezone
from psycopg2.extras import Json
from db import db,audit
from services import execute,sha
STOP=False

def schedule():
    with db() as cur:
        cur.execute('''SELECT w.* FROM ct_watchlists w JOIN ct_users u ON u.id=w.user_id WHERE w.enabled AND u.active AND w.next_poll<=now()
          AND NOT EXISTS (SELECT 1 FROM ct_jobs j WHERE j.payload->>'watch_id'=w.id AND j.state IN ('queued','running'))
          ORDER BY w.next_poll FOR UPDATE OF w SKIP LOCKED LIMIT 20''')
        for w in cur.fetchall():
            payload={'watch_id':w['id'],'wallet_address':w['wallet_address'],'blockchain':w['blockchain'],'max_hops':1}
            cur.execute('INSERT INTO ct_jobs(id,case_id,user_id,kind,payload) VALUES (%s,%s,%s,%s,%s)',(str(uuid.uuid4()),w['case_id'],w['user_id'],'monitor',Json(payload)))
            cur.execute("UPDATE ct_watchlists SET next_poll=now()+interval '1 second'*interval_seconds WHERE id=%s",(w['id'],))

def claim():
    with db() as cur:
        cur.execute("UPDATE ct_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,error='Worker lease expired',lease_token=NULL WHERE state='running' AND lease_until<now()")
        cur.execute("SELECT * FROM ct_jobs WHERE state='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
        job=cur.fetchone()
        if not job:return None
        token=str(uuid.uuid4())
        cur.execute("UPDATE ct_jobs SET state='running',attempts=attempts+1,lease_token=%s,lease_until=now()+interval '10 minutes' WHERE id=%s",(token,job['id']))
        return {**job,'lease_token':token}

def alert(cur,job,key,severity,payload):
    cur.execute('INSERT INTO ct_alerts(id,case_id,watch_id,dedup_key,severity,payload) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
       (str(uuid.uuid4()),job['case_id'],job['payload'].get('watch_id'),key,severity,Json(payload)))

def monitor_result(cur,job,data):
    wid=job['payload']['watch_id'];cur.execute('SELECT * FROM ct_watchlists WHERE id=%s FOR UPDATE',(wid,));w=cur.fetchone()
    if not w or not w['enabled']:return
    if data['status']!='observed':
        key=sha([wid,'coverage',datetime.now(timezone.utc).date().isoformat()])
        alert(cur,job,key,'COVERAGE',{'message':'Monitoring retrieval incomplete; events may be missed','status':data['status'],'trace_id':data['trace_id']})
    if data['status']=='unavailable':return
    # Seed baseline on first successful window. Never fabricate "new" historical events.
    for e in data['edges']:
        cur.execute('INSERT INTO ct_watch_seen VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING event_id',(wid,e['id']))
        new=cur.fetchone()
        if new and w['baseline_set'] and data.get('risk_score') is not None and data['risk_score']>=w['threshold']:
            alert(cur,job,sha([wid,e['id']]),data['risk_category'],{'wallet':w['wallet_address'],'blockchain':w['blockchain'],'event_id':e['id'],'transaction':e['tx_hash'],
                'risk':data['risk_score'],'trace_id':data['trace_id'],'trigger':'Newly observed event with trace risk at or above configured threshold',
                'reasons':next((n.get('risk_reasons',[]) for n in data['nodes'] if n['id']==w['wallet_address']),[])})
    cur.execute('UPDATE ct_watchlists SET baseline_set=TRUE WHERE id=%s',(wid,))

def run_once():
    schedule();job=claim()
    if not job:return False
    try:
        with db() as cur:
            cur.execute('SELECT * FROM ct_users WHERE id=%s AND active',(job['user_id'],));user=cur.fetchone()
            cur.execute('SELECT * FROM ct_cases WHERE case_id=%s',(job['case_id'],));case=cur.fetchone()
        if not user or not case or (case['owner_id']!=user['id'] and user['role']!='admin'):raise ValueError('Job access revoked')
        with db() as lock:
            lock.execute('SELECT pg_try_advisory_lock(hashtext(%s)) AS ok',('trace:'+user['id'],))
            if not lock.fetchone()['ok']:
                with db() as cur:cur.execute("UPDATE ct_jobs SET state='queued',attempts=GREATEST(0,attempts-1),lease_token=NULL WHERE id=%s AND lease_token=%s",(job['id'],job['lease_token']))
                return False
            p=job['payload'];data=execute(case,user,p['wallet_address'],p['blockchain'],p.get('max_hops',2),force=job['kind']=='monitor')
        with db() as cur:
            cur.execute('SELECT state,lease_token FROM ct_jobs WHERE id=%s FOR UPDATE',(job['id'],));state=cur.fetchone()
            if state['state']!='running' or state['lease_token']!=job['lease_token']:return True
            if job['kind']=='monitor':monitor_result(cur,job,data)
            cur.execute("UPDATE ct_jobs SET state='done',finished_at=now(),result=%s,lease_token=NULL WHERE id=%s",(Json({'trace_id':data['trace_id'],'status':data['status'],'risk_score':data['risk_score']}),job['id']))
            audit(cur,user['id'],'job_completed',detail={'job_id':job['id'],'case_id':job['case_id']})
    except Exception:
        logging.exception('Job failed %s',job['id'])
        with db() as cur:cur.execute("UPDATE ct_jobs SET state='failed',finished_at=now(),error='Job failed; inspect worker log',lease_token=NULL WHERE id=%s AND lease_token=%s",(job['id'],job['lease_token']))
    return True

def stop(*_):
    global STOP
    STOP=True

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');a=p.parse_args();signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not STOP:
        try:worked=run_once()
        except Exception:logging.exception('Worker cycle failed');worked=False
        if a.once:break
        if not worked:time.sleep(5)

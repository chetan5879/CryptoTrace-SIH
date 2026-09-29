"""CryptoTrace: authenticated local-first investigation server."""
import hashlib
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from psycopg2.extras import Json
from db import db, init_db, audit
from security import require_user, require_admin, origin_check, digest, COOKIE, hasher, DUMMY_HASH, check_password, visible_case
from ingestion import validate_address, CHAINS
from graph_engine import trace_fund_flow
from attribution import AttributionResolver, refresh_sources, source_status

ROOT = Path(__file__).resolve().parent
PRODUCTION = os.getenv('APP_ENV', 'production') != 'development'

@asynccontextmanager
async def lifespan(app):
    if PRODUCTION and not os.getenv('APP_ORIGIN', '').startswith('https://'):
        raise RuntimeError('Production requires an HTTPS APP_ORIGIN')
    # Run `python manage.py migrate` explicitly using the migration role before starting.
    with db() as cur:
        cur.execute('SELECT 1 FROM ct_users LIMIT 1')
    yield

app = FastAPI(title='CryptoTrace', version='2.4.0', lifespan=lifespan, docs_url=None if PRODUCTION else '/docs', redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(','))

@app.middleware('http')
async def secure_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logging.exception('Unhandled request failure')
        response = JSONResponse({'detail':'Internal error; contact the system administrator'}, status_code=500)
    response.headers.update({'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY',
        'Referrer-Policy':'no-referrer', 'Cache-Control':'no-store',
        'Permissions-Policy':'geolocation=(), camera=(), microphone=()',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
    if PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response

class Login(BaseModel):
    username: str = Field(min_length=3,max_length=64,pattern=r'^[A-Za-z0-9_.-]+$')
    password: str = Field(min_length=1,max_length=256)

@app.post('/auth/login')
def login(body: Login, request: Request, response: Response):
    origin_check(request)
    username = body.username.lower()
    ip = request.client.host if request.client else 'unknown'
    with db() as cur:
        # Serialize attempts across workers; rate limits apply to successes and failures.
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('login:'+ip,))
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('username:'+username,))
        cur.execute("SELECT count(*) AS n FROM ct_audit WHERE action IN ('login_failed','login_success') AND occurred_at>now()-interval '15 minutes' AND (ip=%s OR detail->>'username'=%s)", (ip,username))
        limited = cur.fetchone()['n'] >= 10
        if limited:
            raise HTTPException(429, 'Too many sign-in attempts; try again after 15 minutes')
        cur.execute('SELECT * FROM ct_users WHERE username=%s', (username,))
        user = cur.fetchone()
        good = check_password(body.password, user['password_hash'] if user else DUMMY_HASH)
        if not good or not user or not user['active']:
            audit(cur,None,'login_failed',request,{'username':username})
            failure = True
        else:
            failure = False
            token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            # Re-authentication invalidates the current browser's previous session.
            cur.execute('DELETE FROM ct_sessions WHERE token_hash=%s OR expires_at<now()', (digest(request.cookies.get(COOKIE,'')),))
            cur.execute('INSERT INTO ct_sessions(token_hash,user_id,csrf,expires_at,ip,user_agent) VALUES (%s,%s,%s,%s,%s,%s)',
                (digest(token),user['id'],csrf,datetime.now(timezone.utc)+timedelta(hours=8),ip,request.headers.get('user-agent','')[:512]))
            audit(cur,user['id'],'login_success',request,{'username':username})
    # Raise outside transaction so failed-login audit records are committed.
    if failure:
        raise HTTPException(401, 'Invalid username or password')
    response.set_cookie(COOKIE,token,httponly=True,secure=PRODUCTION,samesite='strict',max_age=8*3600,path='/')
    return {'username':user['username'],'role':user['role'],'csrf':csrf}

@app.get('/auth/me')
def me(user=Depends(require_user)):
    return {k:user[k] for k in ('username','role','csrf')}

@app.post('/auth/logout')
def logout(request: Request, response: Response, user=Depends(require_user)):
    with db() as cur:
        cur.execute('DELETE FROM ct_sessions WHERE token_hash=%s',(user['token_hash'],))
        audit(cur,user['id'],'logout',request)
    response.delete_cookie(COOKIE,path='/')
    return {'status':'signed_out'}

@app.get('/audit')
def audit_history(user=Depends(require_user), offset: int=0):
    if offset < 0 or offset > 1000000:
        raise HTTPException(400,'Invalid offset')
    with db() as cur:
        cur.execute('''SELECT a.id,a.action,a.occurred_at,a.ip,a.user_agent,a.detail,u.username FROM ct_audit a
            LEFT JOIN ct_users u ON u.id=a.user_id WHERE (a.user_id=%s OR %s) ORDER BY a.id DESC LIMIT 100 OFFSET %s''',
            (user['id'],user['role']=='admin',offset))
        return cur.fetchall()

class CaseModel(BaseModel):
    case_id: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.-]+$')
    wallet_address: str = Field(min_length=10,max_length=100)
    blockchain: Literal['Ethereum','Polygon','BNB Chain','Tron','Bitcoin']
    fraud_type: str = Field(min_length=1,max_length=120)
    max_hops: int = Field(default=2,ge=1,le=4)

def checked_address(address, chain):
    try:
        return validate_address(address,chain)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc

@app.post('/cases')
def create_case(case: CaseModel, request: Request, user=Depends(require_user)):
    wallet = checked_address(case.wallet_address,case.blockchain)
    with db() as cur:
        cur.execute('''INSERT INTO ct_cases(case_id,owner_id,wallet_address,blockchain,fraud_type,max_hops)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING case_id''',
            (case.case_id,user['id'],wallet,case.blockchain,case.fraud_type,case.max_hops))
        if not cur.fetchone():
            old = visible_case(cur,case.case_id,user)
            if (old['wallet_address'],old['blockchain'],old['fraud_type'],old['max_hops']) != (wallet,case.blockchain,case.fraud_type,case.max_hops):
                raise HTTPException(409,'Case reference already has different parameters. Use a new reference.')
        audit(cur,user['id'],'case_opened',request,{'case_id':case.case_id})
    return {'status':'success','case_id':case.case_id}

@app.get('/cases')
def cases(user=Depends(require_user), offset: int=0):
    if offset < 0 or offset > 1000000:
        raise HTTPException(400,'Invalid offset')
    with db() as cur:
        cur.execute('SELECT * FROM ct_cases WHERE owner_id=%s OR %s ORDER BY timestamp DESC LIMIT 100 OFFSET %s',
                    (user['id'],user['role']=='admin',offset))
        return cur.fetchall()

class TraceOptions(BaseModel):
    fan_threshold: int = Field(default=5,ge=2,le=50)

@app.post('/cases/{case_id}/trace')
def run_trace(case_id: str, options: TraceOptions, request: Request, user=Depends(require_user)):
    # Session advisory lock is released on connection close, including crashes/exceptions.
    with db() as lock:
        lock.execute('SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired', ('trace:'+user['id'],))
        if not lock.fetchone()['acquired']:
            raise HTTPException(429,'A trace is already running for this investigator')
        case = visible_case(lock,case_id,user)
        with db() as cur:
            audit(cur,user['id'],'trace_started',request,{'case_id':case_id})
        resolver = AttributionResolver(user['id'])
        entity_lookup = resolver.lookup
        try:
            data = trace_fund_flow(case['wallet_address'],case['max_hops'],options.fan_threshold,case['blockchain'],entity_lookup)
            data['attribution_diagnostics'] = resolver.diagnostics
            trace_id = str(uuid.uuid4())
            data.update(trace_id=trace_id,case_id=case_id,fraud_type=case['fraud_type'],investigator=user['username'])
            canonical = json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            sha = hashlib.sha256(canonical.encode()).hexdigest()
            with db() as cur:
                cur.execute('INSERT INTO ct_traces(id,case_id,user_id,payload,sha256) VALUES (%s,%s,%s,%s,%s)',
                    (trace_id,case_id,user['id'],Json(data),sha))
                cur.execute('UPDATE ct_cases SET risk_score=%s,status=%s WHERE case_id=%s', (data['risk_score'],data['status'],case_id))
                audit(cur,user['id'],'trace_saved',request,{'case_id':case_id,'trace_id':trace_id,'sha256':sha,'status':data['status']})
            return {**data,'evidence_sha256':sha}
        except Exception:
            with db() as cur:
                audit(cur,user['id'],'trace_failed',request,{'case_id':case_id})
            raise

@app.get('/cases/{case_id}/traces')
def trace_history(case_id: str,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('SELECT id,created_at,sha256 FROM ct_traces WHERE case_id=%s ORDER BY created_at DESC LIMIT 100',(case_id,))
        return cur.fetchall()

@app.get('/cases/{case_id}/traces/{trace_id}')
def saved_trace(case_id: str,trace_id: str,request: Request,user=Depends(require_user)):
    with db() as cur:
        visible_case(cur,case_id,user)
        cur.execute('SELECT payload,sha256 FROM ct_traces WHERE case_id=%s AND id=%s',(case_id,trace_id))
        row=cur.fetchone()
        if not row:
            raise HTTPException(404,'Trace not found')
        audit(cur,user['id'],'trace_read',request,{'case_id':case_id,'trace_id':trace_id})
        return {**row['payload'],'evidence_sha256':row['sha256']}

@app.get('/stats')
def stats(user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT case_id,risk_score,fraud_type FROM ct_cases WHERE owner_id=%s OR %s',(user['id'],user['role']=='admin'))
        rows=cur.fetchall()
        cur.execute('''SELECT COALESCE(SUM((payload->>'node_count')::int),0) AS n FROM
            (SELECT DISTINCT ON (t.case_id) t.payload FROM ct_traces t JOIN ct_cases c ON c.case_id=t.case_id
            WHERE c.owner_id=%s OR %s ORDER BY t.case_id,t.created_at DESC) latest''',(user['id'],user['role']=='admin'))
        wallets=cur.fetchone()['n']
    distribution={k:{'count':0,'pct':0} for k in ('low','medium','high','critical')}
    types={}
    for row in rows:
        s=row['risk_score']
        if s is not None:
            distribution['critical' if s>=80 else 'high' if s>=50 else 'medium' if s>=20 else 'low']['count']+=1
        types[row['fraud_type']]=types.get(row['fraud_type'],0)+1
    for entry in distribution.values():
        entry['pct']=round(entry['count']/len(rows)*100) if rows else 0
    return dict(active_cases=len(rows),wallets_traced=wallets,high_risk=sum(distribution[k]['count'] for k in ('high','critical')),
        risk_distribution=distribution,unknown_risk=sum(r['risk_score'] is None for r in rows),
        typologies=[{'fraud_type':k,'count':v} for k,v in types.items()])

class EntityModel(BaseModel):
    blockchain: Literal['Ethereum','Polygon','BNB Chain','Tron','Bitcoin']
    wallet_address: str = Field(max_length=100)
    name: str = Field(min_length=1,max_length=120)
    source: str = Field(min_length=5,max_length=500)
    is_vasp: bool=False
    is_mixer: bool=False
    is_sanctioned: bool=False

@app.get('/entities')
def list_entities(q: str='', offset: int=0, user=Depends(require_user)):
    if len(q) > 200 or not 0 <= offset <= 1000000:
        raise HTTPException(400, 'Invalid entity search')
    with db() as cur:
        term = '%'+q+'%'
        cur.execute('SELECT blockchain,wallet_address,name,source,is_vasp,is_mixer,is_sanctioned,updated_at FROM ct_entities WHERE name ILIKE %s OR wallet_address ILIKE %s OR blockchain ILIKE %s ORDER BY blockchain,name,wallet_address LIMIT 100 OFFSET %s', (term,term,term,offset))
        return cur.fetchall()

@app.post('/entities')
def add_entity(body: EntityModel,request: Request,user=Depends(require_admin)):
    wallet=checked_address(body.wallet_address,body.blockchain)
    with db() as cur:
        cur.execute('''INSERT INTO ct_entities(blockchain,wallet_address,name,source,is_vasp,is_mixer,is_sanctioned,updated_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(blockchain,wallet_address) DO UPDATE SET
            name=EXCLUDED.name,source=EXCLUDED.source,is_vasp=EXCLUDED.is_vasp,is_mixer=EXCLUDED.is_mixer,
            is_sanctioned=EXCLUDED.is_sanctioned,updated_by=EXCLUDED.updated_by,updated_at=now()''',
            (body.blockchain,wallet,body.name,body.source,body.is_vasp,body.is_mixer,body.is_sanctioned,user['id']))
        audit(cur,user['id'],'entity_updated',request,body.model_dump())
    return {'status':'saved'}

@app.get('/attribution/status')
def attribution_status(user=Depends(require_user)):
    return source_status()

@app.get('/attribution/cached')
def cached_attributions(user=Depends(require_user)):
    with db() as cur:
        cur.execute("SELECT blockchain,wallet_address,payload,status,checked_at,expires_at FROM ct_online_entities WHERE status IN ('matched','conflict') ORDER BY checked_at DESC LIMIT 100")
        return cur.fetchall()

@app.post('/attribution/refresh')
def refresh_attributions(request: Request,user=Depends(require_admin)):
    result = refresh_sources(force=True)
    with db() as cur:
        audit(cur,user['id'],'attribution_sources_refreshed',request,result)
    return result

@app.get('/health')
def health(user=Depends(require_user)):
    with db() as cur:
        cur.execute('SELECT 1')
    return {'database':'connected','providers':{name:'configured; not live-tested' if os.getenv(key) else 'not configured'
        for name,key in [('Alchemy','ALCHEMY_API_KEY'),('BNB / NodeReal','NODEREAL_API_KEY'),('TronScan','TRONSCAN_API_KEY')]}}

# Serve an explicit public asset allowlist. Never expose .env, source or database files.
@app.get('/')
def index():
    return FileResponse(ROOT/'index.html')

@app.get('/assets/{filename}')
def vendor_asset(filename: str):
    if filename not in ('vis-network.min.js','jspdf.umd.min.js','jspdf.plugin.autotable.min.js','fontawesome.min.css','fa-solid-900.woff2','fa-regular-400.woff2','report-regular.ttf','report-bold.ttf') or not (ROOT/'assets'/filename).is_file():
        raise HTTPException(404,'Asset unavailable; run the vendor setup command')
    return FileResponse(ROOT/'assets'/filename)

@app.get('/{filename}')
def static_file(filename: str):
    if filename not in ('style.css','script.js','events.js','graph-ui.js','reports.js'):
        raise HTTPException(404,'Not found')
    return FileResponse(ROOT/filename)

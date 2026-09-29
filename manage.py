"""Offline administrator commands; credentials never passed on the command line."""
import argparse
import getpass
import uuid
from db import db,init_db,audit
from security import hasher

parser=argparse.ArgumentParser()
sub=parser.add_subparsers(dest='command',required=True)
sub.add_parser('migrate')
sub.add_parser('refresh-attribution')
sub.add_parser('check-deployment')
create=sub.add_parser('create-user')
create.add_argument('username')
create.add_argument('--role',choices=['admin','investigator'],default='investigator')
for action in ('disable-user','reset-password'):
    sub.add_parser(action).add_argument('username')
args=parser.parse_args()
if args.command=='migrate':
    init_db()
    print('Additive migration applied. Legacy cases/entities retained separately.')
elif args.command=='check-deployment':
    import os,json
    checks={}
    with db() as cur:
        for table in ('ct_jobs','ct_watchlists','ct_alerts','ct_event_index','ct_raw_evidence','ct_complaints'):
            cur.execute('SELECT to_regclass(%s) AS name',(table,));checks[table]=bool(cur.fetchone()['name'])
        cur.execute("SELECT count(*) AS n FROM ct_jobs WHERE state='queued' AND created_at<now()-interval '15 minutes'");checks['stale_queued_jobs']=cur.fetchone()['n']
    checks['https_origin']=os.getenv('APP_ORIGIN','').startswith('https://')
    checks['production_mode']=os.getenv('APP_ENV')=='production'
    checks['agency_connector']='pending official access'
    print(json.dumps(checks,indent=2));print('Configuration check only. Run integration/load/security acceptance checks before deployment.')
elif args.command=='refresh-attribution':
    from attribution import refresh_sources
    result=refresh_sources(force=True)
    with db() as cur:
        audit(cur,None,'attribution_sources_refreshed',detail=result)
    print(result)
else:
    import re
    username=args.username.lower()
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}',username):
        raise SystemExit('Username must be 3–64 letters, digits, underscores, periods or hyphens')
    encoded=None
    if args.command in ('create-user','reset-password'):
        pw=getpass.getpass('Password (at least 14 characters): ')
        if not 14<=len(pw)<=256 or pw!=getpass.getpass('Repeat password: '):
            raise SystemExit('Password length or confirmation invalid')
        encoded=hasher.hash(pw)
    with db() as cur:
        if args.command=='create-user':
            uid=str(uuid.uuid4())
            cur.execute('INSERT INTO ct_users(id,username,password_hash,role) VALUES (%s,%s,%s,%s)',(uid,username,encoded,args.role))
        else:
            cur.execute('SELECT id FROM ct_users WHERE username=%s',(username,))
            row=cur.fetchone()
            if not row: raise SystemExit('User not found')
            uid=row['id']
            if args.command=='disable-user':
                cur.execute('UPDATE ct_users SET active=FALSE WHERE id=%s',(uid,))
            else:
                cur.execute('UPDATE ct_users SET password_hash=%s WHERE id=%s',(encoded,uid))
            cur.execute('DELETE FROM ct_sessions WHERE user_id=%s',(uid,))
        audit(cur,uid,args.command,detail={'username':username})
    print('Done')

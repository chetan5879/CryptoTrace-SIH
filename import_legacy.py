"""Import legacy cases only after an administrator explicitly assigns an owner.
Dry run by default. Damaged case-sensitive addresses are reported and skipped.
Unverified legacy entity seeds and inferred old scores are never promoted.
"""
import argparse
from db import db,audit
from ingestion import validate_address

p=argparse.ArgumentParser()
p.add_argument('--owner',required=True)
p.add_argument('--apply',action='store_true')
a=p.parse_args()
with db() as cur:
    cur.execute('SELECT id FROM ct_users WHERE username=%s',(a.owner.lower(),))
    user=cur.fetchone()
    if not user:raise SystemExit('Owner account not found')
    cur.execute("SELECT to_regclass('public.cases') AS relation")
    if not cur.fetchone()['relation']:raise SystemExit('No legacy cases table found')
    cur.execute('SELECT * FROM cases ORDER BY timestamp')
    legacy=cur.fetchall()
    import re
    for c in legacy:
        try:
            wallet=validate_address(c['wallet_address'],c['blockchain'])
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',c['case_id']):raise ValueError('Case reference format requires manual correction')
            if not 1<=c.get('max_hops',2)<=4:raise ValueError('Invalid hop count')
        except (ValueError,TypeError) as exc:
            print(c['case_id'],'SKIPPED:',exc)
            continue
        if a.apply:
            cur.execute('''INSERT INTO ct_cases(case_id,owner_id,wallet_address,blockchain,fraud_type,max_hops,status,timestamp)
                VALUES (%s,%s,%s,%s,%s,%s,'Legacy - retrace required',%s) ON CONFLICT DO NOTHING RETURNING case_id''',
                (c['case_id'],user['id'],wallet,c['blockchain'],c['fraud_type'],c.get('max_hops',2),c['timestamp']))
            print(c['case_id'],'imported' if cur.fetchone() else 'already exists')
        else:print(c['case_id'],'eligible')
    if a.apply:audit(cur,user['id'],'legacy_cases_imported',detail={'owner':a.owner,'legacy_rows':len(legacy)})
print('Legacy table unchanged. Review timestamps: old TIMESTAMP values are interpreted in the database session timezone.')

"""Persistent bounded provider cache and case-authorised evidence access."""
import hashlib
import json
from datetime import datetime,timezone
from psycopg2.extras import Json
from db import db
from ingestion import History,normalize

class IndexedHistory(History):
    def __init__(self,case_id,force=False,**kwargs):
        super().__init__(**kwargs);self.case_id=case_id;self.force=force;self.evidence_refs=[]
    def request(self,method,url,**kwargs):
        payload=super().request(method,url,**kwargs)
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        # Store response data only. URL paths, query credentials and headers are excluded.
        provider='Alchemy' if 'alchemy.com/' in url else 'NodeReal' if 'nodereal.io/' in url else 'TronScan' if 'tronscanapi.com/' in url else 'Mempool.space'
        sha=hashlib.sha256(raw.encode()).hexdigest()
        with db() as cur:
            cur.execute('INSERT INTO ct_raw_evidence(sha256,provider,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(sha,provider,Json(payload)))
            cur.execute('INSERT INTO ct_case_evidence VALUES (%s,%s) ON CONFLICT DO NOTHING',(self.case_id,sha))
        self.evidence_refs.append(sha)
        return payload
    def fetch(self,wallet,chain):
        wallet=normalize(wallet,chain)
        if (chain,wallet) in self.cache:return self.cache[(chain,wallet)]
        with db() as cur:
            cur.execute("SELECT * FROM ct_wallet_cache WHERE blockchain=%s AND wallet_address=%s AND fetched_at>now()-interval '5 minutes'",(chain,wallet));cached=cur.fetchone()
        if cached and not self.force:
            rows=cached['payload'];self.diagnostics.extend([{**d,'cache_hit':True} for d in cached['diagnostics']]);self.evidence_refs.extend(cached['evidence_refs'])
            with db() as cur:
                for sha in cached['evidence_refs']:cur.execute('INSERT INTO ct_case_evidence VALUES (%s,%s) ON CONFLICT DO NOTHING',(self.case_id,sha))
        else:
            start=len(self.diagnostics);estart=len(self.evidence_refs);rows=super().fetch(wallet,chain)
            diags=self.diagnostics[start:]
            # Do not cache failed/partial pages as an exhausted window.
            if diags and all(d['status']=='ok' for d in diags):
                with db() as cur:cur.execute('''INSERT INTO ct_wallet_cache(blockchain,wallet_address,payload,diagnostics,evidence_refs) VALUES (%s,%s,%s,%s,%s)
                  ON CONFLICT(blockchain,wallet_address) DO UPDATE SET payload=EXCLUDED.payload,diagnostics=EXCLUDED.diagnostics,evidence_refs=EXCLUDED.evidence_refs,fetched_at=now()''',
                  (chain,wallet,Json(rows),Json(diags),Json(self.evidence_refs[estart:])))
        with db() as cur:
            for r in rows:
                cur.execute('''INSERT INTO ct_event_index(blockchain,event_id,sender,receiver,tx_hash,asset_id,occurred_at,payload)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(blockchain,event_id) DO UPDATE SET payload=EXCLUDED.payload,occurred_at=EXCLUDED.occurred_at''',
                  (chain,r['id'],r['from'],r['to'],r['hash'],r['asset_id'],r['metadata'].get('blockTimestamp'),Json(r)))
                cur.execute('INSERT INTO ct_case_events VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(self.case_id,chain,r['id']))
        self.cache[(chain,wallet)]=rows
        return rows

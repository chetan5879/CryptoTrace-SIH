"""Public-source address attribution. No remote code execution or ownership inference."""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import requests
import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken
from psycopg2.extras import Json
from db import db, audit
from ingestion import normalize, validate_address

BASE = 'https://raw.githubusercontent.com/graphsense/graphsense-tagpacks/master/packs/'
# Selected reserve disclosures, not exchange token contracts or inferred clusters.
PACKS = tuple('exchange-wallets-'+name+'.yaml' for name in
              ('binance','bitfinexcom','bybit','cryptocom','deribit','huobi','kucoin','okx','swissborg')) + ('tornado_cash.yaml','blender_io.yaml','sinbad_io.yaml')
CHAINS = {'ETH':'Ethereum','BTC':'Bitcoin','TRX':'Tron','BSC':'BNB Chain','BEP20':'BNB Chain','MATIC':'Polygon','POLYGON':'Polygon'}
MAX_BYTES = 256 * 1024


def now():
    return datetime.now(timezone.utc)


def enabled():
    return os.getenv('ONLINE_ATTRIBUTION_ENABLED', 'true').lower() in ('true','1','yes')


def parse_pack(raw, filename):
    """Only explicit chain/address classifications are accepted; YAML includes are rejected."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Source exceeds size limit')
    if any(isinstance(t, (AliasToken, AnchorToken, TagToken)) for t in yaml.scan(raw)):
        raise ValueError('YAML aliases, anchors and custom tags are not accepted')
    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict) or not isinstance(doc.get('tags'), list) or len(doc['tags']) > 5000:
        raise ValueError('Unsupported source schema')
    records, skipped = [], 0
    for tag in doc['tags']:
        if not isinstance(tag, dict):
            skipped += 1
            continue
        item = {**doc, **tag}
        category = item.get('category')
        chain = CHAINS.get(str(item.get('currency', '')).upper())
        # BNB is ambiguous between Beacon/BEP2 and BSC: do not guess.
        if category not in ('exchange','mixing_service') or not chain:
            skipped += 1
            continue
        try:
            address = validate_address(str(item.get('address','')), chain)
        except ValueError:
            skipped += 1
            continue
        name = item.get('label') or item.get('actor')
        source = item.get('source')
        if not isinstance(name, str) or not name.strip() or not isinstance(source, str) or urlparse(source).scheme not in ('https','http'):
            skipped += 1
            continue
        records.append({'blockchain':chain,'wallet_address':address,'name':name.strip()[:120],
            'actor':str(item.get('actor') or name).lower()[:120],
            'source':source[:500], 'source_url':BASE+filename, 'source_date':str(item.get('lastmod') or 'Not supplied'),
            'source_confidence':str(item.get('confidence') or 'unspecified'),
            'is_vasp':category=='exchange','is_mixer':category=='mixing_service','is_sanctioned':False,
            'attribution_status':'external_unreviewed', 'source_sha256':hashlib.sha256(raw).hexdigest()})
    if not records:
        raise ValueError('Source contains no supported attribution records')
    return records, skipped


def fetch_pack(filename, deadline):
    import re
    if filename not in ('tornado_cash.yaml','blender_io.yaml','sinbad_io.yaml') and not re.fullmatch(r'exchange-wallets-[a-z0-9_-]+\.yaml', filename):
        raise ValueError('Unapproved source')
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Refresh budget reached')
    # Fixed endpoints, no redirects, no address queries, no arbitrary URL supplied by a user/feed.
    with requests.get(BASE+filename, timeout=(min(5,remaining),min(20,remaining)), stream=True,
                      allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f'Source HTTP {response.status_code}')
        chunks, size = [], 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() > deadline:
                raise ValueError('Source size/time limit reached')
            chunks.append(chunk)
    raw = b''.join(chunks)
    return parse_pack(raw, filename)


def discover_packs(force=False):
    """Discover new reserve-wallet packs from the approved publisher, without following arbitrary URLs."""
    with db() as cur:
        cur.execute("SELECT * FROM ct_attribution_sources WHERE source_id='catalog'")
        row = cur.fetchone()
    if not force and row and row['retry_after'] > now():
        return tuple(row['payload']) or PACKS
    try:
        import re
        with requests.get('https://api.github.com/repos/graphsense/graphsense-tagpacks/git/trees/master?recursive=1',
                          timeout=5,stream=True,allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError('Catalog unavailable')
            raw = response.raw.read(1024*1024+1, decode_content=True)
            if len(raw)>1024*1024:
                raise ValueError('Catalog too large')
        tree = json.loads(raw)
        if tree.get('truncated') or not isinstance(tree.get('tree'),list):
            raise ValueError('Incomplete catalog')
        names = sorted({t['path'].split('/')[-1] for t in tree['tree']
                        if re.fullmatch(r'packs/exchange-wallets-[a-z0-9_-]+\.yaml', t.get('path',''))
                        and t.get('type')=='blob' and 0<t.get('size',0)<=MAX_BYTES})
        names = ['tornado_cash.yaml','blender_io.yaml','sinbad_io.yaml'] + names[:27]
        if len(names)<2:
            raise ValueError('Empty catalog')
        with db() as cur:
            cur.execute("""INSERT INTO ct_attribution_sources(source_id,payload,fetched_at,retry_after)
                VALUES ('catalog',%s,now(),now()+interval '24 hours') ON CONFLICT(source_id) DO UPDATE SET
                payload=EXCLUDED.payload,fetched_at=EXCLUDED.fetched_at,retry_after=EXCLUDED.retry_after,last_error=NULL""",(Json(names),))
        return tuple(names)
    except (requests.RequestException,ValueError,KeyError,TypeError):
        names = tuple(row['payload']) if row else PACKS
        with db() as cur:
            cur.execute("""INSERT INTO ct_attribution_sources(source_id,payload,retry_after,last_error)
                VALUES ('catalog',%s,now()+interval '10 minutes','Catalog unavailable; using selected packs')
                ON CONFLICT(source_id) DO UPDATE SET retry_after=EXCLUDED.retry_after,last_error=EXCLUDED.last_error""", (Json(names),))
        return names


def refresh_sources(force=False):
    """Persistent daily refresh, one refresh process at a time; failures back off ten minutes."""
    if not enabled():
        return {'status':'disabled'}
    updated = []
    deadline = time.monotonic()+45
    with db() as guard:
        guard.execute("SELECT pg_try_advisory_xact_lock(hashtext('ct-attribution-refresh')) AS acquired")
        if not guard.fetchone()['acquired']:
            return {'status':'refresh_in_progress'}
        packs = discover_packs(force)
        due = []
        for filename in packs:
            with db() as cur:
                cur.execute('SELECT * FROM ct_attribution_sources WHERE source_id=%s', (filename,))
                old = cur.fetchone()
            if force or not old or old['retry_after'] <= now():
                due.append(filename)
        # Independent public files download concurrently; DB mutations stay sequential.
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_pack, name, deadline):name for name in due}
            for future in as_completed(futures):
                filename = futures[future]
                try:
                    rows, skipped = future.result()
                    with db() as cur:
                        cur.execute("""INSERT INTO ct_attribution_sources(source_id,payload,fetched_at,retry_after,last_error,skipped)
                            VALUES (%s,%s,now(),now()+interval '24 hours',NULL,%s)
                            ON CONFLICT(source_id) DO UPDATE SET payload=EXCLUDED.payload,fetched_at=EXCLUDED.fetched_at,
                            retry_after=EXCLUDED.retry_after,last_error=NULL,skipped=EXCLUDED.skipped""", (filename,Json(rows),skipped))
                    updated.append(filename)
                except (requests.RequestException, ValueError, yaml.YAMLError, TimeoutError):
                    with db() as cur:
                        cur.execute("""INSERT INTO ct_attribution_sources(source_id,payload,retry_after,last_error)
                            VALUES (%s,'[]',now()+interval '10 minutes','Source unavailable or schema rejected')
                            ON CONFLICT(source_id) DO UPDATE SET retry_after=EXCLUDED.retry_after,last_error=EXCLUDED.last_error""",(filename,))
    if force or updated:
        with db() as cur:
            cur.execute('UPDATE ct_online_entities SET expires_at=now() WHERE expires_at>now()')
    return {'status':'completed','updated':updated,'packs':packs}


def source_status():
    with db() as cur:
        cur.execute('SELECT source_id,fetched_at,retry_after,last_error,skipped,jsonb_array_length(payload) AS records FROM ct_attribution_sources ORDER BY source_id')
        rows = cur.fetchall()
    return {'enabled':enabled(),'sources':rows,'expected_sources':len(PACKS)}


def choose_match(candidates):
    if not candidates:
        return {}, 'not_found'
    # A conflict never quietly picks the first entity or the most severe category.
    identities = {(c['actor'], c['is_vasp'], c['is_mixer']) for c in candidates}
    if len(identities) > 1:
        return {'attribution_status':'conflict','candidates':candidates}, 'conflict'
    result = dict(candidates[0])
    result['evidence_sources'] = list({json.dumps(c,sort_keys=True):None for c in candidates})
    result['evidence_sources'] = [json.loads(c) for c in result['evidence_sources']]
    return result, 'matched'


class AttributionResolver:
    def __init__(self, user_id):
        self.user_id = user_id
        self.memo = {}
        self.index = None
        self.complete = False
        self.feed_expiry = now()
        self.diagnostics = {'enabled':enabled(),'local_matches':0,'cache_hits':0,'online_matches':0,
                            'not_found':0,'conflicts':0,'unavailable':0,
                            'note':'External labels are unreviewed source claims, not proof of current control or cash-out.'}

    def _load_index(self):
        refresh_sources()
        self.index = {}
        with db() as cur:
            cur.execute('SELECT * FROM ct_attribution_sources')
            feeds = {r['source_id']:r for r in cur.fetchall()}
        packs = tuple(feeds.get('catalog',{}).get('payload',[])) or PACKS
        valid = [r for name,r in feeds.items() if name in packs and r['fetched_at'] and
                 r['fetched_at']+timedelta(hours=24) > now()]
        self.complete = len(valid)==len(packs)
        self.feed_expiry = min((r['fetched_at']+timedelta(hours=24) for r in valid), default=now())
        self.diagnostics['fresh_sources'] = len(valid)
        self.diagnostics['expected_sources'] = len(packs)
        for feed in valid:
            for row in feed['payload']:
                entry = {**row,'fetched_at':feed['fetched_at'].isoformat()}
                self.index.setdefault((row['blockchain'],row['wallet_address']),[]).append(entry)

    def lookup(self, address, chain):
        key = (chain, normalize(address,chain))
        if key in self.memo:
            return self.memo[key]
        with db() as cur:
            cur.execute('SELECT * FROM ct_entities WHERE blockchain=%s AND wallet_address=%s',key)
            local = cur.fetchone()
        if local:
            self.diagnostics['local_matches'] += 1
            result = {**dict(local),'attribution_status':'analyst_reviewed'}
        elif not enabled():
            result = {}
        else:
            with db() as cur:
                cur.execute('SELECT * FROM ct_online_entities WHERE blockchain=%s AND wallet_address=%s AND expires_at>now()',key)
                cached = cur.fetchone()
            if cached:
                self.diagnostics['cache_hits'] += 1
                if cached['status']!='matched':
                    self.diagnostics[{'conflict':'conflicts','not_found':'not_found','unavailable':'unavailable'}[cached['status']]] += 1
                result = dict(cached['payload']) if cached['status']=='matched' else {}
            else:
                if self.index is None:
                    self._load_index()
                payload, status = choose_match(self.index.get(key,[]))
                if status=='not_found' and not self.complete:
                    status = 'unavailable'
                self.diagnostics[{'matched':'online_matches','conflict':'conflicts','not_found':'not_found','unavailable':'unavailable'}[status]] += 1
                expiry = min(now()+timedelta(hours=24),self.feed_expiry) if status in ('matched','conflict','not_found') else now()+timedelta(minutes=10)
                payload['updated_at'] = now().isoformat()
                with db() as cur:
                    cur.execute('''INSERT INTO ct_online_entities(blockchain,wallet_address,payload,status,expires_at)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT(blockchain,wallet_address) DO UPDATE SET
                        payload=EXCLUDED.payload,status=EXCLUDED.status,expires_at=EXCLUDED.expires_at,checked_at=now()''',
                        (*key,Json(payload),status,expiry))
                    if status in ('matched','conflict'):
                        audit(cur,self.user_id,'online_attribution_cached',detail={'blockchain':chain,'wallet_address':key[1],
                              'status':status,'evidence':payload})
                result = payload if status=='matched' else {}
        self.memo[key] = result
        return result

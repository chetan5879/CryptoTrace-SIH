"""Cross-chain candidate correlation and bounded LI.FI provider evidence.
Never equate an exchange deposit with a specific customer withdrawal.
"""
import hashlib,json,os,re
from decimal import Decimal
from datetime import datetime,timezone
import requests
from analytics import ts,dec
from ingestion import validate_address
CHAIN_IDS={'Ethereum':1,'BNB Chain':56,'Polygon':137}

def correlate(events,assets,bridges,limit=200):
    matches=[];bset={(b['blockchain'],b['wallet_address']) for b in bridges}
    amap={(a['blockchain'],a['asset_id']):a['canonical_asset'] for a in assets}
    # Only configured bridge endpoints and explicitly mapped asset identities qualify.
    sends=[e for e in events if (e['chain'],e['to']) in bset]
    receives=[e for e in events if (e['chain'],e['from']) in bset]
    for a in sends:
        asset=amap.get((a['chain'],a['asset_id']));at=ts(a.get('timestamp'));value=dec(a['amount'])
        if not asset or at is None or not value:continue
        for b in receives:
            bt=ts(b.get('timestamp'))
            if a['chain']==b['chain'] or amap.get((b['chain'],b['asset_id']))!=asset or bt is None:continue
            delta=bt-at;ratio=dec(b['amount'])/value
            if 0<=delta<=7200 and Decimal('.95')<=ratio<=Decimal('1.005'):
                matches.append({'kind':'amount_time_candidate','from_chain':a['chain'],'to_chain':b['chain'],
                    'from_address':a['from'],'to_address':b['to'],'sending_tx':a['tx_hash'],'receiving_tx':b['tx_hash'],
                    'event_ids':[a['id'],b['id']],'asset':asset,'seconds':delta,'amount_ratio':str(ratio),
                    'status':'unverified','basis':'Registered bridge endpoints, mapped asset, 0–2h and 95–100.5% amount. Multiple matches may exist.'})
                if len(matches)>=limit:return matches,True
    return matches,False

def parse_lifi(doc,chain,txhash):
    if doc.get('status')!='DONE' or doc.get('substatus')!='COMPLETED':return None
    a=doc.get('sending') or {};b=doc.get('receiving') or {};reverse={v:k for k,v in CHAIN_IDS.items()}
    if str(a.get('txHash','')).lower()!=txhash.lower() or a.get('chainId')!=CHAIN_IDS.get(chain):raise ValueError('Provider source transaction mismatch')
    dest=reverse.get(b.get('chainId'))
    if not dest or dest==chain:return None
    rx=b.get('txHash','')
    if not re.fullmatch(r'0x[0-9a-fA-F]{64}',rx):raise ValueError('Invalid destination hash')
    return dict(kind='bridge_provider_link',status='provider_reported',provider='LI.FI',from_chain=chain,to_chain=dest,
        sending_tx=txhash,receiving_tx=rx,from_address=validate_address(doc.get('fromAddress',''),chain),
        to_address=validate_address(doc.get('toAddress',''),dest),bridge=str(doc.get('tool',''))[:120],
        sending=a,receiving=b,source='https://li.quest/v1/status',fetched_at=datetime.now(timezone.utc).isoformat(),
        basis='LI.FI reports COMPLETED. Not independently verified bridge consensus or ownership.')

def lookup(chain,txhash):
    if chain not in CHAIN_IDS or not re.fullmatch(r'0x[0-9a-fA-F]{64}',txhash):raise ValueError('Supported EVM chain and transaction hash required')
    headers={}
    if os.getenv('LIFI_API_KEY'):headers['x-lifi-api-key']=os.environ['LIFI_API_KEY']
    with requests.get('https://li.quest/v1/status',params={'txHash':txhash,'fromChain':CHAIN_IDS[chain]},headers=headers,timeout=(5,12),allow_redirects=False,stream=True) as r:
        if r.status_code!=200:raise ValueError('Bridge provider unavailable (HTTP '+str(r.status_code)+')')
        raw=b''
        for part in r.iter_content(16384):
            raw+=part
            if len(raw)>1_000_000:raise ValueError('Bridge response exceeded limit')
    doc=json.loads(raw);link=parse_lifi(doc,chain,txhash)
    return link,doc

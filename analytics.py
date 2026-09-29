"""Versioned, evidence-linked triage. Pattern matches are investigative hypotheses."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime
import math

FEATURES = ['incoming_count','outgoing_count','fan_in','fan_out','counterparties','tx_per_hour','mean_interval_seconds','amount_cv','out_in_ratio','rapid_pairs','peel_splits','round_fraction']
FEATURE_VERSION = 'wallet-same-asset-v1'

def ts(value):
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
        return d.timestamp() if d.tzinfo else None
    except (ValueError,TypeError,AttributeError): return None

def dec(value):
    try:
        n=Decimal(str(value))
        return n if n.is_finite() and n>=0 else Decimal(0)
    except InvalidOperation:return Decimal(0)

def extract(data):
    """Separate assets; BTC transaction vertices are not wallets. Missing time is explicit."""
    rows=[]
    for n in data['nodes']:
        if n['id'].startswith(('btc-tx:','btc-script:')):continue
        groups=defaultdict(list)
        for e in data['edges']:
            if n['id'] in (e['from'],e['to']):groups[e['asset_id']].append(e)
        for asset,edges in groups.items():
            incoming=[e for e in edges if e['to']==n['id']]; outgoing=[e for e in edges if e['from']==n['id']]
            times=sorted(t for e in edges if (t:=ts(e.get('timestamp'))) is not None)
            vals=[float(min(dec(e['amount']),Decimal('1e30'))) for e in edges]
            mean=sum(vals)/len(vals);var=sum((v-mean)**2 for v in vals)/len(vals)
            inc=sum((dec(e['amount']) for e in incoming),Decimal(0));out=sum((dec(e['amount']) for e in outgoing),Decimal(0))
            rapid=[]
            for a in incoming:
                at=ts(a.get('timestamp'))
                if at is None:continue
                for b in outgoing:
                    bt=ts(b.get('timestamp'))
                    if bt is not None and 0<=bt-at<86400:rapid.append((a['id'],b['id']))
            # Same-transaction output splits. EVM grouping alone does not establish change ownership.
            splits=defaultdict(list)
            for e in outgoing:splits[e['tx_hash']].append(e)
            peel=sum(1 for es in splits.values() if len(es)==2 and sum(dec(e['amount']) for e in es)>0 and
                     Decimal('.80')<=max(dec(e['amount']) for e in es)/sum(dec(e['amount']) for e in es)<=Decimal('.99'))
            hours=max((times[-1]-times[0])/3600,1) if len(times)>1 else 1
            feat=[len(incoming),len(outgoing),len({e['from'] for e in incoming}),len({e['to'] for e in outgoing}),
                  len({e['from'] for e in incoming}|{e['to'] for e in outgoing}),len(edges)/hours,
                  (times[-1]-times[0])/(len(times)-1) if len(times)>1 else 0,math.sqrt(var)/mean if mean else 0,
                  min(float(out/inc),100) if inc else 0,len(rapid),peel,
                  sum(dec(e['amount'])>0 and dec(e['amount'])%1==0 for e in outgoing)/max(1,len(outgoing))]
            rows.append({'wallet':n['id'],'asset_id':asset,'features':dict(zip(FEATURES,feat)),
                'eligible':len(edges)>=5 and len(times)==len(edges) and n.get('coverage')=='provider_window_exhausted',
                'event_ids':[e['id'] for e in edges], 'rapid_pairs':rapid[:100],
                'span_seconds':times[-1]-times[0] if len(times)>1 else 0})
    return rows

def patterns(data,rows):
    findings=[]
    for r in rows:
        f=r['features']; wallet=r['wallet'];ids=r['event_ids']
        if f['incoming_count'] and f['outgoing_count'] and .95<=f['out_in_ratio']<=1.05 and r['rapid_pairs'] and r['span_seconds']<=86400:
            findings.append(dict(kind='pass_through',wallet=wallet,points=15,event_ids=ids,
                explanation='Observed same-asset outflow is within 5% of inflow with rapid timing; opening balance and fund identity unproven'))
        if f['outgoing_count']>=5 and f['round_fraction']>=.8:
            findings.append(dict(kind='round_amount_pattern',wallet=wallet,points=5,event_ids=ids,
                explanation='At least five outflows, 80% whole-unit amounts; denomination-dependent pattern, not proof of structuring'))
        if f['fan_in']>=10 and f['fan_out']>=10:
            findings.append(dict(kind='potential_service_hub',wallet=wallet,points=0,event_ids=ids,
                explanation='High observed fan-in and fan-out; possible service hub, no exchange name or ownership inferred'))
    # Account-chain peeling candidates: repeated dominant outputs in bounded 24h splits.
    if data['blockchain']!='Bitcoin':
        by_wallet=defaultdict(list)
        for e in data['edges']:
            if ts(e.get('timestamp')) is not None:by_wallet[(e['from'],e['asset_id'])].append(e)
        dominant={}
        for key,es in by_wallet.items():
            if len(es)!=2:continue
            total=sum(dec(e['amount']) for e in es)
            if not total or abs(ts(es[0]['timestamp'])-ts(es[1]['timestamp']))>86400:continue
            big=max(es,key=lambda e:dec(e['amount']))
            if Decimal('.80')<=dec(big['amount'])/total<=Decimal('.99'):dominant[key]=(big,es)
        for key,(big,es) in dominant.items():
            next_split=dominant.get((big['to'],big['asset_id']))
            if next_split and all(0<=ts(e['timestamp'])-ts(big['timestamp'])<=86400 for e in next_split[1]):
                findings.append(dict(kind='peeling_candidate',wallet=key[0],points=15,event_ids=[e['id'] for e in es+next_split[1]],
                    explanation='Two consecutive dominant-output splits of 80–99% in 24h windows; balances and fund continuity unproven'))
    # BTC peeling: use exact previous-output spend links; never assign an input owner to an output.
    outputs=defaultdict(list); spends={}
    for e in data['edges']:
        u=e.get('utxo_details') or {}
        if u.get('kind')=='output':outputs[e['tx_hash']].append(e)
        if u.get('kind')=='input':spends[(u.get('prev_txid'),u.get('prev_vout'))]=e['tx_hash']
    peel={}
    for tx,es in outputs.items():
        total=sum(dec(e['amount']) for e in es)
        if len(es)==2 and total:
            big=max(es,key=lambda e:dec(e['amount']))
            if Decimal('.80')<=dec(big['amount'])/total<=Decimal('.99'):
                peel[tx]=(spends.get((tx,big['utxo_details']['vout'])),es)
    for start in peel:
        path=[];seen=set();cur=start
        while cur in peel and cur not in seen and len(path)<10:
            seen.add(cur);nxt,es=peel[cur];path.extend(e['id'] for e in es);cur=nxt
        if len(seen)>=2:
            touched={e['from'] for e in data['edges'] if e['tx_hash'] in seen and (e.get('utxo_details') or {}).get('kind')=='input'}
            for wallet in touched:
                if not wallet.startswith(('btc-tx:','btc-script:')):
                    findings.append(dict(kind='peeling_chain',wallet=wallet,points=25,event_ids=path,
                        explanation='Repeated 80–99% output splits connected by exact UTXO spends; change ownership remains a hypothesis'))
    # Chronological 3-edge same-asset paths provide layering candidates on account chains.
    if data['blockchain']!='Bitcoin':
        adj=defaultdict(list)
        for e in data['edges']:
            if ts(e.get('timestamp')) is not None:adj[e['from']].append(e)
        count=0
        for a in data['edges']:
            at=ts(a.get('timestamp'))
            if at is None:continue
            for b in adj[a['to']]:
                if b['asset_id']!=a['asset_id'] or not at<=ts(b['timestamp'])<=at+86400:continue
                for c in adj[b['to']]:
                    if c['asset_id']==a['asset_id'] and ts(b['timestamp'])<=ts(c['timestamp'])<=at+86400 and len({a['from'],a['to'],b['to'],c['to']})==4:
                        findings.append(dict(kind='layering_path',wallet=a['to'],points=10,event_ids=[a['id'],b['id'],c['id']],explanation='Three chronological same-asset hops within 24h; continuity of funds unproven'));count+=1
                    if count>=100:break
                if count>=100:break
            if count>=100:break
    return findings

def clusters(data):
    adj=defaultdict(set)
    for e in data['edges']:adj[e['from']].add(e['to']);adj[e['to']].add(e['from'])
    # Shared-neighbour groups, not inferred common ownership.
    groups=defaultdict(list)
    for wallet,neighbors in adj.items():
        if wallet.startswith(('btc-tx:','btc-script:')):continue
        key=tuple(sorted(neighbors))
        if len(key)>=2:groups[key].append(wallet)
    return [dict(members=v,common_counterparties=list(k),basis='Identical observed counterparty sets; common control unproven') for k,v in groups.items() if len(v)>=2][:100]

def enrich(data):
    from ml_engine import infer
    rows=extract(data); findings=patterns(data,rows); ml=infer(rows,data['blockchain'])
    by=defaultdict(list)
    for f in findings:by[f['wallet']].append(f)
    for n in data['nodes']:
        if n['id'].startswith(('btc-tx:','btc-script:')):continue
        base=n.get('risk_score'); parts=[{'rule':'base_rules','points':base or 0}]; kinds=set()
        for f in by[n['id']]:
            if f['kind'] in kinds:continue
            kinds.add(f['kind']);parts.append({'rule':f['kind'],'points':f['points']})
            n['risk_reasons'].append(f["explanation"]+f" (+{f['points']})")
        if n.get('is_mixer') and n.get('attribution_status')=='external_unreviewed':
            parts.append({'rule':'sourced_mixer','points':60})
            n['risk_reasons'].append('Approved-source exact mixer attribution (+60); historical source claim, not proof of crime')
        predictions=[r for r in ml.get('results',[]) if r['wallet']==n['id']]
        n['ml']=predictions or [{'status':ml['status']}]
        if ml.get('fusion_enabled') and any(r.get('anomalous') for r in predictions):
            parts.append({'rule':'isolation_forest','points':10});n['risk_reasons'].append('Validated-reference Isolation Forest outlier (+10); anomaly is not fraud')
        score=sum(p['points'] for p in parts)
        n['risk_score']=min(100,score) if base is not None or score else None
        n['risk_category']=category(n['risk_score']);n['score_components']=parts;n['flags']=list(n['risk_reasons'])
        n['categories']=sorted(kinds|({'mixer'} if n.get('is_mixer') else set())|({'vasp'} if n.get('is_vasp') else set())|({'ml_anomaly'} if any(r.get('anomalous') for r in predictions) else set()))
    scores=[n['risk_score'] for n in data['nodes'] if n.get('risk_score') is not None]
    data.update(risk_score=max(scores) if scores else None,features=rows,patterns=findings,clusters=clusters(data),ml=ml,scoring_version='triage-v3.0; policy weights uncalibrated')
    data['risk_category']=category(data['risk_score'])
    return data

def category(s):return 'UNKNOWN' if s is None else 'CRITICAL' if s>=80 else 'HIGH' if s>=50 else 'MEDIUM' if s>=20 else 'LOW'

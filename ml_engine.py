"""Isolation Forest with transparent feature inputs and reproducible reference fitting.
JSON references only: no executable pickle/joblib models are accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from functools import lru_cache
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from analytics import FEATURES, FEATURE_VERSION

MODEL_PATH=Path(os.getenv('ML_REFERENCE_PATH',str(Path(__file__).with_name('models')/'reference.json')))

def matrix(rows):
    a=np.array([[r['features'][f] for f in FEATURES] for r in rows],dtype=float)
    if a.ndim!=2 or a.shape[1]!=len(FEATURES) or not np.isfinite(a).all() or (a<0).any():raise ValueError('Invalid/nonfinite feature matrix')
    return np.log1p(a)

def fit(rows):return IsolationForest(n_estimators=200,max_samples=min(256,len(rows)),contamination=.05,random_state=42,n_jobs=1).fit(matrix(rows))

@lru_cache(maxsize=4)
def load(path,mtime):
    raw=Path(path).read_bytes()
    if len(raw)>20_000_000:raise ValueError('Reference too large')
    doc=json.loads(raw)
    if doc['feature_version']!=FEATURE_VERSION or doc['sklearn_version']!=sklearn.__version__:raise ValueError('Reference feature/library version mismatch; retrain')
    return doc,{chain:fit(rows) for chain,rows in doc['training'].items()},hashlib.sha256(raw).hexdigest()

def infer(rows,chain):
    eligible=[r for r in rows if r['eligible']]
    if not eligible:return {'status':'insufficient_data','results':[],'fusion_enabled':False,'reason':'Need at least five timestamped events and exhausted provider window per wallet/asset'}
    try:
        if MODEL_PATH.exists():
            doc,models,sha=load(str(MODEL_PATH),MODEL_PATH.stat().st_mtime_ns)
            if chain not in models:return {'status':'no_chain_reference','results':[],'fusion_enabled':False}
            model=models[chain];reference=doc['training'][chain];status='reference_model';fusion=bool(doc.get('enable_fusion',False));version=sha
        else:
            # Exploratory operation is active when enough distinct observed wallets exist.
            if len({r['wallet'] for r in eligible})<20:return {'status':'insufficient_reference','results':[],'fusion_enabled':False,'reason':'No trained reference installed; exploratory fit requires 20 eligible distinct wallets'}
            reference=eligible;model=fit(reference);status='exploratory_same_trace';fusion=False
            version=hashlib.sha256(json.dumps(reference,sort_keys=True).encode()).hexdigest()
        x=matrix(eligible);decisions=model.decision_function(x);scores=-model.score_samples(x);med=np.median(matrix(reference),axis=0)
        results=[]
        for r,v,d,s in zip(eligible,x,decisions,scores):
            strongest=np.argsort(np.abs(v-med))[::-1][:3]
            results.append(dict(wallet=r['wallet'],asset_id=r['asset_id'],anomaly_score=round(float(s),6),decision_function=round(float(d),6),
                anomalous=bool(d<0),status=status,features=r['features'],
                feature_deviations=[{'feature':FEATURES[i],'value':r['features'][FEATURES[i]],'reference_median':round(float(np.expm1(med[i])),6)} for i in strongest]))
        return dict(status=status,results=results,fusion_enabled=fusion,model_sha256=version,feature_version=FEATURE_VERSION,sklearn_version=sklearn.__version__,
            threshold=0,contamination=.05,random_state=42,reference_rows=len(reference),
            interpretation='Anomaly score is not fraud probability. Deviations describe inputs, not causal feature contributions.')
    except (ValueError,KeyError,TypeError,OSError) as e:
        return {'status':'model_unavailable','reason':type(e).__name__,'results':[],'fusion_enabled':False}

def train(train_path,test_path,out,enable_fusion=False):
    training=json.loads(Path(train_path).read_text());testing=json.loads(Path(test_path).read_text())
    if not 100<=len(training)<=100000 or not 30<=len(testing)<=100000:raise ValueError('Need 100–100000 training rows and 30–100000 test rows')
    if {(r['chain'],r['wallet']) for r in training}&{(r['chain'],r['wallet']) for r in testing}:raise ValueError('Training and evaluation wallets must be disjoint')
    if any(not r.get('eligible') or not r.get('source') or not r.get('observed_at') for r in training+testing):raise ValueError('Every row needs eligible=true, source and observed_at')
    from analytics import ts
    train_times=[ts(r['observed_at']) for r in training];test_times=[ts(r['observed_at']) for r in testing]
    if None in train_times+test_times or max(train_times)>=min(test_times):raise ValueError('Evaluation observations must be later than all training observations')
    if any(r.get('label') not in (0,1) for r in testing):raise ValueError('Evaluation requires binary reference labels')
    chains=sorted({r['chain'] for r in training});groups={};metrics={}
    from ingestion import CHAINS
    for chain in chains:
        if chain not in CHAINS:raise ValueError('Unsupported chain')
        tr=[r for r in training if r['chain']==chain];te=[r for r in testing if r['chain']==chain]
        if len(tr)<100 or len(te)<30 or len({r['label'] for r in te})<2:raise ValueError('Each chain needs >=100 train and >=30 eval rows with both labels')
        m=fit(tr);pred=m.predict(matrix(te))==-1;y=np.array([r['label'] for r in te]);tp=int(((y==1)&pred).sum());fp=int(((y==0)&pred).sum());fn=int(((y==1)&~pred).sum());tn=int(((y==0)&~pred).sum())
        metrics[chain]={'tp':tp,'fp':fp,'fn':fn,'tn':tn,'precision':tp/max(1,tp+fp),'recall':tp/max(1,tp+fn),'false_positive_rate':fp/max(1,fp+tn),'evaluation_rows':len(te)};groups[chain]=tr
    if enable_fusion and any(m['precision']<.8 or m['recall']<.5 or m['false_positive_rate']>.1 for m in metrics.values()):raise ValueError('Fusion gate failed: precision>=.80, recall>=.50, FPR<=.10 required per chain')
    doc=dict(feature_version=FEATURE_VERSION,sklearn_version=sklearn.__version__,training=groups,evaluation=metrics,enable_fusion=enable_fusion,
        training_sha256=hashlib.sha256(Path(train_path).read_bytes()).hexdigest(),evaluation_sha256=hashlib.sha256(Path(test_path).read_bytes()).hexdigest(),
        note='Measured on supplied labels. These policy gates do not establish deployment fitness or legal approval.')
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);temp=out.with_suffix('.tmp');temp.write_text(json.dumps(doc,sort_keys=True));temp.replace(out)
    return {k:v for k,v in doc.items() if k!='training'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--train',required=True);p.add_argument('--evaluate',required=True);p.add_argument('--output',default=str(MODEL_PATH));p.add_argument('--enable-fusion',action='store_true');a=p.parse_args()
    print(json.dumps(train(a.train,a.evaluate,a.output,a.enable_fusion),indent=2))

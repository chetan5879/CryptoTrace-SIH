"""Real local renderer + synthetic API, dense graphs, hover actions, navigation and PDF content.
Run with a static server on 127.0.0.1:8765. No real credentials/provider traffic.
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader
out=Path(os.getenv('CT_REVIEW_OUTPUT','/tmp/cryptotrace-v22-review'));out.mkdir(parents=True,exist_ok=True)
root='0x'+'1'*40

def fixture(count):
    nodes=[{'id':root if i==0 else '0x'+f'{i:040x}','type':'reported_wallet' if i==0 else 'wallet','hop':0 if i==0 else 1 if i<35 else 2,'risk_score':None if i%7==0 else (i*13)%100,'risk_reasons':['Synthetic fixture; not a real fraud attribution','Incomplete history' if i%7==0 else 'Same-asset receive/send within 24h (+20); fund continuity unproven']} for i in range(count)]
    nodes[1].update(is_vasp=True,entity_name='Synthetic VASP',entity_source='https://example.org/historical-disclosure',attribution_status='external_unreviewed',attribution_source_date='2022-11-10')
    nodes[2].update(is_mixer=True,entity_name='Synthetic mixer',entity_source='Test fixture only')
    edges=[{'id':f'event-{i}','tx_hash':'0x'+f'{i:064x}','from':root if i<35 else nodes[1+i%34]['id'],'to':nodes[i]['id'],'amount':'1.234500000000000001','asset':'ETH','asset_id':'native:ETH','timestamp':'2026-09-28T08:00:00+00:00','relationship':'observed_transfer','rapid_movement':i%5==0} for i in range(1,count)]
    for i in range(1,min(60,count)):
        edges.append({**edges[i-1],'id':f'extra-{i}','from':nodes[(i+1)%count]['id'],'to':nodes[i]['id']})
    return {'case_id':'CT-DEMO-SYNTHETIC','trace_id':f'synthetic-{count}','wallet_address':root,'blockchain':'Ethereum','fraud_type':'Synthetic demonstration','max_hops':2,'risk_score':85,'status':'partial','coverage_note':'Synthetic demonstration. Partial provider history; absence of flags is not a clean-wallet finding.','scoring_version':'transparent-triage-v2; ML disabled pending evaluation','investigator':'demo-investigator','fetched_at':'2026-09-28T08:00:00+00:00','evidence_sha256':'a'*64,'nodes':nodes,'edges':edges,'node_count':len(nodes),'edge_count':len(edges),'diagnostics':[{'wallet':root,'provider':'Synthetic fixture','category':'outgoing','status':'truncated','message':'Page budget reached in this synthetic demonstration','pages':3,'records':count,'fetched_at':'2026-09-28T08:00:00+00:00'}],'truncated_wallets':[{'wallet':nodes[-1]['id'],'reason':'Synthetic expansion limit'}]}

with sync_playwright() as p:
    browser=p.chromium.launch();context=browser.new_context(viewport={'width':1440,'height':1080},accept_downloads=True);context.grant_permissions(['clipboard-read','clipboard-write']);page=context.new_page();errors=[];failed=[]
    page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:failed.append(r.url) if r.status>=400 else None)
    def mock(route):
        path=route.request.url.split('8765')[-1]
        if path=='/':
            response=route.fetch();return route.fulfill(response=response,headers={**response.headers,'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'"})
        if path=='/auth/me':return route.fulfill(json={'username':'demo','role':'investigator','csrf':'test'})
        if path.startswith('/entities'):return route.fulfill(json=[])
        if path.startswith('/cases'):return route.fulfill(json=[])
        if path=='/stats':return route.fulfill(json={'active_cases':0,'wallets_traced':0,'high_risk':0,'unknown_risk':0,'risk_distribution':{k:{'pct':0,'count':0} for k in ['low','medium','high','critical']}})
        return route.continue_()
    page.route('**/*',mock);page.goto('http://127.0.0.1:8765/');page.locator('body:not(.signed-out)').wait_for()
    page.evaluate('(data)=>addGraphWorkspace(data)',fixture(118))
    # Poll through public read-only evaluation; avoid wait_for_function under the application CSP.
    for _ in range(70):
        if page.evaluate('graphWorkspaces.get(activeGraph).ready'):break
        page.wait_for_timeout(100)
    assert page.evaluate('graphWorkspaces.get(activeGraph).ready')
    assert page.evaluate('graphWorkspaces.get(activeGraph).nodes.get().every(n=>n.label==="" && !n.title)')
    assert page.evaluate('graphWorkspaces.get(activeGraph).edges.get().every(e=>!e.title)')
    assert page.evaluate("nodeColor(currentTraceData.nodes[1])")== '#171b22'
    assert page.evaluate("nodeColor(currentTraceData.nodes[2])")== '#8b542f'
    assert not page.locator('#nodeInspector').is_visible()
    page.locator('#networkGraph').scroll_into_view_if_needed()
    page.screenshot(path=str(out/'graph-desktop.png'),full_page=True)
    # Actual mouse hover, then move from the canvas into the popover and click Copy.
    xy=page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph),p=t.network.canvasToDOM(t.network.getPosition(currentTraceData.wallet_address)),r=t.container.getBoundingClientRect();return {x:r.x+p.x,y:r.y+p.y}})()')
    page.mouse.move(xy['x'],xy['y']);page.locator('#nodeInspector').wait_for();page.locator('#copyAddress').hover();page.click('#copyAddress');expect(page.locator('#copyFeedback')).to_have_text('Copied full address');assert page.evaluate('navigator.clipboard.readText()')==root
    page.screenshot(path=str(out/'graph-hover.png'),full_page=True)
    page.click('#focusNode');assert page.evaluate('graphWorkspaces.get(activeGraph).nodes.get().some(n=>n.hidden)')
    # Report must include hidden nodes, every original edge and its original amount.
    with page.expect_download(timeout=60000) as dl:page.evaluate('generateReport()')
    pdf=out/'CryptoTrace-Dossier-Sample.pdf';dl.value.save_as(str(pdf));reader=PdfReader(pdf);text='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>=6
    assert 'INVESTIGATOR REVIEW DRAFT' in text and 'NCRP COMPLIANT' not in text
    assert 'OBSERVED RELATIONSHIP MAP' in text and 'ANALYST REVIEW & HANDOVER' in text
    assert 'Snapshot SHA-256' in text and 'a'*64 in text.replace('\n','')
    compact=''.join(text.split())
    for n in fixture(118)['nodes']:assert n['id'] in compact,n['id']
    for e in fixture(118)['edges']:assert e['id'] in compact,e['id']
    assert '1.234500000000000001' in compact
    page.click('#focusNode');page.click('#closeNode');assert page.evaluate('graphWorkspaces.get(activeGraph).nodes.get().every(n=>!n.hidden)')
    # Real scroll gestures hit the zoom bounds; programmatic extreme panning exercises the same clamp.
    box=page.locator('#networkGraph').bounding_box();page.mouse.move(box['x']+100,box['y']+100);page.mouse.wheel(0,100000);page.wait_for_timeout(200)
    assert page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph);return t.network.getScale()>=t.minScale-.0001})()')
    page.mouse.wheel(0,-100000);page.wait_for_timeout(200);assert page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph);return t.network.getScale()<=t.maxScale+.0001})()')
    page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph);t.network.moveTo({position:{x:1e8,y:-1e8}});constrainView(t)})()')
    assert page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph),p=t.network.getViewPosition();return Math.abs(p.x)<1e7&&Math.abs(p.y)<1e7})()')
    assert page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph),p=t.network.getViewPosition(),s=t.network.getScale(),w=t.container.clientWidth/s,h=t.container.clientHeight/s;return t.nodes.get().filter(n=>!n.hidden).some(n=>{const q=t.network.getPosition(n.id);return Math.abs(q.x-p.x)<w/2&&Math.abs(q.y-p.y)<h/2})})()')
    page.click('#fitGraph');assert page.evaluate('(()=>{const t=graphWorkspaces.get(activeGraph);return Math.abs(t.network.getScale()-t.fitScale)<.001})()')
    page.click('#minimizeGraph');page.click('#openGraphs');page.click('#fullscreenGraph');page.wait_for_timeout(200);assert page.evaluate('!!document.fullscreenElement||!!document.querySelector(".modal-content.expanded")');page.click('#fullscreenGraph')
    page.evaluate('(data)=>addGraphWorkspace(data)',fixture(500));assert page.evaluate('graphWorkspaces.get(activeGraph).effectiveLayout')=='hops'
    assert page.evaluate('graphWorkspaces.get(activeGraph).nodes.length')==500
    assert page.evaluate('graphWorkspaces.get(activeGraph).edges.length')==558
    distance=page.evaluate('(()=>{const p=Object.values(graphWorkspaces.get(activeGraph).network.getPositions());let d=Infinity;for(let i=0;i<p.length;i++)for(let j=i+1;j<p.length;j++)d=Math.min(d,Math.hypot(p[i].x-p[j].x,p[i].y-p[j].y));return d})()');assert distance>=39,distance
    page.screenshot(path=str(out/'graph-500.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200);page.click('#fitGraph');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.select_option('#nodePicker',root);expect(page.locator('#nodeInspector')).to_be_visible();page.screenshot(path=str(out/'graph-mobile.png'),full_page=True)
    page.click('#closeNode');page.click('#minimizeGraph');page.screenshot(path=str(out/'dashboard-mobile.png'),full_page=True)
    assert not errors,errors;assert not failed,failed
    print(f'PASS: 118/500-node layouts, actual hover/copy, focus preservation, bounded zoom/pan, fit, window controls, mobile inspection, {len(reader.pages)}-page full-data PDF; no JS/asset errors. Output: {out}')
    browser.close()

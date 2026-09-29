"""Browser regression with synthetic API responses; no provider/production credentials."""
import json,threading,functools
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
A='0x'+'1'*40;B='0x'+'2'*40
OV={'scope':'Synthetic review fixture','nodes':[{'id':'Ethereum:'+A,'address':A,'chain':'Ethereum','type':'reported_wallet','risk_score':60,'is_mixer':True,'entity_name':'Synthetic Mixer'},{'id':'Polygon:'+B,'address':B,'chain':'Polygon','type':'wallet','risk_score':20}], 'edges':[], 'links':[{'payload':{'kind':'bridge_provider_link','from_chain':'Ethereum','to_chain':'Polygon','from_address':A,'to_address':B,'status':'provider_reported'}}], 'candidates':[], 'traces':[{'chain':'Ethereum','wallet':A,'ml':{'status':'insufficient_reference'},'patterns':[],'clusters':[],'raw_evidence_refs':['abc']}]}
requests=[]
def respond(route):
    req=route.request;path=req.url.split('/workspace/',1)[-1];requests.append((req.method,path,req.post_data))
    if '/auth/me' in req.url:data={'username':'reviewer','role':'admin','csrf':'token'}
    elif req.url.endswith('/cases'):data=[{'case_id':'CT-TEST','fraud_type':'Synthetic'}]
    elif path.endswith('/overview'):data=OV
    elif '/events?' in path:data=[{'blockchain':'Ethereum','tx_hash':'0x'+'a'*64,'sender':A,'receiver':B,'occurred_at':'2026-01-01T00:00:00Z','payload':{'value':'10','asset':'ETH'}}]
    elif path=='jobs':data=[{'id':'job1','case_id':'CT-TEST','state':'failed','error':'Synthetic failure'}]
    elif path=='alerts':data=[{'id':'alert1','case_id':'CT-TEST','severity':'HIGH','created_at':'2026-01-01','payload':{'trigger':'Synthetic alert'},'acknowledged_at':None}]
    elif path=='watchlists' and req.method=='GET':data=[{'id':'watch1','case_id':'CT-TEST','blockchain':'Ethereum','wallet_address':A,'interval_seconds':600,'baseline_set':True,'enabled':True}]
    elif path=='complaints':data={'case_id':'CT-NEW','jobs':['j']}
    elif path.endswith('/wallets'):data={'job_id':'queued1'}
    elif path=='integration':data={'status':'local_import_export_ready','schema':{}}
    else:data={'status':'saved'}
    route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
handler=functools.partial(SimpleHTTPRequestHandler,directory=str(ROOT));http=ThreadingHTTPServer(('127.0.0.1',0),handler);threading.Thread(target=http.serve_forever,daemon=True).start()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/auth/me',respond);page.route('**/cases',respond);page.route('**/workspace/**',respond)
    page.goto(f'http://127.0.0.1:{http.server_port}/workspace.html');page.wait_for_function("document.querySelector('#identity').textContent.includes('reviewer')")
    page.click('#loadCase');page.wait_for_selector('#graph canvas');page.wait_for_function("document.querySelector('#events').textContent.includes('10 ETH')")
    page.screenshot(path='/tmp/cryptotrace-v3-workspace.png',full_page=True)
    page.fill('#walletAddress',A);page.click('#walletForm button');page.wait_for_function("document.querySelector('#notice').textContent.includes('Queued job')")
    page.click('[data-page="monitor"]');page.click('#refreshMonitor');page.wait_for_function("document.querySelector('#alerts').textContent.includes('HIGH')");page.get_by_role('button',name='Acknowledge',exact=True).click()
    page.click('[data-page="intake"]');page.fill('#newCase','CT-NEW');page.fill('#victim','REF-1');page.fill('#fraud','Synthetic');page.fill('#amount','100');page.fill('#incident','2026-01-01T12:00');page.fill('#intakeWallet',A);page.click('#complaintForm button');page.wait_for_function("document.querySelector('#notice').textContent.includes('Created CT-NEW')")
    page.click('[data-page="jobs"]');page.click('#refreshJobs');page.get_by_role('button',name='Retry',exact=True).click()
    page.set_viewport_size({'width':390,'height':844});page.click('[data-page="cases"]');page.wait_for_timeout(500);page.screenshot(path='/tmp/cryptotrace-v3-mobile.png',full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+2')
    assert not errors,errors
    assert any('acknowledge' in r[1] for r in requests)
    browser.close()
http.shutdown();print('WORKSPACE BROWSER CHECK PASSED')

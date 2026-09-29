"""Run while `python -m http.server 8765 --directory .` serves the project.
Uses synthetic mocked API responses. This is not a real DB/provider integration test.
Requires playwright Python package and Chromium installation.
"""
import json
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

output=Path(tempfile.mkdtemp(prefix='cryptotrace-browser-'))
root='0x'+'1'*40
other='0x'+'2'*40
base={'wallet_address':root,'blockchain':'Ethereum','max_hops':2,'case_id':'CT-TEST','fraud_type':'Test',
 'risk_score':25,'status':'partial','node_count':2,'edge_count':1,'coverage_note':'Partial provider history; not a clean-wallet conclusion.',
 'diagnostics':[{'wallet':root,'provider':'Test','category':'native','status':'truncated','pages':3}],
 'truncated_wallets':[],'fetched_at':'2026-09-26T19:00:00Z','trace_id':'trace-1','investigator':'alice','evidence_sha256':'a'*64,
 'nodes':[{'id':root,'type':'reported_wallet','risk_score':25,'risk_reasons':['Reported wallet'],'hop':0},
          {'id':other,'type':'wallet','risk_score':None,'risk_reasons':['Unexpanded history'],'hop':1}],
 'edges':[{'id':'tx:1','tx_hash':'0xabc','from':root,'to':other,'amount':'1','asset':'ETH','timestamp':'2026-01-01T00:00:00Z'}]}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
    context.grant_permissions(['clipboard-read','clipboard-write'])
    page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def mock(route):
        path=route.request.url.split('8765')[-1]
        if path=='/':
            response=route.fetch()
            return route.fulfill(response=response,headers={**response.headers,'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        if path=='/auth/me':return route.fulfill(status=401,json={'detail':'Sign in required'})
        if path=='/auth/login':return route.fulfill(json={'username':'alice','role':'investigator','csrf':'test'})
        if path=='/auth/logout':return route.fulfill(json={'status':'signed_out'})
        if path.startswith('/cases'):
            if path.endswith('/trace'):return route.fulfill(json=base)
            if route.request.method=='POST':return route.fulfill(json={'status':'success'})
            return route.fulfill(json=[])
        if path=='/stats':return route.fulfill(json={'active_cases':0,'wallets_traced':0,'high_risk':0,'unknown_risk':0,'risk_distribution':{k:{'pct':0,'count':0} for k in ['low','medium','high','critical']}})
        if path.startswith('/audit'):return route.fulfill(json=[{'occurred_at':'2026-09-26T19:00:00Z','username':'alice','action':'login_success','ip':'127.0.0.1','user_agent':'Test browser'}])
        return route.continue_()
    page.route('**/*',mock)
    page.goto('http://127.0.0.1:8765/');page.wait_for_selector('#loginScreen')
    page.fill('#loginUsername','alice');page.fill('#loginPassword','test-password');page.click('#loginForm button')
    page.locator('body:not(.signed-out)').wait_for()
    page.evaluate('openInvestigation()');page.fill('#walletInput',root);page.select_option('#blockchain','Ethereum');page.click('.trace-button')
    page.wait_for_selector('#traceModal.show');page.wait_for_selector('#networkGraph canvas')
    assert page.locator('#coverageBanner').inner_text().startswith('PARTIAL')
    page.evaluate('selectNode(currentTraceData.nodes[0])')
    assert page.locator('#selectedAddress').input_value()==root
    page.click('#copyAddress');page.get_by_text('Copied full address',exact=True).wait_for()
    assert page.evaluate('navigator.clipboard.readText()')==root
    page.click('#minimizeGraph');assert not page.locator('#traceModal').evaluate("e=>e.classList.contains('show')")
    page.click('#openGraphs');page.click('#fullscreenGraph');page.wait_for_timeout(150)
    assert page.evaluate('!!document.fullscreenElement || !!document.querySelector(".modal-content.expanded")')
    page.click('#fullscreenGraph');page.wait_for_timeout(150)
    page.evaluate('(data)=>addGraphWorkspace({...data,trace_id:"trace-2",wallet_address:data.nodes[1].id,case_id:"CT-SECOND"})',base)
    assert page.locator('#graphTabs button').count()==2
    page.locator('#graphTabs button').first.click();page.evaluate('selectNode(currentTraceData.nodes[0])');assert page.locator('#selectedAddress').input_value()==root
    page.evaluate('selectNode(currentTraceData.nodes[1])');page.click('#investigateAddress')
    assert page.locator('#walletInput').input_value()==other
    assert page.locator('#caseId').input_value()==''
    page.click('#openGraphs')
    page.screenshot(path=str(output/'graph-preview.png'),full_page=True)
    with page.expect_download() as dl:page.evaluate('generateReport()')
    assert dl.value.suggested_filename.endswith('_draft.pdf')
    dl.value.save_as(str(output/'test-report.pdf'))
    page.click('#closeGraphTab');assert page.locator('#graphTabs button').count()==1
    page.click('#minimizeGraph');page.click('#auditButton');page.wait_for_selector('#auditRows tr');assert page.locator('#auditRows').inner_text().find('login_success')>=0
    page.click('#closeAudit');page.click('#logoutButton');page.locator('body.signed-out').wait_for()
    assert page.locator('#graphTabs button').count()==0
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'login-preview.png'),full_page=True)
    assert not errors,errors
    print('PASS: login, real graph renderer with CSP, clipboard, partial diagnostics, minimise/reopen, fullscreen, multiple tabs, related investigation, PDF, audit, logout; zero page errors')
    browser.close()

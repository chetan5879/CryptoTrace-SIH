"""Saved-trace navigation and sourced registry UI using synthetic API fixtures."""
import ast
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
# Reuse the smoke fixture without running its browser scenario.
source=Path(__file__).with_name('browser_smoke.py').read_text()
namespace={}
for node in ast.parse(source).body:
    if isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('root','other','base') for t in node.targets):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'fixture','exec'),namespace)
base=namespace['base'];address=namespace['other']
entity={'blockchain':'Ethereum','wallet_address':address,'name':'Synthetic exchange','source':'Fixture only','is_vasp':True,'is_mixer':False,'is_sanctioned':False}
with sync_playwright() as p:
    browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];writes=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def mock(route):
        path=route.request.url.split('8765')[-1]
        if path=='/auth/me':return route.fulfill(json={'username':'admin','role':'admin','csrf':'test'})
        if path.startswith('/cases/CT-TEST/traces/'):return route.fulfill(json=base)
        if path=='/cases/CT-TEST/traces':return route.fulfill(json=[{'id':'trace-1','created_at':'2026-01-01T00:00:00Z'}])
        if path.startswith('/cases'):return route.fulfill(json=[base])
        if path=='/attribution/status':return route.fulfill(json={'enabled':True,'sources':[]})
        if path=='/attribution/cached':return route.fulfill(json=[{'blockchain':'Ethereum','wallet_address':address,'payload':{**entity,'name':'Online fixture exchange','source_date':'2022-11-10'},'status':'matched','expires_at':'2099-01-01T00:00:00Z'}])
        if path=='/attribution/refresh':return route.fulfill(json={'status':'completed'})
        if path.startswith('/entities'):
            if route.request.method=='POST':writes.append(route.request.post_data_json);return route.fulfill(json={'status':'saved'})
            return route.fulfill(json=[entity])
        if path=='/stats':return route.fulfill(json={'active_cases':1,'wallets_traced':2,'high_risk':0,'unknown_risk':0,'typologies':[], 'risk_distribution':{k:{'pct':0,'count':0} for k in ['low','medium','high','critical']}})
        return route.continue_()
    page.route('**/*',mock);page.goto('http://127.0.0.1:8765/');page.locator('body:not(.signed-out)').wait_for()
    assert page.locator('#blockchain').input_value()==''
    page.evaluate("showPage('transactions')");page.select_option('#txCasePicker','CT-TEST');page.select_option('#txTracePicker','trace-1')
    expect(page.locator('#txTable tbody')).to_contain_text('0xabc')
    page.fill('#txSearchFilter',address);assert page.locator('#txTable tbody tr:visible').count()==1
    expect(page.locator('#txContext')).to_contain_text('CT-TEST')
    page.evaluate("showPage('settings')");expect(page.locator('#entityRows')).to_contain_text('Synthetic exchange');page.get_by_role('button',name='Edit',exact=True).click()
    page.locator('#entityForm input[name=name]').fill('Updated synthetic exchange');page.get_by_role('button',name='Save attribution').click()
    expect(page.locator('#entityMessage')).to_contain_text('Attribution saved')
    assert writes[0]['name']=='Updated synthetic exchange' and writes[0]['is_vasp'] is True
    page.click('#onlineStatusButton');expect(page.locator('#onlineEntityRows')).to_contain_text('Online fixture exchange')
    page.get_by_role('button',name='Review label',exact=True).click()
    assert page.locator('#entityForm input[name=name]').input_value()=='Online fixture exchange'
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path='/tmp/ct-registry-mobile.png',full_page=True)
    assert not errors,errors
    browser.close();print('PASS: explicit network selection, saved case/trace transaction loading, full-address filtering, registry edit with sourced attribution.')

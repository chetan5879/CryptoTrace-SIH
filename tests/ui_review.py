"""Visual regression checks against a local static server with synthetic API fixtures."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

out=Path(os.getenv('CT_UI_OUTPUT','/tmp/cryptotrace-ui-review'));out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1527,'height':950},device_scale_factor=1)
    errors=[];failed=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('response',lambda r:failed.append(r.url) if r.status>=400 else None)
    def mock(route):
        path=route.request.url.split('8765')[-1]
        if path=='/':
            response=route.fetch()
            return route.fulfill(response=response,headers={**response.headers,'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'"})
        if path=='/auth/me':return route.fulfill(json={'username':'investigator','role':'investigator','csrf':'test'})
        if path.startswith('/entities'):return route.fulfill(json=[])
        if path.startswith('/cases'):return route.fulfill(json=[])
        if path=='/stats':return route.fulfill(json={'active_cases':0,'wallets_traced':0,'high_risk':0,'unknown_risk':0,'typologies':[], 'risk_distribution':{k:{'pct':0,'count':0} for k in ['low','medium','high','critical']}})
        return route.continue_()
    page.route('**/*',mock)
    page.goto('http://127.0.0.1:8765/');page.locator('body:not(.signed-out)').wait_for()
    page.wait_for_selector('.empty-cell');page.evaluate('document.fonts.ready')
    assert page.evaluate('document.fonts.check(\'900 16px "Font Awesome 6 Free"\')')
    assert page.locator('.logo-box i').evaluate("e=>getComputedStyle(e,'::before').content") not in ('none','normal','""')
    assert page.locator('.workspace-actions>p').first.evaluate('e=>getComputedStyle(e).fontSize')=='14px'
    assert page.locator('#openGraphs').evaluate('e=>getComputedStyle(e).borderRadius')=='8px'
    assert 'gradient' not in page.locator('.risk-circle').evaluate('e=>getComputedStyle(e).backgroundImage')
    page.screenshot(path=str(out/'dashboard.png'),full_page=True)
    page.click('.help-trigger');assert page.locator('#helpDialog').is_visible();page.click('#closeHelp')
    for name in ['investigations','wallets','transactions','alerts','analytics','reports','settings']:
        page.evaluate('(name)=>showPage(name)',name)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),name
        page.screenshot(path=str(out/(name+'.png')),full_page=True)
    page.evaluate("showPage('investigations')")
    page.fill('#walletInput','invalid-address')
    assert page.locator('#walletMismatchError').is_visible()
    page.fill('#walletInput','0x'+'1'*40)
    assert not page.locator('#walletValidationBadge').is_visible()
    page.select_option('#blockchain','Ethereum')
    assert page.locator('#walletValidationBadge').is_visible()
    assert not page.locator('#walletMismatchError').is_visible()
    page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
    for name in ['dashboard','investigations','reports','settings']:
        page.evaluate('(name)=>showPage(name)',name)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),name+' mobile overflow'
        page.screenshot(path=str(out/('mobile-'+name+'.png')),full_page=True)
    page.click('.mobile-menu');expect(page.locator('.sidebar')).to_have_css('transform','matrix(1, 0, 0, 1, 0, 0)');assert page.locator('.sidebar').evaluate('e=>e.getBoundingClientRect().left')>=-1
    # Account for nav transition before measuring mobile navigation.
    assert not errors,errors
    assert not failed,failed
    print('PASS: local icon fonts, typography, styled controls, empty risk ring, all eight pages, mobile overflow, validation, no failed assets or JS errors')
    browser.close()

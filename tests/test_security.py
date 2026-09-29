from contextlib import contextmanager
from unittest.mock import MagicMock,patch
import pytest
from fastapi.testclient import TestClient
import main
import security

client=TestClient(main.app)
ORIGIN={'Origin':'http://127.0.0.1:8000'}
USER={'id':'alice','username':'alice','role':'investigator','csrf':'csrf-token','token_hash':'hash'}

@contextmanager
def fake_db(cur):
    yield cur

@pytest.mark.parametrize('path',['/cases','/stats','/audit','/health','/entities','/attribution/status','/attribution/cached','/cases/private/traces'])
def test_protected_reads_reject_anonymous(path):
    assert client.get(path).status_code==401

@pytest.mark.parametrize('path',['/.env','/schema.sql','/main.py','/security.py','/db.py'])
def test_source_and_secrets_not_served(path):
    assert client.get(path).status_code==404

def test_login_rejects_cross_site():
    response=client.post('/auth/login',json={'username':'alice','password':'password'},headers={'Origin':'https://evil.example'})
    assert response.status_code==403

def test_failed_login_audited_and_generic():
    cur=MagicMock();cur.fetchone.side_effect=[{'n':0},None]
    with patch.object(main,'db',lambda:fake_db(cur)),patch.object(main,'check_password',return_value=False),patch.object(main,'audit') as audit:
        response=client.post('/auth/login',json={'username':'alice','password':'wrong'},headers=ORIGIN)
        assert response.status_code==401
        assert response.json()['detail']=='Invalid username or password'
        assert audit.call_args.args[2]=='login_failed'

def test_login_secure_cookie_and_no_password_returned():
    cur=MagicMock();cur.fetchone.side_effect=[{'n':0},{**USER,'password_hash':'encoded','active':True}]
    with patch.object(main,'db',lambda:fake_db(cur)),patch.object(main,'check_password',return_value=True),patch.object(main,'audit'):
        response=client.post('/auth/login',json={'username':'alice','password':'correct'},headers=ORIGIN)
        assert response.status_code==200
        cookie=response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie and 'secure' in cookie
        assert 'password' not in response.text

def test_throttle_before_password_hashing():
    cur=MagicMock();cur.fetchone.return_value={'n':10}
    with patch.object(main,'db',lambda:fake_db(cur)),patch.object(main,'check_password') as password:
        assert client.post('/auth/login',json={'username':'alice','password':'wrong'},headers=ORIGIN).status_code==429
        password.assert_not_called()

def test_authenticated_write_requires_csrf():
    cur=MagicMock();cur.fetchone.return_value=USER
    with patch.object(security,'db',lambda:fake_db(cur)):
        response=client.post('/auth/logout',headers={**ORIGIN,'Cookie':'ct_session='+'x'*40})
        assert response.status_code==403

def test_expired_or_revoked_session_rejected():
    cur=MagicMock();cur.fetchone.return_value=None
    with patch.object(security,'db',lambda:fake_db(cur)):
        response=client.get('/cases',headers={'Cookie':'ct_session='+'x'*40})
        assert response.status_code==401

def test_other_investigators_case_not_found():
    cur=MagicMock();cur.fetchone.return_value=None
    main.app.dependency_overrides[main.require_user]=lambda:USER
    try:
        with patch.object(main,'db',lambda:fake_db(cur)):
            response=client.get('/cases/bob-case/traces')
            assert response.status_code==404
            assert cur.execute.call_args.args[1]==('bob-case','alice',False)
    finally:main.app.dependency_overrides.clear()

def test_nonadmin_cannot_change_entities():
    cur=MagicMock();cur.fetchone.return_value=USER
    with patch.object(security,'db',lambda:fake_db(cur)):
        response=client.post('/entities',json={'blockchain':'Ethereum','wallet_address':'0x'+'1'*40,'name':'X','source':'Reviewed record'},
            headers={**ORIGIN,'Cookie':'ct_session='+'x'*40,'X-CSRF-Token':'csrf-token'})
        assert response.status_code==403

def test_csp_and_nostore():
    response=client.get('/')
    assert response.status_code==200
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert response.headers['cache-control']=='no-store'
    assert 'allow-origin' not in str(response.headers).lower()

@pytest.mark.parametrize('asset',['fontawesome.min.css','fa-solid-900.woff2','fa-regular-400.woff2','report-regular.ttf','report-bold.ttf'])
def test_local_font_assets_served(asset):
    response=client.get('/assets/'+asset)
    assert response.status_code==200
    assert len(response.content)>1000
    assert response.headers['x-content-type-options']=='nosniff'

@pytest.mark.parametrize('script',['graph-ui.js','reports.js'])
def test_workspace_scripts_served_locally(script):
    response=client.get('/'+script)
    assert response.status_code==200
    assert response.headers['x-content-type-options']=='nosniff'
    assert len(response.content)>1000


def test_nonadmin_cannot_force_online_refresh():
    cur=MagicMock();cur.fetchone.return_value=USER
    with patch.object(security,'db',lambda:fake_db(cur)):
        response=client.post('/attribution/refresh',headers={**ORIGIN,'Cookie':'ct_session='+'x'*40,'X-CSRF-Token':'csrf-token'})
        assert response.status_code==403

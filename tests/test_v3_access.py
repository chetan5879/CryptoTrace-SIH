from unittest.mock import MagicMock,patch
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
import main,security,workspace_api
from workspace_api import Complaint
client=TestClient(main.app)
@contextmanager
def fake(cur):yield cur
USER={'id':'a','username':'alice','role':'investigator','csrf':'csrf','token_hash':'hash'}
@pytest.mark.parametrize('path',['/workspace/jobs','/workspace/watchlists','/workspace/alerts','/workspace/integration','/workspace/cases/x/overview','/workspace/cases/x/export','/workspace/cases/x/events','/workspace/cases/x/evidence/abc'])
def test_private_reads(path):assert client.get(path).status_code==401
@pytest.mark.parametrize('path,body',[('/workspace/registry/assets',{'blockchain':'Ethereum','asset_id':'x','canonical_asset':'x','source':'source'}),('/workspace/registry/bridges',{'blockchain':'Ethereum','wallet_address':'0x'+'1'*40,'name':'bridge','source':'source'})])
def test_registry_requires_admin(path,body):
    cur=MagicMock();cur.fetchone.return_value=USER
    with patch.object(security,'db',lambda:fake(cur)):
        r=client.post(path,json=body,headers={'Origin':'http://127.0.0.1:8000','Cookie':'ct_session='+'x'*40,'X-CSRF-Token':'csrf'})
        assert r.status_code==403
@pytest.mark.parametrize('path',['overview','events','export','evidence/abc'])
def test_case_access_filtered(path):
    cur=MagicMock();cur.fetchone.return_value=None
    main.app.dependency_overrides[security.require_user]=lambda:USER
    try:
        with patch.object(workspace_api,'db',lambda:fake(cur)):
            r=client.get('/workspace/cases/secret/'+path);assert r.status_code==404
            assert cur.execute.call_args.args[1]==('secret','a',False)
    finally:main.app.dependency_overrides.clear()
def test_complaint_schema_and_address():
    body={'case_id':'x','victim_reference':'ref','fraud_type':'test','reported_amount':'1.23','currency':'INR','incident_date':'2026-01-01T00:00:00Z','wallets':[{'blockchain':'Ethereum','wallet_address':'0x'+'1'*40}]}
    assert Complaint(**body).reported_amount.as_tuple().exponent==-2
    body['incident_date']='2026-01-01T00:00:00'
    with pytest.raises(ValueError):Complaint(**body)
def test_missing_agency_connector_does_not_submit():
    from agency_connector import UnconfiguredAgencyConnector
    with pytest.raises(RuntimeError):UnconfiguredAgencyConnector().submit_case({},'x')

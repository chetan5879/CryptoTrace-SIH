'use strict';
let currentTraceData = null;
let signedInUser = null;
let csrfToken = '';
let activeGraph = null;
let selectedNode = null;
let auditOffset = 0;
let caseOffset = 0;
let lastWalletInput = "";
const graphWorkspaces = new Map();
const $ = id => document.getElementById(id);
const shortAddress = value => value.length > 15 ? `${value.slice(0,5)}...${value.slice(-5)}` : value;
const scoreText = value => value === null || value === undefined ? 'Unknown' : `${value}/100`;
function element(tag,text,className) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(className)node.className=className; return node; }
function text(id,value) { if($(id))$(id).textContent=value; }
async function api(path,options={}) {
    const headers={...(options.headers||{})};
    if(options.body) headers['Content-Type']='application/json';
    if(options.method && options.method!=='GET') headers['X-CSRF-Token']=csrfToken;
    const response=await fetch(path,{...options,headers,credentials:'same-origin'});
    const data=await response.json().catch(()=>({}));
    if(!response.ok) {
        if(response.status===401 && path!=='/auth/login') showLogin();
        throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status})`);
    }
    return data;
}
function showLogin() {
    signedInUser=null;csrfToken='';currentTraceData=null;activeGraph=null;selectedNode=null;
    for(const tab of graphWorkspaces.values())disposeGraph(tab);
    graphWorkspaces.clear(); $('graphTabs').replaceChildren();text('graphCount',0);
    document.querySelectorAll('tbody').forEach(n=>n.replaceChildren());$('alertsContainer').replaceChildren();$('coverageDetails').textContent='';$('selectedAddress').value='';$('nodeReasons').textContent='';
    ['dashTotalCases','dashTotalCasesCircle','dashWalletsTraced','dashHighRisk','intelRiskScore','intelTxCount','intelAnomalies','intelVaspLead'].forEach(id=>text(id,'—'));
    $('auditPanel').hidden=true; closeModal();document.body.classList.add('signed-out');
}
function onAuthenticated(user) {
    signedInUser=user;csrfToken=user.csrf;document.body.classList.remove('signed-out');
    document.querySelectorAll('.top-user strong,.user strong').forEach(n=>n.textContent=user.username);
    if($('settingName')){$('settingName').value=user.username;$('settingName').readOnly=true;}
    $('entityForm').hidden=user.role!=='admin';$('onlineRefreshButton').hidden=user.role!=='admin';showPage('dashboard');loadRecentCases();loadDashboardStats();emptyTable($('txTable').querySelector('tbody'),6,'Run an investigation to view observed transfers.');
}
function showPage(pageId,button) {
    const pages=['dashboard','investigations','wallets','transactions','alerts','analytics','reports','settings'];
    button=button||document.querySelectorAll('.menu-item')[pages.indexOf(pageId)];
    document.querySelector('.case-pagination').hidden=!['dashboard','reports'].includes(pageId);
    document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active-page',p.id===pageId));
    document.querySelectorAll('.menu-item').forEach(b=>b.classList.toggle('active',b===button));
    if(pageId==='settings')loadEntities();
    $('sidebar')?.classList.remove('open');document.querySelector('.mobile-menu').setAttribute('aria-expanded','false');
}
function toggleSidebar() {const open=$('sidebar').classList.toggle('open');document.querySelector('.mobile-menu').setAttribute('aria-expanded',String(open));}
function openInvestigation() {closeModal();showPage('investigations',document.querySelectorAll('.menu-item')[1]);$('walletInput').focus();}
function resetInvestigationForm() {
    $('walletInput').value='';$('caseId').value='';$('blockchain').value='';$('hopDepth').value='2';$('fanThreshold').value='5';hideValidationFeedback();
}
function handleGlobalSearch(event) {
    if(event.key==='Enter') {openInvestigation();$('walletInput').value=event.target.value.trim();handleWalletAddressInput();}
}
function detectBlockchain(address) {
    if(/^0x[a-fA-F0-9]{40}$/.test(address))return 'EVM';
    if(/^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(address))return 'Tron';
    if(/^[13][1-9A-HJ-NP-Za-km-z]{25,34}$|^bc1[ac-hj-np-z02-9]{11,87}$/.test(address))return 'Bitcoin';
    return 'Unknown';
}
function handleWalletAddressInput() {
    const address=$('walletInput').value.trim();
    const detected=detectBlockchain(address);
    if(detected==='EVM'&&address!==lastWalletInput)$('blockchain').value='';
    lastWalletInput=address;
    if(['Tron','Bitcoin'].includes(detected))$('blockchain').value=detected;
    validateAddressAndChain();
}
function validateAddressAndChain() {
    const detected=detectBlockchain($('walletInput').value.trim());
    const chain=$('blockchain').value;
    const good=detected===chain||(detected==='EVM'&&['Ethereum','Polygon','BNB Chain'].includes(chain));
    const badge=$('walletValidationBadge');
    const entered=!!$('walletInput').value.trim();
    badge.hidden=!entered||!good;badge.textContent=detected==='EVM'?`EVM format only — verify ${chain} is the incident network`:'Address format matches';
    $('walletMismatchError').hidden=!entered||good;
    text('mismatchMessageText',!chain?'Choose the incident blockchain. An EVM address does not identify its network.':'Address format does not match the selected network.');
    return good;
}
function hideValidationFeedback() {$('walletValidationBadge').hidden=true;$('walletMismatchError').hidden=true;}
async function startTrace() {
    if(!validateAddressAndChain())return alert('Check the address and selected network. Preserve Tron/Bitcoin address casing.');
    if(graphWorkspaces.size>=10)return alert('Close a graph tab before opening another (limit: 10). Saved traces remain in the case history.');
    const button=document.querySelector('.trace-button');
    const caseId=$('caseId').value.trim()||`CT-${crypto.randomUUID()}`;
    const details={case_id:caseId,wallet_address:$('walletInput').value.trim(),blockchain:$('blockchain').value,
        fraud_type:$('fraudType').value,max_hops:Number($('hopDepth').value)};
    button.disabled=true;button.textContent='Retrieving history…';
    try {
        await api('/cases',{method:'POST',body:JSON.stringify(details)});
        const data=await api(`/cases/${encodeURIComponent(caseId)}/trace`,{method:'POST',body:JSON.stringify({fan_threshold:Number($('fanThreshold').value)})});
        addGraphWorkspace(data);loadRecentCases();loadDashboardStats();
    } catch(error) {alert(error.message);}
    finally {button.disabled=false;button.replaceChildren(element('i',undefined,'fa-solid fa-bolt'),document.createTextNode('Execute trace'));}
}
function relatedInvestigation(address,chain) {
    openInvestigation();$('walletInput').value=address;$('blockchain').value=chain;$('caseId').value='';
    handleWalletAddressInput();$('blockchain').value=chain;validateAddressAndChain();
}
function tableRow(values) {const row=element('tr');for(const value of values)row.append(element('td',String(value??'')));return row;}
function emptyTable(body,columns,message){if(body.children.length)return;const row=element('tr');const cell=element('td',message,'empty-cell');cell.colSpan=columns;row.append(cell);body.append(row);}
async function loadRecentCases(){
    try {
        const cases=await api(`/cases?offset=${caseOffset}`);text('casePageLabel',cases.length?`Cases ${caseOffset+1}–${caseOffset+cases.length}`:'No cases yet');$('previousCases').disabled=caseOffset===0;$('nextCases').disabled=cases.length<100;const body=document.querySelector('#dashboard tbody');body.replaceChildren();
        for(const c of cases)body.append(tableRow([c.case_id,shortAddress(c.wallet_address),c.blockchain,c.fraud_type,scoreText(c.risk_score),c.status]));
        emptyTable(body,6,'No investigations yet. Create your first investigation to start the case ledger.');populateReports(cases);populateAlerts(cases);populateTxCases(cases);
    }catch(error){text('loginError',error.message);}
}
async function loadDashboardStats(){
    try {
        const s=await api('/stats');text('dashTotalCases',s.active_cases);text('dashTotalCasesCircle',s.active_cases);text('dashWalletsTraced',s.wallets_traced);text('dashHighRisk',s.high_risk);text('unknownRisk',`Unknown risk: ${s.unknown_risk||0}`);
        const colors={low:'#17a978',medium:'#edb636',high:'#f08239',critical:'#db506c'};
        let position=0;const slices=[];
        for(const k of ['low','medium','high','critical']){
            const count=s.risk_distribution[k].count||0;
            text('pct'+k[0].toUpperCase()+k.slice(1),s.risk_distribution[k].pct+'%');
            const end=position+(s.active_cases?count/s.active_cases*100:0);
            if(end>position)slices.push(`${colors[k]} ${position}% ${end}%`);
            position=end;
        }
        if(position<100)slices.push(`#e6edf3 ${position}% 100%`);
        document.querySelector('.risk-circle').style.background=s.active_cases?`conic-gradient(${slices.join(',')})`:'#e6edf3';
        text('analyticsTotalCases',s.active_cases);text('analyticsCriticalCases',s.high_risk);text('analyticsHopsTracked',s.wallets_traced);
        const container=$('typologyContainer');container.replaceChildren();
        if(!s.typologies?.length)container.append(element('p','No case categories yet. Registered investigations will appear here.'));
        for(const t of s.typologies||[]){
            const pct=s.active_cases?Math.round(t.count/s.active_cases*100):0;
            const row=element('div',undefined,'typology-row');const track=element('div',undefined,'typology-track');const fill=element('b');fill.style.width=pct+'%';track.append(fill);
            row.append(element('span',t.fraud_type),track,element('strong',`${t.count} · ${pct}%`));container.append(row);
        }
    }catch(error){console.error(error.message);}
}
function populateReports(cases){const body=$('reportsTableBody');body.replaceChildren();for(const c of cases){const row=tableRow([c.case_id,shortAddress(c.wallet_address),c.blockchain,scoreText(c.risk_score)]);const cell=element('td');const btn=element('button','Saved traces','small-button');btn.addEventListener('click',()=>openSavedTraces(c));cell.append(btn);row.append(cell);body.append(row);}emptyTable(body,5,'No saved reports yet. Complete an investigation to record a trace.');}
async function openSavedTraces(c){
    try{const traces=await api(`/cases/${encodeURIComponent(c.case_id)}/traces`);if(!traces.length)return alert('No saved traces for this case. Run an investigation first.');
        const body=$('reportsTableBody');const row=element('tr');const cell=element('td');cell.colSpan=5;cell.append(element('strong',`Trace history: ${c.case_id}`));
        for(const t of traces){const btn=element('button',new Date(t.created_at).toLocaleString(),'small-button');btn.addEventListener('click',async()=>{try{addGraphWorkspace(await api(`/cases/${encodeURIComponent(c.case_id)}/traces/${t.id}`));}catch(e){alert(e.message);}});cell.append(btn);}row.append(cell);body.prepend(row);
    }catch(error){alert(error.message);}
}
function populateAlerts(cases){const list=$('alertsContainer');list.replaceChildren();const flagged=cases.filter(c=>c.risk_score>=50);text('sidebarAlertCount',flagged.length);text('topbarAlertCount',flagged.length);if(!flagged.length)list.append(element('p','No high-score cases in the loaded case list. Missing data and unknown scores require review.'));
    for(const c of flagged){const box=element('div',undefined,'alert-card');box.append(element('h3',`${c.case_id} · ${scoreText(c.risk_score)}`),element('p',`${c.blockchain} · ${c.wallet_address}`));const button=element('button','Review saved evidence');button.addEventListener('click',()=>{showPage('reports');openSavedTraces(c);});box.append(button);list.append(box);}}
function updateSecondaryTabs(data){const body=$('txTable')?.querySelector('tbody');if(body){body.replaceChildren();for(const e of data.edges)body.append(tableRow([e.tx_hash,e.from,e.to,`${e.amount} ${e.asset}`,e.timestamp||'Timestamp unavailable',e.rapid_movement?'Rapid Movement':e.utxo_details?`UTXO ${e.utxo_details.kind}: ${JSON.stringify(e.utxo_details)}`:'Observed transfer']));emptyTable(body,6,'No transfers retrieved. Check the graph retrieval diagnostics.');}
    text('txContext',`${data.case_id} · ${data.blockchain} · ${data.edges.length} relationships · ${data.fetched_at||''}`);filterTransactionsTable();
    text('intelRiskScore',scoreText(data.risk_score));text('intelTxCount',data.edge_count);text('intelAnomalies',data.nodes.filter(n=>(n.risk_score||0)>0).length);text('intelVaspLead',data.nodes.find(n=>n.is_vasp||n.type==='exchange')?.entity_name||'None observed');}
function analyzeStandaloneWallet(){const address=$('intelSearchInput').value.trim();relatedInvestigation(address,detectBlockchain(address)==='EVM'?$('blockchain').value:detectBlockchain(address));$('hopDepth').value='1';}
function filterTransactionsTable(){const value=$('txSearchFilter')?.value.toLowerCase()||'';const risk=$('txRiskFilterSelect')?.value||'all';document.querySelectorAll('#txTable tbody tr').forEach(row=>{const rapid=row.textContent.includes('Rapid Movement');row.hidden=!row.textContent.toLowerCase().includes(value)||(risk==='rapid'&&!rapid)||(risk==='standard'&&rapid);});}
function saveInvestigatorSettings(){alert('Account identity is managed by the administrator and is recorded on every saved trace.');}
async function checkSystemDiagnostics(){try{const h=await api('/health');text('diagBackend','Online');text('diagDb',h.database);text('diagAlchemy',h.providers.Alchemy);text('providerDiagnostics',Object.entries(h.providers).map(([k,v])=>`${k}: ${v}`).join('\n')+'\nBitcoin: public Mempool API; no key needed; not live-tested.\nConfiguration checks do not test provider entitlement. Open trace retrieval diagnostics for actual request errors.');}catch(e){alert(e.message);}}
async function showAudit(){try{const rows=await api(`/audit?offset=${auditOffset}`);$('auditRows').replaceChildren();for(const r of rows)$('auditRows').append(tableRow([new Date(r.occurred_at).toLocaleString(),r.username||r.detail?.username||'Unknown',r.action,r.ip,r.user_agent]));$('auditPanel').hidden=false;}catch(e){alert(e.message);}}
function openLatestReport(){generateReport();}
document.addEventListener('DOMContentLoaded',async()=>{
    $('previousCases').addEventListener('click',()=>{caseOffset=Math.max(0,caseOffset-100);loadRecentCases();});
    $('nextCases').addEventListener('click',()=>{caseOffset+=100;loadRecentCases();});
    $('loginForm').addEventListener('submit',async event=>{event.preventDefault();const btn=event.currentTarget.querySelector('button');btn.disabled=true;text('loginError','');try{const user=await api('/auth/login',{method:'POST',body:JSON.stringify({username:$('loginUsername').value,password:$('loginPassword').value})});$('loginPassword').value='';onAuthenticated(user);}catch(e){text('loginError',e.message);}finally{btn.disabled=false;}});
    $('logoutButton').addEventListener('click',async()=>{try{await api('/auth/logout',{method:'POST'});showLogin();}catch(e){alert(e.message);}});
    $('openGraphs').addEventListener('click',()=>activeGraph?activateGraph(activeGraph):alert('Run an investigation to open a graph.'));
    $('fullscreenGraph').addEventListener('click',fullScreenGraph);$('minimizeGraph').addEventListener('click',closeModal);
    $('fitGraph').addEventListener('click',()=>fitGraph());$('newGraph').addEventListener('click',()=>{openInvestigation();$('caseId').value='';});
    $('closeGraphTab').addEventListener('click',closeCurrentGraph);$('copyAddress').addEventListener('click',copySelectedAddress);
    $('investigateAddress').addEventListener('click',()=>selectedNode&&relatedInvestigation(selectedNode.id,currentTraceData.blockchain));
    $('auditButton').addEventListener('click',()=>{auditOffset=0;showAudit();});$('closeAudit').addEventListener('click',()=>$('auditPanel').hidden=true);
    $('nextAudit').addEventListener('click',()=>{auditOffset+=100;showAudit();});$('txSearchFilter')?.addEventListener('input',filterTransactionsTable);
    document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('sidebar').classList.remove('open');document.querySelector('.mobile-menu').setAttribute('aria-expanded','false');if(!document.fullscreenElement)closeModal();}});
    document.addEventListener('click',e=>{if(!e.target.closest('.sidebar,.mobile-menu')){$('sidebar').classList.remove('open');document.querySelector('.mobile-menu').setAttribute('aria-expanded','false');}});
    document.addEventListener('fullscreenchange',()=>setTimeout(()=>graphWorkspaces.get(activeGraph)?.network?.redraw(),50));
    try{onAuthenticated(await api('/auth/me'));}catch{showLogin();}
});

function populateTxCases(cases){
    const picker=$('txCasePicker'),previous=picker.value;picker.replaceChildren(new Option('Select a saved case from the current case page',''));
    for(const c of cases)picker.add(new Option(`${c.case_id} · ${c.blockchain} · ${shortAddress(c.wallet_address)}`,c.case_id));picker.value=previous;
}
let txSelectionVersion=0;
async function chooseTxCase(){
    const version=++txSelectionVersion,caseId=$('txCasePicker').value;
    $('txTracePicker').replaceChildren(new Option('Select a saved trace',''));if(!caseId)return;
    try{const rows=await api(`/cases/${encodeURIComponent(caseId)}/traces`);if(version!==txSelectionVersion)return;
        for(const t of rows)$('txTracePicker').add(new Option(new Date(t.created_at).toLocaleString()+' · '+t.id,t.id));
        text('txContext',rows.length?'Select the retrieval snapshot to load its transactions.':'This case has no saved transfer snapshot. Run a new trace.');
    }catch(e){text('txContext',e.message);}
}
async function chooseTxTrace(){
    const version=++txSelectionVersion,caseId=$('txCasePicker').value,id=$('txTracePicker').value;if(!id)return;
    try{const data=await api(`/cases/${encodeURIComponent(caseId)}/traces/${encodeURIComponent(id)}`);if(version!==txSelectionVersion)return;
        $('txSearchFilter').value='';$('txRiskFilterSelect').value='all';currentTraceData=data;updateSecondaryTabs(data);
    }catch(e){text('txContext',e.message);}
}
async function loadEntities(){
    try{const rows=await api('/entities?q='+encodeURIComponent($('entitySearch').value));const body=$('entityRows');body.replaceChildren();
        for(const e of rows){const row=tableRow([e.blockchain,e.wallet_address,e.name,[e.is_vasp?'VASP':'',e.is_mixer?'Mixer':'',e.is_sanctioned?'Sanctions':''].filter(Boolean).join(', '),e.source]);
            if(signedInUser?.role==='admin'){const cell=element('td'),button=element('button','Edit','small-button');button.addEventListener('click',()=>{for(const key of ['blockchain','wallet_address','name','source'])$('entityForm').elements[key].value=e[key];for(const key of ['is_vasp','is_mixer','is_sanctioned'])$('entityForm').elements[key].checked=e[key];});cell.append(button);row.append(cell);}body.append(row);}
        emptyTable(body,6,'No matching attributions. An administrator can add sourced labels below.');
    }catch(e){text('entityMessage',e.message);}
}
document.addEventListener('DOMContentLoaded',()=>{
    $('txCasePicker').addEventListener('change',chooseTxCase);$('txTracePicker').addEventListener('change',chooseTxTrace);
    $('refreshTxCases').addEventListener('click',loadRecentCases);$('entityRefresh').addEventListener('click',loadEntities);
    $('entityForm').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,body={};
        for(const k of ['blockchain','wallet_address','name','source'])body[k]=form.elements[k].value.trim();for(const k of ['is_vasp','is_mixer','is_sanctioned'])body[k]=form.elements[k].checked;
        try{await api('/entities',{method:'POST',body:JSON.stringify(body)});text('entityMessage','Attribution saved. Run a new trace to apply it; existing evidence snapshots remain unchanged.');loadEntities();}catch(e){text('entityMessage',e.message);}
    });
});

async function showOnlineAttributions(){
    try{
        const [status,rows]=await Promise.all([api('/attribution/status'),api('/attribution/cached')]);
        text('onlineSourceStatus',(status.enabled?'Online lookup enabled':'Online lookup disabled')+'\n'+(status.sources.length?status.sources.map(s=>`${s.source_id}: ${s.records} entries; fetched ${s.fetched_at||'never'}${s.last_error?' · '+s.last_error:''}`).join('\n'):'Sources will be fetched on the first unknown-address lookup.'));
        const body=$('onlineEntityRows');body.replaceChildren();
        for(const entry of rows){const e=entry.payload,expired=new Date(entry.expires_at)<=new Date();
            const row=tableRow([`${entry.blockchain} / ${entry.wallet_address}`,e.name||'Conflicting source labels',`${e.source||'See source conflict'} / ${e.source_date||'Not recorded'}`,`${entry.status} · ${expired?'Expired; recheck needed':'External, unreviewed'}`]);
            const cell=element('td');if(entry.status==='conflict'){const details=element('details');details.append(element('summary','Inspect conflicting sources'),element('pre',JSON.stringify(e.candidates||[],null,2)));cell.append(details);}if(signedInUser?.role==='admin'&&entry.status==='matched'){
                const button=element('button','Review label','small-button');button.addEventListener('click',()=>{
                    const form=$('entityForm');form.elements.blockchain.value=entry.blockchain;form.elements.wallet_address.value=entry.wallet_address;
                    form.elements.name.value=e.name;form.elements.source.value=e.source+' (source date '+e.source_date+')';
                    form.elements.is_vasp.checked=!!e.is_vasp;form.elements.is_mixer.checked=!!e.is_mixer;form.elements.is_sanctioned.checked=false;
                    form.scrollIntoView({behavior:'smooth'});text('entityMessage','Verify the source and current classification, then save to create a reviewed local label.');
                });cell.append(button);
            }row.append(cell);body.append(row);
        }emptyTable(body,5,'No cached matches yet. Run a new trace; unmatched addresses do not imply innocence.');
    }catch(e){text('onlineSourceStatus',e.message+' — if upgrading, run python manage.py migrate with your database migration account.');}
}
document.addEventListener('DOMContentLoaded',()=>{
    $('onlineStatusButton').addEventListener('click',showOnlineAttributions);
    $('onlineRefreshButton').addEventListener('click',async()=>{const b=$('onlineRefreshButton');b.disabled=true;text('onlineSourceStatus','Refreshing public sources…');
        try{await api('/attribution/refresh',{method:'POST'});await showOnlineAttributions();}catch(e){text('onlineSourceStatus',e.message);}finally{b.disabled=false;}
    });
});

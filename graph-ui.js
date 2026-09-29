'use strict';
// View state is separate from the immutable investigation snapshot.
let hoverTimer;
let hoverPinned = false;
let resizeGraphFrame;
const graphPalette = {origin:'#8746b6',unknown:'#8ba0b3',low:'#16a886',medium:'#e5b534',high:'#f18439',critical:'#dc3545',vasp:'#171b22',mixer:'#8b542f'};
function nodeColor(n) {
    if(n.type==='reported_wallet')return graphPalette.origin;
    if(n.is_mixer||n.type==='mixer')return graphPalette.mixer;
    if(n.is_vasp||n.type==='exchange')return graphPalette.vasp;
    return n.risk_score==null?graphPalette.unknown:n.risk_score>=80?graphPalette.critical:n.risk_score>=50?graphPalette.high:n.risk_score>=20?graphPalette.medium:graphPalette.low;
}
function graphPositions(data, mode) {
    const positions={};const groups=new Map();
    for(const n of data.nodes){const h=Number.isFinite(n.hop)?n.hop:1;if(!groups.has(h))groups.set(h,[]);groups.get(h).push(n);}
    let radius=0,bandRight=-300;
    for(const [hop,list] of [...groups].sort((a,b)=>a[0]-b[0])){
        list.sort((a,b)=>a.id.localeCompare(b.id));
        if(mode==='hops'){
            // Wide bands, rather than a single very tall column, preserve usable fit scale.
            const rows=Math.max(1,Math.ceil(Math.sqrt(list.length)*1.4));
            const cols=Math.ceil(list.length/rows);
            const bandWidth=(cols-1)*76;const bandCenter=bandRight+220+bandWidth/2;bandRight=bandCenter+bandWidth/2;
            list.forEach((n,i)=>positions[n.id]={x:bandCenter+(Math.floor(i/rows)-(cols-1)/2)*76,y:((i%rows)-(Math.min(rows,list.length)-1)/2)*76});
        } else if(hop===0&&list.length===1)positions[list[0].id]={x:0,y:0};
        else {radius=Math.max(radius+160,list.length*66/(2*Math.PI));list.forEach((n,i)=>{const angle=2*Math.PI*i/list.length+hop*.17;positions[n.id]={x:Math.cos(angle)*radius,y:Math.sin(angle)*radius};});}
    }
    return positions;
}
function edgeVisuals(data) {
    const groups=new Map();
    for(const e of data.edges){const key=JSON.stringify([e.from,e.to].sort());if(!groups.has(key))groups.set(key,[]);groups.get(key).push(e);}
    const result=[];
    for(const group of groups.values())group.forEach((e,i)=>{
        const canonical=e.from<=e.to;const side=i%2===0;
        const type=(side===canonical)?'curvedCW':'curvedCCW';
        const tooltip=element('div');tooltip.append(element('strong',`${e.amount} ${e.asset}`),element('p',`Transaction: ${e.tx_hash}`),element('p',e.timestamp||'Timestamp unavailable'));
        result.push({id:e.id,from:e.from,to:e.to,arrows:{to:{enabled:true,scaleFactor:.42}},width:1,
            color:{color:'#b5cddd',highlight:'#1976aa',hover:'#1976aa',inherit:false,opacity:.65},
            smooth:{enabled:true,type,roundness:group.length>1?Math.min(.7,.12+Math.floor(i/2)*.08):.09}});
    });return result;
}
function addGraphWorkspace(data) {
    if(graphWorkspaces.has(data.trace_id)){activateGraph(data.trace_id);return;}
    if(graphWorkspaces.size>=10)return alert('Close a graph tab first. Saved traces remain in case history.');
    const container=element('div',undefined,'graph-canvas');container.hidden=true;$('networkGraph').prepend(container);
    const button=element('button',`${data.blockchain} · ${shortAddress(data.wallet_address)}`);button.setAttribute('role','tab');button.title=`${data.case_id} / ${data.wallet_address}`;button.addEventListener('click',()=>activateGraph(data.trace_id));$('graphTabs').append(button);
    const tab={data,container,button,network:null,layout:'auto',ready:false,focusId:null,viewGuard:false};graphWorkspaces.set(data.trace_id,tab);
    if(window.vis){
        tab.nodes=new vis.DataSet(data.nodes.map(n=>({id:n.id,label:'',shape:n.type==='transaction'?'diamond':'dot',size:n.type==='reported_wallet'?22:n.type==='transaction'?11:14,
            color:{background:nodeColor(n),border:'#ffffff',highlight:{background:nodeColor(n),border:'#113f63'},hover:{background:nodeColor(n),border:'#113f63'}},borderWidth:2,shadow:{enabled:data.nodes.length<=150,color:'rgba(25,55,80,.18)',size:7,x:0,y:3}})));
        tab.edges=new vis.DataSet(edgeVisuals(data));
        tab.network=new vis.Network(container,{nodes:tab.nodes,edges:tab.edges},{autoResize:true,layout:{improvedLayout:false,randomSeed:17},physics:false,
            interaction:{hover:true,hoverConnectedEdges:false,selectConnectedEdges:false,zoomSpeed:.3,tooltipDelay:400},nodes:{chosen:false},edges:{selectionWidth:1,hoverWidth:1}});
        tab.network.on('hoverNode',p=>{if(!hoverPinned)showNodeHover(tab,p.node,false);highlightNeighbourhood(tab,p.node);});
        tab.network.on('blurNode',()=>scheduleHoverHide());
        tab.network.on('hoverEdge',p=>{if(!hoverPinned&&$('nodeInspector').hidden)showEdgeHover(tab,p.edge);});
        tab.network.on('blurEdge',()=>scheduleHoverHide());
        tab.network.on('click',p=>{if(p.nodes.length)showNodeHover(tab,p.nodes[0],true);else hideNodeHover();});
        tab.network.on('doubleClick',p=>{const n=data.nodes.find(n=>n.id===p.nodes[0]);if(n&&n.type!=='transaction')relatedInvestigation(n.id,data.blockchain);});
        tab.network.on('zoom',()=>{hideNodeHover();constrainView(tab);});
        tab.network.on('dragStart',()=>hideNodeHover());
        tab.network.on('dragging',()=>constrainView(tab));
        tab.network.on('dragEnd',p=>{if(p.nodes.length){separateNodes(tab);updateViewBounds(tab);}constrainView(tab);});
        tab.resizeObserver=new ResizeObserver(()=>{cancelAnimationFrame(resizeGraphFrame);resizeGraphFrame=requestAnimationFrame(()=>{if(activeGraph===data.trace_id&&tab.ready){updateViewBounds(tab);constrainView(tab);}});});tab.resizeObserver.observe(container);
    }else container.append(element('p','Graph renderer unavailable. Retrieved evidence remains available in the report.'));
    activateGraph(data.trace_id);applyGraphLayout(tab,'auto');
}
function applyGraphLayout(tab,choice) {
    if(!tab?.network)return;
    hideNodeHover();tab.layout=choice;tab.ready=false;
    if(tab.settleHandler)tab.network.off('stabilizationIterationsDone',tab.settleHandler);
    clearTimeout(tab.settleTimer);tab.network.setOptions({physics:false});
    const mode=choice==='auto'?(tab.data.nodes.length>150?'hops':'repulsion'):choice;
    tab.effectiveLayout=mode;
    const positions=graphPositions(tab.data,mode);
    tab.nodes.update(tab.data.nodes.map(n=>({id:n.id,...positions[n.id],fixed:false,physics:true})));
    text('layoutStatus',`${mode==='hops'?'Spaced hop layout':'Repulsive layout'} · ${tab.data.nodes.length} nodes / ${tab.data.edges.length} transfers`);
    const settle=()=>{if(tab.ready)return;clearTimeout(tab.settleTimer);tab.network.setOptions({physics:false});separateNodes(tab);tab.ready=true;fitGraph(tab);};
    if(mode==='repulsion'&&tab.data.nodes.length>1){
        tab.settleHandler=settle;tab.network.once('stabilizationIterationsDone',settle);
        tab.network.setOptions({physics:{enabled:true,solver:'barnesHut',barnesHut:{gravitationalConstant:-7000,centralGravity:.12,springLength:160,springConstant:.035,damping:.35,avoidOverlap:1},maxVelocity:35,minVelocity:.5,stabilization:{enabled:true,iterations:260,updateInterval:50,fit:false}}});
        tab.settleTimer=setTimeout(settle,5000);
    }else settle();
}
function separateNodes(tab) {
    const ids=tab.data.nodes.map(n=>n.id),pos=tab.network.getPositions(ids);
    // A bounded collision pass after physics; no source nodes or edges are removed.
    for(let pass=0;pass<24;pass++){
        let changed=false;
        for(let i=0;i<ids.length;i++)for(let j=i+1;j<ids.length;j++){
            const a=pos[ids[i]],b=pos[ids[j]];let dx=b.x-a.x,dy=b.y-a.y;let d=Math.hypot(dx,dy);
            const gap=(ids[i]===tab.data.wallet_address||ids[j]===tab.data.wallet_address)?52:40;
            if(d>=gap)continue;if(d<.01){dx=1;dy=(j%2?.5:-.5);d=Math.hypot(dx,dy);}const force=(gap-d)/2+.1;
            a.x-=dx/d*force;a.y-=dy/d*force;b.x+=dx/d*force;b.y+=dy/d*force;changed=true;
        }if(!changed)break;
    }
    for(const id of ids)tab.network.moveNode(id,pos[id].x,pos[id].y);
}
function updateViewBounds(tab) {
    if(!tab?.network||!tab.container.clientWidth)return;
    const positions=Object.values(tab.network.getPositions());if(!positions.length)return;
    const xs=positions.map(p=>p.x),ys=positions.map(p=>p.y);
    tab.bounds={left:Math.min(...xs)-35,right:Math.max(...xs)+35,top:Math.min(...ys)-35,bottom:Math.max(...ys)+35};
    const b=tab.bounds,w=tab.container.clientWidth,h=tab.container.clientHeight;
    tab.fitScale=Math.min(1.4,w/(b.right-b.left+100),h/(b.bottom-b.top+100));
    tab.minScale=tab.fitScale*.8;tab.maxScale=Math.max(3,tab.fitScale*2);
}
function constrainView(tab) {
    if(!tab?.ready||tab.viewGuard||!tab.bounds)return;
    const b=tab.bounds,scale=Math.max(tab.minScale,Math.min(tab.maxScale,tab.network.getScale()));
    const p=tab.network.getViewPosition(),w=tab.container.clientWidth/scale,h=tab.container.clientHeight/scale;
    const px=Math.min(w*.4,100/scale),py=Math.min(h*.4,80/scale);
    let x=Math.max(b.left-w/2+px,Math.min(b.right+w/2-px,p.x));
    let y=Math.max(b.top-h/2+py,Math.min(b.bottom+h/2-py,p.y));
    const visible=tab.nodes.get().filter(n=>!n.hidden).map(n=>tab.network.getPosition(n.id));
    if(visible.length&&!visible.some(n=>Math.abs(n.x-x)<=w/2-px&&Math.abs(n.y-y)<=h/2-py)){
        let best=null,distance=Infinity;
        for(const n of visible){const nx=Math.max(n.x-w/2+px,Math.min(n.x+w/2-px,x)),ny=Math.max(n.y-h/2+py,Math.min(n.y+h/2-py,y)),d=(nx-x)**2+(ny-y)**2;if(d<distance){distance=d;best={x:nx,y:ny};}}
        x=best.x;y=best.y;
    }
    if(Math.abs(scale-tab.network.getScale())>1e-6||Math.abs(x-p.x)>.01||Math.abs(y-p.y)>.01){tab.viewGuard=true;tab.network.moveTo({position:{x,y},scale,animation:false});tab.viewGuard=false;}
    if(activeGraph===tab.data.trace_id)text('zoomLevel',`${Math.round(scale/tab.fitScale*100)}% of fit`);
}
function fitGraph(tab=graphWorkspaces.get(activeGraph)) {
    if(!tab?.network)return;updateViewBounds(tab);if(!tab.bounds)return;
    const b=tab.bounds;tab.network.moveTo({position:{x:(b.left+b.right)/2,y:(b.top+b.bottom)/2},scale:tab.fitScale,animation:false});constrainView(tab);
}
function zoomGraph(factor){const tab=graphWorkspaces.get(activeGraph);if(!tab?.ready)return;tab.network.moveTo({scale:Math.max(tab.minScale,Math.min(tab.maxScale,tab.network.getScale()*factor)),animation:false});hideNodeHover();constrainView(tab);}
function highlightNeighbourhood(tab,id) {
    if(tab.highlightId===id)return;tab.highlightId=id;
    tab.edges.update(tab.data.edges.map(e=>({id:e.id,width:!id?1:e.from===id||e.to===id?2:1,color:{color:!id?'#b5cddd':e.from===id||e.to===id?'#2f86b5':'#cfdae4',opacity:!id?.65:e.from===id||e.to===id?.95:.13}})));
}
function setGraphFocus(tab,id) {
    if(!tab)return;tab.focusId=id;
    const keep=new Set(id?[id]:tab.data.nodes.map(n=>n.id));
    if(id)for(const e of tab.data.edges)if(e.from===id||e.to===id){keep.add(e.from);keep.add(e.to);}
    tab.nodes.update(tab.data.nodes.map(n=>({id:n.id,hidden:!keep.has(n.id)})));
    tab.edges.update(tab.data.edges.map(e=>({id:e.id,hidden:!!id&&e.from!==id&&e.to!==id})));
    text('focusStatus',id?`Neighbourhood view: ${keep.size} of ${tab.data.nodes.length} nodes. Reports still include all retrieved records.`:'All retrieved nodes shown');
    $('resetFocus').hidden=!id;
    $('focusNode').setAttribute('aria-pressed',String(!!id));
    $('focusNode').textContent=id?'Focus connections (click to restore)':'Focus connections';
}
function showNodeHover(tab,id,pinned=false) {
    clearTimeout(hoverTimer);const node=tab.data.nodes.find(n=>n.id===id);if(!node)return;
    selectedNode=node;hoverPinned=pinned;
    $('focusNode').hidden=false;$('investigateAddress').hidden=false;
    text('nodeLabel',`${node.type==='transaction'?'UTXO transaction':node.entity_name||'Wallet'} · ${scoreText(node.risk_score)}`);
    $('selectedAddress').value=node.id; text('nodeShortAddress',shortAddress(node.id));
    text('nodeReasons',(node.risk_reasons||[]).join('\n')||'No flags recorded; check retrieval coverage.');
    text('copyFeedback','');$('copyAddress').disabled=false;$('investigateAddress').disabled=['transaction','script'].includes(node.type);
    text('hoverState',pinned?'Pinned inspection · close to dismiss':'Hover inspection · click node to pin');
    const card=$('nodeInspector');card.hidden=false;
    const p=tab.network.canvasToDOM(tab.network.getPosition(id)),w=$('networkGraph').clientWidth,h=$('networkGraph').clientHeight;
    const left=p.x+18+card.offsetWidth<w?p.x+18:p.x-card.offsetWidth-18;
    card.style.left=Math.max(8,Math.min(w-card.offsetWidth-8,left))+'px';card.style.top=Math.max(8,Math.min(h-card.offsetHeight-8,p.y-25))+'px';
}
function selectNode(node){const tab=graphWorkspaces.get(activeGraph);if(node&&tab)showNodeHover(tab,node.id,true);else hideNodeHover();}
function scheduleHoverHide(){if(hoverPinned)return;clearTimeout(hoverTimer);hoverTimer=setTimeout(()=>hideNodeHover(),350);}
function hideNodeHover(){clearTimeout(hoverTimer);hoverPinned=false;selectedNode=null;$('nodeInspector').hidden=true;const tab=graphWorkspaces.get(activeGraph);if(tab)highlightNeighbourhood(tab,null);}
async function copySelectedAddress(){if(!selectedNode)return;const id=selectedNode.id;try{await navigator.clipboard.writeText(id);text('copyFeedback','Copied full address');}catch{$('selectedAddress').focus();$('selectedAddress').select();text('copyFeedback','Press Ctrl+C / Command+C to copy');}}
function activateGraph(id) {
    const tab=graphWorkspaces.get(id);if(!tab)return;hideNodeHover();activeGraph=id;currentTraceData=tab.data;
    for(const [key,item]of graphWorkspaces){item.container.hidden=key!==id;item.button.setAttribute('aria-selected',String(key===id));}
    $('traceModal').classList.add('show');text('graphCount',graphWorkspaces.size);$('graphLayout').value=tab.layout;
    const data=tab.data;text('coverageBanner',`${data.status.toUpperCase().replaceAll('_',' ')} · ${data.coverage_note}`);$('coverageBanner').dataset.status=data.status;
    $('coverageDetails').closest('details').open=['unavailable','partial'].includes(data.status);
    text('coverageDetails',JSON.stringify({fetched_at:data.fetched_at,providers:data.diagnostics,attribution:data.attribution_diagnostics,limits:data.truncated_wallets},null,2));
    const result=document.querySelector('.trace-result');result.replaceChildren();for(const [label,value]of [['Triage score',scoreText(data.risk_score)],['Nodes',data.node_count],['Transfers',data.edge_count],['Case',data.case_id]]){const field=element('div');field.append(element('span',label),element('strong',String(value)));result.append(field);}
    const picker=$('nodePicker');picker.replaceChildren(new Option('Inspect a node (keyboard / touch)',''));for(const n of data.nodes)picker.add(new Option(`${shortAddress(n.id)} · hop ${n.hop}`,n.id));
    let leads=$('graphEntityLeads');if(!leads){leads=element('div');leads.id='graphEntityLeads';document.querySelector('.trace-result').after(leads);}leads.replaceChildren();
    const attributed=data.nodes.filter(n=>n.is_vasp||n.is_mixer||['exchange','mixer'].includes(n.type));
    leads.append(element('p',attributed.length?`${attributed.length} VASP / mixer label matches. Click a lead to inspect its source. These are not confirmed cash-outs.`:'No VASP / mixer labels matched this snapshot. Check the entity registry and retrieval coverage.'));
    if(data.attribution_diagnostics){const a=data.attribution_diagnostics;leads.append(element('p',`Online attribution: ${a.enabled?'enabled':'disabled'} · ${a.online_matches||0} new matches · ${a.cache_hits||0} cache hits · ${a.unavailable||0} unavailable · ${a.conflicts||0} conflicts. External labels require review.`));}
    for(const n of attributed){const button=element('button',`${n.entity_name||n.type} · ${shortAddress(n.id)}`,'small-button');button.addEventListener('click',()=>showNodeHover(tab,n.id,true));leads.append(button);}
    setGraphFocus(tab,tab.focusId);updateSecondaryTabs(data);
    text('layoutStatus',`${tab.effectiveLayout==='hops'?'Spaced hop layout':'Repulsive layout'} · ${data.node_count} nodes / ${data.edge_count} transfers`);
    requestAnimationFrame(()=>{tab.network?.redraw();updateViewBounds(tab);constrainView(tab);});
}
function closeModal(){hideNodeHover();if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});$('traceModal')?.classList.remove('show');}
function syncWindowControls(){const expanded=!!document.fullscreenElement||document.querySelector('#traceModal .modal-content').classList.contains('expanded');$('fullscreenGraph').title=expanded?'Restore window':'Full screen';$('fullscreenGraph').setAttribute('aria-label',$('fullscreenGraph').title);$('fullscreenGraph').firstElementChild.className=expanded?'fa-regular fa-window-restore':'fa-regular fa-square';}
async function fullScreenGraph(){hideNodeHover();const panel=document.querySelector('#traceModal .modal-content');try{if(document.fullscreenElement)await document.exitFullscreen();else if(panel.classList.contains('expanded'))panel.classList.remove('expanded');else await panel.requestFullscreen();}catch{panel.classList.toggle('expanded');}syncWindowControls();requestAnimationFrame(()=>{const tab=graphWorkspaces.get(activeGraph);tab?.network?.redraw();updateViewBounds(tab);constrainView(tab);});}
function disposeGraph(tab){clearTimeout(tab.settleTimer);tab.resizeObserver?.disconnect();tab.network?.destroy();tab.container.remove();tab.button.remove();}
function closeCurrentGraph(){const tab=graphWorkspaces.get(activeGraph);if(!tab)return;hideNodeHover();disposeGraph(tab);graphWorkspaces.delete(activeGraph);text('graphCount',graphWorkspaces.size);const next=graphWorkspaces.keys().next().value;if(next)activateGraph(next);else{activeGraph=null;currentTraceData=null;closeModal();}}
document.addEventListener('DOMContentLoaded',()=>{
    $('nodeInspector').addEventListener('mouseenter',()=>clearTimeout(hoverTimer));$('nodeInspector').addEventListener('mouseleave',scheduleHoverHide);
    $('nodeInspector').addEventListener('focusin',()=>{clearTimeout(hoverTimer);hoverPinned=true;});
    $('closeNode').addEventListener('click',hideNodeHover);
    $('graphLayout').addEventListener('change',e=>applyGraphLayout(graphWorkspaces.get(activeGraph),e.target.value));
    $('zoomIn').addEventListener('click',()=>zoomGraph(1.3));$('zoomOut').addEventListener('click',()=>zoomGraph(1/1.3));
    $('focusNode').addEventListener('click',()=>{const tab=graphWorkspaces.get(activeGraph);if(selectedNode&&tab)setGraphFocus(tab,tab.focusId===selectedNode.id?null:selectedNode.id);});
    $('resetFocus').addEventListener('click',()=>setGraphFocus(graphWorkspaces.get(activeGraph),null));
    $('nodePicker').addEventListener('change',e=>{if(e.target.value){showNodeHover(graphWorkspaces.get(activeGraph),e.target.value,true);$('copyAddress').focus();}});
    document.addEventListener('fullscreenchange',syncWindowControls);
});

function showEdgeHover(tab,id){
    const e=tab.data.edges.find(e=>e.id===id);if(!e)return;
    clearTimeout(hoverTimer);selectedNode={id:e.tx_hash};hoverPinned=false;
    text('hoverState','Observed transaction relationship');text('nodeShortAddress',`${e.amount} ${e.asset}`);
    text('nodeLabel',e.relationship||'Observed transfer');$('selectedAddress').value=e.tx_hash;
    text('nodeReasons',`From: ${e.from}\nTo: ${e.to}\nUTC: ${e.timestamp||'Unavailable'}${e.utxo_details?'\nUTXO: '+JSON.stringify(e.utxo_details):''}`);
    text('copyFeedback','');$('copyAddress').disabled=false;$('focusNode').hidden=true;$('investigateAddress').hidden=true;
    const card=$('nodeInspector');card.hidden=false;card.style.left='12px';card.style.top='12px';
}

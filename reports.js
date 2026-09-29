'use strict';
let reportFontPromise;
let reportBusy=false;
async function loadReportFonts(){
    if(!reportFontPromise)reportFontPromise=Promise.all(['report-regular.ttf','report-bold.ttf'].map(async name=>{
        const response=await fetch('/assets/'+name);if(!response.ok)throw new Error('Local report font is missing. Extract the complete update, including assets/.');
        const bytes=new Uint8Array(await response.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary);
    })).catch(error=>{reportFontPromise=null;throw error;});
    return reportFontPromise;
}
function reportGraphImage(data,tab){
    const canvas=document.createElement('canvas');canvas.width=1600;canvas.height=850;const ctx=canvas.getContext('2d');
    ctx.fillStyle='#f4f9fd';ctx.fillRect(0,0,1600,850);
    const pos=tab?.network&&tab.data.trace_id===data.trace_id?tab.network.getPositions(data.nodes.map(n=>n.id)):graphPositions(data,'hops');
    const all=Object.values(pos);if(!all.length)return canvas.toDataURL('image/png');
    const xs=all.map(p=>p.x),ys=all.map(p=>p.y),left=Math.min(...xs)-40,right=Math.max(...xs)+40,top=Math.min(...ys)-40,bottom=Math.max(...ys)+40;
    const scale=Math.min(1480/(right-left),730/(bottom-top),3);const point=id=>({x:800+(pos[id].x-(left+right)/2)*scale,y:425+(pos[id].y-(top+bottom)/2)*scale});
    ctx.strokeStyle='#a6bfd2';ctx.lineWidth=1.1;
    for(const e of data.edges){if(!pos[e.from]||!pos[e.to])continue;const a=point(e.from),b=point(e.to);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();const angle=Math.atan2(b.y-a.y,b.x-a.x),x=b.x-Math.cos(angle)*9,y=b.y-Math.sin(angle)*9;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-5*Math.cos(angle-.5),y-5*Math.sin(angle-.5));ctx.lineTo(x-5*Math.cos(angle+.5),y-5*Math.sin(angle+.5));ctx.closePath();ctx.fillStyle='#8eacc1';ctx.fill();}
    for(const n of data.nodes){const p=point(n.id);const r=n.type==='reported_wallet'?12:Math.max(3,Math.min(7,7*scale));ctx.beginPath();if(n.type==='transaction'){ctx.moveTo(p.x,p.y-r);ctx.lineTo(p.x+r,p.y);ctx.lineTo(p.x,p.y+r);ctx.lineTo(p.x-r,p.y);ctx.closePath();}else ctx.arc(p.x,p.y,r,0,Math.PI*2);ctx.fillStyle=nodeColor(n);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();}
    return canvas.toDataURL('image/png');
}
async function generateReport(){
    const data=currentTraceData,tab=graphWorkspaces.get(activeGraph);if(!data)return alert('Open a saved trace or run an investigation first.');
    if(!window.jspdf)return alert('Install the local PDF assets first.');if(reportBusy)return;reportBusy=true;
    const buttons=[...document.querySelectorAll('[data-bind-23]')];buttons.forEach(b=>b.disabled=true);
    try{
        const fonts=await loadReportFonts();
        if(tab?.network&&!tab.ready)await new Promise(resolve=>{let attempts=0;const timer=setInterval(()=>{if(tab.ready||++attempts>=60){clearInterval(timer);resolve();}},100);});
        const doc=new window.jspdf.jsPDF({orientation:'landscape',unit:'mm',format:'a4',compress:true});
        doc.addFileToVFS('report-regular.ttf',fonts[0]);doc.addFont('report-regular.ttf','Report','normal');doc.addFileToVFS('report-bold.ttf',fonts[1]);doc.addFont('report-bold.ttf','Report','bold');doc.setFont('Report','normal');
        doc.setProperties({title:`CryptoTrace dossier - ${data.case_id}`,subject:'Automated investigation draft for analyst review',author:'CryptoTrace',creator:'CryptoTrace 3.0.0'});
        const W=297,H=210,M=17,C={navy:[14,43,66],blue:[12,112,171],muted:[93,115,134],line:[215,229,238],paper:[243,248,252]};
        let section='CASE OVERVIEW',y=42;const pageSections={1:section};const generated=new Date().toISOString();
        const str=value=>String(value??'Not recorded').replace(/\u2011/g,'-');
        const newPage=title=>{doc.addPage('a4','landscape');section=title;pageSections[doc.internal.getNumberOfPages()]=title;y=43;};
        const paragraph=(value,size=9,color=C.muted)=>{doc.setFont('Report','normal');doc.setFontSize(size);doc.setTextColor(...color);const lines=doc.splitTextToSize(str(value),W-2*M);for(const line of lines){if(y>184)newPage(section);doc.text(line,M,y);y+=size*.46;}y+=4;};
        const heading=value=>{if(y>174)newPage(section);doc.setFont('Report','bold');doc.setFontSize(12);doc.setTextColor(...C.navy);doc.text(value,M,y);y+=8;};
        const table=(head,body,options={})=>{doc.autoTable({startY:y,head:[head],body:body.length?body:[head.map((_,i)=>i?'':'No records retrieved')],theme:'grid',margin:{left:M,right:M,top:42,bottom:22},
            styles:{font:'Report',fontSize:8,cellPadding:2.4,textColor:C.navy,lineColor:C.line,lineWidth:.15,overflow:'linebreak'},headStyles:{fillColor:C.blue,textColor:[255,255,255],fontStyle:'bold',fontSize:8},alternateRowStyles:{fillColor:C.paper},rowPageBreak:'avoid',
            didDrawPage:()=>{pageSections[doc.internal.getCurrentPageInfo().pageNumber]=section;},...options});y=doc.lastAutoTable.finalY+8;};
        const metrics=[['MAXIMUM NODE SCORE',scoreText(data.risk_score)],['OBSERVED NODES',str(data.node_count)],['TRANSFER RELATIONSHIPS',str(data.edge_count)],['RETRIEVAL STATUS',str(data.status).replaceAll('_',' ').toUpperCase()]];
        metrics.forEach(([label,value],i)=>{const x=M+i*67;doc.setFillColor(...C.paper);doc.setDrawColor(...C.line);doc.roundedRect(x,40,62,24,2,2,'FD');doc.setTextColor(...C.muted);doc.setFontSize(7);doc.text(label,x+4,47);doc.setFont('Report','bold');doc.setFontSize(14);doc.setTextColor(...C.navy);doc.text(value,x+4,57);doc.setFont('Report','normal');});
        y=71;table(['CASE FIELD','RECORDED VALUE'],[
            ['Case / network',`${data.case_id} / ${data.blockchain} mainnet`],['Reported address',data.wallet_address],['Category / requested depth',`${data.fraud_type||'Not recorded'} / ${data.max_hops} hops`],['Retrieved at (UTC)',data.fetched_at],['Recorded investigator / trace ID',`${data.investigator||'Not recorded'} / ${data.trace_id}`],['Snapshot SHA-256',data.evidence_sha256||'Not recorded']
        ],{columnStyles:{0:{cellWidth:54,fontStyle:'bold'},1:{cellWidth:209}},styles:{font:'Report',fontSize:8.5,cellPadding:2.6,lineColor:C.line,lineWidth:.15,textColor:C.navy}});
        paragraph('Prepared for investigator review. This dossier is not an NCRP approval, a legal certificate, or proof of wallet ownership. The case reference is application-entered and is not verified against NCRP.',8);
        paragraph(`Coverage: ${data.coverage_note}`,8);
        newPage('OBSERVED RELATIONSHIP MAP');
        doc.addImage(reportGraphImage(data,tab),'PNG',M,43,263,139.7);
        y=189;doc.setFontSize(7);doc.setTextColor(...C.muted);doc.text('Full retrieved graph • Purple: reported • Green: 0–19 • Yellow: 20–49 • Orange: 50–79 • Red: 80–100 • Grey: unknown • Black: VASP • Brown: mixer',M,y);
        doc.text('Overview only: parallel transfers share paths in this image. Exact addresses and individual events follow in the ledgers. Funds continuity is not established.',M,y+4);
        newPage('VASP & MIXER LEADS');
        paragraph('Sourced address labels are investigative leads, not proof of fiat conversion, customer identity or common ownership. Incoming-only exchange contact is not a downstream off-ramp. Absence of labels can mean an incomplete registry or retrieval.',8);
        table(['ENTITY / ROLE','ADDRESS','OBSERVED RELATIONSHIPS','SOURCE / REVIEW DATE'],data.nodes.filter(n=>n.is_vasp||n.is_mixer||['exchange','mixer'].includes(n.type)).map(n=>[`${n.entity_name||'Unnamed'} / ${n.is_mixer||n.type==='mixer'?'Mixer':'VASP'}`,n.id,`${data.edges.filter(e=>e.to===n.id).length} incoming; ${data.edges.filter(e=>e.from===n.id).length} outgoing in this graph. ${n.id===data.wallet_address?'Reported origin.':''}`,`${n.entity_source||'Not recorded in this snapshot'} / ${n.entity_updated_at||'Not recorded'} / ${n.attribution_status||'Legacy label; review source'} / Source date: ${n.attribution_source_date||'Not recorded'}`]),{columnStyles:{0:{cellWidth:45},1:{cellWidth:75},2:{cellWidth:63},3:{cellWidth:80}}});
        newPage('WALLET & ENTITY REGISTER');
        paragraph('This register maps each graph node to its address, role, attribution and reasons. Full addresses, observed hop distance and recorded reasons. Unknown scores are not zero. Exchange labels identify leads and do not establish innocence.',8);
        table(['HOP','ADDRESS / IDENTIFIER','ROLE / ENTITY','SCORE','RECORDED REASONS'],data.nodes.map(n=>[n.hop,n.id,`${str(n.type).replaceAll('_',' ')}${n.entity_name?' / '+n.entity_name:''}`,scoreText(n.risk_score),(n.risk_reasons||[]).join('; ')||'No recorded reasons']),{columnStyles:{0:{cellWidth:12},1:{cellWidth:74},2:{cellWidth:39},3:{cellWidth:20},4:{cellWidth:118}}});
        newPage('PATTERNS AND MACHINE LEARNING');
        paragraph('Scores are triage policy weights, not calibrated fraud probabilities. Unreviewed exact mixer matches from approved sources contribute 60 points once. Historical labels require source-date review.',8);
        table(['PATTERN','WALLET','EVIDENCE EVENTS','INTERPRETATION'],(data.patterns||[]).map(p=>[p.kind,p.wallet,(p.event_ids||[]).join('\n'),p.explanation]));
        paragraph('ML status: '+(data.ml?.status||'Not recorded')+'; fusion enabled: '+Boolean(data.ml?.fusion_enabled),8);
        if(data.ml?.model_sha256)paragraph('Model/reference SHA-256: '+data.ml.model_sha256,8);
        paragraph(data.ml?.interpretation||data.ml?.reason||'See the saved snapshot for features and model metadata.',8);
        table(['WALLET / ASSET','ANOMALY SCORE','DECISION','INPUT DEVIATIONS'],(data.ml?.results||[]).map(r=>[r.wallet+' / '+r.asset_id,r.anomaly_score,r.anomalous?'Anomalous':'Not flagged',JSON.stringify(r.feature_deviations)]));
        paragraph('Raw source evidence references: '+(data.raw_evidence_refs||[]).join(', '),8);
        newPage('RETRIEVAL COVERAGE & LIMITS');
        if(data.attribution_diagnostics)paragraph('Online attribution coverage: '+JSON.stringify(data.attribution_diagnostics),8);
        paragraph(`Scoring version: ${data.scoring_version||'Not recorded in this snapshot'}`,8);
        paragraph('Provider exhaustion covers only the supported windows retrieved under the configured bounds. It does not certify complete blockchain history. Pages and records below are provider retrieval counters, not unique graph counts.',8);
        table(['PROVIDER / CATEGORY','WALLET','STATUS / MESSAGE','PAGES / RECORDS','FETCHED AT (UTC)'],(data.diagnostics||[]).map(d=>[`${d.provider} / ${d.category}`,d.wallet,`${d.status}${d.message?': '+d.message:''}${d.scope_note?' / '+d.scope_note:''}${d.skipped_records?' / Skipped records: '+d.skipped_records:''}`,`${d.pages??'—'} / ${d.records??'—'}`,d.fetched_at||data.fetched_at]),{columnStyles:{0:{cellWidth:40},1:{cellWidth:65},2:{cellWidth:91},3:{cellWidth:25},4:{cellWidth:42}}});
        if(data.truncated_wallets?.length){heading('Expansion limits reached');table(['WALLET','REASON'],data.truncated_wallets.map(t=>[t.wallet,t.reason]),{columnStyles:{0:{cellWidth:85},1:{cellWidth:178}}});}
        newPage('OBSERVED TRANSFER LEDGER');
        paragraph('Amounts retain their original assets; no cross-asset total is implied. Bitcoin rows represent UTXO relationships and must not be read as a one-to-one input-to-output payment.',8);
        table(['TRANSACTION / EVENT','FROM','TO','AMOUNT / ASSET','UTC / RELATIONSHIP'],data.edges.map(e=>[`${e.tx_hash}\nEvent: ${e.id}`,e.from,e.to,`${e.amount} ${e.asset}\nAsset ID: ${e.asset_id||'Not recorded'}`,`${e.timestamp||'Timestamp unavailable'}\n${e.relationship||'observed_transfer'}${e.rapid_movement?'\nRapid same-asset timing indicator':''}${e.utxo_details?'\nUTXO: '+JSON.stringify(e.utxo_details):''}`]),{styles:{font:'Report',fontSize:7,cellPadding:2.2,lineWidth:.15,lineColor:C.line,textColor:C.navy},columnStyles:{0:{cellWidth:64},1:{cellWidth:51},2:{cellWidth:51},3:{cellWidth:51},4:{cellWidth:46}}});
        newPage('ANALYST REVIEW & HANDOVER');
        heading('Interpretation and verification');
        paragraph('Review the originating complaint, reconcile significant transfers with independent chain records, and verify entity-label sources and dates before making an attribution. A high score is a triage signal; a low or unknown score does not clear an address. Graph connections do not prove common control or that the same stolen funds moved.');
        heading('Integrity and provenance');
        paragraph('The SHA-256 printed on the case overview identifies the canonical saved trace payload before the response-only evidence_sha256 field is added. It is not the hash of this PDF, a digital signature, an independent timestamp or a complete chain of custody. Browser-generated exports can be modified; retain the trusted stored snapshot and controlled source evidence separately.');
        paragraph(`Dossier generated (UTC): ${generated}. Report renderer: CryptoTrace 3.0.0. API keys, passwords and login-session tokens are not included.`,8);
        heading('Review worksheet - complete outside the application');
        table(['REVIEW FIELD','TO BE COMPLETED BY THE RESPONSIBLE OFFICER'],[['Official complaint / FIR linkage',''],['Independent verification references / exhibits',''],['Source evidence preservation / custody reference',''],['Analyst name, designation, signature and date',''],['Reviewer name, designation, signature and date','']],{columnStyles:{0:{cellWidth:90},1:{cellWidth:173}}});
        paragraph('This worksheet is not the statutory electronic-evidence certificate. Where applicable, the responsible parties and expert must address section 63 and the Schedule of the Bharatiya Sakshya Adhiniyam, 2023, with agency/legal guidance. No signatures or official approval are generated by CryptoTrace.',8);
        for(let p=1;p<=doc.internal.getNumberOfPages();p++){
            doc.setPage(p);doc.setFillColor(...C.navy);doc.rect(0,0,W,31,'F');doc.setFillColor(...C.blue);doc.rect(0,31,W,1.4,'F');
            doc.setTextColor(255,255,255);doc.setFont('Report','bold');doc.setFontSize(17);doc.text('CRYPTOTRACE',M,13);doc.setFontSize(9);doc.text('BLOCKCHAIN INVESTIGATION DOSSIER',M,21);
            doc.setFont('Report','normal');doc.setFontSize(8);doc.text('INVESTIGATOR REVIEW DRAFT',W-M,12,{align:'right'});doc.setFontSize(7);doc.text(pageSections[p]||section,W-M,21,{align:'right'});
            doc.setDrawColor(...C.line);doc.line(M,H-12,W-M,H-12);doc.setFontSize(7);doc.setTextColor(...C.muted);
            const ref=String(data.case_id);doc.text(`Case ${ref.length>55?ref.slice(0,52)+'...':ref} | CryptoTrace 3.0.0 | Not an approval or digital signature`,M,H-7);doc.text(`${p} / ${doc.internal.getNumberOfPages()}`,W-M,H-7,{align:'right'});
        }
        doc.save(`${String(data.case_id).replace(/[^A-Za-z0-9_.-]/g,'_')}_${String(data.trace_id).replace(/[^A-Za-z0-9_.-]/g,'_')}_draft.pdf`);
    }catch(error){alert(`Could not generate dossier: ${error.message}`);}finally{reportBusy=false;buttons.forEach(b=>b.disabled=false);}
}

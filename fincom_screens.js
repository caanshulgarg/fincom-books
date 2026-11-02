/* Bank statement to entries: upload a statement, check the suggested ledger on each line, post them together. */
(function(){
'use strict';
const BANK_GROUPS=['Bank Accounts','Bank OCC A/c','Bank OD A/c'];
const NOISE=new Set(['neft','imps','rtgs','upi','chq','cheque','dep','wdl','ref','txn','inb','mob','ift','ach','nach','ecs','cr','dr','to','by','from','the','and','pvt','ltd']);
const st=()=>frame();
const ledgerNames=()=>Object.keys(state.data.ledgers).sort((a,b)=>a.localeCompare(b));
const bankNames=()=>ledgerNames().filter(n=>BANK_GROUPS.includes(state.data.ledgers[n].group_type||state.data.ledgers[n].parent));
const paise=s=>BigInt(String(s).replace('.',''));
// Indian digit grouping: 2,00,000.00
const inr=s=>{const [w,p]=String(s).split('.');const t=w.slice(-3),h=w.slice(0,-3);return (h?h.replace(/\B(?=(\d{2})+(?!\d))/g,',')+','+t:t)+'.'+(p||'00');};
const day=k=>k?k.slice(6,8)+'-'+['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(k.slice(4,6))-1]+'-'+k.slice(0,4):'';
// words that repeat month to month: drop reference numbers and words glued to them
function steadyText(n){return String(n||'').toLowerCase().split(/[^a-z0-9&]+/).filter(w=>w.length>=3&&!/\d/.test(w)&&!NOISE.has(w)).slice(0,3).join(' ');}
function vtypeFor(r){if(!r.ledger)return '';const l=state.data.ledgers[r.ledger];return [...BANK_GROUPS,'Cash-in-hand'].includes(l?.group_type||l?.parent)?'Contra':r.dir==='out'?'Payment':'Receipt';}
function badge(r){
 if(r.state==='matched')return `<span class="bk-badge bk-ok">Matched</span> ${esc(r.voucher)}`;
 if(!r.ledger)return '<span class="bk-badge bk-warn">Choose a ledger</span>';
 return `<span class="bk-badge bk-new">${vtypeFor(r)}</span> ${r.dir==='out'?'Dr':'Cr'} ${esc(r.ledger)}${r.why?` <span class="bk-why">(${esc(r.why)})</span>`:''}`;
}
function counts(rows){const c={matched:0,ready:0,open:0};let out=0n,inn=0n;for(const r of rows){if(r.state==='matched')c.matched++;else if(r.ledger)c.ready++;else c.open++;r.dir==='out'?out+=paise(r.amount):inn+=paise(r.amount);}return {...c,out:decimalMoney(out),inn:decimalMoney(inn)};}
function summary(f){const c=counts(f.rows);return `<div class="bk-card"><span>Already in books</span><b>${c.matched}</b></div><div class="bk-card"><span>Ready to post</span><b class="bk-blue">${c.ready}</b></div><div class="bk-card"><span>Need a ledger</span><b class="${c.open?'bk-amber':''}">${c.open}</b></div><div class="bk-card"><span>Out / In</span><b class="bk-mono">${inr(c.out)} / ${inr(c.inn)}</b></div>`;}
function row(r,i,names){
 const opts=names.map(n=>`<option ${n===r.ledger?'selected':''}>${esc(n)}</option>`).join('');
 const ledger=r.state==='matched'?'':`<select name="bk-ledger" data-i="${i}" aria-label="Ledger for line ${r.line}"><option value=""></option>${opts}</select>`;
 const keep=r.state!=='matched'&&r.ledger&&r.why!==('rule: "'+r.remember+'"')?`<label class="bk-keep"><input type="checkbox" name="bk-keep" data-i="${i}" ${r.keep?'checked':''}> remember "<input name="bk-text" data-i="${i}" value="${esc(r.remember||'')}" aria-label="Text to remember" size="14">"</label>`:'';
 return `<tr class="${r.state==='matched'?'bk-done':''}"><td>${day(r.date)}</td><td class="bk-narr">${esc(r.narration)}${r.ref?`<br><span class="bk-why">${esc(r.ref)}</span>`:''}</td><td class="bk-amt">${r.dir==='out'?inr(r.amount):''}</td><td class="bk-amt">${r.dir==='in'?inr(r.amount):''}</td><td>${ledger}</td><td class="bk-what" id="bk-what-${i}">${badge(r)}${keep}</td></tr>`;
}
function readyRows(f){return f.rows.filter(r=>r.state==='matched'||r.ledger);}
function renderBank(f){
 $('#title').textContent='Bank statement';
 const banks=bankNames(),names=ledgerNames().filter(n=>n!==f.bank);
 if(!f.bank&&banks.length)f.bank=banks[0];
 const toPost=f.rows?f.rows.filter(r=>r.state!=='matched'&&r.ledger).length:0;
 $('#screen').innerHTML=`<div class="bk">
 <div class="bk-head"><h2>Bank statement → entries</h2>
  <label>Bank <select name="bk-bank">${banks.map(b=>`<option ${b===f.bank?'selected':''}>${esc(b)}</option>`).join('')}</select></label>
  <label class="bk-file">Upload statement (Excel or CSV)<input type="file" name="bk-file" accept=".xlsx,.xlsm,.csv,.txt"></label>
  ${f.rows?`<button type="button" class="bk-primary" data-action="bankPost" ${toPost||f.rows.some(r=>r.state==='matched')?'':'disabled'}>Post ${toPost} entr${toPost===1?'y':'ies'}</button>`:''}</div>
 ${banks.length?'':'<p class="bk-note bk-amber">Create a ledger under Bank Accounts first.</p>'}
 ${f.rows?`<p class="bk-note">${esc(f.file)} · ${f.rows.length} lines. Lines with no ledger are left out; post them next time.</p><section class="bk-cards" id="bk-cards">${summary(f)}</section>
 <section class="bk-table"><table><thead><tr><th>Date</th><th>Bank narration</th><th>Out</th><th>In</th><th>Ledger</th><th>What FinCom Books will do</th></tr></thead><tbody>${f.rows.map((r,i)=>row(r,i,names)).join('')}</tbody></table></section>
 <p class="bk-note">Lines already in the books are ticked as cleared on posting. Ticking "remember" fills that ledger automatically next time.</p>`
 :`<p class="bk-note">Download the statement from net banking as Excel or CSV and upload it here. FinCom Books finds the Date, Narration, Withdrawal and Deposit columns, spots entries already in the books and suggests a ledger for the rest. For a PDF statement, open it in Excel and save as .xlsx first.</p>`}
 </div>`;
 setKeys([['Esc','Back','back'],['F2','Date','date'],['F3','Company','company']]);
}
async function readFile(f,file){
 const data=await new Promise((ok,bad)=>{const fr=new FileReader();fr.onload=()=>ok(String(fr.result).split(',')[1]||'');fr.onerror=()=>bad(Error('Could not read the file'));fr.readAsDataURL(file);});
 note('Reading statement…');
 const res=await api('/api/bank_preview',{company:state.data.active_company,bank:f.bank,filename:file.name,content:data});
 const ruleTexts=new Set((res.rules||[]).map(r=>r.text));
 f.rows=res.rows.map(r=>({...r,remember:steadyText(r.narration),keep:false}));
 f.rows.forEach(r=>{const m=/^rule: "(.*)"$/.exec(r.why||'');if(m&&ruleTexts.has(m[1]))r.remember=m[1];});
 f.revision=res.revision;f.file=file.name;render();note(`${f.rows.length} lines read`);
}
async function post(){
 const f=st(),rows=readyRows(f),toPost=rows.filter(r=>r.state!=='matched');
 confirmBox(`Post ${toPost.length} entries to ${f.bank}?`,async()=>{
  const remember=f.rows.filter(r=>r.keep&&r.ledger&&r.remember).map(r=>({text:r.remember,ledger:r.ledger}));
  const res=await api('/api/bank_post',{company:state.data.active_company,bank:f.bank,rows,expected_revision:f.revision,remember});
  await refresh();f.rows=null;render();note(`${res.posted} entries posted, ${res.cleared} already in books ticked as cleared`);
 });
}
document.addEventListener('change',async e=>{
 if(st()?.kind!=='bankImport')return;const f=st(),t=e.target,i=Number(t.dataset.i);
 try{
  if(t.name==='bk-bank'){f.bank=t.value;f.rows=null;render();}
  else if(t.name==='bk-file'&&t.files[0])await readFile(f,t.files[0]);
  else if(t.name==='bk-ledger'){const r=f.rows[i];r.ledger=t.value;r.why=t.value?'chosen':'';render();$(`[name=bk-ledger][data-i="${i}"]`)?.focus();}
  else if(t.name==='bk-keep')f.rows[i].keep=t.checked;
 }catch(err){errorBox(err.message);if(t.name==='bk-file')t.value='';}
});
document.addEventListener('input',e=>{if(st()?.kind==='bankImport'&&e.target.name==='bk-text')st().rows[Number(e.target.dataset.i)].remember=e.target.value;});

/* Document inbox: bills waiting to be entered, shown beside the voucher while you enter them. */
const INBOX_TYPES=[['Purchase','F9'],['Payment','F5'],['Journal','F7'],['Sales','F8']];
const docs=()=>state.data.company_meta?.inbox||[];
const fileUrl=d=>`/api/inbox_file?company=${encodeURIComponent(state.data.active_company)}&id=${encodeURIComponent(d.id)}`;
const kb=n=>n>1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB';
const viewer=d=>d.ext==='.pdf'?`<iframe src="${fileUrl(d)}" title="${esc(d.name)}"></iframe>`:`<img src="${fileUrl(d)}" alt="${esc(d.name)}">`;
function renderInbox(f){
 $('#title').textContent='Document inbox';
 f.tab=f.tab||'waiting';
 const all=docs(),list=all.filter(d=>d.status===f.tab).sort((a,b)=>String(b.received).localeCompare(String(a.received)));
 if(!list.some(d=>d.id===f.sel))f.sel=list[0]?.id;
 const cur=list.find(d=>d.id===f.sel),n=t=>all.filter(d=>d.status===t).length;
 const tab=(t,label)=>`<button type="button" role="tab" aria-selected="${f.tab===t}" data-action="inboxTab" data-args="${t}">${label} <b>${n(t)}</b></button>`;
 const acts=!cur?'':cur.status==='entered'?`<p class="bk-note">Entered as <b>${esc(cur.voucher)}</b> on ${esc(String(cur.entered||'').slice(0,10))}.</p>`
  :cur.status==='aside'?`<button type="button" data-action="inboxStatus" data-args="waiting">Move back to waiting</button>`
  :`<span class="bk-why">Enter as</span>${INBOX_TYPES.map(([t,k])=>`<button type="button" class="${t==='Purchase'?'bk-primary':''}" data-action="inboxEnter" data-args="${t}">${t} <kbd>${k}</kbd></button>`).join('')}<button type="button" data-action="inboxStatus" data-args="aside">Set aside</button>`;
 $('#screen').innerHTML=`<div class="bk ib">
 <div class="bk-head"><h2>Document inbox</h2><label class="bk-file">Add bills (PDF, JPG, PNG)<input type="file" name="ib-file" accept=".pdf,.jpg,.jpeg,.png,.webp" multiple></label></div>
 <div role="tablist" class="ib-tabs">${tab('waiting','Waiting')}${tab('entered','Entered')}${tab('aside','Set aside')}</div>
 ${all.length?'':'<p class="bk-note">Drop purchase bills, expense bills and sales copies here (or use Add bills). Each one opens beside the voucher while you enter it, and is marked entered with the voucher number once saved. The same file added twice is caught.</p>'}
 <div class="ib-body"><ul class="ib-list" aria-label="Documents">${list.map(d=>`<li><button type="button" data-action="inboxPick" data-args="${esc(d.id)}" aria-current="${d.id===f.sel}"><b>${esc(d.name)}</b><span>${esc(String(d.received).slice(0,10))} · ${kb(d.size)}${d.voucher?' · '+esc(d.voucher):''}</span></button></li>`).join('')||'<li class="bk-note">Nothing here.</li>'}</ul>
 ${cur?`<section class="ib-view"><div class="ib-acts">${acts}</div><div class="ib-frame">${viewer(cur)}</div></section>`:''}</div></div>`;
 setKeys([['Esc','Back','back'],['F3','Company','company'],...(cur?.status==='waiting'?['gap',...INBOX_TYPES.map(([t,k])=>[k,t,'inboxEnter',t])]:[])]);
}
async function addFiles(fileList){
 let added=0,dups=[];
 for(const file of fileList){
  const content=await new Promise((ok,bad)=>{const fr=new FileReader();fr.onload=()=>ok(String(fr.result).split(',')[1]||'');fr.onerror=()=>bad(Error('Could not read '+file.name));fr.readAsDataURL(file);});
  const res=await api('/api/inbox_add',{company:state.data.active_company,name:file.name,content});
  res.duplicate?dups.push(`${file.name} (same as ${res.doc.name}${res.doc.voucher?', entered as '+res.doc.voucher:''})`):added++;
 }
 await refresh();const f=frame();if(f.kind==='inbox')f.tab='waiting';render();$('.ib-list button[aria-current=true]')?.focus();
 if(dups.length)errorBox('Already in the inbox: '+dups.join('; '));else note(`${added} document${added===1?'':'s'} added`);
}
function peek(f){
 let el=$('#inbox-peek');const d=f.kind==='voucher'&&f.inboxDoc&&docs().find(x=>x.id===f.inboxDoc);
 document.body.classList.toggle('with-peek',!!d);
 if(!d){el?.remove();document.body.classList.remove('peek-min');return;}
 if(el?.dataset.id===d.id)return;
 el?.remove();
 document.body.insertAdjacentHTML('beforeend',`<aside id="inbox-peek" data-id="${esc(d.id)}" aria-label="Bill being entered"><div class="ib-peek-head"><span><b title="${esc(d.name)}">${esc(d.name)}</b><span class="bk-why">the saved voucher is linked to this bill</span></span><button type="button" data-action="peekToggle">Hide bill</button></div>${viewer(d)}</aside>`);
}
document.addEventListener('change',async e=>{if(frame()?.kind==='inbox'&&e.target.name==='ib-file'&&e.target.files.length){try{await addFiles([...e.target.files]);}catch(err){errorBox(err.message);}}});
document.addEventListener('dragover',e=>{if(frame()?.kind==='inbox')e.preventDefault();});
document.addEventListener('drop',async e=>{if(frame()?.kind!=='inbox')return;e.preventDefault();try{await addFiles([...e.dataTransfer.files]);}catch(err){errorBox(err.message);}});
window.FinComScreens=window.FinComScreens||{routes:{},actions:{}};
window.FinComScreens.routes.bankImport=renderBank;
window.FinComScreens.actions.bankImport=()=>requireCompany()&&navigate({kind:'bankImport'});
window.FinComScreens.actions.bankPost=post;
window.FinComScreens.routes.inbox=renderInbox;
window.FinComScreens.actions.peekToggle=(a,btn)=>{const min=document.body.classList.toggle('peek-min');if(btn)btn.textContent=min?'Show bill':'Hide bill';};
window.FinComScreens.after=peek;
window.FinComScreens.actions.inbox=()=>requireCompany()&&navigate({kind:'inbox'});
window.FinComScreens.actions.inboxTab=t=>{frame().tab=t;frame().sel=null;render();};
window.FinComScreens.actions.inboxPick=id=>{frame().sel=id;render();};
window.FinComScreens.actions.inboxStatus=async status=>{await api('/api/inbox_set',{company:state.data.active_company,id:frame().sel,status});await refresh();render();note(status==='aside'?'Set aside':'Back in waiting');};
window.FinComScreens.actions.inboxEnter=vtype=>{const id=frame().sel;openVoucher(vtype);if(frame().kind==='voucher'){frame().inboxDoc=id;peek(frame());}};
window.FinComBank={steadyText,inr};
})();

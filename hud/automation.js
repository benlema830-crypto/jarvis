/* Local memory, scheduled digests and file tools. No actions on panel open. */
'use strict';
(() => {
  function panel(id,title) {
    const d=make('dialog'); d.id=id; const head=make('div',null,'dialog-head');
    const close=make('button','Close'); close.onclick=()=>d.close(); head.append(make('h2',title),close); d.append(head);
    const body=make('div'), status=make('pre'); status.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';
    status.setAttribute('role','status'); d.append(body,status); document.body.append(d);
    return {d,body,status};
  }
  function button(label,fn,status) {
    const b=make('button',label); b.type='button'; b.onclick=async()=>{ b.disabled=true;
      try {await fn();} catch(e) {status.textContent=e.message;} finally {b.disabled=false;}
    }; return b;
  }
  function field(parent,label,tag='input',value='') {
    const wrap=make('label',label+' '), input=make(tag); input.value=value; input.setAttribute('aria-label',label);
    if(tag==='textarea') input.style.cssText='display:block;width:100%;min-height:80px';
    wrap.append(input); wrap.style.cssText='display:block;margin:10px 0'; parent.append(wrap); return input;
  }
  function menu(label,p,load) {
    const b=button(label,async()=>{document.getElementById('moreMenu').hidden=true;p.d.showModal();await load();},p.status);
    b.setAttribute('role','menuitem'); document.getElementById('moreMenu').prepend(b); return b;
  }
  const post=(path,data)=>J.api(path,data,{timeout:205000});
  const style=panel('responseSettingsDialog','Response settings'), controls={};
  style.body.append(make('p','Honesty stays on: Jarvis should admit uncertainty and report actual results. Directness controls how bluntly he speaks. Changes apply on the next turn.'));
  for(const [key,label,help] of [['humor','Humor','0: no jokes · 100: frequent dry wit'],['directness','Honesty / directness','0: tactful · 100: blunt; always truthful']]) {
    const input=field(style.body,label); input.type='range';input.min=0;input.max=100;input.step=1;
    const value=make('output'); input.after(value);input.oninput=()=>value.textContent=input.value+'%';
    controls[key]=input;style.body.append(make('small',help));
  }
  for(const [key,label,options] of [['detail','Explanation detail',['brief','balanced','detailed']],['tone','Tone',['classic','friendly','professional']],
      ['pushback','How firmly to disagree',['gentle','balanced','firm']],['address','Use of “sir”',['never','occasionally','often']]]) {
    const input=field(style.body,label,'select');for(const option of options)input.append(make('option',option));controls[key]=input;
  }
  function showStyle(data) {for(const [key,input] of Object.entries(controls)){input.value=data[key];input.oninput?.();}}
  style.body.append(button('Save response settings',async()=>{
    const data=Object.fromEntries(Object.entries(controls).map(([k,v])=>[k,v.type==='range'?Number(v.value):v.value]));
    showStyle(await post('/response-settings',data));style.status.textContent='Saved. Applies on the next conversation turn.';
  },style.status),button('Restore default style',async()=>{
    showStyle(await post('/response-settings',{humor:25,directness:75,detail:'brief',tone:'classic',pushback:'balanced',address:'occasionally'}));style.status.textContent='Default style restored.';
  },style.status));
  menu('Response settings',style,async()=>showStyle(await J.api('/response-settings'))).id='responseSettingsBtn';
  const mem=panel('memoryDialog','Memory & privacy'); let state;
  const proposals=make('div'); mem.body.append(proposals);
  async function renderProposals(data) {
    proposals.replaceChildren();
    if(!data.pending.length)return;
    proposals.append(make('h3','Waiting for your approval'),make('p','Found by the nightly journal (an AI summary). Nothing is remembered until you keep it. Facts join memory; decisions join the vault\'s Decision log.'));
    for(const item of data.pending) {
      const row=make('div'), input=field(row,`Proposed ${item.kind} (from ${item.source})`,'textarea',item.text);input.maxLength=2000;
      row.append(button('Keep',async()=>{renderProposals(await post('/memory-proposals',{id:item.id,approve:true,text:input.value===item.text?'':input.value}));state=await J.api('/memory');renderMemory();},mem.status),
        button('Drop',async()=>renderProposals(await post('/memory-proposals',{id:item.id,approve:false})),mem.status));proposals.append(row);
    }
  }
  const facts=make('div'); mem.body.append(make('p','Inspect saved facts and recent dialogue. Corrections, deletions and privacy changes reset model conversation context on the next turn. Older excerpts stay viewable here until cleared. Deleting here does not erase existing documents, handoffs, backups or provider history.'),facts);
  const recent=make('details'); recent.append(make('summary','Recent saved conversation')); const turns=make('pre'); turns.style.whiteSpace='pre-wrap';recent.append(turns);mem.body.append(recent);
  const clear=button('Clear recent conversation',async()=>{if(!confirm('Delete the saved recent conversation?'))return;state=await post('/memory',{action:'clear_recent',revision:state.revision});renderMemory();},mem.status);mem.body.append(clear);
  const terms=field(mem.body,'Private phrases (one per line)','textarea');
  const email=field(mem.body,'Redact email addresses');email.type='checkbox';
  const phone=field(mem.body,'Redact phone numbers');phone.type='checkbox';
  mem.body.append(make('p','Recognizable credentials and SSNs are filtered by default. Selected phrases are stored locally so Jarvis can match them. Detection is imperfect: screenshots and files read directly by external coding tools are outside this text filter.'),
    button('Save privacy filters',async()=>{state=await post('/privacy',{terms:terms.value.split('\n').map(s=>s.trim()).filter(Boolean),email:email.checked,phone:phone.checked});renderMemory();mem.status.textContent='Filters saved; saved facts and recent dialogue scrubbed. The next turn starts with refreshed context.';},mem.status));
  function renderMemory() {
    facts.replaceChildren();
    for(const item of state.facts) {
      const row=make('div'), input=field(row,'Remembered fact','textarea',item.fact);input.maxLength=2000;
      row.append(button('Save correction',async()=>{state=await post('/memory',{action:'update',revision:state.revision,id:item.id,fact:input.value});renderMemory();},mem.status),
        button('Delete fact',async()=>{if(!confirm('Delete this remembered fact?'))return;state=await post('/memory',{action:'delete',revision:state.revision,id:item.id});renderMemory();},mem.status));facts.append(row);
    }
    if(!state.facts.length)facts.append(make('p','No remembered facts. Ask Jarvis to remember something.'));
    turns.textContent=state.recent.map(t=>`${t.time}\nYou: ${t.user}\nJarvis: ${t.assistant}`).join('\n\n');
    terms.value=state.privacy.terms.join('\n');email.checked=state.privacy.email;phone.checked=state.privacy.phone;
  }
  menu('Memory & privacy',mem,async()=>{state=await J.api('/memory');renderMemory();renderProposals(await J.api('/memory-proposals'));}).id='memoryToolsBtn';

  const dig=panel('digestsDialog','Scheduled digests');let selectedId='';
  dig.body.append(make('p','Silent reports saved on this PC. Research uses Codex live search; progress uses saved Jarvis job reports and Git evidence. Brain must be running. Missed days are skipped; today may run after startup.'));
  const jobs=make('div');dig.body.append(jobs);
  const name=field(dig.body,'Schedule name','input','Roblox development update');
  const kind=field(dig.body,'Digest type','select');for(const [v,t] of [['research','Research with sources'],['progress','Jarvis progress']]){const o=make('option',t);o.value=v;kind.append(o);}
  const topic=field(dig.body,'Research topic','input','Recent Roblox development updates from official sources');topic.maxLength=1000;
  const at=field(dig.body,'Daily time','input','18:00');at.type='time';
  const enabled=field(dig.body,'Enable this daily schedule');enabled.type='checkbox';
  dig.body.append(button('Save schedule',async()=>{await post('/digests',{action:'save',...(selectedId?{id:selectedId}:{}),name:name.value,kind:kind.value,topic:topic.value,at:at.value,enabled:enabled.checked});await loadDigests();},dig.status),
    button('New schedule',async()=>{selectedId='';name.value='New digest';enabled.checked=false;dig.status.textContent='New schedule draft. Save to create it.';},dig.status));
  const zone=field(dig.body,'Timezone','input','America/Chicago');
  const quietStart=field(dig.body,'Quiet hours begin','input','22:00');quietStart.type='time';
  const quietEnd=field(dig.body,'Quiet hours end','input','08:00');quietEnd.type='time';
  const limit=field(dig.body,'Maximum runs per day','input','2');limit.type='number';limit.min=1;limit.max=4;
  dig.body.append(make('p','Up to four searches and three minutes per research run. The daily cap includes manual runs and failed attempts. Manual Run now ignores quiet hours; scheduled runs wait. Equal quiet-hour times disable quiet hours.'),
    button('Save quiet hours & limit',async()=>{await post('/digests',{action:'configure',timezone:zone.value,quiet_start:quietStart.value,quiet_end:quietEnd.value,daily_limit:Number(limit.value)});await loadDigests();},dig.status));
  const runs=make('div');dig.body.append(make('h3','Reports & attempts'),runs);
  async function loadDigests() {
    const data=await J.api('/digests');zone.value=data.timezone;quietStart.value=data.quiet_start;quietEnd.value=data.quiet_end;limit.value=data.daily_limit;jobs.replaceChildren();runs.replaceChildren();
    for(const j of data.jobs){const row=make('div');row.append(make('p',`${j.name} · ${j.at} · ${j.enabled?'enabled':'disabled'}`),
      button('Edit',async()=>{selectedId=j.id;name.value=j.name;kind.value=j.kind;topic.value=j.topic;at.value=j.at;enabled.checked=j.enabled;},dig.status),
      button('Run now',async()=>{dig.status.textContent='Preparing a report…';const result=await post('/digests',{action:'run',id:j.id});dig.status.textContent=JSON.stringify(result,null,2);await loadDigests();},dig.status),
      button('Delete schedule',async()=>{if(!confirm('Delete this schedule? Saved reports remain.'))return;await post('/digests',{action:'delete',id:j.id});selectedId='';await loadDigests();},dig.status));jobs.append(row);}
    if(!data.jobs.length)jobs.append(make('p','No schedules. Nothing runs automatically.'));
    for(const r of [...data.runs].reverse().slice(0,30)){const row=make('div');row.append(make('p',`${r.name} · ${r.started} · ${r.status}${r.error?' · '+r.error:''}`));
      if(r.status==='completed')row.append(button('Read report',async()=>{const report=await post('/digests',{action:'report',id:r.id});dig.status.replaceChildren(make('p',report.text));for(const source of report.sources){const a=make('a',source.title||source.url);if(/^https?:\/\//.test(source.url)){a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';}dig.status.append(a,make('br'));}},dig.status));runs.append(row);}
  }
  menu('Scheduled digests',dig,loadDigests).id='digestToolsBtn';

  const files=panel('filesDialog','Spreadsheets, reports & slides');
  files.body.append(make('p','Ask Jarvis for a budget, project tracker, PDF report or slide deck using your own data. Files stay in Documents / JARVIS Documents. The sample below uses clearly labeled sample data.'));
  const format=field(files.body,'File format','select');for(const f of ['xlsx','pdf','pptx'])format.append(make('option',f));
  const title=field(files.body,'Document title','input','Sample project budget');
  const content=field(files.body,'Report text or slide content','textarea','Sample numbers only. Replace them with your actual budget.');
  const values=field(files.body,'Table (tab-separated columns and rows)','textarea','Category\tAmount\nArt\t40\nAudio\t25\nTesting\t10');
  const chart=field(files.body,'Include a chart');chart.type='checkbox';chart.checked=true;
  const fileList=make('div');
  files.body.append(button('Create file',async()=>{const lines=values.value.trim().split('\n').map(l=>l.split('\t'));const columns=lines.shift();const rows=lines.map(r=>r.map(v=>v.trim()!==''&&Number.isFinite(Number(v))?Number(v):v));
    const spec={title:title.value,content:content.value,columns,rows,totals:true,chart:chart.checked?'bar':false};
    spec.slides=[{title:title.value,body:content.value,columns,rows,chart:spec.chart}];
    const result=await post('/artifacts',{format:format.value,spec});files.status.textContent=`Created ${result.name}`;await loadFiles();},files.status),fileList);
  async function loadFiles(){const data=await J.api('/artifacts');fileList.replaceChildren();for(const f of data.files)fileList.append(button(`Open ${f.name}`,async()=>{await post('/artifacts',{action:'open',name:f.name});},files.status));}
  menu('File tools',files,loadFiles).id='fileToolsBtn';
})();

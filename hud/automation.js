/* Response settings and the memory & privacy viewer. No actions on panel open. */
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
  function menu(label,p,load,group,id) {
    J.menuItem(group,label,async()=>{p.d.showModal();try{await load();}catch(e){p.status.textContent=e.message;}},id);
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
  menu('Response style',style,async()=>showStyle(await J.api('/response-settings')),'jarvis','responseSettingsBtn');
  const mem=panel('memoryDialog','Memory & privacy'); let state;
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
  menu('Memory & privacy',mem,async()=>{state=await J.api('/memory');renderMemory();},'jarvis','memoryToolsBtn');
})();

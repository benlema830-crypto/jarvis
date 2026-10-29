/* Real content on the hologram, project resume and accessible pane controls. */
'use strict';
(() => {
  const panes=new Map(), hidden=new Set(store.get('hiddenPanes',[]));
  let current=null, selected=null;
  const button=(label,action)=>{const b=make('button',label);b.type='button';b.onclick=action;return b;};
  const viewer=make('dialog',null,'holo-viewer'),heading=make('h2'),source=make('p',null,'muted'),body=make('pre'),actions=make('div',null,'actions');
  viewer.id='holoPaneDialog';viewer.setAttribute('aria-label','Holographic panel');
  viewer.addEventListener('close',()=>{current=null;});
  viewer.append(button('Close',()=>viewer.close()),heading,source,body,actions);document.body.append(viewer);
  const listDialog=make('dialog'),list=make('div',null,'pane-library');listDialog.id='paneLibrary';listDialog.setAttribute('aria-label','Holographic panels');
  listDialog.append(button('Close',()=>listDialog.close()),make('h2','Holographic panels'),
    make('p','Click a floating panel or choose one below. Say “bring that closer” after selecting a note, or “put that away” to dismiss it.'),list);
  document.body.append(listDialog);
  function library(){
    list.replaceChildren();
    for(const pane of panes.values()) {
      const row=make('div',null,'pane-library-row');
      row.append(button(pane.title,()=>{listDialog.close();focus(pane.id);}),make('small',pane.kind),
        button(hidden.has(pane.id)?'Restore':'Dismiss',()=>{if(hidden.has(pane.id))hidden.delete(pane.id);else hidden.add(pane.id);saveHidden();library();}));
      list.append(row);
    }
    if(!panes.size)list.append(make('p','Panels appear when notes, tasks, files or results are available.'));
  }
  const saveHidden=()=>store.set('hiddenPanes',[...hidden].slice(-200));
  function add(pane, prioritize=false){
    if(!pane?.id || !pane.title)return;
    pane={...pane,title:String(pane.title).slice(0,120),body:String(pane.body||'').slice(0,24000)};
    pane.lines=pane.body.split(/\n/).filter(Boolean).slice(0,14);
    if(prioritize){panes.delete(pane.id);hidden.delete(pane.id);selected=pane.id;}
    panes.set(pane.id,pane);
    while(panes.size>32)panes.delete(panes.keys().next().value);
    if(listDialog.open)library();
  }
  async function focus(query=''){
    const q=String(query).toLowerCase();
    const pane=panes.get(query)||[...panes.values()].find(p=>q && p.title.toLowerCase().includes(q))||(!q?panes.get(selected)||panes.get(current)||J.panes.visible[0]:null);
    if(!pane){J.notice('No panel matches that yet. Open Holographic panels to choose one.');return;}
    selected=current=pane.id;hidden.delete(pane.id);saveHidden();
    heading.textContent=pane.title;source.textContent=pane.source||pane.kind;body.textContent=pane.body;actions.replaceChildren();
    actions.append(button('Put away',()=>dismiss(pane.id)));
    if(pane.kind==='note')actions.append(button('Show in graph',()=>{viewer.close();J.selectById(pane.id);}));
    if(pane.uri && /^(https?:|obsidian:)/i.test(pane.uri)){
      const a=make('a','Open source');a.href=pane.uri;a.target='_blank';a.rel='noopener noreferrer';actions.append(a);
    }
    if(pane.artifact)actions.append(button('Open document',async()=>{try{await J.api('/artifacts',{action:'open',name:pane.artifact});}catch(e){J.notice(e.message);}}));
    if(!viewer.open)viewer.showModal();
    if(pane.projectPath){
      body.textContent='Loading source…';
      try{const file=await J.api('/project-resume',{action:'file',project:pane.project,path:pane.projectPath});if(current===pane.id)body.textContent=file.text+(file.truncated?'\n\n[Preview truncated]':'');}
      catch(e){if(current===pane.id)body.textContent=e.message;}
    }
    if(current===pane.id && !viewer.open)viewer.showModal();
  }
  function dismiss(id=current||selected){if(!id)return;hidden.add(id);saveHidden();if(current===id){viewer.close();current=null;}if(selected===id)selected=null;library();}
  J.panes={add,focus,dismiss,select(id){selected=id;},get selected(){return selected;},
    get visible(){return [...panes.values()].filter(p=>!hidden.has(p.id)).reverse().slice(0,7);},
    paint(ctx,pane,w,h){
      const x=-w/2,y=-h/2;ctx.textAlign='left';ctx.textBaseline='top';
      ctx.fillStyle='#e8d9ff';ctx.font=`600 ${h*.095}px Consolas,monospace`;ctx.fillText(pane.title.slice(0,22),x+w*.08,y+h*.055,w*.84);
      ctx.fillStyle='#b993fa';ctx.font=`${h*.07}px Consolas,monospace`;
      ctx.fillText(pane.kind.toUpperCase(),x+w*.08,y+h*.19,w*.84);
      ctx.save();ctx.beginPath();ctx.rect(x+w*.08,y+h*.31,w*.84,h*.6);ctx.clip();
      ctx.fillStyle='#c4b4e0';ctx.font=`${h*.064}px Consolas,monospace`;
      pane.lines.slice(0,9).forEach((line,i)=>ctx.fillText(line.slice(0,45),x+w*.08,y+h*(.32+i*.065),w*.84));ctx.restore();
    }
  };
  function notes(){for(const n of J.graph.nodes.filter(n=>n.kind==='Note').slice(0,8))add({id:n.id,title:n.label,kind:'note',body:n.body,source:n.source,uri:n.uri});}
  J.on('graph-loaded',notes);notes();
  J.on('selected',n=>{if(n?.kind==='Note')add({id:n.id,title:n.label,kind:'note',body:n.body,source:n.source,uri:n.uri},true);});
  J.on('sources',e=>{for(const s of (e.sources||[]).slice(0,5)){
    if(s.url && /^https?:/i.test(s.url))add({id:'web:'+s.url,title:s.title||s.url,kind:'research',source:s.url,uri:s.url,body:s.snippet||s.excerpt||'Open the cited source to read the full result.'},true);
  }});
  J.on('holo-panel',e=>{if(e.action==='dismiss')dismiss();else focus(e.query||'');});
  J.on('sessions',data=>{for(const s of (data.sessions||[]).slice(-4))add({id:'session:'+s.name,title:s.name,kind:'project',source:s.project,
    body:`${s.status}\n${s.task||''}\n\n${s.progress||s.report||''}`});});
  async function refresh(){
    if(document.hidden||J.online===false)return;
    const results=await Promise.allSettled([J.api('/tasks'),J.api('/artifacts')]);
    if(results[0].status==='fulfilled')add({id:'tasks',title:'Tasks',kind:'tasks',source:'Tasks.md',body:(results[0].value.tasks||[]).filter(t=>!t.done).map(t=>`${t.n}. ${t.text}`).join('\n')||'No open tasks.'});
    if(results[1].status==='fulfilled')for(const f of (results[1].value.files||[]).slice(0,3))add({id:'file:'+f.name,title:f.name,kind:'document',artifact:f.name,body:`Generated document\n${Math.round(f.bytes/1024)} KB\nOpen this panel to launch the file.`});
  }
  J.on('hello',refresh);J.on('stage',refresh);setInterval(refresh,12000);refresh();
  const menu=document.getElementById('moreMenu');
  const panesButton=button('Holographic panels',()=>{menu.hidden=true;library();listDialog.showModal();});panesButton.id='holoPanelsBtn';menu.prepend(panesButton);

  const resumeDialog=make('dialog'),resumeProject=make('select'),resumeBody=make('div');resumeDialog.id='resumeDialog';
  resumeDialog.setAttribute('aria-label','Resume a project');resumeProject.setAttribute('aria-label','Project to resume');
  for(const name of ['Jarvis','Rocket Frontier'])resumeProject.append(make('option',name));
  resumeDialog.append(button('Close',()=>resumeDialog.close()),make('h2','Pick up where you left off'),resumeProject,
    button('Restore workspace',async()=>{try{resumeBody.textContent='Reading current project evidence…';applyResume(await J.api('/project-resume',{project:resumeProject.value}));}catch(e){resumeBody.textContent=e.message;}}),resumeBody);
  document.body.append(resumeDialog);
  function applyResume(data){
    store.set('lastProject',data.project);resumeProject.value=data.project;resumeBody.replaceChildren();
    for(const [label,value] of [['Last reported progress',data.summary],['Source',data.summary_source],['Unresolved',data.unresolved],['Next recorded action',data.next_action]]){
      resumeBody.append(make('h3',label),make('p',value));
    }
    for(const item of data.verified||[])resumeBody.append(make('h3',item.source),make('pre',item.text||'Clean working tree.'));
    add({id:'resume:'+data.project,title:data.project+' — resume',kind:'project',source:data.summary_source,
      body:`${data.summary}\n\nUNRESOLVED\n${data.unresolved}\n\nNEXT ACTION\n${data.next_action}\n\n${data.interpretation}`},true);
    const files=make('div',null,'actions');
    for(const file of data.files||[]){
      const pane={id:'source:'+data.project+':'+file.path,title:file.path,kind:'source',source:data.project,project:data.project,projectPath:file.path,body:'Project source — click to read.'};
      add(pane);files.append(button(file.path,()=>{resumeDialog.close();focus(pane.id);}));
    }
    resumeBody.append(make('h3','Relevant files'),files,make('p',data.interpretation,'muted'));
    if(!J.view.jarvisMain)document.getElementById('stageSlot').click();
    if(!resumeDialog.open)resumeDialog.showModal();
  }
  J.on('project-resume',applyResume);
  const resumeButton=button('Resume project',()=>{menu.hidden=true;resumeProject.value=store.get('lastProject','Jarvis');resumeDialog.showModal();});resumeButton.id='resumeProjectBtn';menu.prepend(resumeButton);

  const orbButton=button('Desktop orb',async()=>{menu.hidden=true;try{await J.api('/desktop-orb',{});J.notice('Desktop orb opened.');}catch(e){J.notice(e.message);}});
  orbButton.id='desktopOrbBtn';menu.prepend(orbButton);
  if(new URLSearchParams(location.search).get('compact')==='1'){
    document.body.classList.add('native-orb');J.setCompact(true);
    const chrome=make('div',null,'orb-chrome'),drag=make('span','JARVIS','pywebview-drag-region');
    const expand=button('Expand',async()=>{
      const compact=!document.body.classList.contains('compact-orb');
      if(window.pywebview?.api)await window.pywebview.api.set_compact(compact);else J.setCompact(compact);
      expand.textContent=compact?'Expand':'Compact';
    });
    chrome.append(drag,expand,button('Close',()=>window.pywebview?.api.close()));document.body.append(chrome);
    document.getElementById('reactor').addEventListener('dblclick',()=>expand.click());
    const ask=make('form',null,'orb-command'),input=make('input');input.placeholder='Ask Jarvis…';input.setAttribute('aria-label','Ask Jarvis from desktop orb');
    const send=make('button','↑');send.type='submit';ask.append(input,send);
    ask.onsubmit=e=>{e.preventDefault();if(input.value.trim()){J.send(input.value);input.value='';}};document.body.append(ask);
  }
})();

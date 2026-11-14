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
    try{const data=await J.api('/tasks');add({id:'tasks',title:'Tasks',kind:'tasks',source:'Tasks.md',body:(data.tasks||[]).filter(t=>!t.done).map(t=>`${t.n}. ${t.text}`).join('\n')||'No open tasks.'});}catch{}
  }
  J.on('hello',refresh);J.on('stage',refresh);setInterval(refresh,12000);refresh();
  J.menuItem('view','Holographic panels',()=>{library();listDialog.showModal();},'holoPanelsBtn');

  const resumeDialog=make('dialog'),resumeProject=make('select'),resumeBody=make('div');resumeDialog.id='resumeDialog';
  resumeDialog.setAttribute('aria-label','Resume a project');resumeProject.setAttribute('aria-label','Project to resume');
  for(const name of ['Jarvis','Rocket Frontier',"Don't Wake the Giant",'KnightShow'])resumeProject.append(make('option',name));
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
  J.menuItem('projects','Resume a project',()=>{resumeProject.value=store.get('lastProject','Jarvis');resumeDialog.showModal();},'resumeProjectBtn');

  J.menuItem('view','Desktop orb',async()=>{try{await J.api('/desktop-orb',{});J.notice('Desktop orb opened.');}catch(e){J.notice(e.message);}},'desktopOrbBtn');
  if(new URLSearchParams(location.search).get('compact')==='1'){
    // The desktop app's orb (jarvis_app.py): his main face in the corner of the screen. It grows while the two of
    // you are talking and shrinks back after a quiet spell; "Open" shows his full window, "Hide" sends him to the tray.
    document.body.classList.add('native-orb');J.setCompact(true);
    const app=()=>window.pywebview?.api;
    const chrome=make('div',null,'orb-chrome'),drag=make('span','JARVIS','pywebview-drag-region');
    const mic=button('Mic',async()=>{try{await J.api('/settings',{mic_muted:!J.micMuted});}catch(e){J.notice(e.message);}});
    mic.title='Mute or unmute the microphone';
    const open=button('Open',()=>app()?app().open_window():J.setCompact(!document.body.classList.contains('compact-orb')));
    open.title='Open his full window';
    const hide=button('Hide',()=>app()?.hide_orb());hide.title='Hide the orb (the icon by the clock brings him back)';
    chrome.append(drag,mic,open,hide);document.body.append(chrome);
    drag.addEventListener('mouseup',()=>setTimeout(()=>app()?.save_position(),150));
    J.on('mic',muted=>{mic.textContent=muted?'Muted':'Mic';mic.classList.toggle('muted',muted);document.body.classList.toggle('mic-muted',muted);});
    document.getElementById('reactor').addEventListener('dblclick',()=>open.click());
    const caption=make('div',null,'orb-caption');document.body.append(caption);
    const ask=make('form',null,'orb-command'),input=make('input');input.placeholder='Ask Jarvis…';input.setAttribute('aria-label','Ask Jarvis from desktop orb');
    const send=make('button','↑');send.type='submit';ask.append(input,send);
    ask.onsubmit=e=>{e.preventDefault();if(input.value.trim()){J.send(input.value);input.value='';active();}};document.body.append(ask);
    // Grow and shrink
    const QUIET_MS=15000;let lastActive=0,size='small',busy=false;
    const resize=want=>{if(want===size)return;size=want;document.body.classList.toggle('orb-big',want==='big');app()?.set_size(want);};
    const active=()=>{lastActive=Date.now();resize('big');};
    J.focusAsk=()=>{active();setTimeout(()=>input.focus(),60);};
    input.addEventListener('focus',active);input.addEventListener('input',active);
    J.on('state',ev=>{busy=ev.state==='thinking';if(busy)active();});
    J.on('you',ev=>{if(!ev.replay){caption.textContent='';active();}});
    J.on('jarvis',ev=>{if(!ev.replay&&ev.text){caption.textContent=ev.text;active();}});
    J.on('audio',ev=>{if((ev.output||0)>.02)lastActive=Date.now();});  // still speaking: stay big
    setInterval(()=>{if(size==='big'&&!busy&&document.activeElement!==input&&Date.now()-lastActive>QUIET_MS){caption.textContent='';resize('small');}},1000);
  }
})();

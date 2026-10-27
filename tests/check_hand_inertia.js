/* Inert tests of production camera and landmark interpreter. No camera or CDN.
   Node: node tests/check_hand_inertia.js. Also callable in the test harness V8. */
function checkHandInertia(brain, modes) {
  new Function(brain); new Function(modes);
  const motion = brain.slice(brain.indexOf('// Hand release uses'), brain.indexOf('/* ---------- Rendering'));
  const gestures = modes.slice(modes.indexOf('  class OneEuro'), modes.indexOf('  function drawHands'));
  const pointer = brain.slice(brain.indexOf("canvas.addEventListener('pointerdown'"), brain.indexOf("canvas.addEventListener('dblclick'"));
  return new Function(`
    const G={cam:{yaw:0,pitch:0,panX:0,panY:0,velocityYaw:0,velocityPitch:0},is3d:true,orbit:false};
    const reduced={matches:false}; let settling=0,drag=null,taps=0;
    const hit=()=>null,pinDraggedNode=()=>{},reheat=()=>{};
    const fit=()=>stopMomentum(), performance={now:()=>100};
    const innerWidth=1000,innerHeight=800,W=1000,H=800;
    const el=()=>({style:{},classList:{toggle(){}},hidden:true});
    const handlers={},$=el,document={addEventListener(){}},addEventListener=()=>{};
    const canvas={addEventListener:(name,fn)=>handlers[name]=fn,setPointerCapture(){},hasPointerCapture:()=>false,
      classList:{add(){},remove(){}}};
    const J={hit:()=>null,clearSelection:()=>taps++,select:()=>taps++};
    ${motion}
    ${gestures}
    ${pointer}
    const assert=(v,m)=>{if(!v)throw Error(m)};
    const near=(a,b)=>Math.abs(a-b)<1e-9;
    function reset(){stopMomentum();G.cam.yaw=G.cam.pitch=0;G.cam.goal=null;reduced.matches=false}
    const point=(type,x,y,button=0)=>handlers[type]({pointerId:1,clientX:x,clientY:y,button});
    function fling(){reset();beginHandDrag(0);moveHandDrag(10,3,40);moveHandDrag(10,3,80);endHandDrag(100)}
    fling();const start=G.cam.yaw;stepCamera(.1);const first=G.cam.yaw-start;
    const mid=G.cam.yaw;stepCamera(.1);assert(first>0&&G.cam.yaw-mid<first,'release must coast and decelerate');
    function travel(hz){fling();const x=G.cam.yaw;for(let i=0;i<hz;i++)stepCamera(1/hz);return G.cam.yaw-x}
    assert(near(travel(30),travel(60))&&near(travel(60),travel(144)),'frame rate changes travel');
    fling();const x=G.cam.yaw;stepCamera(.05,5);
    assert(near(G.cam.yaw-x,travel(60)),'delayed frame changes distance');
    const final=G.cam.yaw;stepCamera(1);assert(near(G.cam.yaw,final)&&handMotion.age===1,'must settle by one second');
    fling();beginHandDrag(110);const grabbed=G.cam.yaw;stepCamera(.2);assert(G.cam.yaw===grabbed,'re-grab did not cancel');
    reset();beginHandDrag(0);moveHandDrag(100,0,20);moveHandDrag(0,0,200);endHandDrag(240);stepCamera(1);
    assert(near(G.cam.yaw,.8),'stationary hold launched stale velocity');
    reset();beginHandDrag(0);moveHandDrag(5,0,40);endHandDrag(60,true);const tapped=G.cam.yaw;stepCamera(1);
    assert(G.cam.yaw===tapped,'tap launched inertia');
    reset();beginHandDrag(0);moveHandDrag(10000,10000,20);endHandDrag(40);
    assert(Math.hypot(handMotion.yaw,handMotion.pitch)<=4.000001,'velocity unbounded');
    stepCamera(1);assert(G.cam.pitch<=1.45,'pitch left viewport limit');
    fling();reduced.matches=true;const still=G.cam.yaw;stepCamera(.5);assert(G.cam.yaw===still,'reduced motion did not stop coast');
    beginHandDrag(200);stepCamera(.1);moveHandDrag(10,0,240);assert(G.cam.yaw>still,'reduced motion broke direct drag');
    endHandDrag(260);const direct=G.cam.yaw;stepCamera(1);assert(G.cam.yaw===direct,'reduced motion launched inertia');
    // Real interpreter, synthetic landmarks, bypass only jitter filtering for deterministic coordinates.
    function hand(x,pinch){const lm=Array.from({length:21},()=>({x,y:.5}));lm[0]={x,y:.8};lm[9]={x,y:.5};
      lm[4]={x,y:.4};lm[8]={x:x+(pinch?.02:.2),y:.4};return lm}
    function trackingReset(){reset();for(const t of tracks){t.pinched=false;t.fx.filter=t.fy.filter=t.mx.filter=t.my.filter=x=>x;t.palmSince=t.peaceSince=0}}
    trackingReset();interpret([hand(.6,true)],0);interpret([hand(.55,true)],200);interpret([hand(.5,true)],240);interpret([hand(.45,true)],280);
    interpret([hand(.45,false)],300);const release=G.cam.yaw;stepCamera(.1);
    assert(G.cam.yaw>release,'landmark release did not launch coast');
    interpret([hand(.45,true)],320);const regrab=G.cam.yaw;stepCamera(.1);assert(G.cam.yaw===regrab,'landmark re-grab did not stop');
    interpret([],340);assert(!handMotion.held&&handMotion.age===1,'tracking loss did not cancel');
    fling();interpret([hand(.3,true),hand(.7,true)],150);assert(handMotion.age===1,'two hands did not cancel');
    trackingReset();interpret([hand(.5,true)],200);interpret([hand(.41,false)],240);
    assert(taps===1&&handMotion.age===1,'quick pinch selection changed');
    // Fast selection never starts rotating, even with finger closure movement and jitter.
    trackingReset(); const selected={id:'node'};let selectedNode=null;
    J.hit=()=>selected;J.select=n=>{selectedNode=n;taps++};
    interpret([hand(.5,true)],500);
    interpret([hand(.49,true)],540);interpret([hand(.51,true)],580);
    J.hit=()=>null;interpret([hand(.6,false)],620);
    assert(G.cam.yaw===0&&selectedNode===selected,'quick pinch moved graph or selected release location');
    trackingReset();selectedNode=null;
    interpret([hand(.5,true)],700);interpret([hand(.499,true)],920);interpret([hand(.501,true)],960);
    assert(!handMotion.held&&G.cam.yaw===0,'stationary pinch jitter started drag');
    interpret([hand(.501,false)],1000);
    trackingReset();const beforeTwo=taps;
    interpret([hand(.3,true),hand(.7,true)],1100);
    interpret([hand(.3,false),hand(.7,false)],1200);
    assert(taps===beforeTwo,'two-hand zoom release selected a node');
    return 'PASS: hand release/deceleration, 30/60/144 Hz, delayed frames, one-second stop, re-grab, held/tap releases, velocity/pitch bounds, reduced motion, synthetic landmark drag/release/re-grab/loss/two-hand takeover/tap.';
  `)();
}
if(typeof module!=='undefined'&&require.main===module){
  const fs=require('fs'),path=require('path');
  console.log(checkHandInertia(fs.readFileSync(path.join(__dirname,'../hud/brain.js'),'utf8'),fs.readFileSync(path.join(__dirname,'../hud/modes.js'),'utf8')));
}

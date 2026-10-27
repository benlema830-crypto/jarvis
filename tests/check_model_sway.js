/* Regression: the removed air-resistance pose must not affect projection. */
function checkModelSway(brain) {
  new Function(brain);
  if (/modelSway|stepModelSway|moveModelSway/.test(brain)) throw Error('Air-resistance layer is still present');
  const projection = brain.slice(brain.indexOf('function project(n)'), brain.indexOf('let settling ='));
  return new Function(`
    const W=1000,H=800,FOCAL=620,centerX=()=>500;
    const G={is3d:true,cam:{yaw:0,pitch:0,zoom:1,panX:0,panY:0,target:{x:0,y:0,z:0}}};
    ${projection}
    const n={x:80,y:40,z:0,r:5};project(n);
    const expectedX=500+80*800/820,expectedY=800*.46+40*800/820;
    if(Math.abs(n.sx-expectedX)>1e-9||Math.abs(n.sy-expectedY)>1e-9)throw Error('Unexpected floating offset');
    const start=[n.sx,n.sy];for(let i=0;i<120;i++)project(n);
    if(n.sx!==start[0]||n.sy!==start[1])throw Error('Stationary model drifted');
    return 'PASS: no air-resistance layer, direct projection, stationary model stays still.';
  `)();
}
if(typeof module!=='undefined'&&require.main===module){
  const fs=require('fs'),path=require('path');console.log(checkModelSway(fs.readFileSync(path.join(__dirname,'../hud/brain.js'),'utf8')));
}

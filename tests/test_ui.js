const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
require('./test_run_drawer.js');
(async()=>{
 const source=fs.readFileSync('ui/app.js','utf8');
 const html=fs.readFileSync('ui/index.html','utf8');
 assert(!html.includes('id="liveSplit"'), 'Redundant score cards stay out of the run view');
 assert(!source.includes("$('liveSplit')"), 'Renderer does not target removed score cards');
 assert(!html.includes('The chart follows the selected saved run'), 'Redundant chart instructions stay removed');
 assert(html.includes('id="liveScoreChart"') && html.includes('id="liveMetrics"'), 'Chart and primary metrics remain available');
 const button={},messages=[],full='BEGIN\n'+'x'.repeat(60000)+'\nEND';let copied=null,url;
 const context={$:()=>button,logId:'fixture',S:{calibration_available:true},toast:m=>messages.push(m),navigator:{clipboard:{writeText:async t=>{copied=t}}},fetch:async u=>{url=u;return {ok:true,text:async()=>full}}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf("$('copyFullLog').onclick="),source.indexOf('function allJobs()')),context);
 await button.onclick();assert.equal(url,'/api/log/full?job=fixture');assert.equal(copied,full);assert.equal(button.disabled,false);assert(messages[0].includes('60,010'));
 context.fetch=async()=>({ok:false});copied=null;await button.onclick();assert.equal(copied,null);assert(messages.at(-1).includes('Could not copy'));
 console.log('Full-log copy: all 60,010 characters copied; failed fetch reports error without claiming success.');
})().catch(e=>{console.error(e);process.exit(1)});

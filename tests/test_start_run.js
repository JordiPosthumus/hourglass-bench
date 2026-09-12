'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
(async()=>{
  const app=fs.readFileSync('ui/app.js','utf8');
  const source=app.slice(app.indexOf("$('reviewRun').onclick="),app.indexOf('function renderJobs()'));
  const elements={},element=id=>elements[id]??=( {value:'',dataset:{},hidden:true,focus(){this.focused=true},scrollIntoView(){this.scrolled=true},close(){this.closed=true}} );
  const config={name:'fixture',model:'example-fp16-alias',base_url:'http://example.invalid/v1',max_tokens:262144};
  const naming={values:{hardware:'Recorded machine',model_name:config.model,server_name:'Recorded engine',server_version:'Recorded build'},identity:{name:'Recordedmachine-XXX-example-fp16-alias-XXX',overridden:false}};
  let actions,html,fail=true,submitted,refreshes=0;
  const context={$:element,modelConfig:()=>config,bankTasks:()=>[{id:'example',title:'Setup fixture',task_bundle_sha:'fixture-hash'}],
    S:{endpoint_hardware:{revision:'hardware-revision'},models_revision:'model-revision',jobs:{running:[],pending:[]}},draftSourceRunId:null,
    endpointHardware:{dirty:false,saving:false,summary:()=> 'Recorded machine'},esc:String,
    api:async(path,body)=>{if(path==='/api/run-identity')return naming;assert.equal(path,'/api/run');submitted=body;if(fail)throw Error('Model settings changed after review.');return {job:'new-run'}},
    dialog:(title,body,buttons)=>{html=body;actions=buttons},
    closeRunBuilder:()=>{element('runSetupDrawer').close()},toast:()=>{},selectLog:()=>{},refresh:async()=>{refreshes++}};
  vm.createContext(context);vm.runInContext(source,context);await element('reviewRun').onclick();
  assert(!html.includes('<input'));assert(html.includes('Recorded engine · Recorded build'));assert(html.includes('id="startRunError"'));assert(html.includes('role="alert"'));
  const button={textContent:'Start run',disabled:false};await actions[1].click(button);
  assert.equal(element('startRunError').hidden,false);assert.equal(element('startRunError').textContent,'Model settings changed after review.');
  assert(element('startRunError').focused&&element('startRunError').scrolled);assert(!element('dialog').closed);
  assert.equal(button.disabled,false);assert.equal(button.textContent,'Start run');
  assert.equal(submitted.identity.model_name,config.model);
  assert(!Object.hasOwn(submitted,'repeat'));assert(!fs.readFileSync('ui/index.html','utf8').includes('id="repeat"'));
  fail=false;await actions[1].click(button);
  assert.equal(submitted.identity.quantization,undefined);assert.equal(submitted.identity.server_name,'Recorded engine');
  assert.equal(submitted.models_revision,'model-revision');assert.equal(submitted.task_bundles.example,'fixture-hash');
  assert.equal(element('startRunError').hidden,true);assert.equal(element('dialog').closed,true);assert.equal(refreshes,1);
  assert.equal(element('runSetupDrawer').closed,true);
  console.log('Start run: recorded setup is shown without duplicate inputs; errors stay visible; configuration and revision checks survive retry.');
})().catch(error=>{console.error(error);process.exit(1)});

const assert=require('node:assert/strict');
const forms=require('../ui/model-picker.js');
const values={name:'Example',model:'served-alias',base_url:'http://host:8000/v1/',hardware:'Inference machine',max_tokens:'262144',context_window:''};
const extra={extra:{reasoning:{enabled:true}},custom:[1,2]};
const entry=forms.entry(values,extra);
assert.equal(entry.max_tokens,262144);
assert.equal(entry.base_url,'http://host:8000/v1');
assert.equal('context_window' in entry,false);
assert.deepEqual(entry.extra,extra.extra);
entry.custom.push(3);assert.deepEqual(extra.custom,[1,2]);
for(const value of ['',0,-1,'1.2','Infinity']) assert.throws(()=>forms.entry({...values,max_tokens:value}));
assert.equal(forms.uniqueName('Example',[{name:'Example'},{name:'Example-2'}]),'Example-3');
assert.throws(()=>forms.entry(values,[]));
console.log('Model form checks passed.');

assert.throws(()=>forms.entry(values,{extra:{max_tokens:1024}}),/override/);
assert.equal(forms.entry(values,{extra:{max_tokens:262144}}).extra.max_tokens,262144);

const original={custom:{preserve:true},models:[{name:'Keep',extra:{thinking:true}},{name:'Remove',model:'same-id'}]};
assert.deepEqual(forms.withoutModel(JSON.stringify(original),'Remove'),{custom:original.custom,models:[original.models[0]]});
assert.equal(original.models.length,2);
assert.deepEqual(forms.withoutModel(JSON.stringify({models:[{name:'Only'}]}),'Only'),{models:[]});
assert.throws(()=>forms.withoutModel(JSON.stringify(original),'Missing'),/changed/);

assert.equal(forms.entry({...values,api_key:'fixture-secret'},extra).api_key,'fixture-secret');
assert.equal(forms.entry(values,{api_key:'existing-secret'}).api_key,'existing-secret');
assert.equal('api_key' in forms.entry({...values,api_key:''},{api_key:'existing-secret'}),false);

// Credentials must persist without crossing endpoint boundaries.
const {ServerKeyMemory}=forms;
const memoryData=new Map(),storage={getItem:k=>memoryData.get(k)??null,setItem:(k,v)=>memoryData.set(k,v)};
const keys=new ServerKeyMemory(storage),server='http://localhost:30000/testing/v1';
assert(keys.remember(server,'fixture-key'));
assert.equal(new ServerKeyMemory(storage).recall('http://127.0.0.1:30000/testing/v1/models').key,'fixture-key');
for(const other of ['http://127.0.0.1:30001/testing/v1','http://other.invalid:30000/testing/v1','https://localhost:30000/testing/v1','http://localhost:30000/other/v1'])assert.equal(keys.recall(other),null);
assert.equal(keys.recall('http://host:8000/v1',[{base_url:'http://host:8000',api_key:'saved-model-key'}]).key,'saved-model-key');
assert.equal(keys.recall('http://host:8000/v1',[{base_url:'http://host:8000',api_key:'one'},{base_url:'http://host:8000/v1',api_key:'two'}]),null);
assert.equal(new ServerKeyMemory({getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}}).remember(server,'key'),false);
assert.match(ServerKeyMemory.rejection({error:'Model discovery failed (HTTP 401)'},''),/No key was sent/);
assert.match(ServerKeyMemory.rejection({error:'Model discovery failed (HTTP 401)'},'wrong'),/server rejected this API key/);
console.log('Server keys: persistent recall, endpoint isolation, saved-model fallback, ambiguous-key handling and clear authentication messages passed.');

// Exercise the actual form: only successful, still-current inspections save a key.
(async()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 const elements={},$=id=>elements[id]??={value:'',textContent:'',innerHTML:'',open:true,classList:{add(){},remove(){}},addEventListener(){},querySelectorAll(){return []},close(){this.open=false}};
 const state={model_library_available:true,models_revision:'fixture',model_configs:[]};
 let answer,finish,request,html;
 const ctx={URL,structuredClone,window:{localStorage:storage},InferenceProfileEditor:class{static markup(){return ''}mount(){}apply(x){return x}}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('ui/model-picker.js','utf8')+'\nglobalThis.Picker=ModelPicker',ctx);
 const picker=new ctx.Picker({getState:()=>state,$,esc:String,dialog:(title,body)=>{html=body;$('dialog').open=true},refresh:async()=>{},toast:()=>{},canOpen:()=>true,
 api:async(path,body)=>{request={path,body};return answer==='pending'?await new Promise(resolve=>{finish=resolve}):structuredClone(answer)}});
 picker.open('server');
 assert(!html.includes('API key (optional)'));assert(html.includes('Successful keys are remembered'));
 $('mf-base_url').value=server;$('mf-base_url').oninput();assert.equal($('mf-api_key').value,'fixture-key');
 $('mf-base_url').value='http://other.invalid:8000/v1';$('mf-base_url').oninput();assert.equal($('mf-api_key').value,'');
 $('mf-api_key').value='not-yet-valid';$('mf-api_key').oninput();
 answer={base_url:'http://other.invalid:8000/v1',models:[],error:'Model discovery failed (HTTP 401)'};
 await $('inspectModelEndpoint').onclick();assert.equal(keys.recall(answer.base_url),null);assert.match($('modelDiscoveryStatus').textContent,/server rejected/);
 $('mf-api_key').value='accepted-fixture';
 answer={base_url:'http://other.invalid:8000/v1',models:[{model_id:'fixture'}],reachable:true,kind:'OpenAI-compatible model list'};
 await $('inspectModelEndpoint').onclick();
 assert.equal(request.body.api_key,'accepted-fixture');assert.equal(keys.recall(answer.base_url).key,'accepted-fixture');assert.match($('serverKeyHelp').textContent,/remembered/);
 picker.open('server');$('mf-base_url').value=answer.base_url;$('mf-base_url').oninput();assert.equal($('mf-api_key').value,'accepted-fixture');
 $('mf-api_key').value='late-key';answer='pending';const pending=$('inspectModelEndpoint').onclick();
 $('mf-base_url').value='http://third.invalid:8000/v1';$('mf-base_url').oninput();
 finish({base_url:'http://other.invalid:8000/v1',models:[{model_id:'fixture'}],reachable:true});await pending;
 assert.equal(keys.recall('http://third.invalid:8000/v1'),null);assert.equal(keys.recall('http://other.invalid:8000/v1').key,'accepted-fixture');
 assert.equal($('mf-base_url').value,'http://third.invalid:8000/v1');assert.match($('modelDiscoveryStatus').textContent,/details changed/);
 console.log('Model form: successful keys survive reopening; rejected and stale responses cannot save or send keys to another endpoint.');
})().catch(error=>{console.error(error);process.exitCode=1});

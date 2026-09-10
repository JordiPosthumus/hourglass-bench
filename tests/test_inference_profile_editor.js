'use strict';
const assert = require('node:assert/strict');
const Editor = require('../ui/inference-profile.js');
const metadata = {
  era:'explicit-v1', mapping_version:'request-api-v1',
  lanes:{standard:'No thinking mode (manual)', thinking:'Thinking', 'non-thinking':'Non-thinking'},
  fields:{temperature:'Temperature', enable_thinking:'Thinking enabled', reasoning_effort:'Reasoning effort', seed:'Seed', preserve_thinking:'Preserve thinking history'},
  backends:{mtplx:{label:'MTPLX', fields:{temperature:'temperature', enable_thinking:'enable_thinking', reasoning_effort:'reasoning_effort'}, server_managed_fields:['preserve_thinking']}},
};
const candidate = value => [{value, source:'README.md'}];
const source = (lane, suggested) => ({repository:'Qwen/Qwen3.8-27B', revision:'a'.repeat(40), lane,
  suggested, candidates:Object.fromEntries(Object.entries(suggested).map(([k,v])=>[k,candidate(v)])),
  notes:[], card_supported:true, conflicts:{}});
const thinking = source('thinking', {temperature:1, enable_thinking:true, reasoning_effort:'xhigh', preserve_thinking:true});
const nonthinking = source('non-thinking', {enable_thinking:false, temperature:0.7, preserve_thinking:true});
nonthinking.candidates.temperature = [...candidate(1), {value:0.7, source:'generation_config.json'}];
const result = {repository:thinking.repository, revision:thinking.revision, proposals:{thinking, 'non-thinking':nonthinking}};

async function setup(pull = async () => structuredClone(result), copy, catalog=metadata) {
  const elements = new Map();
  const $ = id => {
    if (!elements.has(id)) {
      let value = '';
      elements.set(id, {get value(){return value;}, set value(v){value=String(v);}, innerHTML:'', textContent:'', open:true});
    }
    return elements.get(id);
  };
  const requests = [];
  const editor = new Editor({$, esc:String, copy, preview:()=>{}, api:async (url,body)=>{
    if (url === '/api/inference-profiles') return catalog;
    requests.push(body); return pull();
  }});
  await editor.mount();
  $('ip-repository').value = thinking.repository;
  $('ip-backend').value = 'mtplx';
  $('ip-value-seed').value = 17;
  return {editor,$,requests};
}

(async () => {
  const {editor,$,requests} = await setup();
  const before = editor.values();
  await editor.pull();
  assert.deepEqual(requests,[{repository:thinking.repository, revision:'main'}]);
  assert.deepEqual(editor.values(),before, 'Pull must not apply settings');
  assert.equal($('ip-lane').value,'', 'Pull must not select a mode');
  assert.equal(editor.source,null);
  assert.match($('ip-proposal').innerHTML,/Use Thinking settings/);
  assert.match($('ip-proposal').innerHTML,/Not overridden by Hourglass/);
  const choose = mode => { $('ip-proposal-mode').value=mode; $('ip-proposal-mode').onchange(); };
  $('ip-accept').onclick();
  assert.equal($('ip-lane').value,'thinking');
  assert.equal(editor.values().reasoning_effort,'xhigh');
  assert.equal(editor.values().seed,17);
  choose('non-thinking');
  $('ip-accept').onclick();
  assert.equal($('ip-lane').value,'non-thinking');
  assert.equal(editor.values().enable_thinking,false);
  assert.equal(editor.values().temperature,0.7,'Uses mode-specific recommendations');
  assert.equal('preserve_thinking' in editor.values(),false);
  assert.deepEqual(editor.serverManaged,['preserve_thinking']);
  assert.equal('reasoning_effort' in editor.values(),false,'Previous imported effort must not leak across modes');
  assert.equal(editor.values().seed,17);
  assert.equal(editor.source.lane,'non-thinking');
  assert.equal(requests.length,1,'Switching proposals must not fetch again');
  const entry = editor.apply({max_tokens:262144, context_window:262144});
  assert.equal(entry.inference_profile.lane,'non-thinking');
  assert.equal(entry.inference_profile.source.lane,'non-thinking');
  assert.deepEqual(entry.inference_profile.server_managed,['preserve_thinking']);
  assert.equal(entry.inference_profile.source.suggested.preserve_thinking,true);
  assert.equal(entry.max_tokens,262144);
  assert.equal(entry.context_window,262144);
  choose('thinking');
  $('ip-accept').onclick();
  $('ip-value-reasoning_effort').value='medium';
  choose('non-thinking');
  $('ip-accept').onclick();
  assert.equal(editor.values().reasoning_effort,'medium','Owner edits must be preserved for validation');
  const accepted=structuredClone(editor.source);
  $('ip-repository').value='Other/model';
  choose('thinking');
  $('ip-accept').onclick();
  assert.deepEqual(editor.source,accepted,'Stale source cannot be accepted');
  assert.match($('ip-source-status').textContent,/Source changed/);

  let resolve;
  const pending = await setup(()=>new Promise(r=>{resolve=r;}));
  const pulling=pending.editor.pull();
  pending.$('ip-lane').value='thinking';
  resolve(result); await pulling;
  assert.match(pending.$('ip-source-status').textContent,/Recommendations loaded/,'Mode changes do not invalidate all-mode download');
  const stale = await setup(()=>new Promise(r=>{resolve=r;}));
  const stalePull=stale.editor.pull();
  stale.$('ip-revision').value='other';
  resolve(result); await stalePull;
  assert.equal(stale.editor.pendingPull,null);
  assert.equal(stale.$('ip-proposal').innerHTML,'');
  const failed = await setup(async()=>{throw Error('Download failed');});
  await failed.editor.pull();
  assert.equal(failed.$('ip-pull').disabled,false);
  assert.equal(failed.$('ip-source-status').textContent,'Download failed');
  const nativeCopy={sampling_era:'pi-native-v1',pi_thinking_level:'xhigh',output_budget:'pi',inference_profile:{backend:'mtplx',backend_version:'fixture',route:{kind:'direct'}}};
  const native=await setup(undefined,nativeCopy,{...metadata,native_era:'pi-native-v1'});
  assert.equal(native.$('ip-custom-settings').hidden,true);
  assert.equal(native.$('ip-thinking-wrap').hidden,false);
  assert.equal(native.$('ip-thinking').value,'xhigh');
  const nativeEntry=native.editor.apply({max_tokens:262144,context_window:262144,pi_model:{thinkingLevelMap:{xhigh:'xhigh'}}});
  assert.equal(nativeEntry.pi_thinking_level,'xhigh');
  assert.equal(nativeEntry.output_budget,'pi');
  assert.equal(nativeEntry.sampling_era,'pi-native-v1');
  assert.equal('values' in nativeEntry.inference_profile,false);
  assert.equal(nativeEntry.pi_model.thinkingLevelMap.xhigh,'xhigh');
  console.log('Inference profile editor checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

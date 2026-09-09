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

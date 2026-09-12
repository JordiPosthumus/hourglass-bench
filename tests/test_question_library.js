'use strict';
const assert=require('node:assert/strict');
const {summarize,sort}=require('../ui/question-library.js');
const tasks=[{id:'A',title:'Alpha',points:2,task_sha:'current',task_bundle_sha:'bundle'},
             {id:'B',title:'Beta',points:1,task_sha:'b'}, {id:'C',title:'Unknown',points:null}];
const jobs={done:[{id:'saved'},{id:'archived',archived:true}],running:[],pending:[]};
const row=(id,extra={})=>({task:'A',evaluation_id:'saved',run_id:id,model:'one',task_sha:'current',status:'completed',solved:true,duration_s:20,...extra});
const rows=[row('correct'),row('wrong',{solved:false,duration_s:40}),row('timeout',{status:'timeout',duration_s:900}),row('error',{status:'error',duration_s:7}),
  row('correct'),row('probe',{evaluation_id:null}),row('old',{task_sha:'old'}),row('copied',{repair_inherited:true}),
  row('skipped',{score_reason:'unsupported_vision'}),row('not-reached',{status:'not_attempted'}),
  row('changed-assets',{task_bundle_sha:'other-bundle'}),row('other',{task:'B',task_sha:'b',model:'two',evaluation_id:'archived',duration_s:0})];
const before=JSON.stringify([tasks,rows,jobs]),stats=summarize(tasks,rows,jobs);
assert.deepEqual(stats.get('A'),{attempts:4,answered:2,wrong:1,timeouts:1,errors:1,timed:2,seconds:60,average:30,wrongRate:.5,timeoutRate:.25,errorRate:.25});
assert.equal(stats.get('B').average,0);assert.equal(stats.get('C').average,null);assert.equal(stats.get('C').wrongRate,null);
assert.equal(summarize(tasks,rows,jobs,'two').get('A').attempts,0);
assert.deepEqual(sort(tasks,stats,'average','desc').map(t=>t.id),['A','B','C']);
assert.deepEqual(sort(tasks,stats,'average','asc').map(t=>t.id),['B','A','C']);
assert.deepEqual(sort(tasks,stats,'points','asc').map(t=>t.id),['B','A','C']);
assert.deepEqual(sort(tasks,stats,'wrongRate','desc').map(t=>t.id),['A','B','C']);
assert.equal(JSON.stringify([tasks,rows,jobs]),before);
console.log('Question library: current revisions, saved/archived runs, deduplication, model filter, missing data, rates and sorting passed.');

const fs=require('node:fs'),vm=require('node:vm'),app=fs.readFileSync('ui/app.js','utf8'),html=fs.readFileSync('ui/index.html','utf8');
const keys=['title','tier','points','average','wrongRate','timeoutRate','errorRate','attempts'];
const buttons=keys.map(key=>({dataset:{librarySort:key,label:key},attrs:{},closest(){return {setAttribute:(k,v)=>this.attrs[k]=v};}}));
const reset={};let renders=0;
const context={librarySort:'order',libraryDirection:'desc',limit:20,$:()=>reset,
  document:{querySelectorAll:()=>buttons},renderLibrary:()=>{renders++;vm.runInContext('updateLibrarySortHeaders()',context);}};
vm.createContext(context);
vm.runInContext(app.slice(app.indexOf('function updateLibrarySortHeaders()'),app.indexOf("$('liveStop').onclick=")),context);
for(const button of buttons){
  button.onclick();assert.equal(context.librarySort,button.dataset.librarySort);
  const direction=context.libraryDirection;assert.equal(button.attrs['aria-sort'],direction==='asc'?'ascending':'descending');
  button.onclick();assert.notEqual(context.libraryDirection,direction);
}
reset.onclick();assert.equal(context.librarySort,'order');assert.equal(renders,17);
assert(!/id="(?:selectAll|selectMatching|clearSelection|selectionCount|librarySort|libraryDirection)"/.test(html));
assert(!app.includes("store.get('selected'"));assert(!app.includes('data-task='));
for(const key of keys)assert(html.includes(`data-library-sort="${key}"`));
console.log('Question headings: all eight columns toggle direction with aria-sort; reset restores bank order; subset-selection controls are absent.');

'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
(async()=>{
 const app=fs.readFileSync('ui/app.js','utf8');
 const source=app.slice(app.indexOf('async function renderCurrentQuestion(){'),app.indexOf('\nfunction renderTps('));
 const elements={},element=id=>elements[id]??={classList:{add(){},remove(){}},textContent:'',innerHTML:''};
 const job={id:'job1',current_task:'fixture',model:'model',repeat:1};
 const task={id:'fixture',title:'Fixture',prompt:'PROMPT',files:[],images:[],options:[{id:'001',text:'ACTUAL'}],presentation:{job:'job1',repeat:1,exact:true}};
 let result=task,paths=[];
 const context={$:element,S:{jobs:{running:[job]},results:[]},currentQuestionKey:'',currentQuestionRequest:0,
  esc:String,workspaceFilesHtml:()=>'',api:async path=>{paths.push(path);return structuredClone(result)}};
 vm.createContext(context);vm.runInContext(source,context);
 await context.renderCurrentQuestion();
 assert.equal(paths[0],'/api/task?id=fixture&job=job1');
 assert.match(element('currentQuestionOptions').innerHTML,/001 — ACTUAL/);
 // A checkpoint may advance to another repeat without the result index changing.
 result={...task,options:[{id:'001',text:'SECOND REPEAT'}],presentation:{...task.presentation,repeat:2}};
 await context.renderCurrentQuestion();
 assert.match(element('currentQuestionOptions').innerHTML,/SECOND REPEAT/);
 assert.match(element('currentQuestionStatus').textContent,/Repeat 2/);
 // An old controller's unqualified bank view must never be shown as exact.
 result={...task};delete result.presentation;job.repeat=2;
 await context.renderCurrentQuestion();
 assert.match(element('currentQuestionStatus').textContent,/updated controller/);
 // An old-controller attachment uses its exact options, never static image metadata options.
 job.repeat=1;paths=[];
 context.api=async path=>{paths.push(path);if(path.startsWith('/api/task?'))return {id:'fixture'};if(path.startsWith('/run-previews/'))return {...task,vision:true,presentation:{...task.presentation,transport:'attachment'}};return {images:['/fixture.png'],options:[{id:'999',text:'OBSOLETE'}]}};
 await context.renderCurrentQuestion();
 assert.match(element('currentQuestionOptions').innerHTML,/001 — ACTUAL/);
 assert.doesNotMatch(element('currentQuestionOptions').innerHTML,/OBSOLETE/);
 assert.match(element('currentQuestionImages').innerHTML,/fixture.png/);
 console.log('Current viewer: frozen job options, advancing repeats, exact legacy attachment, and stale image-option rejection passed.');
})().catch(error=>{console.error(error);process.exit(1)});

const assert=require('node:assert/strict'),p=require('../ui/score-predictor.js');
const epoch=1700000000;
function job(id,elapsed=3600,state='final'){return {id,started:epoch,ended:state==='final'?epoch+elapsed:null,benchmark_version:'fixture',scoring_policy:'net-hour-v3',round_policy:'rounds',question_timeout_policy:'900s',expected:['a','b','c'].map(task=>({task,task_bundle_sha:task,weight:2})),hour_score:{state,elapsed_s:elapsed,hourglass_score:4}};}
function row(id,task,time,solved=true,extra={}){return {evaluation_id:id,task,run:1,status:'completed',solved,ts:new Date((epoch+time)*1000).toISOString(),...extra};}
const a=job('a'),b=job('b'),live=job('live',600,'in_progress');
const rows=[row('a','a',100),row('a','b',200),row('b','a',300),row('b','b',400),row('live','a',150)];
let out=p.predict(live,[a,b,live],rows);assert.equal(out.status,'experimental');assert.equal(out.training_runs,2);assert.equal(out.prefix_length,1);assert(Math.abs(out.value-4)<1e-9);
assert.equal(p.predict(live,[a,live],rows).status,'unavailable');
assert.equal(p.predict(a,[a,b],rows).status,'unavailable');
const partial={...b,hour_score:{...b.hour_score,state:'partial',elapsed_s:1200}};
assert.equal(p.predict(live,[a,partial],rows).status,'unavailable');
assert.equal(p.predict(live,[a,{...b,scoring_policy:'net-hour-v2'}],rows).status,'unavailable');
assert.equal(p.predict(live,[a,{...b,repair:{}}],rows).status,'unavailable');
assert.equal(p.predict(live,[a,{...b,expected:b.expected.map(t=>({...t,task_bundle_sha:'changed'}))}],rows).status,'unavailable');
assert.equal(p.predict(live,[a,b],rows.filter(r=>!(r.evaluation_id==='b'&&r.task==='b'))).status,'unavailable');
const mixed=[row('a','a',100,false),row('a','b',200,false,{score_reason:'abstained'}),row('a','c',300,false,{status:'timeout'}),row('a','a',100,false),row('a','c',3700),row('a','b',400,false,{status:'error'})];
assert.deepEqual(p.events(a,mixed).map(e=>e.value),[-1,0,0]);
const paused={...a,resume_count:1,active_intervals:[{start:epoch,end:epoch+100},{start:epoch+1000,end:epoch+2000}]};
assert.equal(p.events(paused,[row('a','a',1100)])[0].time,200);
const model=p.fit([[0,0],[1,0],[0,1],[1,1]],[1,3,4,6],0.000001);
assert(Math.abs(model.intercept-1)<0.00001);assert(Math.abs(model.weights[0]-2)<0.00001);assert(Math.abs(model.weights[1]-3)<0.00001);
const stable=p.fit([[1,1,1],[1,1,1]],[2,4]);assert.equal(stable.intercept,3);assert(stable.weights.every(w=>w===0));
const fs=require('fs'),app=fs.readFileSync('ui/app.js','utf8'),html=fs.readFileSync('ui/index.html','utf8');
assert(app.includes("scoreLabel=predicting?'Predicted final score':'Total points'"));assert(app.includes('Earned: '));assert(html.indexOf('/score-predictor.js')<html.indexOf('/app.js'));
console.log('Prefix ridge: fit, signed outcomes, elapsed time, pauses, deduplication, history eligibility, missing records, final-score separation and UI loading passed.');

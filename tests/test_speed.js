const assert=require('node:assert/strict');
const {compareRunSpeed}=require('../ui/speed.js');
const row=(id,model,task,duration,extra={})=>({evaluation_id:id,model,task,run:1,status:'completed',solved:true,duration_s:duration,completion_tokens:100,task_sha:task+'hash',benchmark_version:'2.0.0',node:'machine',pi_version:'0.85.1',pi_lock_sha256:'frozen',model_config_hash:model,ts:'2026-01-01T00:00:00Z',...extra});
const job={id:'current',model:'new',started:Date.parse('2026-01-02T00:00:00Z')/1000};
const tasks=[{id:'text',vision:false},{id:'image',vision:true}];
const current=[row('current','new','text',10),row('current','new','image',30)];
const previous=[row('previous','old','text',20),row('previous','old','image',60,{solved:false})];
let r=compareRunSpeed([...previous,...current],job,'all',tasks);
assert.equal(r.current.seconds_per_attempt,20);assert.equal(r.comparisons[0].current_speed_ratio,2);assert.equal(r.comparisons[0].accuracy,.5);
r=compareRunSpeed([...previous,...current],job,'vision',tasks);assert.equal(r.current.attempts,1);assert.equal(r.current.seconds_per_attempt,30);
for(const change of [{task_sha:'changed'},{benchmark_version:'1.3.0'},{node:'other'},{pi_lock_sha256:'other'},{duration_s:0},{score_reason:'unsupported_vision'},{status:'error'},{ts:'2026-01-03T00:00:00Z'}]){
 r=compareRunSpeed([previous[0],{...previous[1],...change},...current],job,'all',tasks);assert.equal(r.comparisons.length,0,JSON.stringify(change));
}
assert.equal(compareRunSpeed([previous[0],...current],job,'all',tasks).comparisons.length,0);
assert.equal(compareRunSpeed([],job).current,null);
assert.equal(compareRunSpeed(current,job).comparisons.length,0);
const retry=[...previous,row('current','new','text',90,{status:'error'}),...current];assert.equal(compareRunSpeed(retry,job).current.seconds_per_attempt,20);
const skipped=[...previous,...current,row('current','new','skip',0,{score_reason:'wrong_streak_limit'})];assert.equal(compareRunSpeed(skipped,job).current.attempts,2);
const newer=previous.map(x=>({...x,evaluation_id:'newer',ts:'2026-01-01T12:00:00Z',duration_s:x.duration_s/2}));r=compareRunSpeed([...previous,...newer,...current],job);assert.equal(r.comparisons.length,1);assert.equal(r.comparisons[0].id,'newer');
console.log('Speed comparisons: matched attempts, lanes, timing, versions, machines, skips, retries and latest model run passed.');

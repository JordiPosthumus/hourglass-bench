'use strict';
// Match exactly the completed attempt set, never compare different question mixes.
function compareRunSpeed(rows,job,lane='all',tasks=[]){
  const raw=rows.filter(r=>r.evaluation_id===job.id);
  const vision=new Map(tasks.map(t=>[t.id,!!t.vision]));
  const key=r=>r.task+'\0'+(r.run??1);
  const measured=r=>r.status==='completed'&&!r.score_reason&&Number.isFinite(r.duration_s)&&r.duration_s>0;
  const effective=rs=>{const m=new Map();for(const r of rs){const old=m.get(key(r));if(!old||r.status==='completed'||old.status!=='completed')m.set(key(r),r)}return [...m.values()]};
  const current=effective(raw).filter(r=>measured(r)&&(lane==='all'||vision.has(r.task)&&vision.get(r.task)===(lane==='vision')));
  if(!current.length)return {current:null,comparisons:[],reason:'Speed comparisons appear after a measured attempt completes.'};
  const metric=rs=>{const duration=rs.reduce((n,r)=>n+r.duration_s,0);return {attempts:rs.length,seconds_per_attempt:duration/rs.length,accuracy:rs.filter(r=>r.solved).length/rs.length,output_tokens_per_second:rs.reduce((n,r)=>n+(r.completion_tokens||0),0)/duration}};
  const result={current:metric(current),comparisons:[],reason:'No earlier run matches these completed attempts, question versions, harness and machine yet.'};
  const version=current[0].benchmark_version,node=current[0].node,pi=current[0].pi_version,lock=current[0].pi_lock_sha256;
  if(!version||!node||node==='unknown'||current.some(r=>r.benchmark_version!==version||r.node!==node||r.pi_version!==pi||r.pi_lock_sha256!==lock||!r.task_sha)){
    result.reason='Comparable benchmark, question and machine metadata is missing or mixed.';return result;
  }
  const groups=new Map();
  for(const r of rows){if(!r.evaluation_id||r.evaluation_id===job.id||r.model===job.model)continue;if(!groups.has(r.evaluation_id))groups.set(r.evaluation_id,[]);groups.get(r.evaluation_id).push(r)}
  const start=job.started||Math.min(...raw.map(r=>Date.parse(r.ts)/1000-(r.duration_s||0)).filter(Number.isFinite));
  for(const [id,rs] of groups){
    const ended=Math.max(...rs.map(r=>Date.parse(r.ts)/1000));if(!Number.isFinite(ended)||ended>start)continue;
    const indexed=new Map(effective(rs).map(r=>[key(r),r]));
    const matching=current.map(r=>indexed.get(key(r)));
    if(matching.some((r,i)=>!r||!measured(r)||r.task_sha!==current[i].task_sha||r.benchmark_version!==version||r.node!==node||r.pi_version!==pi||r.pi_lock_sha256!==lock))continue;
    if(new Set(matching.map(r=>r.model)).size!==1||new Set(matching.map(r=>r.model_config_hash)).size!==1)continue;
    const m=metric(matching);result.comparisons.push({...m,id,model:matching[0].model,ended,current_speed_ratio:m.seconds_per_attempt/result.current.seconds_per_attempt});
  }
  // One latest matching run per model avoids repeated runs dominating the display.
  result.comparisons.sort((a,b)=>b.ended-a.ended);
  result.comparisons=result.comparisons.filter((r,i,a)=>a.findIndex(x=>x.model===r.model)===i);
  return result;
}
if(typeof module!=='undefined')module.exports={compareRunSpeed};

'use strict';
// Experimental display-only prefix regressions. Never used by execution or scoring.
const ScorePredictor=(()=>{
  const VERSION='prefix-ridge-v1',ALPHA=0.1;
  const neutral=new Set(['unsupported_vision','abstained','question_timeout','not_attempted','turn_limit','stopped','unfinished','wrong_streak_limit','five_wrong_in_row']);
  function signature(job){
    if(!job.expected?.length||job.expected.some(t=>!t.task_bundle_sha||!Number.isFinite(t.weight)))return null;
    return JSON.stringify([job.benchmark_version,job.scoring_policy,job.round_policy,job.question_timeout_policy,job.expected.map(t=>[t.task,t.task_bundle_sha,t.weight,t.repeat||1])]);
  }
  function events(job,rows){
    if(job.repair||job.results_reset||job.hour_timing_unknown||job.resume_count&&!job.active_intervals?.length)return [];
    const intervals=job.active_intervals?.length?job.active_intervals:job.started?[{start:job.started,end:job.ended}]:[];
    const weights=new Map((job.expected||[]).map(t=>[t.task,t.weight]));
    const effective=new Map();
    for(const r of rows){
      if(r.evaluation_id!==job.id||!weights.has(r.task)||!['completed','timeout'].includes(r.status))continue;
      if(['not_attempted','stopped','unfinished','wrong_streak_limit','five_wrong_in_row'].includes(r.score_reason)||r.repair_inherited)continue;
      const ts=Date.parse(r.ts)/1000;
      if(!Number.isFinite(ts)||!intervals.length||ts<intervals[0].start||job.ended&&ts>job.ended)continue;
      const time=intervals.reduce((n,p)=>n+Math.max(0,Math.min(ts,p.end||ts)-p.start),0);
      if(time>3600)continue;
      const key=r.task+'|'+(r.run??1),value=r.status==='timeout'?0:r.solved?weights.get(r.task):neutral.has(r.score_reason)||neutral.has(r.termination)?0:-1;
      const event={key,time,value,ts};
      if(!effective.has(key)||effective.get(key).ts<=ts)effective.set(key,event);
    }
    return [...effective.values()].sort((a,b)=>a.ts-b.ts||a.key.localeCompare(b.key));
  }
  // Centered dual ridge: solve an m-by-m system, efficient with few saved runs.
  function fit(xs,ys,alpha=ALPHA){
    const m=xs.length,d=xs[0].length;
    const mean=Array.from({length:d},(_,j)=>xs.reduce((s,x)=>s+x[j],0)/m),base=ys.reduce((a,b)=>a+b,0)/m;
    const centered=xs.map(x=>x.map((v,j)=>v-mean[j]));
    const a=centered.map((x,i)=>[...centered.map((y,j)=>x.reduce((s,v,k)=>s+v*y[k],0)+(i===j?alpha:0)),ys[i]-base]);
    for(let i=0;i<m;i++){
      let pivot=i;for(let k=i+1;k<m;k++)if(Math.abs(a[k][i])>Math.abs(a[pivot][i]))pivot=k;
      [a[i],a[pivot]]=[a[pivot],a[i]];const v=a[i][i];
      for(let j=i;j<=m;j++)a[i][j]/=v;
      for(let k=0;k<m;k++)if(k!==i){const f=a[k][i];for(let j=i;j<=m;j++)a[k][j]-=f*a[i][j];}
    }
    const weights=Array.from({length:d},(_,j)=>centered.reduce((s,x,i)=>s+x[j]*a[i][m],0));
    return {weights,intercept:base-weights.reduce((s,w,j)=>s+w*mean[j],0),alpha};
  }
  function predict(job,jobs,rows){
    const h=job.hour_score,unavailable=reason=>({version:VERSION,status:'unavailable',reason});
    if(h?.state!=='in_progress')return unavailable('Forecasts are shown only during active runs.');
    const sig=signature(job),prefix=events(job,rows),n=prefix.length;
    if(!sig||!n||!Number.isFinite(h.elapsed_s))return unavailable('Waiting for a scored question and complete timing metadata.');
    const samples=[],seen=new Set();
    for(const other of jobs){
      if(other.id===job.id||seen.has(other.id)||signature(other)!==sig)continue;
      seen.add(other.id);const score=other.hour_score;
      if(score?.state!=='final'||score.elapsed_s<3600||!Number.isFinite(score.hourglass_score))continue;
      const history=events(other,rows);
      if(history.length<n||Math.abs(history.reduce((s,e)=>s+e.value,0)-score.hourglass_score)>0.0001)continue;
      if(prefix.some((e,i)=>e.key!==history[i].key))continue;
      samples.push({x:[...history.slice(0,n).map(e=>e.value/2),history[n-1].time/3600],y:score.hourglass_score,id:other.id});
    }
    if(samples.length<2)return {...unavailable('Waiting for at least two compatible full-hour runs at this question prefix.'),training_runs:samples.length,prefix_length:n};
    const model=fit(samples.map(s=>s.x),samples.map(s=>s.y));
    const x=[...prefix.map(e=>e.value/2),h.elapsed_s/3600];
    const value=model.intercept+x.reduce((s,v,i)=>s+v*model.weights[i],0);
    if(!Number.isFinite(value))return unavailable('Prediction could not be computed.');
    return {version:VERSION,status:'experimental',value,training_runs:samples.length,prefix_length:n,training_ids:samples.map(s=>s.id),model};
  }
  return {predict,fit,events,signature,VERSION};
})();
if(typeof module!=='undefined')module.exports=ScorePredictor;

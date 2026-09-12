'use strict';
function questionWeight(t){
  if(t.section==='challenge')return 2;
  if(['math','math_logic'].includes(t.section))return {advanced_high_school:1,advanced_undergraduate:1.5,graduate:2}[t.level]??1;
  const max=['chart','charts'].includes(t.section)||t.kind==='chart-vqa'?10:t.section==='games'?5:null;
  return max&&typeof t.tier==='number'&&Number.isFinite(t.tier)?Math.round((1+(Math.min(max,Math.max(1,t.tier))-1)/(max-1))*1e6)/1e6:1;
}
// Mirrors hour_score.py; shared boundary fixtures test Python/browser parity.
function hourScore(job, rows, expected=[], now=Date.now()/1000){
  expected=expected.length?expected:(job.expected||[]);
  const tids=new Set(job.tasks||job.order||expected.map(t=>t.task));
  const vision=new Map(expected.map(t=>[t.task,!!t.vision]));
  if(job.repair&&!job._repair_rows_materialized){const own=rows.filter(r=>r.evaluation_id===job.id);rows=[...job.repair.retained.filter(r=>!own.some(x=>x.run_id===r.run_id&&x.repair_inherited)).map(r=>({...r,evaluation_id:job.id,repair_inherited:true})),...own];}
  const raw=rows.filter(r=>r.evaluation_id===job.id&&tids.has(r.task));
  let intervals=job.active_intervals;
  const timingKnown=!job.hour_timing_unknown&&(!job.resume_count||!!intervals?.length),started=job.started;
  if(!intervals?.length)intervals=started?[{start:started,end:job.ended}]:[];
  const activeAt=ts=>intervals.reduce((n,p)=>n+Math.max(0,Math.min(ts,p.end||ts)-p.start),0);
  const elapsed=timingKnown?activeAt(job.ended||now)+(job.repair?.base_elapsed_s||0):(job.progress?.elapsed_s||0);
  const events=[],within=[],after=new Set(),timeouts=new Set();let errors=0,unknown=0;
  for(const r of raw){
    if(['five_wrong_in_row','wrong_streak_limit'].includes(r.score_reason))continue;
    const ts=Date.parse(r.ts)/1000;
    if(!Number.isFinite(ts)||!r.repair_inherited&&(!intervals.length||ts<intervals[0].start)){unknown++;continue}
    const rowElapsed=r.repair_inherited?r.repair_elapsed_s:(job.repair?.base_elapsed_s||0)+activeAt(ts);
    if(rowElapsed>3600){if(r.status==='completed')after.add(r.task);continue}
    if(r.status==='timeout')timeouts.add(r.task);else if(r.status==='error')errors++;else if(r.status==='completed'){within.push(r);events.push([rowElapsed,r]);}
  }
  if(job.scoring_policy==='net-hour-v3'){const effective=new Map();for(const r of within)effective.set(r.task+'|'+(r.run??1),r);within.splice(0,within.length,...effective.values())}
  const available=timingKnown&&!unknown&&!job.results_reset,correct=new Set(within.filter(r=>r.solved).map(r=>r.task)),completed=new Set(within.map(r=>r.task));
  const netPolicy=['net-hour-v1','net-hour-v2','net-hour-v3'].includes(job.scoring_policy),neutral=['unsupported_vision','abstained','question_timeout','not_attempted','turn_limit','stopped','unfinished','wrong_streak_limit','five_wrong_in_row'];
  const wrong=new Set(within.filter(r=>!r.solved&&(!netPolicy||!neutral.includes(r.score_reason)&&!neutral.includes(r.termination))).map(r=>r.task).filter(t=>!correct.has(t)));
  const countReason=reason=>new Set(within.filter(r=>r.score_reason===reason).map(r=>r.task).filter(t=>!correct.has(t)&&!wrong.has(t))).size;
  const weights=new Map(expected.map(t=>[t.task,t.weight??questionWeight(t)]));
  const weighted=ids=>available?Math.round([...ids].reduce((n,id)=>n+(weights.get(id)??1),0)*1e6)/1e6:null;
  const lanes={};
  for(const lane of ['text','vision']){
    const rs=within.filter(r=>(vision.has(r.task)?vision.get(r.task):r.kind==='chart-vqa'||['chart','charts'].includes(r.section))===(lane==='vision'));
    const correctLane=new Set(rs.filter(r=>r.solved).map(r=>r.task));
    lanes[lane]={points:available?correctLane.size:null,weighted_points:available?Math.round((weighted(correctLane)-(netPolicy?[...new Set(rs.map(r=>r.task))].filter(t=>wrong.has(t)).length:0))*1e6)/1e6:null,completed_questions:new Set(rs.map(r=>r.task)).size};
  }
  const repeats=new Map(expected.map(t=>[t.task,t.repeat??1]));
  const discovery={};
  for(const domain of ['games','hourglass','dsg']){
    const group=expected.filter(t=>t.section==='repository_discovery'&&t.discovery_domain===domain&&tids.has(t.task)).map(t=>t.task);
    if(group.length)discovery[domain]={points:available?group.filter(t=>correct.has(t)).length:null,weighted_points:available?Math.round((weighted(new Set(group.filter(t=>correct.has(t))))-(netPolicy?group.filter(t=>wrong.has(t)).length:0))*1e6)/1e6:null,completed_questions:group.filter(t=>completed.has(t)).length,total_questions:group.length};
  }
  const cumulative=job.scoring_policy==='net-hour-v3';
  const attemptMap=new Map();for(const r of within)attemptMap.set(r.task+'|'+(r.run??1),r);
  const attempts=[...attemptMap.values()],correctAttempts=attempts.filter(r=>r.solved),wrongAttempts=attempts.filter(r=>!r.solved&&!neutral.includes(r.score_reason)&&!neutral.includes(r.termination));
  const gross=cumulative?(available?correctAttempts.reduce((n,r)=>n+(weights.get(r.task)??1),0):null):weighted(correct);
  const penalties=netPolicy?(cumulative?wrongAttempts.length:wrong.size):0;
  const total=available?Math.round((gross-penalties)*1e6)/1e6:null;
  if(cumulative){
    const apply=(sub,rs)=>{sub.points=available?rs.filter(r=>r.solved).length:null;sub.weighted_points=available?Math.round(rs.reduce((n,r)=>n+(r.solved?(weights.get(r.task)??1):!neutral.includes(r.score_reason)&&!neutral.includes(r.termination)?-1:0),0)*1e6)/1e6:null;};
    for(const lane of ['text','vision'])apply(lanes[lane],attempts.filter(r=>(vision.has(r.task)?vision.get(r.task):r.kind==='chart-vqa'||['chart','charts'].includes(r.section))===(lane==='vision')));
    for(const [domain,sub] of Object.entries(discovery)){const ids=new Set(expected.filter(t=>t.discovery_domain===domain).map(t=>t.task));apply(sub,attempts.filter(r=>ids.has(r.task)));}
  }
  const allFinished=tids.size>0&&[...tids].every(tid=>timeouts.has(tid)||Array.from({length:repeats.get(tid)??1},(_,i)=>i+1).every(n=>within.some(r=>r.task===tid&&(r.run??1)===n)));
  const final=available&&(elapsed>=3600||(allFinished&&!job.round_policy));
  const state=!available?'unavailable':final?'final':job.state==='running'?'in_progress':!started?'not_started':'partial';
  const horizon=final?3600:Math.max(0,Math.min(3600,elapsed));
  const totalAvailable=Math.round([...tids].reduce((n,tid)=>n+(weights.get(tid)??1),0)*1e6)/1e6;
  return {version:'hour-v1',window_s:3600,points:available?(cumulative?correctAttempts.length:correct.size):null,correct_tasks:available?[...correct].sort():[],breakdown:lanes,repository_discovery:discovery,
    score_version:'total-points-v1',hourglass_score:total,total_available_points:totalAvailable,
    weighted_version:'weighted-hour-v1',weighted_points:total,
    scoring_policy:job.scoring_policy??'weighted-hour-v1',gross_points:gross,net_points:netPolicy?total:null,penalty_points:penalties,abstained_questions:countReason('abstained'),unsupported_questions:countReason('unsupported_vision'),
    timeouts:timeouts.size,resolved_questions:new Set([...completed,...timeouts]).size,resolved_available_points:weighted(new Set([...completed,...timeouts])),question_timeout_policy:job.question_timeout_policy??null,
    completed_questions:completed.size,incorrect_questions:cumulative?wrongAttempts.length:wrong.size,total_questions:tids.size,
    after_deadline_questions:after.size,errors,elapsed_s:elapsed,remaining_s:Math.max(0,3600-elapsed),state,
    repair_policy:job.repair?.policy??null,
    timing_note:job.results_reset?'Selected question results were reset; rerun them with a fresh clock. The original hourly score is withheld.':job.repair&&available?job.repair.note:available?'Recorded completion timestamps on active wall clock, including thinking, tools and retries.':'Missing completion timestamps or historical pause intervals; hourly score withheld.'};
}
if(typeof module!=='undefined')module.exports={hourScore,questionWeight};

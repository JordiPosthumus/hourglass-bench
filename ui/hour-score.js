'use strict';
function questionWeight(t){
  if(['math','math_logic'].includes(t.section))return {advanced_high_school:1,advanced_undergraduate:1.5,graduate:2}[t.level]??1;
  const max=['chart','charts'].includes(t.section)||t.kind==='chart-vqa'?10:t.section==='games'?5:null;
  return max&&typeof t.tier==='number'&&Number.isFinite(t.tier)?Math.round((1+(Math.min(max,Math.max(1,t.tier))-1)/(max-1))*1e6)/1e6:1;
}
// Mirrors hour_score.py; shared boundary fixtures test Python/browser parity.
function hourScore(job, rows, expected=[], now=Date.now()/1000){
  expected=expected.length?expected:(job.expected||[]);
  const tids=new Set(job.tasks||job.order||expected.map(t=>t.task));
  const vision=new Map(expected.map(t=>[t.task,!!t.vision]));
  const raw=rows.filter(r=>r.evaluation_id===job.id&&tids.has(r.task));
  let intervals=job.active_intervals;
  const timingKnown=!job.hour_timing_unknown&&(!job.resume_count||!!intervals?.length),started=job.started;
  if(!intervals?.length)intervals=started?[{start:started,end:job.ended}]:[];
  const activeAt=ts=>intervals.reduce((n,p)=>n+Math.max(0,Math.min(ts,p.end||ts)-p.start),0);
  const elapsed=timingKnown?activeAt(job.ended||now):(job.progress?.elapsed_s||0);
  const within=[],after=new Set(),timeouts=new Set();let errors=0,unknown=0;
  for(const r of raw){
    if(['five_wrong_in_row','wrong_streak_limit'].includes(r.score_reason))continue;
    const ts=Date.parse(r.ts)/1000;
    if(!Number.isFinite(ts)||!intervals.length||ts<intervals[0].start){unknown++;continue}
    if(activeAt(ts)>3600){if(r.status==='completed')after.add(r.task);continue}
    if(r.status==='timeout')timeouts.add(r.task);else if(r.status==='error')errors++;else if(r.status==='completed')within.push(r);
  }
  const available=timingKnown&&!unknown,correct=new Set(within.filter(r=>r.solved).map(r=>r.task)),completed=new Set(within.map(r=>r.task));
  const netPolicy=['net-hour-v1','net-hour-v2'].includes(job.scoring_policy),neutral=['unsupported_vision','abstained','question_timeout','not_attempted','turn_limit','stopped','unfinished','wrong_streak_limit','five_wrong_in_row'];
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
  const allFinished=tids.size>0&&[...tids].every(tid=>timeouts.has(tid)||Array.from({length:repeats.get(tid)??1},(_,i)=>i+1).every(n=>within.some(r=>r.task===tid&&(r.run??1)===n)));
  const final=available&&(elapsed>=3600||allFinished);
  const state=!available?'unavailable':final?'final':job.state==='running'?'in_progress':!started?'not_started':'partial';
  return {version:'hour-v1',window_s:3600,points:available?correct.size:null,correct_tasks:available?[...correct].sort():[],breakdown:lanes,
    weighted_version:'weighted-hour-v1',weighted_points:available?Math.round((weighted(correct)-(netPolicy?wrong.size:0))*1e6)/1e6:null,
    scoring_policy:job.scoring_policy??'weighted-hour-v1',gross_points:weighted(correct),net_points:available&&netPolicy?Math.round((weighted(correct)-wrong.size)*1e6)/1e6:null,penalty_points:netPolicy?wrong.size:0,abstained_questions:countReason('abstained'),unsupported_questions:countReason('unsupported_vision'),
    timeouts:timeouts.size,resolved_questions:new Set([...completed,...timeouts]).size,question_timeout_policy:job.question_timeout_policy??null,
    completed_questions:completed.size,incorrect_questions:wrong.size,total_questions:tids.size,
    after_deadline_questions:after.size,errors,elapsed_s:elapsed,remaining_s:Math.max(0,3600-elapsed),state,
    timing_note:available?'Recorded completion timestamps on active wall clock, including thinking, tools and retries.':'Missing completion timestamps or historical pause intervals; hourly score withheld.'};
}
if(typeof module!=='undefined')module.exports={hourScore,questionWeight};

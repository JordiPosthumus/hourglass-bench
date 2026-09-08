'use strict';
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
  const within=[],after=new Set();let errors=0,unknown=0;
  for(const r of raw){
    if(['five_wrong_in_row','wrong_streak_limit'].includes(r.score_reason))continue;
    const ts=Date.parse(r.ts)/1000;
    if(!Number.isFinite(ts)||!intervals.length||ts<intervals[0].start){unknown++;continue}
    if(activeAt(ts)>3600){if(r.status==='completed')after.add(r.task);continue}
    if(r.status==='error')errors++;else if(r.status==='completed')within.push(r);
  }
  const available=timingKnown&&!unknown,correct=new Set(within.filter(r=>r.solved).map(r=>r.task)),completed=new Set(within.map(r=>r.task));
  const lanes={};
  for(const lane of ['text','vision']){
    const rs=within.filter(r=>(vision.has(r.task)?vision.get(r.task):r.kind==='chart-vqa'||['chart','charts'].includes(r.section))===(lane==='vision'));
    lanes[lane]={points:available?new Set(rs.filter(r=>r.solved).map(r=>r.task)).size:null,completed_questions:new Set(rs.map(r=>r.task)).size};
  }
  const final=available&&(elapsed>=3600||tids.size>0&&completed.size===tids.size);
  const state=!available?'unavailable':final?'final':job.state==='running'?'in_progress':!started?'not_started':'partial';
  return {version:'hour-v1',window_s:3600,points:available?correct.size:null,correct_tasks:available?[...correct].sort():[],breakdown:lanes,
    completed_questions:completed.size,incorrect_questions:[...completed].filter(t=>!correct.has(t)).length,total_questions:tids.size,
    after_deadline_questions:after.size,errors,elapsed_s:elapsed,remaining_s:Math.max(0,3600-elapsed),state,
    timing_note:available?'Recorded completion timestamps on active wall clock, including thinking, tools and retries.':'Missing completion timestamps or historical pause intervals; hourly score withheld.'};
}
if(typeof module!=='undefined')module.exports={hourScore};

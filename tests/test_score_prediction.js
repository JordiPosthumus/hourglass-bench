'use strict';
const assert=require('node:assert/strict');
const {predictedHourglassScore, hourScore}=require('../ui/hour-score');
const base={state:'in_progress',window_s:3600,elapsed_s:600,resolved_questions:1,total_questions:3,points:1,incorrect_questions:0,weighted_points:1,total_available_points:3,resolved_available_points:1,auc_point_seconds:0,score_denominator_point_seconds:54,scoring_policy:'net-hour-v2'};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,`${a} != ${b}`);
// A finite perfect bank: predicted completions at minutes 10, 20 and 30.
close(predictedHourglassScore(base),133.33333333333334);
close(predictedHourglassScore({...base,state:'partial'}),predictedHourglassScore(base));
// Near the deadline there is no time for another answer; existing points still accrue area.
close(predictedHourglassScore({...base,elapsed_s:3500}),100/54);
assert.equal(predictedHourglassScore({...base,state:'final'}),null);
assert.equal(predictedHourglassScore({...base,state:'unavailable'}),null);
assert.equal(predictedHourglassScore({...base,points:0,incorrect_questions:0}),null);
assert.equal(predictedHourglassScore({...base,elapsed_s:0}),null);
// Mistakes reduce future area; unsupported/timeouts contribute no predicted reward.
close(predictedHourglassScore({...base,points:0,incorrect_questions:1,weighted_points:-1}),-133.33333333333334);
close(predictedHourglassScore({...base,resolved_questions:2,resolved_available_points:2,elapsed_s:1200}),3300/54);
// Remaining questions use their actual total weight, not the weight of the first question.
close(predictedHourglassScore({...base,weighted_points:2,resolved_available_points:2,total_available_points:4,score_denominator_point_seconds:72}),141.66666666666666);
// Resume uses active intervals, and forecasting cannot mutate the measured score.
const job={id:'x',state:'running',started:1000,resume_count:1,active_intervals:[{start:1000,end:1300},{start:10000,end:null}],tasks:['a','b','c'],scoring_policy:'net-hour-v2'};
const row={evaluation_id:'x',task:'a',status:'completed',solved:true,ts:new Date(10300*1000).toISOString()};
const h=hourScore(job,[row],job.tasks.map(task=>({task,weight:1})),10300),before=JSON.stringify(h);
close(predictedHourglassScore(h),predictedHourglassScore(base));assert.equal(JSON.stringify(h),before);
console.log('Score prediction checks passed.');

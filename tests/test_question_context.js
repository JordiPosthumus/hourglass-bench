const assert=require('node:assert/strict');
const {questionAt,longestQuestion}=require('../ui/question-context');
const model={end_s:100,spans:[{task:'a',start_s:0,end_s:30,status:'Correct',summary:'First question'},{task:'b',start_s:30,end_s:100,status:'Working',summary:'Second question'}]};
assert.equal(questionAt(model,29).task,'a');assert.equal(questionAt(model,30).task,'b');
assert.equal(questionAt(model,50).duration,20);assert.equal(questionAt(model,50).status,'Working then');
assert.equal(questionAt(model,null).duration,70);assert.equal(questionAt(model,300).duration,70);
assert.equal(longestQuestion(model).task,'b');assert.equal(questionAt({end_s:0,spans:[]},null).duration,0);
console.log('Question inspection: boundaries, current time, finished runs and longest duration passed.');

import assert from 'node:assert/strict';
import {completeResponseFetch} from '../harness/complete-response.mjs';
import {stream} from '../vendor/pi-0.85.1/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js';
let sent;
const fixture={id:'test',created:1,model:'deepseek-v4-flash',choices:[{index:0,message:{role:'assistant',reasoning_content:'fixture reasoning',content:null,tool_calls:[{id:'call_1',type:'function',function:{name:'answer_question',arguments:'{"option":"007"}'}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:31,completion_tokens:12,total_tokens:43}};
const fetch=completeResponseFetch(async (url, init)=>{sent=JSON.parse(init.body);return Response.json(fixture);});
const model={id:'deepseek-v4-flash',name:'fixture',api:'openai-completions',provider:'benchmark',baseUrl:'http://fixture.invalid/v1',contextWindow:262144,maxTokens:262144,reasoning:true,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const result=await stream(model,{messages:[{role:'user',content:'fixture',timestamp:1}]},{apiKey:'local',maxTokens:262144,fetch}).result();
assert.equal(result.stopReason,'toolUse');assert.deepEqual(result.content.find(c=>c.type==='toolCall').arguments,{option:'007'});assert.equal(result.content.find(c=>c.type==='thinking').thinking,'fixture reasoning');assert.equal(result.usage.input,31);assert.equal(result.usage.output,12);assert.equal(sent.stream,false);assert.equal('stream_options' in sent,false);
const error=await completeResponseFetch(async()=>new Response('upstream error',{status:500}))('http://fixture.invalid',{body:'{}'});assert.equal(error.status,500);
const controller=new AbortController();controller.abort();await assert.rejects(()=>completeResponseFetch(async(u,i)=>{i.signal.throwIfAborted();})('http://fixture.invalid',{body:'{}',signal:controller.signal}),{name:'AbortError'});
console.log('Frozen Pi tool arguments, reasoning, usage, HTTP errors and cancellation: passed.');

assert.equal(sent.max_completion_tokens ?? sent.max_tokens,262144);
const configured={model:'test',messages:[{role:'user',content:'x'}],tools:[{type:'function',function:{name:'a'}}],stream:true,stream_options:{include_usage:true},max_tokens:262144,reasoning:{enabled:true},top_p:0.91};
let transported;
await completeResponseFetch(async(u,i)=>{transported=JSON.parse(i.body);return Response.json(fixture);})('http://fixture.invalid',{body:JSON.stringify(configured)});
const expected={...configured,stream:false};delete expected.stream_options;assert.deepEqual(transported,expected);

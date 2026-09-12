// Separate conversation: no benchmark question, tools, files or answer recording.
import fs from 'node:fs';
import {streamSimple} from '../vendor/pi-0.85.1/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js';
import {DEFAULT_THINKING_LEVEL} from '../vendor/pi-0.85.1/dist/core/defaults.js';
import {applyExplicitSettings,dsgRouteFetch} from './inference-settings.mjs';
import {completeResponseFetch} from './complete-response.mjs';
const input=JSON.parse(fs.readFileSync(0,'utf8')),cfg=input.config;
const abort=new AbortController();
process.on('SIGTERM',()=>abort.abort());process.on('SIGINT',()=>abort.abort());
let transport=globalThis.fetch;
if(cfg.inference_profile?.route?.kind==='dsg')transport=dsgRouteFetch(transport,cfg.inference_profile.route.name);
if(cfg.response_mode==='complete')transport=completeResponseFetch(transport);
const prompt='This is an unscored server warm-up. Read the following neutral text, then count upward from 1, separating numbers with spaces, until you reach 100.\n'+
  'The river runs past the trees. A bridge connects the paths. People walk through the garden in the morning. '.repeat(12);
const result=await streamSimple(input.model,{messages:[{role:'user',content:prompt,timestamp:Date.now()}]},
  {apiKey:cfg.api_key||'local',maxTokens:input.max_tokens,reasoning:cfg.pi_thinking_level??DEFAULT_THINKING_LEVEL,
   fetch:transport,signal:abort.signal,maxRetries:0,
   onPayload:body=>{
     if(cfg.sampling_era!=='pi-native-v1') {
       if(input.settings)applyExplicitSettings(body,input.settings);
       else {delete body.reasoning_effort;delete body.temperature;Object.assign(body,cfg.extra||{});if(cfg.reasoning!==undefined)body.reasoning=cfg.reasoning;}
     }
     // A warm-up-only budget; the benchmark model declaration stays untouched.
     delete body.max_completion_tokens;body.max_tokens=input.max_tokens;
     return body;
   }}).result();
if(['error','aborted'].includes(result.stopReason)||!(result.usage?.output>0||result.content?.some(c=>c.text||c.thinking)))process.exitCode=1;
else console.log(JSON.stringify({status:'completed',output_tokens:result.usage?.output||null}));

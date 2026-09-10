import {completeResponseFetch} from './complete-response.mjs';
import {applyExplicitSettings, settingsCaptureFetch, dsgRouteFetch} from './inference-settings.mjs';
import fs from 'node:fs';
import {createIsolatedFileTools} from './tool-files.mjs';
import path from 'node:path';
import {createAgentSession, ModelRuntime, DefaultResourceLoader, SessionManager, SettingsManager} from '../vendor/pi-0.85.1/dist/index.js';
import {configureHttpDispatcher} from '../vendor/pi-0.85.1/dist/core/http-dispatcher.js';
import {resolveToCwd,resolveReadPath} from '../vendor/pi-0.85.1/dist/core/tools/path-utils.js';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const emit=x=>process.stdout.write(JSON.stringify(x)+'\n');
const cfg=input.model, cwd=fs.realpathSync(input.cwd), agentDir=input.agentDir;
const nativePi=cfg.sampling_era==='pi-native-v1';
const quote=s=>"'"+s.replaceAll("'","'\\''")+"'";
function guard(p,read){
  let resolved=read?resolveReadPath(p,cwd):resolveToCwd(p,cwd), existing=resolved;
  while(!fs.existsSync(existing)){const parent=path.dirname(existing);if(parent===existing)break;existing=parent;}
  const actual=path.resolve(fs.realpathSync(existing),path.relative(existing,resolved));
  if(actual!==cwd&&!actual.startsWith(cwd+path.sep))throw new Error('Path must stay inside the benchmark workspace');
  return resolved;
}
let session, answer, captureSummary, lastAssistantEnd, turns=0, stopped=false;
const fileTools=createIsolatedFileTools(cwd,input.sandboxProfile);
const settingsManager=SettingsManager.inMemory(nativePi?{}:{httpIdleTimeoutMs:0});
configureHttpDispatcher(settingsManager.getHttpIdleTimeoutMs());
const loader=new DefaultResourceLoader({cwd,agentDir,settingsManager,noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,
 appendSystemPrompt:[input.instructions], extensionFactories:[pi=>{
 if(!nativePi)pi.on('before_provider_request',e=>{
   const p=e.payload;
   if(cfg.sampling_era==='explicit-v1')return applyExplicitSettings(p,input.requestSettings);
   delete p.max_completion_tokens;delete p.reasoning_effort;
   p.max_tokens=cfg.max_tokens??1024;
   if(cfg.reasoning!==undefined)p.reasoning=cfg.reasoning;
   Object.assign(p,cfg.extra??{});delete p.temperature;
   if(cfg.output_budget==='server'){delete p.max_tokens;delete p.max_completion_tokens;}
   const keys=['temperature','top_p','top_k','min_p','repetition_penalty','frequency_penalty','presence_penalty','reasoning','reasoning_effort','max_tokens'];
   emit({requested_settings:{pi_thinking_level:session?.thinkingLevel??null,captured_at:new Date().toISOString(),response_mode:cfg.response_mode ?? 'stream',values:Object.fromEntries(keys.filter(k=>p[k]!==undefined).map(k=>[k,p[k]])),omitted:keys.filter(k=>p[k]===undefined)}});return p;
 });
 pi.on('tool_call',e=>{
   if(['read','write','edit'].includes(e.toolName))e.input.path=guard(e.input.path,e.toolName==='read');
   if(e.toolName==='bash'){
     if(!nativePi)delete e.input.timeout;
     if(input.sandboxProfile)e.input.command='/usr/bin/sandbox-exec -p '+quote(input.sandboxProfile)+' /usr/bin/env -i PATH='+quote(process.env.PATH)+' HOME='+quote(cwd)+' /bin/bash -c '+quote(e.input.command);
   }
 });
}]});
try{
 await loader.reload();
 const runtime=await ModelRuntime.create({authPath:path.join(agentDir,'auth.json'),modelsPath:path.join(agentDir,'models.json')});
 await runtime.setRuntimeApiKey('benchmark',cfg.api_key ?? 'local');
 const model=runtime.getModel('benchmark',cfg.model);if(!model)throw new Error('Frozen Pi could not resolve configured model');
 const finalTool={name:input.finalTool,label:input.finalTool,description:input.answerDescription,
 parameters:input.answerSchema,execute:async(_id,args)=>{answer=args;return {content:[{type:'text',text:'Answer recorded. The benchmark question is complete.'}],details:{}};}};
 ({session}=await createAgentSession({cwd,agentDir,modelRuntime:runtime,model,resourceLoader:loader,settingsManager,...(nativePi&&cfg.pi_thinking_level!==undefined?{thinkingLevel:cfg.pi_thinking_level}:{}),sessionManager:SessionManager.create(cwd,path.join(agentDir,'sessions')),customTools:[...fileTools.tools,finalTool]}));
 if (cfg.response_mode !== undefined && !['stream','complete'].includes(cfg.response_mode)) throw Error('Unknown response_mode; use stream or complete.');
 if (nativePi || cfg.sampling_era === 'explicit-v1') {
   const originalStream = session.agent.streamFunction;
   const record = value => emit({requested_settings:value});
   let transport = globalThis.fetch;
   const route = cfg.inference_profile.route;
   if(route.kind==='dsg') transport = dsgRouteFetch(transport,route.name,value=>emit({route_observation:value}));
   transport = settingsCaptureFetch(transport,record,{thinkingLevel:()=>session?.thinkingLevel,responseMode:cfg.response_mode??'stream',samplingEra:cfg.sampling_era});
   const recorder = transport;
   captureSummary = () => ({request_count:recorder.requestCount()});
   if(cfg.response_mode==='complete') transport = completeResponseFetch(transport);
   session.agent.streamFunction = (model, context, options) => originalStream(model,context,{...options,fetch:transport});
 } else if (cfg.response_mode === 'complete') {
   const originalStream = session.agent.streamFunction;
   const fetchComplete = completeResponseFetch();
   session.agent.streamFunction = (model, context, options) => originalStream(model, context, {...options, fetch:fetchComplete});
 }
 emit({thinking_settings:{pi_thinking_level:session.thinkingLevel,source:"Pi session getter",captured_at:new Date().toISOString()}});
 if(nativePi)emit({session_settings:{baseline:'native Pi 0.85.1',thinking_level:session.thinkingLevel,selected_thinking_level:cfg.pi_thinking_level??'Pi default',
   compaction:settingsManager.getCompactionSettings(),retry:settingsManager.getRetrySettings(),
   http_idle_timeout_ms:settingsManager.getHttpIdleTimeoutMs(),output_budget:'native Pi context calculation'}});
 session.subscribe(e=>{
   // Pi may remove an overflow error from its active messages before trying
   // compaction. Keep the event so an unsuccessful recovery cannot look like
   // a clean response and trigger an endless sequence of Continue prompts.
   // A successful native recovery replaces this with its successful message.
   if(e.type==='message_end'&&e.message?.role==='assistant')lastAssistantEnd=e.message;
   if(e.type!=='message_update'&&e.type!=='tool_execution_update')emit({event:e});
   if(e.type==='turn_start')turns++;
   if(e.type==='tool_execution_end'&&e.toolName===input.finalTool&&answer!==undefined)session.abort();
 });
 process.on('SIGTERM',()=>{stopped=true;session.abort();});
 process.on('SIGINT',()=>{stopped=true;session.abort();});
 await session.prompt(input.prompt,{images:input.images});
 while(answer===undefined&&!stopped){
   const last=lastAssistantEnd??session.messages.filter(x=>x.role==='assistant').at(-1);
   if(last?.stopReason==='error')throw new Error(last.errorMessage||'Pi provider error');
   await session.prompt('Continue working, or call '+input.finalTool+' with your final answer.');
 }
 const last=lastAssistantEnd??session.messages.filter(x=>x.role==='assistant').at(-1);
 if(answer===undefined&&!stopped&&last?.stopReason==='error')throw new Error(last.errorMessage||'Pi provider error');
 emit({result:{answer:answer??{},termination:stopped?'stopped':answer!==undefined?'answered':'unfinished',turns,context_window:model.contextWindow}});
}catch(e){emit({error:e.stack||String(e)});process.exitCode=1;}
finally{if(captureSummary)emit({settings_capture_summary:captureSummary()});session?.dispose();fileTools.close();}

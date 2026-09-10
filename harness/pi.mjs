import {completeResponseFetch} from './complete-response.mjs';
import fs from 'node:fs';
import {createIsolatedFileTools} from './tool-files.mjs';
import path from 'node:path';
import {createAgentSession, ModelRuntime, DefaultResourceLoader, SessionManager, SettingsManager} from '../vendor/pi-0.85.1/dist/index.js';
import {configureHttpDispatcher} from '../vendor/pi-0.85.1/dist/core/http-dispatcher.js';
import {resolveToCwd,resolveReadPath} from '../vendor/pi-0.85.1/dist/core/tools/path-utils.js';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const emit=x=>process.stdout.write(JSON.stringify(x)+'\n');
const cfg=input.model, cwd=fs.realpathSync(input.cwd), agentDir=input.agentDir;
const quote=s=>"'"+s.replaceAll("'","'\\''")+"'";
function guard(p,read){
  let resolved=read?resolveReadPath(p,cwd):resolveToCwd(p,cwd), existing=resolved;
  while(!fs.existsSync(existing)){const parent=path.dirname(existing);if(parent===existing)break;existing=parent;}
  const actual=path.resolve(fs.realpathSync(existing),path.relative(existing,resolved));
  if(actual!==cwd&&!actual.startsWith(cwd+path.sep))throw new Error('Path must stay inside the benchmark workspace');
  return resolved;
}
let session, answer, turns=0, stopped=false;
const fileTools=createIsolatedFileTools(cwd,input.sandboxProfile);
const settingsManager=SettingsManager.inMemory({httpIdleTimeoutMs:0});
configureHttpDispatcher(settingsManager.getHttpIdleTimeoutMs());
const loader=new DefaultResourceLoader({cwd,agentDir,settingsManager,noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,
 appendSystemPrompt:[input.instructions], extensionFactories:[pi=>{
 pi.on('before_provider_request',e=>{
   const p=e.payload;delete p.max_completion_tokens;delete p.reasoning_effort;
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
     delete e.input.timeout;
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
 ({session}=await createAgentSession({cwd,agentDir,modelRuntime:runtime,model,resourceLoader:loader,settingsManager,sessionManager:SessionManager.create(cwd,path.join(agentDir,'sessions')),customTools:[...fileTools.tools,finalTool]}));
 if (cfg.response_mode !== undefined && !['stream','complete'].includes(cfg.response_mode)) throw Error('Unknown response_mode; use stream or complete.');
 if (cfg.response_mode === 'complete') {
   const originalStream = session.agent.streamFunction;
   const fetchComplete = completeResponseFetch();
   session.agent.streamFunction = (model, context, options) => originalStream(model, context, {...options, fetch:fetchComplete});
 }
 emit({thinking_settings:{pi_thinking_level:session.thinkingLevel,source:"Pi session getter",captured_at:new Date().toISOString()}});
 session.subscribe(e=>{
   if(e.type!=='message_update'&&e.type!=='tool_execution_update')emit({event:e});
   if(e.type==='turn_start')turns++;
   if(e.type==='tool_execution_end'&&e.toolName===input.finalTool&&answer!==undefined)session.abort();
 });
 process.on('SIGTERM',()=>{stopped=true;session.abort();});
 process.on('SIGINT',()=>{stopped=true;session.abort();});
 await session.prompt(input.prompt,{images:input.images});
 while(answer===undefined&&!stopped){
   const last=session.messages.filter(x=>x.role==='assistant').at(-1);
   if(last?.stopReason==='error')throw new Error(last.errorMessage||'Pi provider error');
   await session.prompt('Continue working, or call '+input.finalTool+' with your final answer.');
 }
 const last=session.messages.filter(x=>x.role==='assistant').at(-1);
 if(answer===undefined&&!stopped&&last?.stopReason==='error')throw new Error(last.errorMessage||'Pi provider error');
 emit({result:{answer:answer??{},termination:stopped?'stopped':answer!==undefined?'answered':'unfinished',turns,context_window:model.contextWindow}});
}catch(e){emit({error:e.stack||String(e)});process.exitCode=1;}
finally{session?.dispose();fileTools.close();}

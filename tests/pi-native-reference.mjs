// Independent SDK baseline: no Hourglass generation adapter or fetch wrapper.
import fs from 'node:fs';
import path from 'node:path';
import {createAgentSession, ModelRuntime, DefaultResourceLoader, SessionManager, SettingsManager} from '../vendor/pi-0.85.1/dist/index.js';
import {createIsolatedFileTools} from '../harness/tool-files.mjs';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const cwd=fs.realpathSync(input.cwd), agentDir=process.argv[3], cfg=input.model;
fs.mkdirSync(agentDir,{recursive:true});
const definitions=JSON.parse(fs.readFileSync(path.join(input.agentDir,'models.json'),'utf8'));
if(cfg.inference_profile.route.kind==='dsg')definitions.providers.benchmark.headers={'x-dsg-model':cfg.inference_profile.route.name};
fs.writeFileSync(path.join(agentDir,'models.json'),JSON.stringify(definitions));
const settingsManager=SettingsManager.inMemory({});
const loader=new DefaultResourceLoader({cwd,agentDir,settingsManager,noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,appendSystemPrompt:[input.instructions]});
await loader.reload();
const runtime=await ModelRuntime.create({authPath:path.join(agentDir,'auth.json'),modelsPath:path.join(agentDir,'models.json')});
await runtime.setRuntimeApiKey('benchmark','local');
const model=runtime.getModel('benchmark',cfg.model);
const files=createIsolatedFileTools(cwd,input.sandboxProfile);
let answer;
const finalTool={name:input.finalTool,label:input.finalTool,description:input.answerDescription,parameters:input.answerSchema,
 execute:async(_id,args)=>{answer=args;return {content:[{type:'text',text:'Answer recorded. The benchmark question is complete.'}],details:{}};}};
const {session}=await createAgentSession({cwd,agentDir,modelRuntime:runtime,model,resourceLoader:loader,settingsManager,thinkingLevel:cfg.pi_thinking_level,sessionManager:SessionManager.create(cwd,path.join(agentDir,'sessions')),customTools:[...files.tools,finalTool]});
session.subscribe(e=>{if(e.type==='tool_execution_end'&&e.toolName===input.finalTool&&answer!==undefined)session.abort();});
try{await session.prompt(input.prompt,{images:input.images});console.log(JSON.stringify({answer,thinking:session.thinkingLevel}));}
finally{session.dispose();files.close();}

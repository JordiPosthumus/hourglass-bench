import fs from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createReadToolDefinition} from '../vendor/pi-0.85.1/dist/core/tools/read.js';
import {createEditToolDefinition} from '../vendor/pi-0.85.1/dist/core/tools/edit.js';
import {createWriteToolDefinition} from '../vendor/pi-0.85.1/dist/core/tools/write.js';
import {detectSupportedImageMimeType} from '../vendor/pi-0.85.1/dist/utils/mime.js';

// Reuse frozen Pi's definitions, schemas, image processing and mutation queues.
// Only filesystem operations cross into this kernel-confined helper process.
export function createIsolatedFileTools(cwd, profile) {
  if (!profile) throw Error('File tools require a diagnostic isolation profile');
  let worker, sequence=0, closed=false;
  const pending=new Map();
  const rejectPending = error => {for (const {reject} of pending.values()) reject(error); pending.clear();};
  function start() {
    const source=fs.readFileSync(fileURLToPath(new URL('./tool-fs-worker.cjs',import.meta.url)),'utf8');
    worker=spawn('/usr/bin/sandbox-exec',['-p',profile,process.execPath,'--input-type=commonjs','-e',source],{
      cwd,env:{PATH:process.env.PATH,HOME:cwd,LANG:process.env.LANG || 'en_US.UTF-8'},
      stdio:['ignore','ignore','pipe','ipc'],serialization:'advanced'});
    let errorText='';worker.stderr.on('data',chunk=>{errorText+=chunk.toString();});
    worker.on('message',message=>{
      const call=pending.get(message.id);if (!call) return;pending.delete(message.id);
      if (message.error) call.reject(Object.assign(new Error(message.error.message),{code:message.error.code}));
      else call.resolve(message.value);
    });
    worker.on('error',rejectPending);
    worker.on('exit',()=>rejectPending(new Error('Isolated file worker exited'+(errorText ? ': '+errorText : ''))));
  }
  function operation(name, file, data) {
    if (closed) return Promise.reject(new Error('File tools are closed'));
    if (!worker) start();
    return new Promise((resolve,reject)=>{
      const id=++sequence;pending.set(id,{resolve,reject});
      worker.send({id,operation:name,path:file,data},error=>{if (error) {pending.delete(id);reject(error);}});
    });
  }
  const readFile=file=>operation('read',file);
  const writeFile=(file,text)=>operation('write',file,text);
  return {
    tools:[
      createReadToolDefinition(cwd,{operations:{readFile,access:file=>operation('access',file),
        detectImageMimeType:async file=>detectSupportedImageMimeType(await operation('head',file))}}),
      createEditToolDefinition(cwd,{operations:{readFile,writeFile,access:file=>operation('access',file,'write')}}),
      createWriteToolDefinition(cwd,{operations:{writeFile,mkdir:dir=>operation('mkdir',dir)}}),
    ],
    close() {closed=true;rejectPending(new Error('File tools closed'));if (worker?.connected) worker.disconnect();},
  };
}

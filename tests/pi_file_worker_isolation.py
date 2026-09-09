"""Test OS enforcement directly, bypassing the adapter's path guards."""
import json,pathlib,subprocess,sys,tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import diagnostics,hourglass
root=pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='hourglass-file-boundary-') as temp:
 work=pathlib.Path(temp);secret=diagnostics.directory(root,work,create=True)/'secret';secret.write_text('CANARY')
 (work/'link').symlink_to(secret)
 payload={'cwd':str(work),'profile':hourglass.sandbox_profile(work,False),'secret':str(secret),'worker':str(root/'harness/tool-fs-worker.cjs')}
 script=r'''
 const fs=require('fs'),{spawn}=require('child_process');
 const p=JSON.parse(process.argv[1]);
 const child=spawn('/usr/bin/sandbox-exec',['-p',p.profile,process.execPath,'--input-type=commonjs','-e',fs.readFileSync(p.worker,'utf8')],{cwd:p.cwd,env:{PATH:process.env.PATH,HOME:p.cwd},stdio:['ignore','ignore','inherit','ipc'],serialization:'advanced'});
 let id=0;const pending=new Map();child.on('message',m=>{pending.get(m.id)(m);pending.delete(m.id)});
 const op=(operation,path,data)=>new Promise(resolve=>{const i=++id;pending.set(i,resolve);child.send({id:i,operation,path,data})});
 (async()=>{
 for(const operation of ['read','head','access','write'])for(const path of [p.secret,p.cwd+'/link']){
 const r=await op(operation,path,'altered');if(!r.error)throw Error('Diagnostic access allowed: '+operation+path);
 }
 if((await op('write',p.cwd+'/ok','task data')).error)throw Error('Task write denied');
 if(Buffer.from((await op('read',p.cwd+'/ok')).value).toString()!=='task data')throw Error('Task read failed');
 console.log('OS helper: eight direct/symlink probes denied; task read/write passed');child.disconnect();
 })().catch(e=>{console.error(e);child.kill();process.exitCode=1});
 '''
 subprocess.run(['node','-e',script,json.dumps(payload)],check=True,timeout=30)
 assert secret.read_text()=='CANARY'

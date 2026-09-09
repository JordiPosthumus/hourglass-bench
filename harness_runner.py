"""Frozen Pi SDK adapter. Benchmark scoring remains outside the agent process."""
import scoring_policy
import score_weights
import os
import signal
import re
import base64, datetime, hashlib, json, mimetypes, pathlib, subprocess, tempfile, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parent

def stop_child(proc):
    proc.terminate()
    return proc.communicate()

def server_metadata(cfg):
    root=cfg['base_url'].rstrip('/').removesuffix('/v1')
    snapshot={'temperature':None,'temperature_source':'server default — not reported','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen(root+'/api/v1/models',timeout=30) as response:data=json.load(response)
        models=[m for m in data.get('models',[]) if isinstance(m,dict)]
        def instances(m):return [i for i in (m.get('loaded_instances') or []) if isinstance(i,dict)]
        # Served aliases and explicit disk variants are distinct from catalog keys.
        model=next((m for m in models if any(i.get('id')==cfg['model'] for i in instances(m))),None)
        if model is None:model=next((m for m in models if m.get('key')==cfg['model']),None)
        if model is None:model=next((m for m in models if cfg['model']==m.get('selected_variant') or cfg['model'] in (m.get('variants') or [])),None)
        if model:
            snapshot['model']=model
            loaded=instances(model)
            instance=next((i for i in loaded if i.get('id')==cfg['model']),loaded[0] if loaded else {})
            config=instance.get('config',{})
            snapshot['context_window']=config.get('context_length') or model.get('max_context_length')
            if isinstance(config.get('temperature'),(int,float)):
                snapshot.update(temperature=config['temperature'],temperature_source='server loaded instance config')
    except Exception as e:snapshot['metadata_error']=str(e)
    if not snapshot.get('context_window'):
        try:
            with urllib.request.urlopen(root+'/v1/models',timeout=30) as response:data=json.load(response)
            model=next((m for m in data.get('data',[]) if m.get('id')==cfg['model']),{})
            context=model.get('context_length') or model.get('top_provider',{}).get('context_length')
            if type(context) is int and context>0:
                snapshot.update(context_window=context,context_source='server /v1/models')
        except Exception as e:snapshot['openai_metadata_error']=str(e)
    return snapshot

def verify_frozen():
    lock_path=ROOT/'harness/pi-lock.json'
    lock=json.loads(lock_path.read_text())
    for name,expected in lock['files'].items():
        file=ROOT/'vendor/pi-0.85.1'/name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Frozen Pi integrity check failed: '+name)
    return hashlib.sha256(lock_path.read_bytes()).hexdigest()

def run(task,cfg,workdir,sandboxed):
    import hourglass
    started=time.time();trace=[];pt=ct=calls=0
    frozen_hash=verify_frozen()
    metadata=server_metadata(cfg)
    context=cfg.get('context_window') or metadata.get('context_window')
    if not context:raise ValueError('Server did not report context capacity; configure context_window explicitly for this endpoint.')
    prompt=task['prompt'];disp_map=None
    chart=task.get('kind')=='chart-vqa';mcq=task.get('kind')=='mcq'
    if chart:
        display,disp_map=hourglass.shuffle_choices(task);prompt+='\n\n'+display
    elif mcq and task.get('options'):prompt+='\n\n'+hourglass.mcq_display(task)
    final='answer_question' if chart or mcq else 'submit'
    properties={'value':{'type':'number'}} if task.get('mode')=='numeric' else ({'answer':{'type':'string'}} if chart else {'option':{'type':'string'}}) if mcq or chart else {'summary':{'type':'string'}}
    answer_schema, scoring_instructions = scoring_policy.submission(properties,score_weights.weight(task),os.environ.get('HOURGLASS_SCORING_POLICY'))
    images=[]
    for asset in ([task['image']] if chart else task.get('assets',[])):
        file=workdir/asset;mime=mimetypes.guess_type(str(file))[0] or 'image/png'
        if mime.startswith('image/'):
            images.append({'type':'image','data':base64.b64encode(file.read_bytes()).decode(),'mimeType':mime})
    with tempfile.TemporaryDirectory(prefix='hourglassbench-pi-') as private:
        agent_dir=pathlib.Path(private)
        provider={'baseUrl':cfg['base_url'],'api':'openai-completions','apiKey':'local','models':[{'id':cfg['model'],'name':cfg['model'],'reasoning':True,'input':['text','image'],'contextWindow':context,'maxTokens':cfg.get('max_tokens',1024),'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}]}
        (agent_dir/'models.json').write_text(json.dumps({'providers':{'benchmark':provider}}))
        payload={'cwd':str(workdir),'agentDir':private,'model':cfg,'prompt':prompt+'\n\nCall '+final+' when finished.','images':images,
                 'instructions':(scoring_instructions+' ' if scoring_instructions else '')+'Work on exactly this benchmark question. Use the workspace tools as needed. Network access is unavailable. Finish by calling '+final+'.',
                 'finalTool':final,'answerDescription':'Submit the final benchmark answer.',
                 'answerSchema':answer_schema,
                 'sandboxProfile':hourglass.sandbox_profile(workdir) if sandboxed else None}
        request=agent_dir/'request.json';request.write_text(json.dumps(payload))
        result=None;error=None;requested=[];thinking={"pi_thinking_level":None,"source":"not captured","server_reasoning_default":metadata.get("model",{}).get("capabilities",{}).get("reasoning",{}).get("default"),"server_effective_reasoning":None,"thinking_content_observed":False}
        proc=subprocess.Popen(['node',str(ROOT/'harness/pi.mjs'),str(request)],cwd=workdir,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def stop(_signum,_frame):
            tail,stderr=stop_child(proc)
            (workdir/'interrupted-pi-trace.json').write_text(json.dumps({'trace':trace,'remaining_stdout':tail,'stderr':stderr},indent=1))
            raise SystemExit(130)
        previous=signal.signal(signal.SIGTERM,stop)
        for line in proc.stdout:
            try:item=json.loads(line)
            except ValueError:trace.append({'pi_output':line.rstrip()});continue
            trace.append(item)
            if 'requested_settings' in item:requested.append(item['requested_settings'])
            if 'thinking_settings' in item:thinking.update(item['thinking_settings'])
            event=item.get('event',{})
            if event.get('type')=='turn_start':print('MODEL Pi turn: waiting for response',flush=True)
            if event.get('type')=='tool_execution_start':
                calls+=1;print('TOOL '+event.get('toolName',''),flush=True)
            if event.get('type')=='tool_execution_end' and event.get('isError'):
                detail='\n'.join(c.get('text','') for c in event.get('result',{}).get('content',[]) if c.get('type')=='text')
                print('TOOL ERROR '+event.get('toolName','')+': '+detail,flush=True)
            if event.get('type')=='message_end' and event.get('message',{}).get('role')=='assistant':
                thinking['thinking_content_observed'] |= any(c.get('type')=='thinking' and bool(c.get('thinking')) for c in event['message'].get('content',[]))
                usage=event['message'].get('usage',{});pt+=usage.get('input',0)+usage.get('cacheRead',0)+usage.get('cacheWrite',0);ct+=usage.get('output',0)
            if 'result' in item:result=item['result']
            if 'error' in item:error=item['error']
        stderr=proc.stderr.read();rc=proc.wait()
        signal.signal(signal.SIGTERM,previous)
        if rc or error or result is None:
            failure=hourglass.AgentRunError(error or stderr or f'Pi exited {rc} without result',trace,pt,ct,calls,started)
            failure.metrics.update(thinking_settings=thinking,requested_settings=requested,harness='pi',pi_version='0.85.1',pi_lock_sha256=frozen_hash,server_settings=metadata,temperature=metadata['temperature'],temperature_source=metadata['temperature_source'])
            # Pi serializes provider exceptions, so restore the capability-error
            # type that the scoring layer already handles as an unsupported zero.
            if images and error and re.search(r'\b(?:400|415|422|500):',error) and hourglass.vision_rejection(error):
                raise failure from hourglass.UnsupportedVision(error)
            raise failure
        metrics={'prompt_tokens':pt,'completion_tokens':ct,'tool_calls':calls,'duration_s':round(time.time()-started,3),
                 'thinking_settings':thinking,'requested_settings':requested,'termination':result['termination'],'harness':'pi','pi_version':'0.85.1','harness_sha256':hashlib.sha256((ROOT/'harness/pi.mjs').read_bytes()).hexdigest(),
                 'pi_lock_sha256':frozen_hash,'server_settings':metadata,'temperature':metadata['temperature'],'temperature_source':metadata['temperature_source'],'context_window':context}
        return trace,metrics,result['answer'],disp_map

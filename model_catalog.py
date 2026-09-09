"""Read-only model discovery through lms and OpenAI-compatible model lists."""
import json
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def lms_binary():
    found=shutil.which('lms')
    fallback=Path.home()/'.lmstudio/bin'/('lms.exe' if sys.platform=='win32' else 'lms')
    if found:return found
    if fallback.is_file():return str(fallback)
    raise ValueError('LM Studio’s lms CLI was not found. Open LM Studio and install its CLI, then refresh the picker.')


def lms_json(binary, arguments):
    try:result=subprocess.run([binary,*arguments],capture_output=True,text=True,timeout=10)
    except subprocess.TimeoutExpired:
        raise ValueError('lms did not respond. Check that LM Studio is open, then refresh the picker.') from None
    if result.returncode:
        raise ValueError('lms could not read the model library. Check that LM Studio is open and its CLI works.')
    try:return json.loads(result.stdout)
    except ValueError:raise ValueError('lms returned an unreadable model list. Refresh the picker or update the CLI.') from None


def positive_integer(value):
    return value if type(value) is int and value>0 else None


def normalize_lms(downloaded, loaded):
    """Keep quantization variants distinct; loaded aliases are the served IDs."""
    if not isinstance(downloaded,list) or not isinstance(loaded,list):
        raise ValueError('Unexpected lms model-list format.')
    loaded=[m for m in loaded if isinstance(m,dict) and m.get('type','llm')=='llm']
    rows=[];matched=set()
    def row(model, base, instance=None):
        value={**base,**model,**(instance or {})}
        quant=value.get('quantization') or {}
        quant=quant.get('name') if isinstance(quant,dict) else str(quant)
        key=model.get('modelKey') or base.get('modelKey') or value.get('identifier')
        identifier=instance.get('identifier') if instance else key
        # The selected disk variant is served under the catalog's base ID.
        # Other variants retain their explicit key until loaded with an alias.
        if not instance and key==base.get('selectedVariant') and base.get('modelKey'):
            identifier=base['modelKey']
        if not isinstance(identifier,str) or not identifier:return None
        return {'key':('loaded:'+identifier if instance else 'disk:'+key),
                'model_id':identifier,'model_key':key,
                'title':value.get('displayName') or identifier,'quantization':quant,
                'format':value.get('format'),'parameters':value.get('paramsString'),
                'size_bytes':value.get('sizeBytes'),'vision':value.get('vision'),
                'loaded':instance is not None,'status':value.get('status') if instance else 'not loaded',
                'context_length':positive_integer(instance.get('contextLength')) if instance else None,
                'max_context_length':positive_integer(value.get('maxContextLength')),
                'device_identifier':value.get('deviceIdentifier')}
    for group in downloaded:
        if not isinstance(group,dict):continue
        base=group.get('model',group)
        if not isinstance(base,dict) or base.get('type','llm')!='llm':continue
        variants=group.get('variants') or [base]
        if not isinstance(variants,list) or not all(isinstance(v,dict) for v in variants):variants=[base]
        for variant in variants:
            matches=[]
            for index,instance in enumerate(loaded):
                if index in matched:continue
                same=(instance.get('selectedVariant')==variant.get('modelKey') and bool(variant.get('modelKey')) or
                      instance.get('indexedModelIdentifier')==variant.get('indexedModelIdentifier') and bool(variant.get('indexedModelIdentifier')) or
                      len(variants)==1 and instance.get('modelKey')==base.get('modelKey') and bool(base.get('modelKey')))
                if same:matches.append((index,instance))
            if matches:
                for index,instance in matches:
                    item=row(variant,base,instance)
                    if item:rows.append(item);matched.add(index)
            else:
                item=row(variant,base)
                if item:rows.append(item)
    for index,instance in enumerate(loaded):
        if index not in matched:
            item=row(instance,instance,instance)
            if item:rows.append(item)
    unique={r['key']:r for r in rows}
    return sorted(unique.values(),key=lambda r:(not r['loaded'],r['title'].lower(),r.get('quantization') or '',r['model_id']))


def lmstudio():
    binary=lms_binary()
    downloaded=lms_json(binary,['ls','--llm','--variants','--json'])
    loaded=lms_json(binary,['ps','--json'])
    server=lms_json(binary,['server','status','--json'])
    port=server.get('port') if isinstance(server,dict) else None
    if type(port) is not int or not 1<=port<=65535:port=1234
    return {'models':normalize_lms(downloaded,loaded),'base_url':f'http://127.0.0.1:{port}/v1',
            'server_running':isinstance(server,dict) and server.get('running') is True,
            'source':'lms ls / lms ps','read_only':True}


def base_url(value):
    if not isinstance(value,str) or not value.strip():raise ValueError('Enter the server’s base URL.')
    value=value.strip().rstrip('/')
    try:parts=urllib.parse.urlsplit(value);port=parts.port
    except ValueError:raise ValueError('Enter a valid HTTP or HTTPS base URL.') from None
    if parts.scheme not in ('http','https') or not parts.hostname or parts.query or parts.fragment:
        raise ValueError('Use an HTTP or HTTPS base URL without a query or fragment, for example http://server:8000/v1.')
    if parts.username or parts.password:raise ValueError('Use a base URL without embedded login details.')
    return value


def read_endpoint(url):
    """Bounded GET only. Errors are observations, not a reason to send a prompt."""
    result={'url':url,'status':None,'http_server':None}
    try:
        request=urllib.request.Request(url,headers={'Accept':'application/json'})
        with urllib.request.urlopen(request,timeout=4) as response:
            result.update(status=response.status,http_server=response.headers.get('Server'))
            data=response.read(2_000_001)
        if len(data)>2_000_000:raise ValueError('Response exceeds the metadata size limit.')
        result['data']=json.loads(data)
    except urllib.error.HTTPError as exc:result.update(status=exc.code,error=f'HTTP {exc.code}')
    except (urllib.error.URLError,TimeoutError,OSError):result['error']='Could not connect'
    except (ValueError,UnicodeDecodeError):result['error']='Response was not a usable JSON document'
    return result


def metadata(value):
    """Keep inspection local and avoid echoing credentials or prompt contents."""
    hidden={'authorization','api_key','apikey','access_token','password','secret','messages','prompt','system_prompt'}
    if isinstance(value,dict):return {k:('[redacted]' if k.lower() in hidden else metadata(v)) for k,v in value.items()}
    if isinstance(value,list):return [metadata(v) for v in value[:200]]
    if isinstance(value,str):return value[:2000]
    return value


def inspect_endpoint(value):
    entered=base_url(value)
    for suffix in ('/chat/completions','/models'):
        if entered.endswith(suffix):entered=entered[:-len(suffix)];break
    if entered.endswith('/api/v1'):entered=entered[:-7]+'/v1'
    root_path=urllib.parse.urlsplit(entered).path
    bases=[entered+'/v1',entered] if not root_path else [entered]
    probes=[];chosen=bases[0];advertised=[]
    for candidate in bases:
        result=read_endpoint(candidate+'/models');probes.append(result)
        doc=result.get('data')
        if isinstance(doc,dict) and isinstance(doc.get('data'),list):
            chosen=candidate;advertised=doc['data'];break
    root=chosen.removesuffix('/v1')
    urls=[root+'/api/v1/models',root+'/props',root+'/health']
    with ThreadPoolExecutor(max_workers=3) as pool:
        extra=list(pool.map(read_endpoint,urls))
    probes.extend(extra)
    native=extra[0].get('data') or {};props=extra[1].get('data') or {};health=extra[2].get('data') or {}
    native_models=native.get('models',[]) if isinstance(native,dict) else []
    native_models=native_models if isinstance(native_models,list) else []
    def objects(value):return [v for v in value if isinstance(v,dict)] if isinstance(value,list) else []
    props=props if isinstance(props,dict) else {}
    defaults=props.get('default_generation_settings') or {}
    defaults=defaults if isinstance(defaults,dict) else {}
    params=defaults.get('params') if isinstance(defaults.get('params'),dict) else defaults
    rows=[]
    for model in advertised:
        if not isinstance(model,dict) or not isinstance(model.get('id'),str):continue
        mid=model['id'];native_model=next((m for m in native_models if isinstance(m,dict) and (m.get('key')==mid or any(i.get('id')==mid for i in objects(m.get('loaded_instances'))))),{})
        instances=objects(native_model.get('loaded_instances'))
        instance=next((i for i in instances if i.get('id')==mid),instances[0] if len(instances)==1 else {})
        config=instance.get('config') or {}
        config=config if isinstance(config,dict) else {}
        provider=model.get('top_provider') or {}
        provider=provider if isinstance(provider,dict) else {}
        context=config.get('context_length') or model.get('context_length') or model.get('context_window') or model.get('max_model_len') or provider.get('context_length')
        # Endpoint-wide defaults are attributable only when one model is listed.
        if not context and len(advertised)==1:context=params.get('n_ctx') or defaults.get('n_ctx') or props.get('context_length')
        row={'model_id':mid,'title':native_model.get('display_name') or native_model.get('name') or model.get('name') or mid,
             'context_length':positive_integer(context),'max_context_length':positive_integer(native_model.get('max_context_length')),
             'max_output_tokens':positive_integer(model.get('max_completion_tokens') or provider.get('max_completion_tokens')),
             'provider':model.get('owned_by'),'type':native_model.get('type') or model.get('type'),
             'supported_parameters':model.get('supported_parameters') if isinstance(model.get('supported_parameters'),list) else [],
             'loaded':bool(instances) if native_model else None,'metadata':metadata({**model,**({'loaded_config':config} if config else {})})}
        rows.append(row)
    reported=[]
    for label,key in [('Parallel slots','total_slots'),('Parallel slots','n_slots'),('Context length','context_length'),('Server version','version'),('Backend','backend'),('Engine','engine')]:
        if key in props:reported.append({'label':label,'value':metadata(props[key]),'source':'/props'})
    for key in ('n_ctx','n_predict','temperature','top_p','top_k','min_p','repeat_penalty','seed'):
        if key in params:reported.append({'label':key,'value':metadata(params[key]),'source':'/props defaults'})
    if isinstance(health,dict):
        for key in ('status','slots_idle','slots_processing','model','backend','version'):
            if key in health:reported.append({'label':key,'value':metadata(health[key]),'source':'/health'})
    return {'base_url':chosen,'models':rows,'reachable':any(p.get('status') is not None for p in probes),
            'kind':'LM Studio metadata' if native_models else 'OpenAI-compatible model list' if rows else 'No compatible model list found',
            'http_server':next((p['http_server'] for p in probes if p.get('http_server')),None),
            'reported':reported,'probes':[{'path':urllib.parse.urlsplit(p['url']).path,'status':p['status'],'error':p.get('error')} for p in probes],
            'read_only':True}

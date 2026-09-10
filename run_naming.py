"""Canonical display identity; never rewrites execution aliases or raw history."""
import re

POLICY='run-name-v2'
IDENTITY_FIELDS=('hardware','server_name','server_version','model_name','quantization')

def text(value):
    if not isinstance(value,str):return ''
    return ' '.join(value.split())

def hardware(value):
    value=text(value)
    value=re.sub(r'\b(?:Apple\s+)?M([1-9])\s*(ultra|max|pro)\b',lambda m:'M'+m[1]+' '+m[2].title(),value,flags=re.I)
    value=re.sub(r'\b(\d+(?:\.\d+)?)\s*(gib|gb|tib|tb)\b',lambda m:m[1]+' '+{'gib':'GiB','gb':'GB','tib':'TiB','tb':'TB'}[m[2].lower()],value,flags=re.I)
    value=re.sub(r'\b(?:nvidia\s+)?(?:dgx\s+)?spark\b','DGX Spark',value,flags=re.I)
    return value

def normalize(key,value):
    if isinstance(value,str) and any(ord(c)<32 for c in value):raise ValueError('Identity fields must be single lines.')
    value=text(value)
    if value.casefold() in ('', 'unknown', 'not recorded', 'hardware not recorded'):return ''
    if len(value)>160 or any(ord(c)<32 for c in value) or ' | ' in value:
        raise ValueError('Identity fields must be single lines of at most 160 characters, without | separators.')
    if key=='hardware':return hardware(value)
    if key=='server_name':return {'lm studio':'LM Studio','lmstudio':'LM Studio','llama.cpp':'llama.cpp','llama-server':'llama.cpp','mlx-lm':'MLX-LM','vllm':'vLLM','vllm-mlx':'vllm-mlx','mtplx':'MTPLX','omlx':'oMLX','sglang':'SGLang','ds4':'DS4'}.get(value.casefold(),value)
    if key=='server_version':
        value=re.sub(r'^Version\s+', '',value,flags=re.I)
        match=re.fullmatch(r'(.+?)\s*\(\1\)',value)
        if match:value=match[1]
    if key=='quantization':
        if re.fullmatch(r'(?:i?q\d)(?:[_-][a-z0-9]+)*',value,re.I):return value.upper().replace('-', '_')
        if re.fullmatch(r'bf16|fp(?:16|32|8)',value,re.I):return value.upper()
    return value

def describe(manifest,values=None,recorded_hardware=None):
    values=values or {}
    config=manifest.get('model_config_snapshot') or {}
    profile=config.get('inference_profile') if isinstance(config.get('inference_profile'),dict) else {}
    machine=recorded_hardware or manifest.get('hardware') or {}
    fields={
        'hardware':values.get('hardware') or machine.get('label'),
        'server_name':values.get('server_name') or config.get('server_name') or profile.get('backend'),
        'server_version':values.get('server_version') or config.get('server_version') or profile.get('backend_version'),
        'model_name':values.get('model_name') or manifest.get('model_id') or config.get('model'),
        'quantization':values.get('quantization') or config.get('quantization'),
    }
    invalid=[]
    for k,v in fields.items():
        try:fields[k]=normalize(k,v)
        except ValueError:
            fields[k]=text(v)[:160];invalid.append(k)
    if not values.get('model_name') and (fields['model_name'].startswith(('/', '~/')) or re.match(r'^[A-Za-z]:[\\/]',fields['model_name'])):
        fields['model_name']=fields['model_name'].replace('\\','/').rsplit('/',1)[-1]
    missing=[k for k,v in fields.items() if not v]
    short_hardware=fields['hardware'].replace('DGX Spark','DGXSP').replace(' ', '')
    server=fields['server_name'] or 'XXX'
    if fields['server_version']:server+=' ('+fields['server_version']+')'
    generated='-'.join((short_hardware or 'XXX',server,fields['model_name'] or 'XXX',fields['quantization'] or 'XXX'))
    override=text(values.get('run_name'))
    return {'policy':POLICY,'name':override or generated,'generated_name':generated,'overridden':bool(override),'fields':fields,'missing':missing,'invalid':invalid,'legacy_label':override}

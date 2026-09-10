"""Explicit inference profiles layered onto the existing frozen model config.

Unmarked configurations are legacy: neither validation nor mapping changes them.
Mappings describe request APIs, not independently verified server/kernel behavior.
"""
import copy
import math
import re

ERA = 'explicit-v1'
MAPPING_VERSION = 'request-api-v1'
FIELDS = {
    'temperature': 'Temperature', 'top_p': 'Top p', 'top_k': 'Top k',
    'min_p': 'Min p', 'presence_penalty': 'Presence penalty',
    'frequency_penalty': 'Frequency penalty', 'repetition_penalty': 'Repetition penalty',
    'seed': 'Seed', 'enable_thinking': 'Thinking enabled',
    'preserve_thinking': 'Preserve thinking history', 'reasoning_effort': 'Reasoning effort',
}
SAMPLING = ('temperature', 'top_p', 'top_k', 'min_p', 'presence_penalty', 'repetition_penalty')
COMMON = ('temperature', 'top_p', 'presence_penalty', 'frequency_penalty', 'seed')
CT = {k: 'chat_template_kwargs.' + k for k in ('enable_thinking', 'preserve_thinking', 'reasoning_effort')}


def identity(*keys):
    return {k: k for k in keys}


BACKENDS = {
    'ds4': {
        'label': 'DS4', 'fields': {**identity('temperature', 'top_p', 'top_k', 'min_p', 'seed', 'reasoning_effort'), 'enable_thinking': 'thinking'},
        'source': 'https://github.com/antirez/ds4/blob/21e98c129ce20ebb9e5d2de1a1bbf5f991d3795d/ds4_server.c',
        'note': 'DS4 request parser at 21e98c1. Only none/high/max have distinct effort semantics. Think Max requires at least 384K context. Penalties and preserved-thinking control are not mapped.',
    },
    'omlx': {
        'label': 'oMLX', 'fields': {**identity(*COMMON, 'top_k', 'min_p', 'repetition_penalty'), **CT},
        'source': 'https://github.com/jundot/omlx/blob/94530d8d49541ede9e99ef04a4431ee4953117a6/omlx/api/openai_models.py',
        'note': 'API at 94530d8. The model template must support these thinking controls. Server force_sampling or forced template keys can override requests; server configuration remains the backend owner’s responsibility.',
    },
    'vllm': {
        'label': 'vLLM', 'fields': {**identity(*COMMON, 'top_k', 'min_p', 'repetition_penalty'), **CT},
        'source': 'https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/protocol.py',
        'note': 'Chat-completions schema checked 2026-09-10. Thinking controls require the matching model chat template; use the deployed version, not generic OpenAI compatibility, to assess support.',
    },
    'sglang': {
        'label': 'SGLang', 'fields': {**identity(*COMMON, 'top_k', 'min_p', 'repetition_penalty'), **CT},
        'source': 'https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/entrypoints/openai/protocol.py',
        'note': 'Chat-completions schema checked 2026-09-10. Thinking controls require the matching model chat template; harmony models have different reasoning behavior.',
    },
    'mtplx': {
        'label': 'MTPLX', 'fields': {**identity(*COMMON, 'top_k'), 'enable_thinking': 'chat_template_kwargs.enable_thinking', 'reasoning_effort': 'reasoning_effort'},
        'source': 'https://github.com/youssofal/MTPLX/blob/21be78b3f51820eecef020e5e4855c0715eaf9a5/mtplx/server/openai.py',
        'server_managed_fields': ['min_p', 'repetition_penalty', 'preserve_thinking'],
        'note': 'MTPLX accepts sampling and thinking requests listed below. Min p, repetition penalty and thinking-history preservation are not request controls; their effective behavior is determined by the server.',
    },
    'lmstudio': {
        'label': 'LM Studio', 'fields': {**identity(*COMMON, 'top_k'), 'repetition_penalty': 'repeat_penalty'},
        'source': 'https://lmstudio.ai/docs/developer/openai-compat/chat-completions',
        'note': 'Documented /v1/chat/completions fields checked 2026-09-10. Native /api/v1/chat parameters are a different API. Unverified thinking/min-p extensions are not mapped.',
    },
    'llamacpp': {
        'label': 'llama.cpp', 'fields': {**identity(*COMMON, 'top_k', 'min_p'), 'repetition_penalty': 'repeat_penalty', **CT},
        'source': 'https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md',
        'note': 'Server API checked 2026-09-10. Thinking/history kwargs need a compatible Jinja template. Repetition uses repeat_penalty, not repetition_penalty.',
    },
    'ollama': {
        'label': 'Ollama', 'fields': identity(*COMMON, 'reasoning_effort'),
        'source': 'https://docs.ollama.com/api/openai-compatibility',
        'note': 'OpenAI-compatible chat API checked 2026-09-10. Native options such as top_k are not advertised on this API. Reasoning effort depends on the served model.',
    },
}


def catalog():
    return {'era': ERA, 'native_era': __import__('stock_pi').ERA, 'mapping_version': MAPPING_VERSION, 'fields': FIELDS,
            'backends': copy.deepcopy(BACKENDS),
            'lanes': {'standard': 'No thinking mode (manual)', 'thinking': 'Thinking',
                      'non-thinking': 'Non-thinking', 'think-max': 'Think Max'}}


def family(repository):
    if re.fullmatch(r'Qwen/Qwen3\.8-[A-Za-z0-9_.-]+', repository or ''):
        return 'qwen38'
    if re.fullmatch(r'deepseek-ai/DeepSeek-V4-[A-Za-z0-9_.-]+', repository or ''):
        return 'deepseek4'
    return 'manual'


def required_fields(profile):
    kind = family((profile.get('source') or {}).get('repository'))
    lane = profile.get('lane')
    required = set(SAMPLING if kind == 'qwen38' else ('temperature', 'top_p'))
    # Every imported sampling recommendation is controlled, even for an unfamiliar model.
    required.update(k for k in (profile.get('source') or {}).get('candidates', {}) if k in FIELDS)
    if lane != 'standard':
        required.add('enable_thinking')
    if lane in ('thinking', 'think-max'):
        required.add('reasoning_effort')
    if kind == 'qwen38':
        required.add('preserve_thinking')
    return sorted(required)


def _check_values(values):
    if not isinstance(values, dict):
        raise ValueError('Inference settings must be an object.')
    if set(values) - set(FIELDS):
        raise ValueError('Unmapped inference settings: ' + ', '.join(sorted(set(values) - set(FIELDS))))
    for key, value in values.items():
        if key in ('enable_thinking', 'preserve_thinking'):
            valid = type(value) is bool
        elif key == 'reasoning_effort':
            valid = value in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
        else:
            valid = type(value) in (int, float) and math.isfinite(value)
            if valid and key in ('top_p', 'min_p'):
                valid = 0 <= value <= 1 and (key != 'top_p' or value > 0)
            elif valid and key in ('temperature', 'top_k'):
                valid = value >= 0
            elif valid and key == 'repetition_penalty':
                valid = value > 0
            elif valid and key in ('presence_penalty', 'frequency_penalty'):
                valid = -2 <= value <= 2
            if valid and key in ('top_k', 'seed'):
                valid = type(value) is int and abs(value) <= 2**53 - 1
        if not valid:
            raise ValueError('Invalid ' + FIELDS[key] + '.')


def request_settings(config):
    """Validate and map new profiles. Legacy configs return None without mutation."""
    if __import__('stock_pi').enabled(config):
        __import__('stock_pi').validate(config)
        return None  # Native Pi serializes the model declaration itself.
    if config.get('sampling_era') is None:
        if 'inference_profile' in config:
            raise ValueError('An inference profile requires sampling_era: explicit-v1.')
        return None
    if config['sampling_era'] != ERA:
        raise ValueError('Unknown sampling era.')
    profile = config.get('inference_profile')
    if not isinstance(profile, dict) or profile.get('mapping_version') != MAPPING_VERSION:
        raise ValueError('Choose a supported inference profile mapping.')
    backend = profile.get('backend')
    if not isinstance(backend, str) or backend not in BACKENDS:
        raise ValueError('Choose the inference backend.')
    version = profile.get('backend_version')
    if not isinstance(version, str) or not version.strip() or len(version) > 160 or any(ord(c) < 32 for c in version):
        raise ValueError('Record the deployed backend version or build identifier.')
    lane = profile.get('lane')
    if not isinstance(lane, str) or lane not in catalog()['lanes']:
        raise ValueError('Choose a thinking lane explicitly.')
    source = profile.get('source') or {}
    if not isinstance(source, dict):
        raise ValueError('Invalid recommendation source.')
    if source:
        import recommendation_import
        recommendation_import.validate_source(source)
        if source.get('lane') != lane:
            raise ValueError('Choose settings pulled for this lane; the saved source belongs to another lane.')
    kind = family(source.get('repository'))
    if kind == 'qwen38' and lane not in ('thinking', 'non-thinking'):
        raise ValueError('Qwen3.8 requires the thinking or non-thinking lane.')
    if (kind == 'deepseek4' or backend == 'ds4') and lane == 'standard':
        raise ValueError('Choose a DeepSeek thinking lane explicitly.')
    values = profile.get('values')
    _check_values(values)
    server_managed = profile.get('server_managed', [])
    allowed_server_fields = BACKENDS[backend].get('server_managed_fields', [])
    if (not isinstance(server_managed, list) or not all(isinstance(k, str) for k in server_managed)
            or len(set(server_managed)) != len(server_managed) or set(server_managed) - set(allowed_server_fields)):
        raise ValueError('Invalid server-controlled settings for this backend.')
    if set(server_managed) & set(values):
        raise ValueError('A server-controlled setting cannot also be requested. Remove the conflicting request value.')
    missing = set(required_fields(profile)) - set(values) - set(server_managed)
    if missing:
        raise ValueError('Supply required settings: ' + ', '.join(FIELDS[k] for k in sorted(missing)) + '.')
    if lane != 'standard' and values.get('enable_thinking') != (lane != 'non-thinking'):
        raise ValueError('Thinking enabled must match the selected lane.')
    if lane == 'standard' and any(k in values for k in ('enable_thinking', 'preserve_thinking', 'reasoning_effort')):
        raise ValueError('Choose a thinking lane to configure thinking controls.')
    if lane == 'non-thinking' and values.get('reasoning_effort', 'none') != 'none':
        raise ValueError('Non-thinking cannot request a nonzero reasoning effort.')
    if kind == 'qwen38' and lane == 'thinking' and values['reasoning_effort'] not in ('low', 'medium', 'xhigh'):
        raise ValueError('Qwen3.8 supports low, medium or xhigh effort.')
    if lane == 'thinking' and values.get('reasoning_effort') == 'none':
        raise ValueError('The thinking lane requires a nonzero reasoning effort.')
    if (kind == 'deepseek4' or backend == 'ds4') and lane == 'thinking' and values.get('reasoning_effort') == 'max':
        raise ValueError('Select the Think Max lane explicitly for max effort.')
    if lane == 'think-max' and values.get('reasoning_effort') != 'max':
        raise ValueError('Think Max requires max reasoning effort.')
    if backend == 'ds4' and values.get('reasoning_effort', 'none') not in ('none', 'high', 'max'):
        raise ValueError('DS4 only distinguishes none, high and max effort; other names collapse to high.')
    if backend == 'ollama' and values.get('reasoning_effort', 'none') not in ('none', 'low', 'medium', 'high', 'max'):
        raise ValueError('This Ollama API mapping does not support that reasoning effort.')
    context = config.get('context_window')
    if type(context) is not int or context < 1:
        raise ValueError('Record the model context capacity explicitly for a new profile.')
    if (kind == 'deepseek4' or backend == 'ds4') and values.get('reasoning_effort') == 'max' and context < 384 * 1024:
        raise ValueError('Think Max requires at least 384K context; it must not silently fall back to high.')
    budget = config.get('output_budget')
    if budget not in ('explicit', 'server'):
        raise ValueError('Choose an explicit output limit or deliberate server-controlled output.')
    limit = config.get('max_tokens')
    if type(limit) is not int or limit < 1:
        raise ValueError('Choose a positive output token capacity.')
    if budget == 'explicit' and limit > context:
        raise ValueError('The output limit cannot exceed the recorded context capacity.')
    if config.get('extra') or any(k in config for k in (*FIELDS, 'reasoning')):
        raise ValueError('Move additional sampling/reasoning fields into the explicit profile; conflicting legacy fields are not merged.')
    route = profile.get('route')
    if not isinstance(route, dict) or route.get('kind') not in ('direct', 'dsg'):
        raise ValueError('Choose a direct endpoint or DSG route.')
    if route['kind'] == 'dsg' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', route.get('name', '')):
        raise ValueError('Enter the configured single-backend DSG route name. A shared pool does not pin the backend.')
    if route['kind'] == 'direct' and route.get('name'):
        raise ValueError('A direct endpoint must not carry a DSG route name.')
    mapped = {}
    unsupported = set(values) - set(BACKENDS[backend]['fields'])
    # Ollama encodes the on/off choice through its documented effort field.
    if backend == 'ollama' and 'enable_thinking' in unsupported:
        unsupported.remove('enable_thinking')
        if values['enable_thinking'] and values.get('reasoning_effort', 'none') == 'none':
            raise ValueError('Select an explicit Ollama thinking effort.')
        mapped['reasoning_effort'] = values.get('reasoning_effort') if values['enable_thinking'] else 'none'
    if unsupported:
        raise ValueError(BACKENDS[backend]['label'] + ' is ineligible for these settings: ' + ', '.join(FIELDS[k] for k in sorted(unsupported)) + '. No settings were dropped.')
    for key, value in values.items():
        if key not in BACKENDS[backend]['fields']:
            continue
        parts = BACKENDS[backend]['fields'][key].split('.')
        target = mapped
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = copy.deepcopy(value)
    if budget == 'explicit':
        mapped['max_tokens'] = limit
    return mapped


def provenance(profile):
    """Attribute matching candidates; all other chosen values remain owner-supplied."""
    candidates = (profile.get('source') or {}).get('candidates', {})
    result = {}
    for key, value in profile.get('values', {}).items():
        matches = [c['source'] for c in candidates.get(key, []) if type(c['value']) is type(value) and c['value'] == value
                   or type(c['value']) in (int, float) and type(value) in (int, float) and c['value'] == value]
        result[key] = {'value': value, 'sources': matches or ['owner'],
                       'recommendations': copy.deepcopy(candidates.get(key, [])),
                       'custom': bool(candidates.get(key)) and not matches}
    for key in profile.get('server_managed', []):
        result[key] = {'value': None, 'sources': ['server'], 'status': 'server-controlled; effective value not verified',
                       'recommendations': copy.deepcopy(candidates.get(key, [])), 'custom': True}
    return result


def validate_new_entries(before, after):
    """Keep legacy saves/copies working; do not create unrelated new legacy entries."""
    old = before.get('models', [])
    names = {m.get('name') for m in old}
    without_name = lambda m: {k: v for k, v in m.items() if k not in ('name','hardware')}
    for model in after.get('models', []):
        request_settings(model)
        if model.get('sampling_era') is None and model.get('name') not in names:
            if not any(without_name(model) == without_name(prior) for prior in old):
                raise ValueError('New models need an explicit inference profile. Existing legacy profiles and exact copies remain grandfathered.')

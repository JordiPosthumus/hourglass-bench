"""Native Pi model declarations for the stock-session benchmark baseline.

This module never computes request token budgets or serializes generation
requests. The pinned Pi provider does both, using its normal session defaults.
"""
import copy
import json
import re

ERA = 'pi-native-v1'
MODEL_FIELDS = {'reasoning', 'input', 'compat', 'thinkingLevelMap', 'samplingParams'}
THINKING_LEVELS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
GENERATION_OVERRIDES = {'max_tokens', 'max_completion_tokens', 'reasoning_effort',
                        'reasoning', 'thinking', 'enable_thinking', 'chat_template_kwargs'}


def enabled(config):
    return config.get('sampling_era') == ERA


def validate(config):
    import inference_profiles
    profile = config.get('inference_profile')
    if not isinstance(profile, dict) or profile.get('mapping_version') != ERA:
        raise ValueError('Choose a native Pi model profile.')
    if profile.get('backend') not in inference_profiles.BACKENDS:
        raise ValueError('Choose the inference backend.')
    version = profile.get('backend_version')
    if not isinstance(version, str) or not version.strip() or len(version) > 160 or any(ord(c) < 32 for c in version):
        raise ValueError('Record the deployed backend version or build identifier.')
    if set(profile) - {'mapping_version', 'backend', 'backend_version', 'route'}:
        raise ValueError('Native Pi profiles use model declarations, not a legacy request override.')
    route = profile.get('route')
    if not isinstance(route, dict) or route.get('kind') not in ('direct', 'dsg'):
        raise ValueError('Choose a direct endpoint or DSG route.')
    if route['kind'] == 'dsg' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', route.get('name', '')):
        raise ValueError('Enter the configured single-backend DSG route name.')
    if route['kind'] == 'direct' and route.get('name'):
        raise ValueError('A direct endpoint must not carry a DSG route name.')
    for name in ('max_tokens', 'context_window'):
        if type(config.get(name)) is not int or config[name] < 1:
            raise ValueError('Record a positive ' + name + ' model capacity.')
    if config.get('output_budget') != 'pi':
        raise ValueError('Native Pi computes the output allowance; use output_budget: pi.')
    if config.get('pi_thinking_level') not in (None, *THINKING_LEVELS):
        raise ValueError('Choose a supported Pi thinking level.')
    if config.get('extra') or any(k in config for k in (*inference_profiles.FIELDS, 'reasoning')):
        raise ValueError('Native Pi does not use legacy generation overrides. Put sampling in pi_model.samplingParams.')
    declaration = config.get('pi_model', {})
    if not isinstance(declaration, dict) or set(declaration) - MODEL_FIELDS:
        raise ValueError('pi_model accepts native reasoning, input, compat, thinkingLevelMap and samplingParams fields.')
    for field in ('compat', 'thinkingLevelMap', 'samplingParams'):
        if field in declaration and not isinstance(declaration[field], dict):
            raise ValueError('pi_model.' + field + ' must be an object.')
    if 'reasoning' in declaration and type(declaration['reasoning']) is not bool:
        raise ValueError('pi_model.reasoning must be a boolean.')
    if 'input' in declaration and (not isinstance(declaration['input'], list) or not declaration['input']
            or any(kind not in ('text', 'image') for kind in declaration['input'])):
        raise ValueError('pi_model.input must contain text and/or image.')
    if GENERATION_OVERRIDES & set(declaration.get('samplingParams', {})):
        raise ValueError('Let native Pi control thinking and context budgets; samplingParams must not override them.')
    level_map = declaration.get('thinkingLevelMap', {})
    if any(k not in THINKING_LEVELS or v is not None and v not in ('none', *THINKING_LEVELS) for k, v in level_map.items()):
        raise ValueError('thinkingLevelMap must map Pi levels to supported reasoning levels or null.')
    level = config.get('pi_thinking_level')
    if level is not None and (level_map.get(level, False) is None or
            level in ('xhigh', 'max') and level not in level_map or
            declaration.get('reasoning') is False and level != 'off'):
        raise ValueError('The selected thinking level is not declared by this Pi model. Review its thinkingLevelMap.')
    json.dumps(declaration, allow_nan=False)


def compatibility(backend):
    # These are Pi's documented custom-provider fields, not a payload hook.
    compat = {'supportsStore': False, 'supportsDeveloperRole': False,
              'supportsStrictMode': False, 'maxTokensField': 'max_tokens'}
    if backend == 'mtplx':
        compat.update(thinkingFormat='qwen', supportsReasoningEffort=True,
                      requiresReasoningContentOnAssistantMessages=True)
    elif backend in ('vllm', 'sglang', 'omlx', 'llamacpp'):
        compat.update(thinkingFormat='chat-template',
                      requiresReasoningContentOnAssistantMessages=True,
                      chatTemplateKwargs={'enable_thinking': {'$var': 'thinking.enabled'},
                                          'reasoning_effort': {'$var': 'thinking.effort', 'omitWhenOff': True}})
    elif backend == 'ds4':
        compat.update(thinkingFormat='deepseek', supportsReasoningEffort=True,
                      requiresReasoningContentOnAssistantMessages=True)
    elif backend == 'lmstudio':
        compat['supportsReasoningEffort'] = False
    return compat


def model_definition(config, context=None):
    validate(config)
    definition = {'id': config['model'], 'name': config['model'], 'reasoning': True,
                  'input': ['text'] if config.get('supports_vision') is False else ['text', 'image'],
                  'contextWindow': context or config['context_window'], 'maxTokens': config['max_tokens'],
                  'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
                  'compat': compatibility(config['inference_profile']['backend'])}
    supplied = copy.deepcopy(config.get('pi_model', {}))
    definition['compat'].update(supplied.pop('compat', {}))
    definition.update(supplied)
    return definition


def migrate(config):
    """Convert reviewed settings to a model declaration, preserving capacities.

    Callers must back up the original document and show the behavior change.
    Frozen historical configurations are never passed through this function.
    """
    import inference_profiles
    if enabled(config):
        validate(config)
        return copy.deepcopy(config)
    if config.get('sampling_era') != inference_profiles.ERA:
        raise ValueError('Choose the backend before converting a legacy configuration.')
    mapped = inference_profiles.request_settings(config)
    old = config['inference_profile']
    result = copy.deepcopy(config)
    result.update(sampling_era=ERA, output_budget='pi', inference_profile={
        'mapping_version': ERA, 'backend': old['backend'], 'backend_version': old['backend_version'],
        'route': copy.deepcopy(old['route'])})
    # Preserve the reviewed thinking selection as an ordinary Pi session option.
    # Pi retains ownership of serialization and context-aware output sizing.
    values = old.get('values', {})
    effort = values.get('reasoning_effort')
    result['pi_thinking_level'] = 'off' if values.get('enable_thinking') is False else effort or 'medium'
    sampling = {k: v for k, v in mapped.items() if k not in GENERATION_OVERRIDES}
    model = {'samplingParams': sampling} if sampling else {}
    if 'qwen3.8' in config['model'].lower() or 'qwen38' in config['model'].lower():
        model['thinkingLevelMap'] = {'minimal':None, 'low':'low', 'medium':'medium', 'high':None, 'xhigh':'xhigh', 'max':None}
    elif effort in ('xhigh', 'max'):
        model['thinkingLevelMap'] = {effort:effort}
    if 'preserve_thinking' in old.get('values', {}) and old['backend'] in ('vllm', 'sglang', 'omlx', 'llamacpp'):
        model['compat'] = compatibility(old['backend'])
        model['compat']['chatTemplateKwargs']['preserve_thinking'] = old['values']['preserve_thinking']
    result['pi_model'] = model
    result['prior_inference_profile'] = copy.deepcopy(old)
    validate(result)
    return result

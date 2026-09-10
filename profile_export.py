"""Standalone settings handoff; never a generic file download or Pi installer."""
import json
import re
import inference_profiles as profiles

PI_VERSION = '0.85.1'
WIRE_KEYS = {'temperature', 'top_p', 'top_k', 'min_p', 'presence_penalty',
             'frequency_penalty', 'repetition_penalty', 'repeat_penalty', 'seed',
             'reasoning_effort', 'thinking', 'enable_thinking', 'max_tokens', 'max_completion_tokens'}
TEMPLATE_KEYS = {'enable_thinking', 'preserve_thinking', 'reasoning_effort'}


def clean_values(values):
    """Allow known numeric/bool/effort fields only, including inside template kwargs."""
    if not isinstance(values, dict):
        return {}
    result = {}
    for key in WIRE_KEYS:
        value = values.get(key)
        if type(value) in (int, float, bool) or type(value) is str and value in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
            result[key] = value
    nested = values.get('chat_template_kwargs')
    if isinstance(nested, dict):
        subset = {k: v for k, v in nested.items() if k in TEMPLATE_KEYS and (type(v) is bool or type(v) is str and v in ('none', 'low', 'medium', 'high', 'xhigh', 'max'))}
        if subset:
            result['chat_template_kwargs'] = subset
    # Reject nonfinite values rather than emitting invalid code.
    json.dumps(result, allow_nan=False)
    return result


def public_identifier(value, placeholder):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./+ -]{0,159}', value):
        return placeholder
    if any(part in value.lower() for part in ('users/', 'home/', 'private/', 'secret', 'token', 'password', 'api_key', '..')):
        return placeholder
    return value


def extension_source(settings):
    settings = clean_values(settings)
    keys = sorted(WIRE_KEYS | {'chat_template_kwargs', 'reasoning'})
    return ('// Settings handoff for Pi ' + PI_VERSION + '. Replace MODEL_ID before use.\n'
            'const settings = ' + json.dumps(settings, indent=2, allow_nan=False) + ';\n'
            'export default function (pi) {\n'
            "  pi.on('before_provider_request', event => {\n"
            '    if (event.payload.model !== "<MODEL_ID>") return;\n'
            '    const payload = {...event.payload};\n'
            '    for (const key of ' + json.dumps(keys) + ') delete payload[key];\n'
            '    return Object.assign(payload, structuredClone(settings));\n'
            '  });\n'
            '}\n')


def export(manifest, rows):
    if manifest.get('state') in (None, 'running', 'pending'):
        raise ValueError('Export settings after the run has finished or stopped.')
    run_id = manifest.get('id', '')
    if not isinstance(run_id, str) or not run_id.isalnum():
        raise ValueError('Invalid run ID.')
    config = manifest.get('model_config_snapshot') or {}
    if __import__('stock_pi').enabled(config):
        return export_native(manifest, rows)
    explicit = config.get('sampling_era') == profiles.ERA
    expected = profiles.request_settings(config) if explicit else None
    observed, versions, missing, observations = [], set(), 0, 0
    for row in rows:
        if row.get('evaluation_id') != run_id:
            continue
        version = row.get('pi_version')
        if isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version):
            versions.add(version)
        records = row.get('requested_settings') or []
        if not isinstance(records, list):
            records = [records]
        expected_count=(row.get('settings_capture') or {}).get('request_count')
        if explicit:
            if type(expected_count) is not int:
                missing += 1
            else:
                missing += max(0, expected_count-len(records))
        if not records:
            missing += 1
        for record in records:
            if not isinstance(record, dict) or record.get('capture_error') or not isinstance(record.get('values'), dict):
                missing += 1
                continue
            view = clean_values(record['values'])
            observations += 1
            if view not in observed:
                observed.append(view)
    profile = config.get('inference_profile') or {}
    lines = ['# Hourglass inference settings handoff', '',
             'Run: `' + run_id + '`', '',
             'Model: ' + public_identifier(config.get('model'), '<MODEL_ID>'), '',
             'Sampling era: `' + (profiles.ERA if explicit else 'legacy (grandfathered; unknown settings remain unknown)') + '`', '',
             'Hourglass Pi: ' + (', '.join(sorted(versions)) or 'not recorded in available attempt evidence') + '.', '']
    adapter = manifest.get('inference_adapter') or {}
    for key in ('harness_sha256', 'settings_adapter_sha256', 'pi_lock_sha256'):
        value = adapter.get(key)
        if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value):
            lines.extend([key + ': `' + value + '`', ''])
    if explicit:
        backend = profiles.BACKENDS[profile['backend']]
        lines.extend(['Backend: ' + backend['label'] + '; build: ' + public_identifier(profile.get('backend_version'), '<BACKEND_VERSION>') + '.', '',
                      'Lane: ' + profile['lane'] + '.', '',
                      'Output budget: ' + ('explicit combined token limit' if config['output_budget'] == 'explicit' else 'server controlled; no output-limit field sent') + '.', '',
                      'Context capacity recorded by the owner: ' + str(config['context_window']) + ' tokens. This is not a server configuration command.', '',
                      '## Frozen requested settings', '', '```json', json.dumps(expected, indent=2, sort_keys=True), '```', '',
                      'Optional omitted controls: ' + ', '.join(sorted(set(profiles.FIELDS) - set(profile['values']) - set(profile.get('server_managed', [])))) + '.', '',
                      '## Sources and reviewed choices', ''])
        if profile.get('server_managed'):
            lines.extend(['Server-controlled settings (not sent; effective values not verified): ' +
                          ', '.join(profiles.FIELDS[k] for k in profile['server_managed']) + '.', ''])
        source = profile.get('source') or {}
        if source:
            for file in source['files']:
                url = 'https://huggingface.co/' + source['repository'] + '/blob/' + source['revision'] + '/' + file['name']
                lines.extend(['- [' + file['name'] + '](' + url + '), SHA-256 `' + file['sha256'] + '`.'])
            lines.extend(['', 'Importer: `' + source['importer_version'] + '`.', ''])
            retrieved = source.get('retrieved_at')
            if isinstance(retrieved, str) and re.fullmatch(r'[0-9T:+.Z-]{10,40}', retrieved):
                lines.extend(['Retrieved: `' + retrieved + '`.', ''])
        else:
            lines.extend(['Settings were supplied manually by the owner.', ''])
        lines.extend(['```json', json.dumps(profiles.provenance(profile), indent=2, sort_keys=True), '```', '',
                      '[' + backend['label'] + ' mapping source](' + backend['source'] + '). ' + backend['note'], ''])
    lines.extend(['## Recorded outgoing settings', '',
                  str(observations) + ' request observations; ' + str(missing) + ' missing/failed capture records or attempts.', ''])
    if not explicit:
        lines.extend(['Legacy evidence was captured before serialization; it is not proof of final wire settings.', ''])
    if observed:
        for settings in observed:
            lines.extend(['```json', json.dumps(settings, indent=2, sort_keys=True), '```', ''])
    else:
        lines.extend(['No outgoing settings were recorded. Do not infer omitted historical values from current profiles.', ''])
    matches = explicit and bool(observed) and all(view == expected for view in observed) and not missing
    if explicit and not matches:
        lines.extend(['The available outgoing evidence does not establish a complete match to the frozen request. Resolve missing or differing observations before describing the production port as tested.', ''])
    if explicit:
        headers = {'x-dsg-model': '<CONFIGURED_SINGLE_BACKEND_ROUTE>'} if profile['route']['kind'] == 'dsg' else {}
        provider = {'baseUrl': '<ENDPOINT_BASE_URL>', 'api': 'openai-completions', 'apiKey': '<CREDENTIAL_OR_ENV_REFERENCE>',
                    'models': [{'id': '<MODEL_ID>', 'name': '<MODEL_LABEL>', 'reasoning': profile['lane'] != 'standard',
                                'contextWindow': config['context_window'], 'maxTokens': config['max_tokens']}]}
        if headers:
            provider['headers'] = headers
        lines.extend(['## Suggested production Pi configuration', '',
                      'Serializer target: Pi ' + PI_VERSION + '. Other versions require a fresh serializer check. Replace placeholders and review any existing extensions that also modify requests.', '',
                      'Merge this provider into the existing Pi model configuration:', '', '```json',
                      json.dumps({'providers': {'tested-profile': provider}}, indent=2), '```', '',
                      'Load this settings extension for the selected model:', '', '```javascript',
                      extension_source(expected).rstrip(), '```', '',
                      'If using DSG, the route must already select the intended backend. This file does not configure the gateway.', '',
                      'Requested settings are not independently verified effective server values. Matching inference settings does not reproduce benchmark prompts, tools or task quality.', ''])
    lines.extend(['No production Pi files, credentials or server settings were installed or changed by this export.', ''])
    return '\n'.join(lines)


def export_native(manifest, rows):
    """A normal Pi model configuration, with no request-rewriting extension."""
    import stock_pi
    config = manifest['model_config_snapshot']
    definition = stock_pi.model_definition(config)
    # Export only native compatibility data needed to reproduce these requests.
    # Arbitrary saved objects must never become a channel for credentials/paths.
    compat = definition.get('compat', {})
    safe_compat = {k:v for k,v in compat.items() if k in (
        'supportsStore','supportsDeveloperRole','supportsStrictMode','supportsReasoningEffort',
        'requiresReasoningContentOnAssistantMessages','supportsUsageInStreaming') and type(v) is bool}
    for k, allowed in [('maxTokensField',('max_tokens','max_completion_tokens')),
                       ('thinkingFormat',('qwen','chat-template','deepseek','zai','openai'))]:
        if compat.get(k) in allowed: safe_compat[k]=compat[k]
    template = {}
    for k,v in (compat.get('chatTemplateKwargs') or {}).items():
        if k not in TEMPLATE_KEYS: continue
        if type(v) is bool or type(v) is str and v in ('none', *stock_pi.THINKING_LEVELS): template[k]=v
        elif isinstance(v,dict) and v.get('$var') in ('thinking.enabled','thinking.effort'):
            template[k]={'$var':v['$var'], **({'omitWhenOff':v['omitWhenOff']} if type(v.get('omitWhenOff')) is bool else {})}
    if template: safe_compat['chatTemplateKwargs']=template
    omitted_compat = safe_compat != compat
    definition['compat']=safe_compat
    original_sampling=definition.get('samplingParams', {})
    definition['samplingParams']=clean_values(original_sampling)
    omitted_sampling=definition['samplingParams'] != original_sampling
    definition.update(id='<MODEL_ID>', name='<MODEL_LABEL>')
    provider = {'baseUrl':'<ENDPOINT_BASE_URL>', 'api':'openai-completions',
                'apiKey':'<CREDENTIAL_OR_ENV_REFERENCE>', 'models':[definition]}
    if config['inference_profile']['route']['kind'] == 'dsg':
        provider['headers'] = {'x-dsg-model':'<CONFIGURED_SINGLE_BACKEND_ROUTE>'}
    observations, sessions, missing = [], [], 0
    for row in rows:
        if row.get('evaluation_id') != manifest['id']:
            continue
        records = row.get('requested_settings') or []
        if not isinstance(records, list):
            records = []
        count = (row.get('settings_capture') or {}).get('request_count')
        missing += max(0, count-len(records)) if type(count) is int else 1
        for record in records:
            if not isinstance(record, dict) or record.get('capture_error'):
                missing += 1
            else:
                value = clean_values(record.get('values'))
                if value not in observations:
                    observations.append(value)
        session = row.get('pi_session')
        if isinstance(session, dict):
            safe_session={k:v for k,v in session.items() if k in ('thinking_level','selected_thinking_level') and v in (*stock_pi.THINKING_LEVELS, 'Pi default')}
            if type(session.get('http_idle_timeout_ms')) is int:safe_session['http_idle_timeout_ms']=session['http_idle_timeout_ms']
            for k in ('compaction','retry'):
                if isinstance(session.get(k),dict):safe_session[k]={name:value for name,value in session[k].items() if name in ('enabled','reserveTokens','keepRecentTokens','maxRetries','baseDelayMs','maxDelayMs') and type(value) in (int,bool)}
            if safe_session not in sessions:sessions.append(safe_session)
    return '\n'.join([
        '# Hourglass stock Pi handoff', '', 'Run: `' + manifest['id'] + '`.', '',
        'Baseline: native Pi ' + PI_VERSION + ' (`' + stock_pi.ERA + '`).', '',
        'Select thinking level: `' + config.get('pi_thinking_level','Pi default') + '`. Use Pi’s normal session defaults for compaction, retry and HTTP idle timeout. No output-budget, thinking or timeout extension is required.', '',
        ('Some nonstandard model declaration fields were omitted from this public handoff; it is incomplete and requires private review.' if omitted_compat or omitted_sampling else 'The exported model declaration retains the supported native compatibility and sampling fields.'), '',
        'The model output capacity is a ceiling. Pi calculates each request allowance from the remaining context; observed limits can differ between turns and compaction requests.', '',
        '## Pi model configuration', '',
        'Replace the endpoint, credential, model and optional route placeholders. Review existing settings and extensions before merging.', '',
        '```json', json.dumps({'providers':{'tested-profile':provider}}, indent=2), '```', '',
        '## Recorded Pi session settings', '', '```json', json.dumps(sessions, indent=2), '```', '',
        '## Recorded outgoing settings', '',
        str(missing) + ' missing or failed observation records/attempts.', '',
        '```json', json.dumps(observations, indent=2), '```', '',
        'These are client declarations and observations, not independent proof of effective server settings. Hourglass adds its question, answer submission, workspace isolation and scoring clock.', '',
        'This export does not install or change production Pi files, credentials or server configuration.', ''])

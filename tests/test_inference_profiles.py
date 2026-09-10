import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inference_profiles as profiles
import recommendation_import as importer
import profile_export


def config(backend='omlx', lane='standard', values=None):
    return {'name': 'fixture', 'model': 'fixture', 'base_url': 'http://example.invalid/v1',
            'context_window': 262144, 'max_tokens': 131072, 'output_budget': 'explicit',
            'sampling_era': profiles.ERA,
            'inference_profile': {'mapping_version': profiles.MAPPING_VERSION, 'backend': backend,
                                  'backend_version': 'fixture-build', 'lane': lane, 'route': {'kind': 'direct'},
                                  'values': values if values is not None else {'temperature': 0, 'top_p': 0.95}}}


CARD = b'''Qwen3.8 supports `enable_thinking`, `preserve_thinking`, and `reasoning_effort`.
It retains thinking blocks from all historical messages. xhigh by default.
## Best Practices
- Thinking Mode: `temperature=1.0`, `top_p=0.95`, `top_k=20`, `min_p=0.0`, `presence_penalty=0.0`, `repetition_penalty=1.0`
- Instruct (or non-thinking) mode: `temperature=0.7`, `top_p=0.80`, `top_k=20`, `min_p=0.0`, `presence_penalty=1.5`, `repetition_penalty=1.0`
## Other examples
temperature=0.1
'''


def qwen_source(lane='thinking'):
    files = {'generation_config.json': b'{"temperature":1.0,"top_p":0.95,"top_k":20}', 'README.md': CARD}
    return {'repository': 'Qwen/Qwen3.8-27B', 'revision': 'a' * 40, 'lane': lane,
            'importer_version': importer.VERSION, 'retrieved_at': '2026-09-10T00:00:00+00:00',
            'files': [{'name': k, 'sha256': hashlib.sha256(v).hexdigest()} for k, v in files.items()],
            **importer.parse('Qwen/Qwen3.8-27B', lane, files)}


class ProfileTests(unittest.TestCase):
    def test_legacy_is_unchanged_and_needs_no_metadata(self):
        cfg = {'name': 'old', 'model': 'fixture', 'extra': {'temperature': 2, 'custom': False}}
        original = copy.deepcopy(cfg)
        with patch('urllib.request.urlopen', side_effect=AssertionError('No discovery')):
            self.assertIsNone(profiles.request_settings(cfg))
        self.assertEqual(cfg, original)

    def test_all_eight_backends_have_positive_and_rejected_cases(self):
        self.assertEqual(len(profiles.BACKENDS), 8)
        for backend in profiles.BACKENDS:
            with self.subTest(backend=backend):
                cfg = config(backend)
                expected={'temperature':0,'top_p':0.95,'max_tokens':131072}
                if backend=='ds4':
                    cfg['inference_profile'].update(lane='non-thinking')
                    cfg['inference_profile']['values']['enable_thinking']=False
                    expected['thinking']=False
                self.assertEqual(profiles.request_settings(cfg),expected)
                cfg['inference_profile']['values']['unmapped_control'] = True
                with self.assertRaisesRegex(ValueError, 'Unmapped'):
                    profiles.request_settings(cfg)

    def test_qwen_nested_controls_and_custom_values_survive(self):
        source = qwen_source()
        cfg = config(lane='thinking', values=copy.deepcopy(source['suggested']))
        cfg['inference_profile']['source'] = source
        cfg['inference_profile']['values']['temperature'] = 0
        expected = {'temperature': 0, 'top_p': .95, 'top_k': 20, 'min_p': 0.,
                    'presence_penalty': 0., 'repetition_penalty': 1., 'max_tokens': 131072,
                    'chat_template_kwargs': {'enable_thinking': True, 'preserve_thinking': True, 'reasoning_effort': 'xhigh'}}
        self.assertEqual(profiles.request_settings(cfg), expected)
        self.assertEqual(profiles.provenance(cfg['inference_profile'])['temperature']['sources'], ['owner'])
        cfg['inference_profile']['values']['preserve_thinking'] = False
        self.assertFalse(profiles.request_settings(cfg)['chat_template_kwargs']['preserve_thinking'])
        del cfg['inference_profile']['values']['preserve_thinking']
        with self.assertRaisesRegex(ValueError, 'Preserve thinking'):
            profiles.request_settings(cfg)

    def test_unsupported_crucial_fields_do_not_have_an_override(self):
        source = qwen_source()
        for backend in ('ollama', 'lmstudio', 'mtplx', 'ds4'):
            cfg = config(backend, 'thinking', copy.deepcopy(source['suggested']))
            cfg['inference_profile'].update(source=source, acknowledge_unsupported=True, custom=True)
            with self.subTest(backend=backend), self.assertRaises(ValueError):
                profiles.request_settings(cfg)

    def test_mtplx_records_server_controlled_values_without_claiming_requests(self):
        source = qwen_source()
        values = copy.deepcopy(source['suggested'])
        server_fields = profiles.BACKENDS['mtplx']['server_managed_fields']
        for key in server_fields: del values[key]
        cfg = config('mtplx', 'thinking', values)
        cfg['inference_profile'].update(source=source, server_managed=server_fields)
        before = copy.deepcopy(cfg)
        mapped = profiles.request_settings(cfg)
        self.assertEqual(mapped['reasoning_effort'], 'xhigh')
        self.assertEqual(mapped['chat_template_kwargs'], {'enable_thinking': True})
        self.assertEqual(mapped['temperature'], 1)
        for key in server_fields:
            self.assertNotIn(key, mapped)
            provenance = profiles.provenance(cfg['inference_profile'])[key]
            self.assertIsNone(provenance['value'])
            self.assertIn('not verified', provenance['status'])
            self.assertEqual(provenance['recommendations'], source['candidates'][key])
        self.assertEqual(cfg, before)
        for bad in (['reasoning_effort'], ['temperature'], 'min_p', ['min_p','min_p']):
            cfg['inference_profile']['server_managed'] = bad
            with self.assertRaises(ValueError): profiles.request_settings(cfg)
        cfg = before
        cfg['inference_profile']['values']['preserve_thinking'] = False
        with self.assertRaisesRegex(ValueError, 'cannot also be requested'): profiles.request_settings(cfg)

    def test_old_imported_profiles_remain_valid_and_unchanged(self):
        source = qwen_source()
        source['importer_version'] = 'hf-settings-v1'
        cfg = config(lane='thinking', values=copy.deepcopy(source['suggested']))
        cfg['inference_profile']['source'] = source
        before = copy.deepcopy(cfg)
        profiles.request_settings(cfg)
        self.assertEqual(cfg, before)

    def test_named_backend_translations_and_omitted_output(self):
        cfg = config('llamacpp', values={'temperature': 0, 'top_p': .95, 'repetition_penalty': 1})
        cfg['output_budget'] = 'server'
        mapped = profiles.request_settings(cfg)
        self.assertEqual(mapped['repeat_penalty'], 1)
        self.assertNotIn('max_tokens', mapped)
        self.assertNotIn('repetition_penalty', mapped)
        cfg = config('ollama', 'non-thinking', {'temperature': 0, 'top_p': .95, 'enable_thinking': False})
        self.assertEqual(profiles.request_settings(cfg)['reasoning_effort'], 'none')

    def test_missing_invalid_and_conflicting_values_block(self):
        for change in ({'temperature': None}, {'temperature': False}, {'temperature': float('nan')},
                       {'top_p': 1.1}, {'top_k': 1.2}, {'enable_thinking': 'false'}):
            cfg = config(); cfg['inference_profile']['values'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                profiles.request_settings(cfg)
        cfg = config(); cfg['extra'] = {'temperature': 1}
        with self.assertRaisesRegex(ValueError, 'legacy fields'):
            profiles.request_settings(cfg)
        cfg = config(); cfg['inference_profile']['route'] = {'kind': 'dsg'}
        with self.assertRaisesRegex(ValueError, 'route name'):
            profiles.request_settings(cfg)
        cfg['inference_profile']['route']['name'] = 'spark-fixture'
        profiles.request_settings(cfg)

    def test_ds4_does_not_collapse_effort_or_context(self):
        cfg = config('ds4', 'think-max', {'temperature': 1, 'top_p': 1, 'enable_thinking': True, 'reasoning_effort': 'max'})
        with self.assertRaisesRegex(ValueError, '384K'):
            profiles.request_settings(cfg)
        cfg['context_window'] = 1048576
        self.assertEqual(profiles.request_settings(cfg)['reasoning_effort'], 'max')
        cfg['inference_profile'].update(lane='thinking')
        cfg['inference_profile']['values']['reasoning_effort'] = 'medium'
        with self.assertRaisesRegex(ValueError, 'collapse'):
            profiles.request_settings(cfg)

    def test_new_legacy_entries_rejected_but_existing_and_copies_allowed(self):
        old = {'name': 'old', 'model': 'fixture', 'extra': {'temperature': 2}}
        profiles.validate_new_entries({'models': [old]}, {'models': [old, {**old, 'name': 'copy'}]})
        with self.assertRaisesRegex(ValueError, 'explicit inference profile'):
            profiles.validate_new_entries({'models': [old]}, {'models': [{**old, 'name': 'new', 'model': 'other'}]})


class ImportTests(unittest.TestCase):
    def test_pull_without_mode_downloads_once_and_preserves_each_proposal(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if '/api/models/' in url: return json.dumps({'sha': 'b' * 40}).encode()
            return CARD if url.endswith('README.md') else b'{"temperature":1,"top_p":0.95}'
        result = importer.pull('Qwen/Qwen3.8-27B', 'main', fetcher=fetch)
        self.assertEqual(len(calls), 3)
        self.assertEqual(set(result['proposals']), {'thinking', 'non-thinking'})
        for lane, proposal in result['proposals'].items():
            importer.validate_source(proposal)
            self.assertEqual(proposal['lane'], lane)
            self.assertEqual(proposal['revision'], result['revision'])
            self.assertEqual(proposal['files'], result['files'])
            old = importer.pull('Qwen/Qwen3.8-27B', 'main', lane, fetch)
            old['retrieved_at'] = proposal['retrieved_at']
            self.assertEqual(proposal, old)
        self.assertTrue(result['proposals']['thinking']['suggested']['enable_thinking'])
        self.assertFalse(result['proposals']['non-thinking']['suggested']['enable_thinking'])
        self.assertEqual(result['proposals']['non-thinking']['suggested']['temperature'], .7)

    def test_unknown_card_does_not_claim_verified_mode_support(self):
        def fetch(url):
            if '/api/models/' in url: return json.dumps({'sha': 'b' * 40}).encode()
            return b'Unrecognized card' if url.endswith('README.md') else b'{"temperature":0.7}'
        result = importer.pull('Publisher/model', 'main', fetcher=fetch)
        for proposal in result['proposals'].values():
            self.assertFalse(proposal['card_supported'])
            self.assertNotIn('enable_thinking', proposal['suggested'])
            importer.validate_source(proposal)

    def test_greedy_configuration_cannot_mix_with_sampled_card(self):
        with self.assertRaisesRegex(ValueError, 'greedy decoding'):
            importer.parse('Qwen/Qwen3.8-27B', 'thinking',
                           {'generation_config.json': b'{"do_sample":false}', 'README.md': CARD})

    def test_validation_is_offline_and_preserves_saved_source(self):
        source = qwen_source()
        cfg = config(lane='thinking', values=copy.deepcopy(source['suggested']))
        cfg['inference_profile']['source'] = source
        before = copy.deepcopy(cfg)
        with patch.object(importer, 'fetch', side_effect=AssertionError('No network')):
            profiles.request_settings(cfg)
        self.assertEqual(cfg, before)

    def test_mode_specific_card_overrides_defaults_without_losing_evidence(self):
        a = qwen_source('non-thinking'); b = qwen_source('non-thinking')
        self.assertEqual(a, b)
        self.assertEqual(a['candidates']['temperature'], [{'value': 1.0, 'source': 'generation_config.json'}, {'value': .7, 'source': 'README.md'}])
        self.assertEqual(a['suggested']['temperature'], .7)
        self.assertEqual(a['suggested']['top_p'], .8)
        self.assertFalse(a['conflicts'])
        self.assertFalse(a['suggested']['enable_thinking'])
        self.assertNotIn(.1, [c['value'] for c in a['candidates']['temperature']])
        cfg = config(lane='non-thinking', values=copy.deepcopy(a['suggested']))
        cfg['inference_profile']['source'] = a
        self.assertEqual(profiles.request_settings(cfg)['temperature'], .7)

    def test_pull_pins_all_files_and_retains_hashes(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if '/api/models/' in url: return json.dumps({'sha': 'b' * 40}).encode()
            return CARD if url.endswith('README.md') else b'{"temperature":1,"top_p":0.95}'
        source = importer.pull('Qwen/Qwen3.8-27B', 'main', 'thinking', fetch)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all('/resolve/' + 'b' * 40 + '/' in u for u in calls[1:]))
        self.assertEqual(source['files'][1]['sha256'], hashlib.sha256(CARD).hexdigest())
        original = copy.deepcopy(source)
        importer.pull('Qwen/Qwen3.8-27B', 'main', 'thinking', fetch)
        self.assertEqual(source, original)

    def test_unknown_prose_and_source_urls_are_not_guessed(self):
        parsed = importer.parse('Publisher/model', 'standard', {'README.md': b'You should perhaps use a temperature around one.'})
        self.assertEqual(parsed['suggested'], {})
        self.assertFalse(parsed['card_supported'])
        for value in ('file:///etc/passwd', 'http://localhost/model', 'https://huggingface.co/Owner/model?token=secret', '../model', 'Owner/model/../../x'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                importer.repository_name(value)
        for url in ('https://evil.invalid/a', 'file:///tmp/x', 'https://huggingface.co@evil.invalid/x', 'http://huggingface.co/x'):
            with self.assertRaises(ValueError): importer._safe_url(url)
        with self.assertRaises(ValueError): importer.pull('Owner/model', 'main', 'standard', lambda _: None)


class ExportTests(unittest.TestCase):
    def test_custom_diff_timestamp_and_capture_gap(self):
        source = qwen_source()
        cfg = config(lane='thinking', values=copy.deepcopy(source['suggested']))
        cfg['inference_profile']['source'] = source
        cfg['inference_profile']['values']['temperature'] = .25
        m = {'id': 'abc', 'state': 'done', 'model_config_snapshot': cfg}
        rows = [{'evaluation_id': 'abc', 'settings_capture': {'request_count': 2},
                 'requested_settings': [{'values': profiles.request_settings(cfg)}]}]
        text = profile_export.export(m, rows)
        self.assertIn(source['retrieved_at'], text)
        self.assertIn('does not establish a complete match', text)
        choice = profiles.provenance(cfg['inference_profile'])['temperature']
        self.assertTrue(choice['custom'])
        self.assertEqual(choice['recommendations'], source['candidates']['temperature'])

    def test_export_uses_frozen_values_and_strips_private_fields(self):
        cfg = config()
        cfg['api_key'] = 'CREDENTIAL_SENTINEL'
        cfg['base_url'] = 'http://PRIVATE_ENDPOINT/v1'
        m = {'id': 'abc123', 'state': 'done', 'model_config_snapshot': copy.deepcopy(cfg)}
        values = profiles.request_settings(cfg)
        cfg['inference_profile']['values']['temperature'] = 1.8
        rows = [{'evaluation_id': 'abc123', 'pi_version': '0.85.1', 'prompt': 'PRIVATE_PROMPT', 'settings_capture':{'request_count':1},
                 'requested_settings': [{'values': {**values, 'messages': 'PRIVATE_MESSAGES', 'api_key': 'PRIVATE_KEY'}}]}]
        text = profile_export.export(m, rows)
        self.assertIn('"temperature": 0', text)
        for private in ('CREDENTIAL_SENTINEL', 'PRIVATE_ENDPOINT', 'PRIVATE_PROMPT', 'PRIVATE_MESSAGES', 'PRIVATE_KEY', '1.8'):
            self.assertNotIn(private, text)
        self.assertIn('<ENDPOINT_BASE_URL>', text)
        self.assertIn('explicit-v1', text)
        self.assertIn('before_provider_request', text)
        self.assertNotIn('does not establish a complete match', text)

    def test_incomplete_capture_and_legacy_never_invent_evidence(self):
        cfg = config(); m = {'id': 'abc', 'state': 'done', 'model_config_snapshot': cfg}
        self.assertIn('does not establish a complete match', profile_export.export(m, []))
        m['model_config_snapshot'] = {'model': '/' + 'Users/private/secret-model'}
        text = profile_export.export(m, [])
        self.assertIn('legacy', text); self.assertIn('No outgoing settings', text)
        self.assertNotIn('/Users/', text); self.assertNotIn('before_provider_request', text)
        m['state'] = 'running'
        with self.assertRaises(ValueError): profile_export.export(m, [])


if __name__ == '__main__':
    unittest.main()

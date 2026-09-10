import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import endpoint_telemetry as telemetry
import live_tps


def mtplx(tokens=100, elapsed=4, request='one', model='fixture'):
    return {'ts': 100, 'active_requests': 1, 'model_id': 'fixture',
            'in_flight': [{'request_id': request, 'model': model, 'started_s': 90,
                           'prompt_preview': 'PRIVATE PROMPT', 'session_id': 'PRIVATE SESSION',
                           'last_progress': {'completion_tokens': tokens, 'decode_elapsed_s': elapsed,
                                             'decode_tok_s': tokens/elapsed}}],
            'scheduler': {'telemetry': {'foreground_pending': 0}}}


class EndpointTelemetry(unittest.TestCase):
    def test_prometheus_model_filter_counter_reset_and_server_overlap(self):
        def metrics(tokens, other=900):
            return '\n'.join([f'vllm:generation_tokens_total{{model_name="fixture"}} {tokens}',
                              f'vllm:generation_tokens_total{{model_name="other"}} {other}',
                              'vllm:num_requests_running{model_name="fixture"} 1',
                              'vllm:num_requests_running{model_name="other"} 2',
                              'vllm:num_requests_waiting{model_name="fixture"} 4'])
        r = self.reader()
        self.assertEqual(r.prometheus(metrics(100), 100, 'vllm')[0], [])
        samples, status = r.prometheus(metrics(140, 9999), 102, 'vllm')
        self.assertEqual(samples[0]['tps'], 20)
        self.assertEqual(samples[0]['measurement'], 'poll_interval_throughput')
        self.assertEqual((status['observed_requests'], status['observed_model_requests'], status['waiting_requests']), (3, 1, 4))
        self.assertEqual(r.prometheus(metrics(140), 104, 'vllm')[0], [])
        self.assertEqual(r.prometheus(metrics(3), 106, 'vllm')[0], [])
        self.assertEqual(r.prometheus(metrics(23), 108, 'vllm')[0][0]['tps'], 10)

    def test_sglang_unlabelled_counters_are_server_scope_and_missing_is_unknown(self):
        r = self.reader()
        raw = 'sglang:generation_tokens_total 30\nsglang:num_running_reqs 2\nsglang:num_queue_reqs 1'
        _, status = r.prometheus(raw, 100, 'sglang')
        self.assertEqual(status['scope'], 'server_aggregate')
        samples, _ = r.prometheus(raw.replace(' 30', ' 50'), 102, 'sglang')
        self.assertEqual(samples[0]['tps'], 10)
        with self.assertRaises(telemetry.Unavailable): r.prometheus('# no counters', 104, 'sglang')

    def test_omlx_activity_filters_model_and_discards_private_content(self):
        r = self.reader(metrics_model_id='loaded-id')
        data = {'active_models': {'total_active_requests': 3, 'total_waiting_requests': 1,
                'models': [{'id': 'loaded-id', 'active_requests': 1, 'generating': [
                    {'request_id': 'r1', 'generated_tokens': 100, 'elapsed_seconds': 4,
                     'tokens_per_second': 25, 'last_activity_age_seconds': 0, 'prompt': 'PRIVATE'}]},
                    {'id': 'other', 'active_requests': 2, 'generating': []}]}}
        samples, status = r.omlx(data, 100)
        self.assertEqual(samples[0]['tps'], 25)
        self.assertEqual(samples[0]['source'], 'oMLX live activity')
        self.assertEqual((status['observed_requests'], status['observed_model_requests']), (3, 1))
        self.assertNotIn('PRIVATE', json.dumps([samples, status]))
        data['active_models']['models'][0]['generating'][0]['last_activity_age_seconds'] = 12
        samples, status = r.omlx(data, 114)
        self.assertEqual(samples, [])
        self.assertEqual(status['server_phase'], 'stalled')

    def test_llamacpp_slots_do_not_include_prefill_or_bridge_requests(self):
        r = self.reader()
        def slots(tokens, request=1):
            return [{'id': 0, 'id_task': request, 'is_processing': True,
                     'next_token': {'n_decoded': tokens}, 'prompt': 'PRIVATE'}]
        self.assertEqual(r.llamacpp(slots(0), 100)[0], [])
        self.assertEqual(r.llamacpp(slots(20), 110)[0], [])
        samples, status = r.llamacpp(slots(60), 112)
        self.assertEqual(samples[0]['tps'], 20)
        self.assertEqual(status['scope'], 'server_request')
        self.assertNotIn('PRIVATE', json.dumps([samples, status]))
        self.assertEqual(r.llamacpp(slots(80, 2), 114)[0], [])
        self.assertEqual(r.llamacpp(slots(80, 2), 128)[0], [])

    def test_dsg_only_uses_pinned_worker_and_marks_stale_counts(self):
        r = self.reader(worker_id='chosen')
        data = {'service': 'dwarf-star-gate-dashboard', 'gateway_at': 100000,
                'gateway': {'workers': [{'id': 'chosen', 'load': 2, 'queued': 1}]},
                'devices': [{'id': 'other', 'decode': {'time': 100000, 'tps': 900}},
                            {'id': 'chosen', 'phase': 'thinking', 'decode': {'time': 100000, 'tps': 20, 'average': 19}}]}
        samples, status = r.dsg(data, 100)
        self.assertEqual(samples[0]['tps'], 20)
        self.assertEqual(status['observed_requests'], 2)
        self.assertEqual(r.dsg(data, 102)[0], [])
        samples, status = r.dsg(data, 112)
        self.assertEqual(samples, [])
        self.assertIsNone(status['observed_requests'])
        self.assertIn('stale', status['error'])
        with self.assertRaises(telemetry.Unavailable): self.reader(worker_id='absent').dsg(data, 100)

    def test_ollama_explains_missing_live_counters_without_request(self):
        r = self.reader(type='ollama')
        with patch.object(r, 'read') as read:
            with self.assertRaisesRegex(telemetry.Unavailable, 'passive live'): r.poll()
            read.assert_not_called()

    def test_redirect_never_reuses_inference_credentials(self):
        redirect = telemetry.NoRedirect()
        with self.assertRaises(telemetry.Unavailable):
            redirect.redirect_request(None, None, 302, '', {}, 'https://other.invalid/')

    def reader(self, **kw):
        return telemetry.Reader({'type': 'mtplx', 'model_id': 'fixture', 'base_url': 'http://localhost:8001/v1', **kw}, 80)

    def test_mtplx_window_uses_decode_time_and_keeps_average_separate(self):
        r = self.reader()
        first, _ = r.mtplx(mtplx(), 100)
        self.assertEqual(first[0]['measurement'], 'request_average')
        samples, status = r.mtplx(mtplx(130, 6), 103)
        self.assertEqual(samples[0]['tps'], 15)
        self.assertEqual(samples[0]['window_s'], 2)
        self.assertAlmostEqual(samples[0]['request_avg_tps'], 130/6)
        self.assertEqual(status['observed_requests'], 1)
        self.assertNotIn('PRIVATE', json.dumps([samples, status]))

    def test_stalled_snapshot_does_not_refresh_decode_sample(self):
        r = self.reader()
        r.mtplx(mtplx(), 100)
        samples, status = r.mtplx(mtplx(), 115)
        self.assertEqual(samples, [])
        self.assertEqual(status['last_server_event_at'], 100)
        self.assertEqual(status['request_count_at'], 115)

    def test_other_models_count_for_overlap_without_becoming_model_tps(self):
        data = mtplx()
        data['active_requests'] = 2
        data['in_flight'].extend(mtplx(900, 1, 'other', 'other-model')['in_flight'])
        samples, status = self.reader().mtplx(data, 100)
        self.assertEqual(len(samples), 1)
        self.assertEqual(status['observed_requests'], 2)
        self.assertEqual(status['observed_model_requests'], 1)

    def test_prefill_and_idle_have_no_fake_zero_tps(self):
        data = mtplx(); data['in_flight'][0]['last_progress'] = {}
        data['in_flight'][0]['prefill_state'] = {'tokens_done': 1}
        samples, status = self.reader().mtplx(data, 100)
        self.assertEqual(samples, []); self.assertEqual(status['server_phase'], 'prefill')
        data.update(in_flight=[], active_requests=0)
        samples, status = self.reader().mtplx(data, 102)
        self.assertEqual(samples, []); self.assertEqual(status['server_phase'], 'idle')

    def test_changed_request_does_not_bridge_counters(self):
        r = self.reader(); r.mtplx(mtplx(), 100)
        samples, _ = r.mtplx(mtplx(20, 2, 'two'), 102)
        self.assertEqual(samples[0]['tps'], 10)
        self.assertEqual(samples[0]['measurement'], 'request_average')

    def test_pre_run_request_does_not_enter_run_speed_history(self):
        r = self.reader(); r.started = 95
        samples, status = r.mtplx(mtplx(), 100)
        self.assertEqual(samples, [])
        self.assertEqual(status['observed_requests'], 1)

    def test_auto_source_uses_frozen_config_and_does_not_bypass_dsg(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'evaluations').mkdir()
            job = {'id': 'fixture', 'model': 'saved'}
            config = {'model': 'native', 'base_url': 'http://localhost:8001/v1/',
                      'api_key': 'test-key', 'inference_profile': {'backend': 'mtplx', 'route': {'kind': 'direct'}}}
            path = root/'evaluations/fixture.json'
            path.write_text(json.dumps({'model_config_snapshot': config}))
            source = live_tps.source_for(root, job)
            self.assertEqual((source['type'], source['model_id'], source['base_url']), ('mtplx', 'native', 'http://localhost:8001/v1'))
            config['inference_profile']['route'] = {'kind': 'dsg', 'name': 'worker'}
            path.write_text(json.dumps({'model_config_snapshot': config}))
            self.assertIsNone(live_tps.source_for(root, job))

    def test_live_status_clears_old_controller_missing_source_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'logs').mkdir()
            (root/'logs/tps-fixture.jsonl').write_text(json.dumps({'at': 100, 'phase': 'telemetry_status', 'error': None})+'\n')
            self.assertIsNone(live_tps.snapshot(root, {'id': 'fixture', 'model': 'fixture', '_telemetry_error': 'old error'})['error'])

    def test_attachment_stops_with_manifest_and_never_writes_results(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'evaluations').mkdir()
            job = {'id': 'fixture', 'state': 'running', 'started': 80}
            manifest = root/'evaluations/fixture.json'; manifest.write_text(json.dumps(job))
            def stop(_):
                manifest.write_text(json.dumps({**job, 'state': 'stopped'}))
            samples, status = self.reader().mtplx(mtplx(), 100)
            with patch.object(telemetry.Reader, 'poll', return_value=(samples, status)), patch.object(telemetry.time, 'sleep', side_effect=stop):
                telemetry.collect(root, job, self.reader().source, follow_manifest=True)
            rows = [json.loads(line) for line in (root/'logs/tps-fixture.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertFalse((root/'results').exists())

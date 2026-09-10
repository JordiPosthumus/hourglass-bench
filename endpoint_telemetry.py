"""Passive HTTP server telemetry. Only allowlisted numeric metadata is retained."""
import json
import math
import re
import http.cookiejar
import time
import urllib.error
import urllib.parse
import urllib.request


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


class Unavailable(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a saved inference credential to another destination.
        raise Unavailable('Telemetry endpoint redirected; check its configured URL.')


class Reader:
    def __init__(self, source, started=0):
        self.source = source
        self.model = source.get('model_id')
        self.started = started
        self.previous = {}
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(self.cookies))
        self.last_event_at = None

    def read(self, route, *, as_json=True, headers=None, login=False):
        base = self.source['base_url'].rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        url = base + route
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise Unavailable('Invalid telemetry URL.')
        request_headers = {'Accept': 'application/json' if as_json else 'text/plain'}
        key = self.source.get('api_key')
        if key:
            request_headers['Authorization'] = 'Bearer ' + key
        request_headers.update(headers or {})
        body = None
        if login:
            if route != '/admin/api/login' or not key:
                raise Unavailable('oMLX activity authentication is not configured.')
            body = json.dumps({'api_key': key, 'remember': False}).encode()
            request_headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, headers=request_headers, data=body)
        with self.opener.open(request, timeout=3) as response:
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise Unavailable('Telemetry response exceeded the metadata size limit.')
        text = body.decode('utf-8')
        return json.loads(text) if as_json else text

    def status(self, at, label, phase, count, **extra):
        return {'at': at, 'phase': 'telemetry_status', 'tps': None,
                'source': label, 'model_id': self.model, 'server_phase': phase,
                'last_server_event_at': self.last_event_at,
                'request_count_at': at, 'observed_requests': count,
                'attribution': 'model_on_server', 'error': None,
                'other_gpu_workloads': 'not_measured', **extra}

    def mtplx(self, data, at):
        if not isinstance(data, dict) or not isinstance(data.get('in_flight'), list) or number(data.get('active_requests')) is None:
            raise Unavailable('MTPLX live snapshot is unavailable in this server build.')
        rows = data['in_flight']
        matching = [row for row in rows if isinstance(row, dict) and row.get('model', data.get('model_id')) == self.model]
        samples = []
        phases = []
        current = {}
        for row in matching:
            progress = row.get('last_progress') or {}
            request_id = row.get('request_id')
            tokens = number(progress.get('completion_tokens'))
            elapsed = number(progress.get('decode_elapsed_s'))
            average = number(progress.get('decode_tok_s'))
            decoding = tokens is not None and tokens > 0 and elapsed is not None and elapsed > 0
            phases.append('decode' if decoding else 'prefill' if row.get('prefill_state') else 'waiting')
            if not request_id or not decoding:
                continue
            prior = self.previous.get(request_id)
            current[request_id] = {'tokens': tokens, 'elapsed': elapsed, 'at': at}
            if prior and tokens == prior['tokens'] and elapsed >= prior['elapsed']:
                current[request_id] = prior
                continue
            self.last_event_at = at
            if number(row.get('started_s')) is not None and row['started_s'] < self.started:
                continue
            sample = {'at': at, 'server_at': number(data.get('ts')), 'phase': 'decode',
                      'request_id': str(request_id), 'model_id': self.model,
                      'source': 'MTPLX live metrics', 'scope': 'model_request',
                      'output_tokens': tokens, 'request_avg_tps': average,
                      'observed_requests': data['active_requests']}
            if prior and 0 < at - prior['at'] <= 10 and elapsed > prior['elapsed'] and tokens >= prior['tokens']:
                sample.update(tps=(tokens-prior['tokens'])/(elapsed-prior['elapsed']),
                              window_s=round(elapsed-prior['elapsed'], 2), measurement='decode_window')
            elif average is not None:
                sample.update(tps=average, measurement='request_average')
            else:
                continue
            samples.append(sample)
        self.previous = current
        phase = 'decode' if 'decode' in phases else 'prefill' if 'prefill' in phases else 'waiting' if phases else 'idle'
        scheduler = data.get('scheduler') or {}
        telemetry = scheduler.get('telemetry') or {}
        return samples, self.status(at, 'MTPLX live metrics', phase, data['active_requests'],
                                    observed_model_requests=len(matching),
                                    waiting_requests=number(telemetry.get('foreground_pending')),
                                    scope='model_request', coverage='Requests for this model on the observed MTPLX server.')

    def prometheus(self, text, at, kind):
        prefix = kind + ':'
        metrics = {}
        label_model = self.source.get('metrics_model_id') or self.model
        for line in text.splitlines():
            match = re.fullmatch(r'([a-zA-Z_:][\w:]*)(\{.*\})?\s+([-+\d.eE]+)(?:\s+\d+)?\s*', line)
            if not match or not match[1].startswith(prefix):
                continue
            labels = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', match[2] or ''))
            name = labels.get('model_name', labels.get('model'))
            try:
                name = json.loads('"'+name+'"') if name is not None else None
                value = number(float(match[3]))
            except (ValueError, TypeError):
                continue
            if value is None:
                continue
            metric = match[1][len(prefix):]
            metrics.setdefault(metric, []).append((name, value))
        def total(metric, selected=False):
            values = metrics.get(metric, [])
            if selected and any(name is not None for name, _ in values):
                values = [(name, value) for name, value in values if name == label_model]
            return sum(value for _, value in values) if values else None
        running_name = 'num_requests_running' if kind == 'vllm' else 'num_running_reqs'
        waiting_name = 'num_requests_waiting' if kind == 'vllm' else 'num_queue_reqs'
        generated = total('generation_tokens_total', True)
        running = total(running_name)
        if generated is None or running is None:
            raise Unavailable(f'{kind} live token counters are unavailable for this model; check /metrics and its model label.')
        selected_running = total(running_name, True)
        labelled = any(name is not None for name, _ in metrics['generation_tokens_total'])
        scope = 'model_aggregate' if labelled else 'server_aggregate'
        prior = self.previous.get('counter')
        samples = []
        current = {'tokens': generated, 'at': at}
        if prior and generated == prior['tokens']:
            current = prior
        elif prior and generated > prior['tokens'] and 0 < at-prior['at'] <= 30:
            self.last_event_at = at
            samples.append({'at': at, 'phase': 'decode', 'source': kind+' metrics', 'model_id': self.model,
                            'scope': scope, 'measurement': 'poll_interval_throughput',
                            'tps': (generated-prior['tokens'])/(at-prior['at']),
                            'window_s': round(at-prior['at'], 2), 'output_tokens': generated,
                            'observed_requests': running})
        self.previous = {'counter': current}
        phase = 'idle' if selected_running == 0 else 'decode' if samples else 'working'
        return samples, self.status(at, kind+' metrics', phase, running, observed_model_requests=selected_running,
                                    waiting_requests=total(waiting_name), scope=scope, attribution=scope,
                                    coverage='Generated-token counter throughput across '+('this model’s requests.' if labelled else 'all requests on this server.')+' Includes scheduling gaps; counters may update in batches.')

    def omlx(self, data, at):
        activity = data.get('active_models') if isinstance(data, dict) else None
        models = activity.get('models') if isinstance(activity, dict) else None
        if not isinstance(models, list) or any(not isinstance(model, dict) for model in models):
            raise Unavailable('oMLX live activity is unavailable in this server build.')
        def sum_field(field):
            values = [number(model.get(field)) for model in models]
            return sum(values) if all(value is not None for value in values) else None
        running = number(activity.get('total_active_requests'))
        if running is None:
            running = sum_field('active_requests')
        if running is None:
            raise Unavailable('oMLX did not report active request counts.')
        target = self.source.get('metrics_model_id') or self.model
        selected = [model for model in models if model.get('id') == target]
        in_flight = []
        stalled = False
        for model in selected:
            for row in model.get('generating', []):
                if not isinstance(row, dict):
                    raise Unavailable('Invalid oMLX activity metadata.')
                if (number(row.get('last_activity_age_seconds')) or 0) > 10:
                    stalled = True
                    continue
                in_flight.append({'request_id': row.get('request_id'), 'model': self.model,
                                  'last_progress': {'completion_tokens': row.get('generated_tokens'),
                                                    'decode_elapsed_s': row.get('elapsed_seconds'),
                                                    'decode_tok_s': row.get('tokens_per_second')}})
            for row in model.get('prefilling', []):
                in_flight.append({'request_id': row.get('request_id'), 'model': self.model, 'prefill_state': True})
        samples, status = self.mtplx({'in_flight': in_flight, 'active_requests': running}, at)
        for sample in samples:
            sample['source'] = 'oMLX live activity'
        waiting = number(activity.get('total_waiting_requests'))
        status.update(source='oMLX live activity', waiting_requests=waiting if waiting is not None else sum_field('waiting_requests'),
                      observed_model_requests=sum(number(model.get('active_requests')) or 0 for model in selected),
                      coverage='Requests for this model on the observed oMLX server.')
        if stalled and not samples:
            status['server_phase'] = 'stalled'
        elif not in_flight and status['observed_model_requests']:
            status['server_phase'] = 'working'
        if models and not selected:
            status['error'] = 'Configured model is not listed in oMLX activity; check its metrics model ID.'
        return samples, status

    def llamacpp(self, data, at):
        if not isinstance(data, list) or any(not isinstance(slot, dict) or not isinstance(slot.get('is_processing'), bool) for slot in data):
            raise Unavailable('llama.cpp slot telemetry is unavailable; check access to /slots.')
        active = [slot for slot in data if slot['is_processing']]
        samples = []
        current = {}
        decoding = False
        for slot in active:
            tokens = number((slot.get('next_token') or {}).get('n_decoded'))
            if tokens is None or slot.get('id') is None or slot.get('id_task') is None:
                continue
            key = f"{slot['id']}:{slot['id_task']}"
            prior = self.previous.get(key)
            current[key] = {'tokens': tokens, 'at': at}
            decoding |= tokens > 0
            if prior and tokens == prior['tokens']:
                current[key] = prior
                continue
            if prior and prior['tokens'] > 0 and tokens > prior['tokens'] and 0 < at-prior['at'] <= 10:
                self.last_event_at = at
                samples.append({'at': at, 'phase': 'decode', 'source': 'llama.cpp slots', 'scope': 'server_request',
                                'request_id': str(slot['id_task']), 'slot': slot['id'], 'model_id': self.model,
                                'tps': (tokens-prior['tokens'])/(at-prior['at']), 'window_s': round(at-prior['at'], 2),
                                'measurement': 'poll_interval_throughput', 'output_tokens': tokens,
                                'observed_requests': len(active)})
        self.previous = current
        return samples, self.status(at, 'llama.cpp slots', 'decode' if decoding else 'working' if active else 'idle', len(active),
                                    scope='server_request', attribution='server_slots',
                                    coverage='Per-slot token throughput on this server. Slots do not identify the requesting client. Queue depth is not reported here.')

    def dsg(self, data, at):
        worker_id = self.source.get('worker_id')
        if not worker_id or not isinstance(data, dict) or data.get('service') != 'dwarf-star-gate-dashboard':
            raise Unavailable('DSG telemetry needs its dashboard URL and an explicit worker ID matching the inference route.')
        device = next((row for row in data.get('devices', []) if row.get('id') == worker_id), None)
        gateway = data.get('gateway') or {}
        worker = next((row for row in gateway.get('workers', []) if row.get('id') == worker_id), None)
        if not device or not worker:
            raise Unavailable('The configured DSG worker is absent from dashboard telemetry.')
        endpoint = device.get('endpoint_metrics') or {}
        if endpoint.get('connected'):
            observed = number(endpoint.get('activity_at')) or number(endpoint.get('at'))
            rate = number(endpoint.get('live_decode_tps'))
            phase = endpoint.get('phase') or 'unknown'
            measurement = endpoint.get('live_rate_scope') or 'server_reported'
            average = None
        else:
            decode = device.get('decode') or {}
            observed = number(decode.get('time'))
            rate = number(decode.get('tps'))
            average = number(decode.get('average'))
            phase = 'decode' if device.get('phase') == 'thinking' else device.get('phase') or 'unknown'
            measurement = 'server_reported'
        event_at = observed/1000 if observed is not None else None
        gateway_at = number(data.get('gateway_at'))
        count_at = gateway_at/1000 if gateway_at is not None else None
        count_fresh = count_at is not None and -5 <= at-count_at <= 6 and not data.get('gateway_error')
        active = number(worker.get('load')) if count_fresh else None
        samples = []
        marker = (event_at, rate)
        if event_at is not None and self.started <= event_at <= at+5 and at-event_at <= 10:
            self.last_event_at = event_at
            if rate is not None and phase in ('decode', 'mixed') and marker != self.previous.get('marker'):
                samples.append({'at': event_at, 'phase': 'decode', 'tps': rate, 'source': 'DSG worker metrics',
                                'request_avg_tps': average, 'scope': 'server_aggregate', 'measurement': measurement,
                                'model_id': self.model, 'worker_id': str(worker_id), 'observed_requests': active})
        self.previous = {'marker': marker}
        return samples, self.status(at, 'DSG worker metrics', phase, active, request_count_at=count_at,
                                    waiting_requests=number(worker.get('queued')) if count_fresh else None,
                                    scope='server_aggregate', attribution='configured_worker', worker_id=str(worker_id),
                                    coverage='Observed work on the explicitly configured DSG worker. Direct requests outside DSG may be absent from gateway request counts.',
                                    error='DSG gateway status is stale or unavailable.' if not count_fresh else None)

    def poll(self):
        kind = self.source['type']
        if kind == 'mtplx':
            data = self.read('/v1/mtplx/snapshot')
            return self.mtplx(data, time.time())
        if kind in ('vllm', 'sglang'):
            data = self.read('/metrics', as_json=False)
            return self.prometheus(data, time.time(), kind)
        if kind == 'omlx':
            try:
                data = self.read('/admin/api/activity')
            except urllib.error.HTTPError as exc:
                if exc.code not in (401, 403):
                    raise
                self.read('/admin/api/login', login=True)
                data = self.read('/admin/api/activity')
            return self.omlx(data, time.time())
        if kind == 'llamacpp':
            data = self.read('/slots?'+urllib.parse.urlencode({'model': self.model}))
            return self.llamacpp(data, time.time())
        if kind == 'dsg':
            data = self.read('/api/status')
            return self.dsg(data, time.time())
        if kind == 'ollama':
            raise Unavailable('Ollama’s OpenAI API does not expose passive live decode counters. Connect an instrumented telemetry source; loaded-model counts are not request counts.')
        raise Unavailable('No passive metrics reader is configured for this server.')


def collect(root, job, source, condition=None, follow_manifest=False):
    """Attach without restarting inference or the controller; one writer per run."""
    import fcntl
    from pathlib import Path
    root = Path(root)
    jid = job['id']
    if not jid.isalnum():
        raise ValueError('Invalid run ID.')
    path = root/'logs'/f'tps-{jid}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent/f'tps-{jid}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        reader = Reader(source, job.get('started') or 0)
        while job.get('state') == 'running':
            if follow_manifest:
                try:
                    job = json.loads((root/'evaluations'/(jid+'.json')).read_text())
                except (OSError, ValueError):
                    break
                if job.get('state') != 'running':
                    break
                active = job.get('active_question') or {}
                if active.get('token'):
                    try:
                        receipt = json.loads((root/'logs'/f"worker-{jid}-{active['token']}.json").read_text())
                    except (OSError, ValueError):
                        receipt = {}
                    if receipt.get('controller_lost'):
                        break
            try:
                samples, status = reader.poll()
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                reader.previous = {}
                message = str(exc) if isinstance(exc, Unavailable) else 'Server metrics unavailable; retrying.'
                if isinstance(exc, urllib.error.HTTPError):
                    message = f'Server metrics returned HTTP {exc.code}; check telemetry access.'
                status = reader.status(time.time(), source['type'], 'unknown', None, error=message)
                samples = []
            with path.open('a') as output:
                for sample in samples:
                    output.write(json.dumps({**sample, 'task': job.get('current_task')})+'\n')
                output.write(json.dumps(status)+'\n')
            job['_telemetry_error'] = status.get('error')
            if condition:
                with condition:
                    if job.get('state') != 'running':
                        break
                    condition.wait(timeout=2)
            else:
                time.sleep(2)

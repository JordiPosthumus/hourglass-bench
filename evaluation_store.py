"""Frozen evaluation records and atomic persistence. No scoring transformations."""
import datetime as dt
import hashlib
import json
import shutil
import threading
import uuid
from pathlib import Path
import run_tracking
import diagnostics
import task_identity
import option_layout
import score_weights
import scoring_policy
import hardware_records

LOCK = threading.RLock()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def evaluation_manifest(root, job, version, config, legacy=False):
    if not legacy:__import__('inference_profiles').request_settings(config)
    expected = []
    for tid in sorted(job['tasks']):
        raw = (root / 'tasks' / tid / 'task.json').read_bytes()
        task = json.loads(raw)
        expected.append({'task': tid, 'task_sha': hashlib.sha256(raw).hexdigest()[:16],
                         **({'task_bundle_sha':task_identity.identity(root/'tasks'/tid)} if not legacy else {}),
                         'vision': task.get('kind') == 'chart-vqa' or bool(task.get('image') or task.get('assets')),
                         'section':task.get('section'),'tier':task.get('tier'),'level':task.get('level'),
                         **({'discovery_domain':task['discovery_domain']} if task.get('discovery_domain') else {}),
                         'weight':score_weights.weight(task),'weight_version':score_weights.VERSION,
                         'repeat': (job.get('repeat') or task.get('repeat', 3)) if legacy else 1})
    if job.get('reviewed_task_bundles') is not None and job['reviewed_task_bundles']!={t['task']:t['task_bundle_sha'] for t in expected}:
        raise ValueError('Question bundles changed after review. Refresh and review again.')
    if not legacy:
        frozen=root/'evaluations'/(job['id']+'.tasks')
        frozen.mkdir(parents=True,exist_ok=False)
        try:
            for item in expected:
                shutil.copytree(root/'tasks'/item['task'],frozen/item['task'])
                task_identity.verify(frozen/item['task'],item)
        except Exception:
            shutil.rmtree(frozen)
            raise
    manifest = {'id': job['id'], 'model': job['model'], 'model_id': config['model'],
                'benchmark_version': version, 'expected': expected,
                **({'diagnostic_isolation':diagnostics.POLICY,'option_layout_policy':option_layout.POLICY,'presentation_seed':uuid.uuid4().hex,'task_snapshot':str(frozen.relative_to(root))} if not legacy else {}),
                'stop_after_wrong':job.get('stop_after_wrong'), 'order':job['tasks'],
                'created': job['created'], 'started': job.get('started'), 'state': job['state'],
                'config_hash': digest(config), 'model_config_snapshot':json.loads(json.dumps(config)), 'legacy_time_match': legacy}
    if config.get('sampling_era') in ('explicit-v1','pi-native-v1'):
        adapter_root=Path(__file__).resolve().parent
        manifest['inference_adapter']={key:hashlib.sha256((adapter_root/name).read_bytes()).hexdigest() for key,name in [('harness_sha256','harness/pi.mjs'),('settings_adapter_sha256','harness/inference-settings.mjs'),('pi_lock_sha256','harness/pi-lock.json')]}
        if __import__('stock_pi').enabled(config):
            manifest['inference_adapter']['native_profile_sha256']=hashlib.sha256((adapter_root/'stock_pi.py').read_bytes()).hexdigest()
            manifest['pi_model_snapshot']=__import__('stock_pi').model_definition(config)
            manifest['pi_session_baseline']='native Pi 0.85.1'
            manifest['pi_thinking_level']=config.get('pi_thinking_level', 'Pi default')
    for key in ('question_timeout_s','question_timeout_policy','scoring_policy','warmup_policy','round_policy'):
        if key in job:manifest[key]=job[key]
    manifest['hardware']=hardware_records.capture(root,config)
    manifest['scope'] = digest({'version': version, 'expected': expected, 'order':job['tasks'], 'stop_after_wrong':job.get('stop_after_wrong'), **({k:job[k] for k in ('question_timeout_s','question_timeout_policy','scoring_policy') if k in job})})
    if not legacy:manifest['scope']=digest({'original_scope':manifest['scope'],'option_layout_policy':option_layout.POLICY})
    if 'scoring_policy' in job:
        manifest['scoring_policy']=job['scoring_policy']
        manifest['scope']=digest({'original_scope':manifest['scope'],'scoring_policy':job['scoring_policy']})
    if job.get('warmup_policy'):
        manifest['scope']=digest({'original_scope':manifest['scope'],'warmup_policy':job['warmup_policy']})
    if job.get('round_policy'):
        manifest['scope']=digest({'original_scope':manifest['scope'],'round_policy':job['round_policy']})
    with LOCK:
        write(root / 'evaluations' / (job['id'] + '.json'), manifest)
    return manifest


def update_evaluation(root, job):
    with LOCK:
        path = root / 'evaluations' / (job['id'] + '.json')
        manifest = read(path, None)
        if manifest:
            manifest.update({k: job[k] for k in ('started', 'ended', 'state', 'error', 'rc', 'completed_tasks', 'total_tasks', 'label', 'stopped_after', 'current_task', 'repeat', 'elapsed_s', 'active_started', 'resume_count', 'resume_versions','active_intervals','active_question','hour_timing_unknown','stop_reason','question_timeout_s','question_timeout_policy','scoring_policy','question_elapsed_s','warmup_policy','warmup','warmups','round_number','round_order') if k in job})
            write(path, manifest)


def frozen_config_path(root,manifest,current_config=None):
    """Execute exactly the reviewed model configuration, never the editable catalog."""
    config=manifest.get('model_config_snapshot')
    if config is None:
        if current_config is None or digest(current_config)!=manifest.get('config_hash'):
            raise ValueError('Historical run settings changed. Start a new run using the saved setup.')
        config=current_config
    if digest(config)!=manifest.get('config_hash'):
        raise ValueError('Frozen model configuration failed its integrity check.')
    path=root/'evaluations'/(manifest['id']+'.model.json')
    document={'models':[config]}
    if path.exists():
        if read(path,None)!=document:raise ValueError('Frozen model configuration file changed; refusing to mix settings.')
    else:
        # No model secrets are included in public API views or report exports.
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as output:
            import os
            os.chmod(path,0o600)
            output.write(json.dumps(document,indent=2,allow_nan=False)+'\n')
    return path

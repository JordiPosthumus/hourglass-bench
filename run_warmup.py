"""One unscored generation before a new run's clocks start."""
import json
import subprocess
import time
from pathlib import Path
import inference_profiles
import stock_pi
import question_deadline

POLICY = 'unscored-generation-v1'
OUTPUT_TOKENS = 128
TIMEOUT_S = 300


def run(config, job, condition):
    # This declaration is private to the warm-up; never modify saved settings.
    if stock_pi.enabled(config):
        model = stock_pi.model_definition(config)
    else:
        model = {'id':config['model'],'name':config['model'],'reasoning':True,
                 'input':['text'],'contextWindow':config.get('context_window',0),
                 'maxTokens':config.get('max_tokens',1024),
                 'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}
    model.update(provider='benchmark',api='openai-completions',baseUrl=config['base_url'])
    payload = {'config':config,'model':model,'settings':inference_profiles.request_settings(config),
               'max_tokens':OUTPUT_TOKENS}
    started = time.monotonic()
    with condition:
        if job.get('stop_requested'):raise InterruptedError('Warm-up cancelled.')
        proc = subprocess.Popen(['node',str(Path(__file__).parent/'harness/warmup.mjs')],
                                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                text=True,start_new_session=True)
        job['_process'] = proc
    try:
        try:out,_ = proc.communicate(json.dumps(payload),timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            question_deadline.terminate_group(proc);proc.communicate()
            raise ValueError('Warm-up timed out. Scoring has not started.') from None
        if job.get('stop_requested'):raise InterruptedError('Warm-up cancelled.')
        if proc.returncode:raise ValueError('Warm-up request failed. Check the model endpoint; scoring has not started.')
        result=json.loads(out)
        if result.get('status')!='completed':raise ValueError('Warm-up produced no generation. Scoring has not started.')
        return {**result,'policy':POLICY,'duration_s':time.monotonic()-started,'output_limit':OUTPUT_TOKENS}
    finally:
        with condition:job.pop('_process',None)

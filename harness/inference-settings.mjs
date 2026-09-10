// Settings-only observation at the actual fetch boundary. No prompt/response capture.
// This adapter never awaits recording or changes the request passed to fetch.
const scalarKeys = ['temperature','top_p','top_k','min_p','repetition_penalty','repeat_penalty',
  'frequency_penalty','presence_penalty','seed','reasoning_effort','thinking','enable_thinking','max_tokens','max_completion_tokens'];
const templateKeys = ['enable_thinking','preserve_thinking','reasoning_effort'];
const scalar = v => typeof v === 'boolean' || typeof v === 'number' && Number.isFinite(v)
  || typeof v === 'string' && ['none','minimal','low','medium','high','xhigh','max'].includes(v);
export function selectedSettings(body) {
  const values = {};
  for (const key of scalarKeys) if (scalar(body[key])) values[key] = body[key];
  if (body.chat_template_kwargs && typeof body.chat_template_kwargs === 'object') {
    const selected = Object.fromEntries(templateKeys.filter(k => scalar(body.chat_template_kwargs[k])).map(k => [k,body.chat_template_kwargs[k]]));
    if (Object.keys(selected).length) values.chat_template_kwargs = selected;
  }
  return {values, omitted: [...scalarKeys,'chat_template_kwargs'].filter(k => !(k in values))};
}

export function settingsCaptureFetch(fetchImpl, record, context = {}) {
  let sequence = 0;
  const safeRecord = value => { try { record(value); } catch {} };
  const wrapped = (input, init = {}) => {
    const requestIndex = ++sequence, body = init.body;
    // Start transport first. Recording failure cannot prevent or retry inference.
    const response = fetchImpl(input, init);
    setImmediate(() => {
      const base = {sampling_era:context.samplingEra??'explicit-v1', request_index:requestIndex,
        captured_at:new Date().toISOString(), source:'serialized_request',
        pi_thinking_level:context.thinkingLevel?.() ?? null, response_mode:context.responseMode ?? 'stream'};
      try {
        // This bounds observation only, never the inference request or output.
        if (typeof body !== 'string' || body.length > 8 * 1024 * 1024) {
          safeRecord({...base,capture_error:'Serialized request exceeded the settings recorder limit; settings not observed.'});
          return;
        }
        safeRecord({...base,...selectedSettings(JSON.parse(body))});
      } catch { safeRecord({...base,capture_error:'Could not observe serialized settings.'}); }
    });
    return response;
  };
  wrapped.requestCount = () => sequence;
  return wrapped;
}

export function dsgRouteFetch(fetchImpl, route, record = () => {}) {
  return async (input, init = {}) => {
    const headers = new Headers(init.headers);
    headers.set('x-dsg-model', route);
    const response = await fetchImpl(input, {...init,headers});
    const node = response.headers.get('x-ds4-node');
    if (node && /^[A-Za-z0-9_.-]{1,128}$/.test(node)) {
      try { record({requested_route:route, observed_node:node}); } catch {}
    }
    return response;
  };
}

export function applyExplicitSettings(payload, settings) {
  for (const key of [...scalarKeys,'chat_template_kwargs','reasoning']) delete payload[key];
  Object.assign(payload, structuredClone(settings));
  return payload;
}

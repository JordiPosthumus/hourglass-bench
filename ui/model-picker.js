'use strict';
class ServerKeyMemory {
  constructor(storage) { this.storage = storage; }
  static scope(value) {
    try {
      const url = new URL(value);
      if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return '';
      if (url.hostname === 'localhost') url.hostname = '127.0.0.1';
      const path = url.pathname.replace(/\/+$/, '').replace(/\/(?:chat\/completions|models)$/, '').replace(/\/api\/v1$/, '/v1').replace(/\/v1$/, '');
      return url.origin + path;
    } catch { return ''; }
  }
  saved() {
    try {
      const value = JSON.parse(this.storage?.getItem('hourglass.server-api-keys.v1') || '{}');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch { return {}; }
  }
  recall(endpoint, models = []) {
    const scope = ServerKeyMemory.scope(endpoint);
    if (!scope) return null;
    const value = this.saved()[scope];
    if (typeof value === 'string' && value) return {key:value, source:'this browser'};
    const keys = [...new Set(models.filter(m => ServerKeyMemory.scope(m.base_url) === scope && typeof m.api_key === 'string' && m.api_key).map(m => m.api_key))];
    return keys.length === 1 ? {key:keys[0], source:'a saved model'} : null;
  }
  remember(endpoint, key) {
    const scope = ServerKeyMemory.scope(endpoint);
    if (!scope || typeof key !== 'string' || !key || !this.storage) return false;
    try {
      this.storage.setItem('hourglass.server-api-keys.v1', JSON.stringify({...this.saved(), [scope]:key}));
      return true;
    } catch { return false; }
  }
  static rejection(result, key) {
    if (!result.error) return '';
    if (/HTTP 401/.test(result.error)) return key
      ? 'The server rejected this API key (HTTP 401). Enter the key configured on that server, then inspect again.'
      : 'This server requires an API key (HTTP 401). No key was sent. Enter the key configured on that server, then inspect again.';
    return result.error;
  }
}
/* Model discovery is read-only; saving appends one reviewed configuration. */
const ModelForms = {
  entry(fields, advanced = {}) {
    if (!advanced || typeof advanced !== 'object' || Array.isArray(advanced)) throw Error('Additional fields must be a JSON object.');
    const out = structuredClone(advanced);
    for (const key of ['name','model','base_url','hardware']) out[key] = String(fields[key] || '').trim();
    if (!out.name || !out.model) throw Error('Enter a display name and model ID.');
    let url; try { url = new URL(out.base_url); } catch { throw Error('Enter a valid HTTP or HTTPS endpoint.'); }
    if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw Error('Use an HTTP or HTTPS endpoint without credentials, query or fragment.');
    out.base_url = out.base_url.replace(/\/+$/, '');
    const positive = (v, label) => { if (!/^\d+$/.test(String(v)) || !Number.isSafeInteger(+v) || +v < 1) throw Error(`${label} must be a positive whole number.`); return +v; };
    if (Object.hasOwn(fields, 'api_key')) {
      if (fields.api_key) out.api_key = String(fields.api_key);
      else delete out.api_key;
    }
    out.max_tokens = positive(fields.max_tokens, 'Output token limit');
    if (out.extra?.max_tokens !== undefined && out.extra.max_tokens !== out.max_tokens) throw Error('Additional JSON contains a different extra.max_tokens override. Match it to the visible output limit or remove that override.');
    if (String(fields.context_window || '').trim()) out.context_window = positive(fields.context_window, 'Context length');
    else delete out.context_window;
    return out;
  },
  withoutModel(text, name) {
    const doc = JSON.parse(text);
    if (!Array.isArray(doc.models) || doc.models.filter(m => m.name === name).length !== 1) throw Error('Model settings changed. Refresh before removing this model.');
    doc.models = doc.models.filter(m => m.name !== name);
    return doc;
  },
  uniqueName(name, saved) {
    let candidate = name, n = 2; while (saved.some(m => m.name === candidate)) candidate = `${name}-${n++}`; return candidate;
  }
};
if (typeof module !== 'undefined') module.exports = {...ModelForms, ServerKeyMemory};

class ModelPicker {
  constructor({getState, api, $, esc, dialog, refresh, toast, canOpen}) {
    Object.assign(this, {getState, api, $, esc, dialog, refresh, toast, canOpen});
    $('addLmModel').onclick = () => this.open('lmstudio');
    $('addServerModel').onclick = () => this.open('server');
  }
  sync() {
    const models = this.getState()?.model_configs || [], e = this.esc;
    this.$('savedModelRows').innerHTML = models.map((m, i) => `<tr><td><strong>${e(m.name)}</strong><span class="questionmeta">${e(m.model)}</span></td><td>${e(m.base_url)}</td><td>${e(m.hardware || 'Not set')}</td><td>${e(m.extra?.max_tokens ?? m.max_tokens ?? 'Not set')}</td><td><div class="saved-model-actions"><button class="button secondary" data-copy-model="${i}">Duplicate</button><button class="button secondary" data-remove-model="${i}" aria-label="Remove ${e(m.name)}">Remove</button></div></td></tr>`).join('') || '<tr><td colspan="5">Add your first model above.</td></tr>';
    this.$('savedModelRows').querySelectorAll('[data-copy-model]').forEach(b => b.onclick = () => this.open('server', models[+b.dataset.copyModel]));
    this.$('savedModelRows').querySelectorAll('[data-remove-model]').forEach(b => b.onclick = () => this.remove(models[+b.dataset.removeModel]));
  }
  remove(model) {
    if (!this.canOpen()) { this.toast('Save or discard your JSON edits before removing a model.'); return; }
    const state = this.getState(), revision = state.models_revision;
    if ([...(state.jobs?.running || []), ...(state.jobs?.pending || [])].some(j => j.model === model.name)) {
      this.toast('Finish or stop the active and queued runs using this model before removing it.'); return;
    }
    const doc = ModelForms.withoutModel(state.models_json, model.name);
    this.dialog('Remove saved model?', `<p>Remove <strong>${this.esc(model.name)}</strong> from the saved models and new-run picker?</p><p>Past runs and results stay available. Model files and the model server are unchanged. The current configuration is backed up before saving.</p>`, [
      {label:'Cancel', click:() => this.$('dialog').close()},
      {label:'Remove model', primary:true, click:async b => {
        b.disabled = true;
        try {
          const result = await this.api('/api/models', {text:JSON.stringify(doc, null, 2), revision});
          this.$('dialog').close(); await this.refresh(); this.toast(`Model removed. Configuration backup: ${result.backup}`);
        } catch (error) { this.toast(error.message); b.disabled = false; }
      }}
    ]);
  }
  open(source, copy = null) {
    if (!this.getState()?.model_library_available) { this.toast('Restart the Hourglass console from your Terminal to enable model discovery, then refresh this page.'); return; }
    if (!this.canOpen()) { this.toast('Save or discard your JSON edits before adding a model.'); return; }
    const {$, esc:e} = this, revision = this.getState()?.models_revision;
    const fields = ['name','model','base_url','hardware','max_tokens','context_window','api_key'];
    const extras = structuredClone(copy || {}); fields.forEach(k => delete extras[k]);
    delete extras.sampling_era; delete extras.inference_profile;
    let profileEditor;
    const input = (key, label, placeholder = '', numeric = false) => `<label class="model-field">${label}<input id="mf-${key}" ${numeric ? 'type="number" min="1" step="1"' : 'type="text"'} placeholder="${e(placeholder)}" ${key === 'hardware' ? 'maxlength="160"' : ''}></label>`;
    this.dialog(copy ? 'Duplicate model configuration' : source === 'lmstudio' ? 'Add from LM Studio' : 'Add a server model', `
      <p class="help">${source === 'lmstudio' ? 'Choose from your local library. Discovery reads lms; load models with your usual LM Studio settings.' : 'Paste an endpoint to see its advertised models and settings, including DS4 and other OpenAI-compatible servers.'}</p>
      <div class="model-discovery-bar">${input('base_url','Server endpoint','http://server:8000/v1')}<button id="inspectModelEndpoint" class="button secondary">${source === 'lmstudio' ? 'Refresh library' : 'Inspect endpoint'}</button></div>
      <label class="model-field">API key<input id="mf-api_key" type="password" autocomplete="off" spellcheck="false" placeholder="The key configured on this server" aria-describedby="serverKeyHelp"></label><p id="serverKeyHelp" class="help" role="status">Use the exact key configured on your server. Leave blank only if the server allows it. Successful keys are remembered in this browser and saved with any model you add.</p>
      <p id="modelDiscoveryStatus" class="help" role="status"></p>
      <div id="modelDiscoveryReport"></div>
      <div id="modelSearchWrap" hidden><label class="model-field">Find a model<input id="modelLibrarySearch" type="search" placeholder="Search name, ID or quantization"></label></div><div id="modelLibraryRows" class="model-library"></div>
      <div id="selectedModelFacts"></div><h3>Configuration to add</h3><div class="model-form-grid">${input('name','Display name','My server · model')}${input('model','Model ID','Exact ID served by the endpoint')}${input('hardware','Hardware description','Inference machine and accelerator')}${input('max_tokens','Model output capacity','Declared model maximum',true)}${input('context_window','Context capacity','Reported serving capacity',true)}</div>
      <p class="help">Standard Pi treats output capacity as a ceiling and calculates a smaller allowance when the prompt and history need space. A reported total context is only an upper bound for output. Review the declared capacities before saving.</p>
      ${InferenceProfileEditor.markup()}
      <details><summary>Additional JSON fields</summary><p class="help">Optional existing provider fields. Form values above take precedence. Duplicating preserves additional fields exactly.</p><textarea id="modelExtraFields" class="model-json" spellcheck="false">${e(JSON.stringify(extras,null,2))}</textarea></details>
      <details><summary>Preview new JSON entry</summary><pre id="modelEntryPreview" class="previewtext"></pre></details><p id="modelFormError" class="help" role="alert"></p>`, [
      {label:'Cancel',click:()=>$('dialog').close()},
      {label:'Add model',primary:true,click:async b=>{
        try {
          const entry = build(); b.disabled = true;
          const result = await this.api('/api/models/add', {entry, revision});
          $('dialog').close(); await this.refresh(); this.toast(`Added ${entry.name}; backup in ${result.backup}.`);
        } catch (error) { if ($('modelFormError')) $('modelFormError').textContent = error.message; }
        finally { b.disabled = false; }
      }}]);
    $('dialog').classList.add('model-add-dialog');
    $('dialog').addEventListener('close', () => $('dialog').classList.remove('model-add-dialog'), {once:true});
    const body = $('modelFormError'), alive = () => body === $('modelFormError') && $('dialog').open;
    const build = () => { const entry=ModelForms.entry(Object.fromEntries(fields.map(k => [k,$('mf-'+k).value])), JSON.parse($('modelExtraFields').value)); return profileEditor ? profileEditor.apply(entry) : entry; };
    const preview = () => { try { const entry = build(); $('modelEntryPreview').textContent = JSON.stringify({...entry,...(entry.api_key ? {api_key:'[redacted]'} : {})},null,2); $('modelFormError').textContent = ''; } catch (error) { $('modelEntryPreview').textContent = error.message; } };
    fields.forEach(k => { $('mf-'+k).value = copy?.[k] ?? ''; $('mf-'+k).oninput = preview; });
    let keyStorage; try { keyStorage = window.localStorage; } catch {}
    const keyMemory = new ServerKeyMemory(keyStorage);
    let keyScope = copy?.api_key ? ServerKeyMemory.scope($('mf-base_url').value) : null;
    const restoreServerKey = () => {
      const scope = ServerKeyMemory.scope($('mf-base_url').value);
      if (scope === keyScope) return;
      keyScope = scope;
      const saved = keyMemory.recall($('mf-base_url').value, this.getState().model_configs);
      $('mf-api_key').value = saved?.key || '';
      $('serverKeyHelp').textContent = saved
        ? `API key filled from ${saved.source} for this endpoint. You can replace it here.`
        : 'Use the exact key configured on your server. Leave blank only if the server allows it. Successful keys are remembered in this browser and saved with any model you add.';
    };
    $('mf-base_url').oninput = () => { restoreServerKey(); preview(); };
    $('mf-api_key').oninput = () => {
      $('serverKeyHelp').textContent = 'This key will be remembered for this endpoint after a successful connection. The server decides whether it is accepted.';
      preview();
    };
    restoreServerKey();
    if (copy?.extra?.max_tokens !== undefined) $('mf-max_tokens').value = copy.extra.max_tokens;
    if (copy) $('mf-name').value = ModelForms.uniqueName(copy.name, this.getState().model_configs);
    $('modelExtraFields').oninput = preview;
    let rows = [], selectedKey = null;
    const choose = row => {
      selectedKey = row.key || row.model_id;
      $('mf-model').value = row.model_id;
      $('mf-name').value = ModelForms.uniqueName(row.model_id.split('/').pop(),this.getState().model_configs);
      const context = row.context_length || row.max_context_length;
      // These are visible suggestions, never a hidden benchmark or server cap.
      $('mf-max_tokens').value = row.max_output_tokens || context || '';
      const knownHardware = this.getState().model_configs.find(m => m.base_url.replace(/\/+$/, '') === $('mf-base_url').value.replace(/\/+$/, '') && m.hardware);
      if (!$('mf-hardware').value && knownHardware) $('mf-hardware').value = knownHardware.hardware;
      $('selectedModelFacts').innerHTML = `<details open><summary>Selected model reports</summary><dl class="reviewgrid"><dt>Provider</dt><dd>${e(row.provider || 'Not reported')}</dd><dt>Context</dt><dd>${e(row.context_length || 'Not reported')}</dd><dt>Maximum output</dt><dd>${e(row.max_output_tokens || 'Not reported')}</dd><dt>Supported parameters</dt><dd>${e(row.supported_parameters?.join(', ') || 'Not reported')}</dd></dl>${row.metadata ? `<details><summary>Reported model settings</summary><pre class="previewtext">${e(JSON.stringify(row.metadata,null,2))}</pre></details>` : ''}</details>`;
      $('mf-context_window').value = row.context_length || ''; // Use reported serving capacity, not the model's theoretical maximum.
      preview(); renderRows();
    };
    const renderRows = () => {
      const query = $('modelLibrarySearch').value.toLowerCase();
      const matches = rows.filter(r => `${r.title} ${r.model_id} ${r.quantization || ''}`.toLowerCase().includes(query));
      $('modelSearchWrap').hidden = !rows.length;
      $('modelLibraryRows').innerHTML = matches.map(r => `<button type="button" class="model-library-row ${selectedKey === (r.key || r.model_id) ? 'selected' : ''}" data-library-key="${e(r.key || r.model_id)}" aria-pressed="${selectedKey === (r.key || r.model_id)}"><strong>${e(r.title)}</strong><span>${e(r.model_id)}</span><small>${e([r.loaded === true ? 'Loaded' : r.loaded === false ? 'Not loaded' : 'Loaded state: not reported',r.model_key && r.model_key !== r.model_id ? `Disk variant: ${r.model_key}` : '',r.quantization,r.parameters,r.format,r.size_bytes ? `${(r.size_bytes / 2**30).toFixed(1)} GiB` : '',r.context_length ? `Reported context: ${r.context_length.toLocaleString()}` : r.max_context_length ? `Model maximum context: ${r.max_context_length.toLocaleString()}` : 'Context: not reported',r.vision === true ? 'Vision advertised' : ''].filter(Boolean).join(' · '))}</small></button>`).join('') || (rows.length ? '<p class="help">No matching models.</p>' : '');
      $('modelLibraryRows').querySelectorAll('[data-library-key]').forEach(b => b.onclick = () => choose(rows.find(r => (r.key || r.model_id) === b.dataset.libraryKey)));
    };
    $('modelLibrarySearch').oninput = renderRows;
    $('inspectModelEndpoint').onclick = async () => {
      const b = $('inspectModelEndpoint'); b.disabled = true; $('modelDiscoveryStatus').textContent = 'Reading model metadata…';
      const inspectedEndpoint = $('mf-base_url').value, inspectedKey = $('mf-api_key').value;
      try {
        const result = source === 'lmstudio' ? await this.api('/api/model-library/lmstudio') : await this.api('/api/model-library/server', {base_url:inspectedEndpoint,api_key:inspectedKey});
        if (!alive()) return;
        if (source === 'server' && (ServerKeyMemory.scope($('mf-base_url').value) !== ServerKeyMemory.scope(inspectedEndpoint) || $('mf-api_key').value !== inspectedKey)) {
          $('modelDiscoveryStatus').textContent = 'Connection details changed while checking. Inspect the endpoint again.'; return;
        }
        rows = result.models || []; $('mf-base_url').value = result.base_url;
        if (source === 'lmstudio') restoreServerKey();
        if (source === 'server' && !result.error && rows.length && ServerKeyMemory.scope(result.base_url) === ServerKeyMemory.scope(inspectedEndpoint)) {
          keyScope = ServerKeyMemory.scope(result.base_url);
          const saved = keyMemory.remember(result.base_url, inspectedKey);
          $('serverKeyHelp').textContent = inspectedKey
            ? saved ? 'Connected. API key remembered for this endpoint in this browser. It will also be saved with the model when you add it.' : 'Connected. Browser storage is unavailable; the key will still be saved with the model when you add it.'
            : 'Connected. This server accepted the request without an API key.';
        }
        $('modelDiscoveryStatus').textContent = source === 'lmstudio' ? `${rows.length} library entries · server ${result.server_running ? 'running' : 'not running'}. No model was loaded or unloaded.` : ServerKeyMemory.rejection(result, inspectedKey) || `${result.kind} · ${rows.length} model${rows.length === 1 ? '' : 's'} · ${result.reachable ? 'Endpoint responded' : 'Could not reach endpoint'}.`;
        $('modelDiscoveryReport').innerHTML = source === 'lmstudio' ? '' : `<details open><summary>What the endpoint reports</summary><dl class="reviewgrid"><dt>HTTP server</dt><dd>${e(result.http_server || 'Not reported')}</dd>${(result.reported || []).map(r=>`<dt>${e(r.label)}</dt><dd>${e(typeof r.value === 'object' ? JSON.stringify(r.value) : r.value)} <small>(${e(r.source)})</small></dd>`).join('')}</dl><p class="help">Unreported settings remain unknown. Inspection sends only metadata GET requests.</p><details><summary>Discovery responses and model metadata</summary><pre class="previewtext">${e(JSON.stringify({probes:result.probes,models:rows},null,2))}</pre></details></details>`;
        if (!rows.length && !result.error) $('modelDiscoveryStatus').textContent += ' You can enter a model ID manually below.';
        renderRows(); preview();
      } catch (error) { if (alive()) $('modelDiscoveryStatus').textContent = error.message; }
      finally { if (alive()) b.disabled = false; }
    };
    profileEditor = new InferenceProfileEditor({$,esc:e,api:this.api,copy,preview});
    profileEditor.mount();
    preview(); if (source === 'lmstudio') $('inspectModelEndpoint').click();
  }
}

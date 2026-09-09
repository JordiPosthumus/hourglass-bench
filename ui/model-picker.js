'use strict';
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
    out.max_tokens = positive(fields.max_tokens, 'Output token limit');
    if (out.extra?.max_tokens !== undefined && out.extra.max_tokens !== out.max_tokens) throw Error('Additional JSON contains a different extra.max_tokens override. Match it to the visible output limit or remove that override.');
    if (String(fields.context_window || '').trim()) out.context_window = positive(fields.context_window, 'Context length');
    else delete out.context_window;
    return out;
  },
  uniqueName(name, saved) {
    let candidate = name, n = 2; while (saved.some(m => m.name === candidate)) candidate = `${name}-${n++}`; return candidate;
  }
};
if (typeof module !== 'undefined') module.exports = ModelForms;

class ModelPicker {
  constructor({getState, api, $, esc, dialog, refresh, toast, canOpen}) {
    Object.assign(this, {getState, api, $, esc, dialog, refresh, toast, canOpen});
    $('addLmModel').onclick = () => this.open('lmstudio');
    $('addServerModel').onclick = () => this.open('server');
  }
  sync() {
    const models = this.getState()?.model_configs || [], e = this.esc;
    this.$('savedModelRows').innerHTML = models.map((m, i) => `<tr><td><strong>${e(m.name)}</strong><span class="questionmeta">${e(m.model)}</span></td><td>${e(m.base_url)}</td><td>${e(m.hardware || 'Not set')}</td><td>${e(m.extra?.max_tokens ?? m.max_tokens ?? 'Not set')}</td><td><button class="button secondary" data-copy-model="${i}">Duplicate</button></td></tr>`).join('') || '<tr><td colspan="5">Add your first model above.</td></tr>';
    this.$('savedModelRows').querySelectorAll('[data-copy-model]').forEach(b => b.onclick = () => this.open('server', models[+b.dataset.copyModel]));
  }
  open(source, copy = null) {
    if (!this.getState()?.model_library_available) { this.toast('Restart the Hourglass Bench console from your Terminal to enable model discovery, then refresh this page.'); return; }
    if (!this.canOpen()) { this.toast('Save or discard your JSON edits before adding a model.'); return; }
    const {$, esc:e} = this, revision = this.getState()?.models_revision;
    const fields = ['name','model','base_url','hardware','max_tokens','context_window'];
    const extras = structuredClone(copy || {}); fields.forEach(k => delete extras[k]);
    const input = (key, label, placeholder = '', numeric = false) => `<label class="model-field">${label}<input id="mf-${key}" ${numeric ? 'type="number" min="1" step="1"' : 'type="text"'} placeholder="${e(placeholder)}" ${key === 'hardware' ? 'maxlength="160"' : ''}></label>`;
    this.dialog(copy ? 'Duplicate model configuration' : source === 'lmstudio' ? 'Add from LM Studio' : 'Add a server model', `
      <p class="help">${source === 'lmstudio' ? 'Choose from your local library. Discovery reads lms; load models with your usual LM Studio settings.' : 'Paste an endpoint to see its advertised models and settings, including DS4 and other OpenAI-compatible servers.'}</p>
      <div class="model-discovery-bar">${input('base_url','Server endpoint','http://server:8000/v1')}<button id="inspectModelEndpoint" class="button secondary">${source === 'lmstudio' ? 'Refresh library' : 'Inspect endpoint'}</button></div>
      <p id="modelDiscoveryStatus" class="help" role="status"></p>
      <div id="modelDiscoveryReport"></div>
      <div id="modelSearchWrap" hidden><label class="model-field">Find a model<input id="modelLibrarySearch" type="search" placeholder="Search name, ID or quantization"></label></div><div id="modelLibraryRows" class="model-library"></div>
      <div id="selectedModelFacts"></div><h3>Configuration to add</h3><div class="model-form-grid">${input('name','Display name','My server · model')}${input('model','Model ID','Exact ID served by the endpoint')}${input('hardware','Hardware description','Inference machine and accelerator')}${input('max_tokens','Output token limit','Choose explicitly',true)}${input('context_window','Context length (optional)','Discover from server at run time',true)}</div>
      <p class="help">Output is an explicit request limit. Discovery uses a reported output maximum when available, otherwise the reported context as a suggestion. Review it before saving. Context and output limits are separate; the server may share context between input and output.</p>
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
    const build = () => ModelForms.entry(Object.fromEntries(fields.map(k => [k,$('mf-'+k).value])), JSON.parse($('modelExtraFields').value));
    const preview = () => { try { $('modelEntryPreview').textContent = JSON.stringify(build(),null,2); $('modelFormError').textContent = ''; } catch (error) { $('modelEntryPreview').textContent = error.message; } };
    fields.forEach(k => { $('mf-'+k).value = copy?.[k] ?? ''; $('mf-'+k).oninput = preview; });
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
      $('mf-context_window').value = ''; // Retain runtime server discovery unless explicitly entered.
      preview(); renderRows();
    };
    const renderRows = () => {
      const query = $('modelLibrarySearch').value.toLowerCase();
      const matches = rows.filter(r => `${r.title} ${r.model_id} ${r.quantization || ''}`.toLowerCase().includes(query));
      $('modelSearchWrap').hidden = !rows.length;
      $('modelLibraryRows').innerHTML = matches.map(r => `<button type="button" class="model-library-row ${selectedKey === (r.key || r.model_id) ? 'selected' : ''}" data-library-key="${e(r.key || r.model_id)}" aria-pressed="${selectedKey === (r.key || r.model_id)}"><strong>${e(r.title)}</strong><span>${e(r.model_id)}</span><small>${e([r.loaded === true ? 'Loaded' : r.loaded === false ? 'Not loaded' : 'Loaded state: not reported',r.quantization,r.parameters,r.format,r.size_bytes ? `${(r.size_bytes / 2**30).toFixed(1)} GiB` : '',r.context_length ? `Reported context: ${r.context_length.toLocaleString()}` : r.max_context_length ? `Model maximum context: ${r.max_context_length.toLocaleString()}` : 'Context: not reported',r.vision === true ? 'Vision advertised' : ''].filter(Boolean).join(' · '))}</small></button>`).join('') || (rows.length ? '<p class="help">No matching models.</p>' : '');
      $('modelLibraryRows').querySelectorAll('[data-library-key]').forEach(b => b.onclick = () => choose(rows.find(r => (r.key || r.model_id) === b.dataset.libraryKey)));
    };
    $('modelLibrarySearch').oninput = renderRows;
    $('inspectModelEndpoint').onclick = async () => {
      const b = $('inspectModelEndpoint'); b.disabled = true; $('modelDiscoveryStatus').textContent = 'Reading model metadata…';
      try {
        const result = source === 'lmstudio' ? await this.api('/api/model-library/lmstudio') : await this.api('/api/model-library/server', {base_url:$('mf-base_url').value});
        if (!alive()) return;
        rows = result.models || []; $('mf-base_url').value = result.base_url;
        $('modelDiscoveryStatus').textContent = source === 'lmstudio' ? `${rows.length} library entries · server ${result.server_running ? 'running' : 'not running'}. No model was loaded or unloaded.` : `${result.kind} · ${rows.length} model${rows.length === 1 ? '' : 's'} · ${result.reachable ? 'Endpoint responded' : 'Could not reach endpoint'}.`;
        $('modelDiscoveryReport').innerHTML = source === 'lmstudio' ? '' : `<details open><summary>What the endpoint reports</summary><dl class="reviewgrid"><dt>HTTP server</dt><dd>${e(result.http_server || 'Not reported')}</dd>${(result.reported || []).map(r=>`<dt>${e(r.label)}</dt><dd>${e(typeof r.value === 'object' ? JSON.stringify(r.value) : r.value)} <small>(${e(r.source)})</small></dd>`).join('')}</dl><p class="help">Unreported settings remain unknown. Inspection sends only metadata GET requests.</p><details><summary>Discovery responses and model metadata</summary><pre class="previewtext">${e(JSON.stringify({probes:result.probes,models:rows},null,2))}</pre></details></details>`;
        if (!rows.length) $('modelDiscoveryStatus').textContent += ' You can enter a model ID manually below.';
        renderRows(); preview();
      } catch (error) { if (alive()) $('modelDiscoveryStatus').textContent = error.message; }
      finally { if (alive()) b.disabled = false; }
    };
    preview(); if (source === 'lmstudio') $('inspectModelEndpoint').click();
  }
}

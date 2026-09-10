'use strict';
/* Draft-only editor. Publisher traffic happens solely on explicit Pull/Refresh. */
class InferenceProfileEditor {
  static help(label, text, id) {
    const e = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    return `<span class="ip-help"><button type="button" class="ip-help-trigger" aria-label="About ${e(label)}" aria-describedby="${e(id)}">?</button><span class="ip-tooltip" role="tooltip" id="${e(id)}">${e(text)}</span></span>`;
  }
  helpText(key) {
    const descriptions = {
      temperature:'Controls sampling randomness. Higher values generally vary choices more; zero requests the backend’s zero-temperature behavior.',
      top_p:'Keeps a set of likely tokens whose combined probability reaches this threshold. 1 removes this additional filter.',
      top_k:'Limits sampling to the most likely tokens. Zero commonly removes this filter; exact behavior depends on the backend.',
      min_p:'Filters tokens relative to the most likely token. The recommended 0 means no extra min-p filtering.',
      presence_penalty:'An additive penalty for tokens already present, regardless of how often they appeared. This is different from repetition penalty.',
      frequency_penalty:'An additive penalty based on how often a token appeared. It is different from presence and repetition penalties.',
      repetition_penalty:'A multiplicative adjustment for previously seen tokens. 1 is neutral. Do not substitute presence or frequency penalty for it.',
      seed:'Requests a random seed. Reproducibility still depends on backend, model, kernels and concurrency.',
      enable_thinking:'Controls whether this request generates new thinking. It is separate from retaining reasoning from earlier turns.',
      preserve_thinking:'Controls whether earlier reasoning blocks remain in conversation context. It does not turn new thinking on or off.',
      reasoning_effort:'Requests a model-specific reasoning level. It is not a token limit; accepted names and their meaning vary by model and backend.'
    };
    const backend = this.metadata?.backends[this.$('ip-backend').value];
    let support = 'Choose a backend to see how Hourglass sends this setting.';
    if (backend?.fields[key]) support = `Hourglass sends this to ${backend.label} as ${backend.fields[key]}. The deployed server and model template must honor it; this is not a runtime verification.`;
    else if (backend) support = `Hourglass has no verified request mapping for this control on ${backend.label}. This does not establish that every version of that server lacks support.`;
    if (this.$('ip-backend').value === 'ollama' && key === 'enable_thinking') support = 'Hourglass encodes this choice through reasoning_effort: none for disabled, or your selected effort for enabled. Support depends on the deployed model.';
    if (this.$('ip-backend').value === 'mtplx' && ['min_p','repetition_penalty'].includes(key)) support = 'The checked MTPLX request handler does not implement this override. Hourglass keeps the recommendation as reference and sends no value. This does not imply a configurable server switch exists.';
    if (this.$('ip-backend').value === 'mtplx' && key === 'preserve_thinking') support = 'MTPLX uses its server history policy. Its auto policy preserves history for Qwen3.8 unless overridden. Hourglass does not change that policy or verify the running server’s effective value.';
    return `${descriptions[key] || key} ${support}`;
  }
  refreshHelp() {
    for (const key of Object.keys(this.metadata?.fields || {})) this.$('ip-tooltip-field-'+key).textContent = this.helpText(key);
  }
  static markup() {
    return `<section id="inferenceProfileEditor"><h3>Inference settings</h3>
      <label id="ip-legacy-choice" hidden><input type="checkbox" id="ip-explicit" checked> Create an explicit profile from this grandfathered configuration</label>
      <p id="ip-legacy-note" class="help" hidden>This copy retains its grandfathered request behavior.</p>
      <p id="ip-native-note" class="help" hidden>Pi 0.85.1 handles the selected thinking level and available output space, with its default compaction, retries and timeouts. Model capacities and provider compatibility remain explicit.</p>
      <div id="ip-fields"><div class="model-form-grid">
        <label class="model-field">Backend<select id="ip-backend"><option value="">Choose backend…</option></select></label>
        <label class="model-field">Backend version / build<input id="ip-version" maxlength="160" placeholder="Deployed version or build identifier"></label>
        <label class="model-field">Connection<select id="ip-route"><option value="direct">Direct endpoint</option><option value="dsg">Through DSG</option></select></label>
        <label class="model-field" id="ip-route-wrap" hidden>Configured single-backend DSG route<input id="ip-route-name" maxlength="128" placeholder="Route name configured in DSG"></label>
        <label class="model-field">Output budget<select id="ip-output"><option value="">Choose output behavior…</option><option value="pi">Pi calculates available output space</option><option value="explicit">Historical: send fixed output limit</option><option value="server">Historical: omit output limit</option></select></label>
        <label class="model-field" id="ip-thinking-wrap" hidden>Pi thinking level<select id="ip-thinking"><option value="">Pi default (medium where supported)</option>${['off','minimal','low','medium','high','xhigh','max'].map(v=>`<option>${v}</option>`).join('')}</select><small>Uses the model’s declared thinking levels. This is a Pi session choice.</small></label>
      </div><p id="ip-backend-note" class="help"></p>
      <div id="ip-custom-settings">
      <div class="model-form-grid"><label class="model-field">Authoritative publisher repository<input id="ip-repository" placeholder="For example, Qwen/Qwen3.8-27B"></label>
        <label class="model-field">Source revision<input id="ip-revision" value="main" placeholder="Branch, tag or commit"></label></div>
      <button type="button" id="ip-pull" class="button secondary">Pull / Refresh recommended settings</button>
      <p class="help">Review the publisher source before accepting its values. Pull updates this draft only. Saved profiles work without a download.</p>
      <p id="ip-source-status" class="help" role="status"></p><div id="ip-proposal"></div>
      <details id="ip-edit-settings"><summary>Adjust request settings</summary><label class="model-field">Thinking mode for this configuration<select id="ip-lane" aria-describedby="ip-lane-help"><option value="">Choose when reviewing settings…</option></select><small id="ip-lane-help">Accept a proposal above to select its mode, or choose a mode for manual settings. Required when saving, not when pulling.</small></label>
      <div id="ip-values" class="model-form-grid"></div>
      <p id="ip-attribution" class="help"></p></details></div></div></section>`;
  }
  constructor({$, esc, api, copy, preview}) {
    Object.assign(this, {$, esc, api, copy, preview});
    this.source = structuredClone(copy?.inference_profile?.source || null);
    this.metadata = null;
    this.serverManaged = [...(copy?.inference_profile?.server_managed || [])];
  }
  alive() { return this.element === this.$('inferenceProfileEditor') && this.$('dialog').open; }
  async mount() {
    const {$, esc:e, copy} = this;
    this.element = $('inferenceProfileEditor');
    const legacy = copy && !copy.sampling_era;
    $('ip-legacy-choice').hidden = !legacy;
    $('ip-explicit').checked = !legacy;
    const profile = copy?.inference_profile || {};
    $('ip-version').value = profile.backend_version || '';
    $('ip-route').value = profile.route?.kind || 'direct';
    $('ip-route-name').value = profile.route?.name || '';
    $('ip-output').value = copy?.output_budget || '';
    $('ip-thinking').value = copy?.pi_thinking_level || '';
    $('ip-repository').value = this.source?.repository || '';
    $('ip-revision').value = this.source?.requested_revision || 'main';
    const sync = () => {
      $('ip-native-note').hidden = !this.native;
      $('ip-custom-settings').hidden = !!this.native;
      $('ip-thinking-wrap').hidden = !this.native;
      $('ip-output').disabled = !!this.native;
      if (this.native) $('ip-output').value = 'pi';
      $('ip-fields').hidden = !$('ip-explicit').checked;
      $('ip-legacy-note').hidden = $('ip-explicit').checked;
      $('ip-route-wrap').hidden = $('ip-route').value !== 'dsg';
      const backend = this.metadata?.backends[$('ip-backend').value];
      $('ip-backend-note').textContent = this.native ? 'Pi serializes requests using the model declaration and backend compatibility fields. Sampling parameters are in pi_model.samplingParams in the additional JSON.' : $('ip-backend').value === 'mtplx' ? 'MTPLX has three controls that Hourglass does not override. See their help icons for the distinction between an unavailable request control and a server-owned policy.' : backend?.note || 'Choose the backend that applies the request settings.';
      this.refreshHelp();
      if (this.pendingPull) this.renderProposals();
      this.preview();
    };
    for (const id of ['ip-explicit','ip-backend','ip-route','ip-output','ip-lane','ip-thinking']) $(id).onchange = sync;
    for (const id of ['ip-version','ip-route-name']) $(id).oninput = sync;
    $('ip-pull').onclick = () => this.pull();
    const helpFields = {
      'ip-backend':['Backend','Choose the actual inference engine behind the endpoint, even when connecting through DSG. Support shown here describes Hourglass’s mapping, not every version of that server.'],
      'ip-version':['Backend version','Record the deployed version or build. Newer server releases may accept controls missing from the current Hourglass mapping.'],
      'ip-route':['Connection','Through DSG uses the DSG ingress key. DSG chooses the worker and supplies its separate backend credential.'],
      'ip-route-name':['DSG route','This existing DSG route name is sent as x-dsg-model on inference requests. The body model ID is separate. Choose a route configured for one intended backend; this form does not configure DSG.'],
      'ip-output':['Output budget','Pi calculates an allowance from the model ceiling and remaining context. Historical profiles can send a fixed limit or omit it. Context capacity includes input and output.'],
      'ip-repository':['Publisher source','Recommendations come from this model publisher. A recommendation is not proof that your deployed server implements or applies a parameter.']
    };
    for (const [id,[label,text]] of Object.entries(helpFields)) {
      $(id).setAttribute?.('title',text);
      $(id).insertAdjacentHTML?.('afterend',InferenceProfileEditor.help(label,text,id+'-help'));
    }
    this.element.addEventListener?.('keydown',event => { if (event.key === 'Escape' && event.target.classList.contains('ip-help-trigger')) { event.stopPropagation(); event.preventDefault(); event.target.blur(); } });
    sync();
    try {
      const metadata = await this.api('/api/inference-profiles');
      if (!this.alive()) return;
      this.metadata = metadata;
      this.native = !!metadata.native_era && (!copy || copy.sampling_era === metadata.native_era);
      $('ip-backend').innerHTML += Object.entries(metadata.backends).map(([k,v]) => `<option value="${e(k)}">${e(v.label)}</option>`).join('');
      $('ip-lane').innerHTML += Object.entries(metadata.lanes).map(([k,v]) => `<option value="${e(k)}">${e(k === 'standard' ? 'No explicit thinking controls (manual)' : v)}</option>`).join('');
      $('ip-backend').value = profile.backend || '';
      $('ip-lane').value = profile.lane || '';
      $('ip-values').innerHTML = Object.entries(metadata.fields).map(([key,label]) => {
        let field;
        if (['enable_thinking','preserve_thinking'].includes(key)) field = `<select id="ip-value-${key}"><option value="">Choose if applicable…</option><option value="true">Enabled</option><option value="false">Disabled</option></select>`;
        else if (key === 'reasoning_effort') field = `<select id="ip-value-${key}"><option value="">Choose if applicable…</option>${['none','minimal','low','medium','high','xhigh','max'].map(v=>`<option>${v}</option>`).join('')}</select>`;
        else field = `<input id="ip-value-${key}" type="number" step="${['top_k','seed'].includes(key)?'1':'any'}" placeholder="Not specified">`;
        return `<div class="model-field" id="ip-field-${key}"><label for="ip-value-${key}">${e(label)}</label>${InferenceProfileEditor.help(label,this.helpText(key),"ip-tooltip-field-"+key)}${field}<small id="ip-source-${key}"></small></div>`;
      }).join('');
      const old = {...copy?.extra, ...copy?.extra?.chat_template_kwargs};
      if (copy?.temperature !== undefined) old.temperature = copy.temperature;
      const values = profile.values || old;
      for (const key of Object.keys(metadata.fields)) {
        $('ip-value-'+key).value = values[key] ?? '';
        $('ip-value-'+key).oninput = () => {
          this.attribution();
          if (this.pendingPull) this.renderProposals();
          this.preview();
        };
      }
      this.attribution(); sync();
    } catch (error) { if (this.alive()) $('ip-source-status').textContent = error.message; }
  }
  values() {
    const values = {};
    for (const key of Object.keys(this.metadata?.fields || {})) {
      const raw = this.$('ip-value-'+key).value.trim();
      if (raw === '') continue;
      values[key] = ['enable_thinking','preserve_thinking'].includes(key) ? raw === 'true' : key === 'reasoning_effort' ? raw : Number(raw);
    }
    return values;
  }
  attribution() {
    const values = this.values();
    let custom = false;
    for (const key of Object.keys(this.metadata.fields)) {
      const options = this.source?.candidates[key] || [];
      const selected = options.filter(o => o.value === values[key]);
      const conflict = Boolean(this.source?.conflicts?.[key]);
      if (key in values && (!selected.length || !options.length)) custom = true;
      this.$('ip-field-'+key).hidden = this.serverManaged.includes(key) && !(key in values);
      this.$('ip-source-'+key).textContent = conflict ? 'Choose a value: publisher sources conflict.' : selected.length ? 'Publisher recommendation' : key in values ? 'Custom value' : '';
    }
    this.$('ip-attribution').textContent = this.source ? (this.serverManaged.length ? 'Request settings follow the selected recommendations; server-controlled values are recorded separately and are not verified.' : custom ? 'Custom values are recorded alongside the publisher recommendations.' : 'Using the selected publisher recommendations.') : 'Manual profile — entered settings are owner supplied.';
    if (this.source) this.$('ip-source-status').textContent = `${this.source.repository} · ${this.source.revision} · ${this.source.importer_version}`;
  }
  sourceMatches(request) {
    return request.repository === this.$('ip-repository').value && request.revision === this.$('ip-revision').value;
  }
  renderProposals() {
    const {$, esc:e} = this;
    const {request, result} = this.pendingPull;
    const modes = Object.keys(result.proposals);
    const mode = modes.includes(this.reviewMode) ? this.reviewMode : modes.includes($('ip-lane').value) ? $('ip-lane').value : modes[0];
    this.reviewMode = mode;
    const proposal = result.proposals[mode];
    const backend = this.metadata.backends[$('ip-backend').value];
    const allowedServer = backend?.server_managed_fields || [];
    const serverKeys = Object.keys(proposal.candidates).filter(k => allowedServer.includes(k));
    const unsupported = backend ? Object.keys(proposal.candidates).filter(k => !(k in backend.fields) && !allowedServer.includes(k)) : [];
    const label = key => key === 'standard' ? 'Manual' : this.metadata.lanes[key];
    const display = value => value === undefined ? 'Choose a value' : value === true ? 'Enabled' : value === false ? 'Disabled' : String(value);
    const applied = this.source?.revision === result.revision && this.source?.lane === mode;
    $('ip-proposal').innerHTML = `<div class="ip-recommendation">
      <div class="ip-recommendation-head"><div><h4>Publisher recommendations</h4><p>${e(result.repository)}</p></div>
        <label class="model-field">Review mode<select id="ip-proposal-mode">${modes.map(k => `<option value="${e(k)}" ${k === mode ? 'selected' : ''}>${e(label(k))}</option>`).join('')}</select></label></div>
      <p class="help">${proposal.card_supported ? 'Uses the model card’s recommendations for this mode.' : 'Unrecognized model-card format. Review these defaults manually; mode support is unknown.'}</p>
      <table class="ip-recommendation-table"><thead><tr><th>Setting</th><th>Recommended value</th></tr></thead><tbody>${Object.keys(proposal.candidates).filter(k => !serverKeys.includes(k)).map(k => `<tr><td>${e(this.metadata.fields[k])} ${InferenceProfileEditor.help(this.metadata.fields[k],this.helpText(k),"ip-tooltip-proposal-"+k)}</td><td>${e(display(proposal.suggested[k]))}${proposal.conflicts?.[k] ? ' · conflicting sources' : ''}</td></tr>`).join('')}</tbody></table>
      ${serverKeys.length ? `<div class="ip-server-settings"><strong>Not overridden by Hourglass</strong><p>These are not sent in requests. Saving keeps the recommendations as reference; the server’s effective values are not verified.</p><ul>${serverKeys.map(k => `<li>${e(this.metadata.fields[k])} ${InferenceProfileEditor.help(this.metadata.fields[k],this.helpText(k),"ip-tooltip-server-"+k)} · publisher recommends ${e(display(proposal.suggested[k]))}</li>`).join('')}</ul></div>` : ''}
      ${unsupported.length ? `<p class="ip-compatibility-error">Hourglass has no verified ${e(backend.label)} request mapping for ${unsupported.map(k => e(this.metadata.fields[k])).join(', ')}. Choose a compatible backend or configure a manual profile.</p>` : !backend ? '<p class="help">Choose the backend above to apply these settings.</p>' : ''}
      <div class="ip-recommendation-actions"><button type="button" id="ip-accept" class="button ${applied ? 'secondary' : 'primary'}" ${!backend || unsupported.length ? 'disabled' : ''}>${applied ? 'Reapply' : 'Use'} ${e(label(mode))} settings</button>${applied ? '<span role="status">Applied to draft</span>' : ''}</div>
      <details class="ip-source-details"><summary>Source details</summary><p class="help">Revision ${e(result.revision)}. Mode-specific model-card values take precedence over general generation defaults.</p><table><thead><tr><th>Setting</th><th>Source values</th></tr></thead><tbody>${Object.entries(proposal.candidates).map(([k,options]) => `<tr><td>${e(this.metadata.fields[k])}</td><td>${options.map(o => `${e(o.source)}: ${e(display(o.value))}`).join('<br>')}</td></tr>`).join('')}</tbody></table>${proposal.notes.map(n => `<p class="help">${e(n)}</p>`).join('')}</details>
    </div>`;
    $('ip-proposal-mode').onchange = () => { this.reviewMode = $('ip-proposal-mode').value; this.renderProposals(); };
    $('ip-accept').onclick = () => {
      if (!backend || unsupported.length) return;
      if (!this.sourceMatches(request)) {
        $('ip-source-status').textContent = 'Source changed. Pull the selected source before accepting.'; return;
      }
      const values = this.values();
      for (const [key, value] of Object.entries(this.source?.suggested || {})) {
        if (!(key in proposal.candidates) && values[key] === value) $('ip-value-'+key).value = '';
      }
      this.source = structuredClone(proposal);
      // Unsent controls remain explicit in the profile, never claimed as applied.
      // Existing manually entered values are retained for validation, not discarded.
      this.serverManaged = serverKeys;
      $('ip-lane').value = mode;
      for (const key of Object.keys(proposal.candidates)) {
        if (!serverKeys.includes(key)) $('ip-value-'+key).value = proposal.suggested[key] ?? '';
      }
      this.attribution(); this.preview(); this.renderProposals();
      $('ip-source-status').textContent = `${label(mode)} settings applied. You can adjust the request settings below.`;
    };
  }
  async pull() {
    const {$} = this;
    if (!this.metadata) { $('ip-source-status').textContent = 'Wait for the inference settings editor to load.'; return; }
    const request = {repository:$('ip-repository').value, revision:$('ip-revision').value};
    const pullId = this.pullId = (this.pullId || 0) + 1;
    this.pendingPull = null;
    $('ip-proposal').innerHTML = '';
    $('ip-pull').disabled = true; $('ip-source-status').textContent = 'Reading publisher settings for all modes…';
    try {
      const result = await this.api('/api/inference-profiles/pull', request);
      if (!this.alive() || pullId !== this.pullId) return;
      if (!this.sourceMatches(request)) {
        $('ip-source-status').textContent = 'Source changed during the pull. Pull again for the selected source.'; return;
      }
      if (!result.proposals) throw Error('The running console needs to be restarted to load the updated recommendation importer.');
      this.pendingPull = {request, result};
      this.renderProposals();
      $('ip-source-status').textContent = 'Recommendations loaded. Review a mode below and use its settings in the draft.';
    } catch (error) { if (this.alive() && pullId === this.pullId) $('ip-source-status').textContent = error.message; }
    finally { if (this.alive() && pullId === this.pullId) $('ip-pull').disabled = false; }
  }
  apply(entry) {
    if (!this.$('ip-explicit').checked) return entry;
    if (!this.metadata) throw Error('Wait for the inference settings editor to load.');
    if (this.native) {
      entry.sampling_era = this.metadata.native_era;
      entry.output_budget = 'pi';
      if (this.$('ip-thinking').value) entry.pi_thinking_level = this.$('ip-thinking').value;
      else delete entry.pi_thinking_level;
      entry.inference_profile = {mapping_version:this.metadata.native_era,
        backend:this.$('ip-backend').value, backend_version:this.$('ip-version').value.trim(),
        route:{kind:this.$('ip-route').value, ...(this.$('ip-route').value === 'dsg' ? {name:this.$('ip-route-name').value.trim()} : {})}};
      return entry;
    }
    const values = this.values();
    // A conversion is a new reviewed profile. Move only recognized legacy keys;
    // unknown additional fields remain visible and fail validation, never vanish.
    for (const key of Object.keys(this.metadata.fields)) {
      if (key in values) { delete entry[key]; if (entry.extra) delete entry.extra[key]; }
      if (key in values && entry.extra?.chat_template_kwargs) delete entry.extra.chat_template_kwargs[key];
    }
    if (entry.extra?.chat_template_kwargs && !Object.keys(entry.extra.chat_template_kwargs).length) delete entry.extra.chat_template_kwargs;
    if (entry.extra && !Object.keys(entry.extra).length) delete entry.extra;
    entry.sampling_era = this.metadata.era;
    entry.output_budget = this.$('ip-output').value;
    entry.inference_profile = {mapping_version:this.metadata.mapping_version, backend:this.$('ip-backend').value,
      backend_version:this.$('ip-version').value.trim(), lane:this.$('ip-lane').value,
      route:{kind:this.$('ip-route').value, ...(this.$('ip-route').value === 'dsg' ? {name:this.$('ip-route-name').value.trim()} : {})},
      values, ...(this.serverManaged.length ? {server_managed:[...this.serverManaged]} : {}), ...(this.source ? {source:structuredClone(this.source)} : {})};
    return entry;
  }
}
if (typeof module !== 'undefined') module.exports = InferenceProfileEditor;

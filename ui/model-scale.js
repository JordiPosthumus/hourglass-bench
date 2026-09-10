'use strict';
let modelScaleData=null,modelScaleLoading=false,modelScaleFetchedAt=0;
async function loadModelScale(force=false){
  if(modelScaleLoading||(!force&&Date.now()-modelScaleFetchedAt<10000))return;
  modelScaleLoading=true;
  try{modelScaleData=await api('/api/model-scale');modelScaleFetchedAt=Date.now();renderModelScale()}
  catch(error){document.getElementById('modelScaleStatus').textContent='Custom scale could not load: '+error.message}
  finally{modelScaleLoading=false}
}
function renderModelScale(){
  if(!modelScaleData)return;
  const data=modelScaleData,select=document.getElementById('modelScaleRuns'),previous=select.value,scopes=[...new Set(data.evaluations.map(e=>e.scope))];
  select.innerHTML=`<option value="">All runs (${data.evaluations.length})</option>`+scopes.map(id=>{const rows=data.evaluations.filter(e=>e.scope===id),e=rows[0];return `<option value="${esc(id)}">v${esc(e.benchmark_version)} · ${e.questions} questions · ${rows.length} run${rows.length===1?'':'s'}</option>`}).join('');
  select.value=scopes.includes(previous)?previous:'';
  const rows=data.evaluations.filter(e=>!select.value||e.scope===select.value),fit=data.fit;
  document.getElementById('modelScaleStatus').textContent='Assign scores of your choosing to a few models. Recorded raw weighted points place the other models approximately on your scale.';
  document.getElementById('modelScaleFit').innerHTML=`<div class="notice"><strong>${esc(fit.message)}</strong>${fit.status==='ready'?`<details><summary>How this scale is calculated</summary><p>Custom score ≈ ${fit.intercept.toFixed(3)} ${fit.slope<0?'−':'+'} ${Math.abs(fit.slope).toFixed(3)} × raw weighted points. Each reference model has equal weight. Assigned targets stay exact; other models use the fitted line.</p><p>Values beyond your reference range (${fit.min_points.toFixed(1)}–${fit.max_points.toFixed(1)} points) are labelled extrapolated. This is your approximate scale across recorded banks, hardware and rules.</p></details>`:''}</div>`;
  document.getElementById('modelScaleRows').innerHTML=rows.length?rows.map(e=>{
    const state={final:'Final',in_progress:'In progress',partial:'Partial',not_started:'Not started',unavailable:'Timing unavailable'}[e.state]||e.state;
    return `<tr><td><details class="scale-model"><summary title="${esc(e.display_name)}">${esc(e.display_name)}</summary><p>${esc(e.model)}<br>${esc(e.hardware)}<br>v${esc(e.benchmark_version)} · ${esc(e.id.slice(0,8))}</p></details><small>${esc(new Date(e.created*1000).toLocaleString())}</small></td><td><strong>${e.points==null?'—':Number(e.points).toFixed(1)}</strong><small>${esc(e.scoring_policy)}</small></td><td>${esc(state)}${caveatBadges(e.caveats)}<small>${e.completed_questions} / ${e.questions} questions · ${seconds(e.elapsed_s)}</small>${e.timeouts?`<small>${e.timeouts} timed out</small>`:''}</td><td><strong>${e.custom_score==null?'—':Number(e.custom_score).toFixed(1)}</strong><small>${esc(e.score_note)}</small></td><td>${e.reference?`<strong>${esc(e.reference.target)}</strong><small>Saved at ${Number(e.reference.points).toFixed(1)} points</small>`:''}<div class="scale-target-actions"><button type="button" class="textbutton" data-model-target="${esc(e.id)}">${e.reference?'Edit target':'Set target'}</button>${e.reference?`<button type="button" class="textbutton" data-remove-model-target="${esc(e.id)}" aria-label="Remove target for ${esc(e.display_name)}">Remove</button>`:''}</div></td></tr>`;
  }).join(''):'<tr><td colspan="5">No runs in this view yet.</td></tr>';
  document.querySelectorAll('[data-model-target]').forEach(button=>button.onclick=()=>editModelTarget(button.dataset.modelTarget));
  document.querySelectorAll('[data-remove-model-target]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api('/api/model-scale/remove',{evaluation_id:button.dataset.removeModelTarget});await loadModelScale(true);toast('Target removed from your custom scale.')}catch(error){toast(error.message);button.disabled=false}});
}
function editModelTarget(id){
  const e=modelScaleData.evaluations.find(e=>e.id===id);if(!e)return;
  if(!e.available){dialog('Target needs a recorded score',`<p>${esc(e.unavailable_reason)}</p>`,[{label:'Close',click:()=>document.getElementById('dialog').close()}]);return}
  const existing=modelScaleData.references.find(r=>r.model===e.model);
  dialog(`Set target · ${e.display_name}`,`<p>Recorded raw weighted points: <strong>${Number(e.points).toFixed(1)} points</strong>. ${e.state==='final'?'Final run.':'This is a partial snapshot of the run.'}</p><label class="fieldlabel" for="modelTarget">Your score for this model</label><input id="modelTarget" class="repeatinput" type="number" step="any" placeholder="For example, 1 or 5" value="${existing?.target??''}"><p class="help">${existing?'Saving replaces the previous reference for this saved model.':'This becomes a reference for your approximate model scale.'} The reference keeps this recorded raw weighted points even if the run continues.</p><p id="modelTargetError" class="help" role="alert"></p>`,[{label:'Cancel',click:()=>document.getElementById('dialog').close()},{label:'Save target',primary:true,click:async button=>{
    const text=document.getElementById('modelTarget').value,target=Number(text);
    if(!text.trim()||!Number.isFinite(target)){document.getElementById('modelTargetError').textContent='Enter a finite number for your target.';return}
    button.disabled=true;
    try{await api('/api/model-scale/reference',{evaluation_id:id,target,expected_points:e.points});document.getElementById('dialog').close();await loadModelScale(true);toast('Target saved to your custom model scale.')}
    catch(error){document.getElementById('modelTargetError').textContent=error.message;button.disabled=false}
  }}]);
}
function initializeModelScale(){
  document.getElementById('refreshModelScale').onclick=()=>loadModelScale(true);
  document.getElementById('modelScaleRuns').onchange=renderModelScale;
  document.getElementById('accuracyTools').ontoggle=()=>{if(document.getElementById('accuracyTools').open)loadCalibration()};
}

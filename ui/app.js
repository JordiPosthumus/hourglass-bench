'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const store={get(k,d){try{return JSON.parse(localStorage.getItem('hourglass.v2.'+k))??d}catch{return d}},set(k,v){try{localStorage.setItem('hourglass.v2.'+k,JSON.stringify(v))}catch{}}};
let S=null,page='bench',limit=20,taskSignature='',modelSignature='',dirty=false,refreshing=false,logId=null,activeDetails=null;
let editorBaseRevision=null;
let checked={},toastTimer,liveRunId=null,draftSourceRunId=null;
let archiveView=false,workspaceView='visible',chartView='comparison';
let librarySort='order',libraryDirection='desc',libraryStats=new Map(),libraryHistorySignature='';
let currentQuestionKey='',currentQuestionRequest=0,chartFailedUrl='';
// The independent report helper can update while benchmark work stays active.
let reportBase='/scores';
function renderPublish(){if(!S)return;const jobs=allJobs(),select=$('publishRunSelect'),previous=select.value||liveRunId;select.innerHTML=jobs.map(j=>`<option value="${esc(j.id)}">${esc(j.model)}</option>`).join('');if(jobs.some(j=>j.id===previous))select.value=previous;const id=select.value;$('publishEmpty').hidden=!!id;$('publishFrame').hidden=!id;if(id){const url=reportBase+'/?job='+encodeURIComponent(id)+'&scope=all&embed=1#publish';if($('publishFrame').getAttribute('src')!==url)$('publishFrame').src=url}}
function openPublish(id){renderPublish();if(id)$('publishRunSelect').value=id;setPage('publish')}

const sectionNames={games:'Games',charts:'Charts',math:'Math & logic',code:'Code',challenge:'Challenges',repository_discovery:'Repository discovery'};
const sectionKey=s=>s==='chart'?'charts':s==='math_logic'?'math':s;
const sectionName=s=>sectionNames[sectionKey(s)]||s||'Other';
const seconds=s=>s<1?`${(s||0).toFixed(2)}s`:s<60?`${s.toFixed(1)}s`:`${Math.floor(s/60)}m ${Math.round(s%60)}s`;
const median=a=>{a=[...a].sort((a,b)=>a-b);return a.length?(a[Math.floor(a.length/2)]+a[Math.ceil(a.length/2)-1])/2:0};
const version=r=>r.benchmark_version||'unversioned';
const resultLabel=r=>(r.repair_inherited?'Retained · ':'')+(r.score_reason==='abstained'?'Abstained · 0':r.status==='timeout'?'Timed out · 0':r.status==='not_attempted'?'Not attempted · awaiting retry':['five_wrong_in_row','wrong_streak_limit'].includes(r.score_reason)?'Not attempted · 0':r.score_reason==='unsupported_vision'?'Vision unsupported · 0':r.status==='error'?'Execution error':r.solved?'Correct':'Incorrect');
const outcome=r=>r.status==='timeout'?'timeout':r.status==='not_attempted'?'not_attempted':r.status==='error'?'error':r.solved?'correct':'incorrect';
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),5000)}
async function api(url,body){const r=await fetch(url,body!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||`Request failed (${r.status})`);return data}

function setPage(p){if(!['bench','results','settings','current','publish'].includes(p))p='bench';page=p;document.querySelectorAll('.page').forEach(el=>el.classList.toggle('hidden',el.id!=='page-'+p));document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.page===p));if(location.hash!=='#'+p)history.replaceState(null,'','#'+p);if(p==='results'&&S)renderResults();if(p==='current'&&S)renderCurrentQuestion();if(p==='publish'&&S){renderPublish();if(liveRunId){$('publishRunSelect').value=liveRunId;renderPublish()}}}
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>setPage(b.dataset.page));window.addEventListener('hashchange',()=>setPage(location.hash.slice(1)));$('backToBench').onclick=()=>setPage('bench');
function filteredTasks(){if(!S)return[];const q=$('search').value.toLowerCase(),section=$('sectionFilter').value,tier=$('tierFilter').value;return S.tasks.filter(t=>(!section||sectionKey(t.section)===section)&&(!tier||(tier==='untiered'?(t.order_tier??t.tier)==null:String(t.order_tier??t.tier)===tier))&&(!q||`${t.id} ${t.title} ${t.summary||""} ${t.family}`.toLowerCase().includes(q)))}
function renderLibrary(){updateLibrarySortHeaders();const rows=QuestionLibrary.sort(filteredTasks(),libraryStats,librarySort,libraryDirection),shown=rows.slice(0,limit);$('libraryCaption').textContent=`${rows.length} question${rows.length===1?'':'s'} · ${new Set(rows.map(t=>t.family)).size} ${new Set(rows.map(t=>t.family)).size===1?'family':'families'}`;$('taskRows').innerHTML=shown.map(t=>{const stats=libraryStats.get(t.id)||{},rate=(value,n,d)=>value==null?'—':`${(value*100).toFixed(1)}%<span class="questionmeta">${n}/${d}</span>`;return `<tr><td><button class="textbutton questiontitle" data-preview="${esc(t.id)}">${esc(t.title)}</button>${t.summary?`<span class="questionmeta">${esc(t.summary)}</span>`:""}<span class="questionmeta"><code>${esc(t.id)}</code> ${esc(t.discovery_domain?({games:'Games',hourglass:'Hourglass',dsg:'DSG'}[t.discovery_domain]+' · repository discovery'):t.family)}${questionReviewFlag(t.id)}${t.issues.length?' · Needs attention':''}</span></td><td><span class="tier t${Number(t.order_tier??t.tier)}" title="${esc(t.tier_estimated?`Estimated from ${t.level.replaceAll('_',' ')}`:'Authored difficulty tier')}">${(t.order_tier??t.tier)==null?(t.section==='repository_discovery'?'Uncalibrated':'Untiered'):`${t.tier_estimated?'~':''}T${Number(t.order_tier??t.tier)}`}</span></td><td>${Number.isFinite(t.points)?Number(t.points.toFixed(2)):'—'}</td><td>${stats.average==null?'—':seconds(stats.average)}<span class="questionmeta">${stats.timed||0} timed answers</span></td><td>${rate(stats.wrongRate,stats.wrong,stats.answered)}</td><td>${rate(stats.timeoutRate,stats.timeouts,stats.attempts)}</td><td>${rate(stats.errorRate,stats.errors,stats.attempts)}</td><td>${stats.attempts||0}</td><td><button class="iconbutton" data-preview="${esc(t.id)}" aria-label="Preview ${esc(t.id)}" title="View question">View</button></td></tr>`}).join('');$('shownCount').textContent=`Showing ${shown.length} of ${rows.length}`;$('moreTasks').classList.toggle('hidden',shown.length>=rows.length);$('noTasks').classList.toggle('hidden',rows.length>0);$('taskRows').querySelectorAll('[data-preview]').forEach(b=>b.onclick=()=>preview(b.dataset.preview))}
for(const id of ['search','sectionFilter','tierFilter'])$(id).addEventListener(id==='search'?'input':'change',()=>{limit=20;renderLibrary()});$('moreTasks').onclick=()=>{limit+=20;renderLibrary()};
function syncRunBuilder(){
  const hasRuns=!!(S.jobs.running.length+S.jobs.pending.length+S.jobs.done.length),drawer=$('runSetupDrawer'),home=$('runBuilderHome'),builder=$('runBuilder');
  const target=hasRuns?drawer:home;
  if(builder.parentElement!==target){if(drawer.open)drawer.close();target.append(builder);}
  home.hidden=hasRuns||workspaceView==='questions';
  $('closeRunBuilder').hidden=!hasRuns;
  $('firstGuide').classList.add('hidden');
  $('emptyNewRun').hidden=!hasRuns||allJobs().length>0||workspaceView==='questions';
  $('page-bench').querySelector('h1').textContent=hasRuns?'Your runs.':'Build your first run.';
}
function showRunBuilder(){setPage('bench');if(workspaceView!=='visible')setWorkspaceView('visible');syncRunBuilder();const drawer=$('runSetupDrawer');if($('runBuilder').parentElement===drawer&&!drawer.open)drawer.showModal();else $('runBuilder').scrollIntoView({behavior:'smooth',block:'center'});$('model').focus({preventScroll:true});}
function closeRunBuilder(){if($('runSetupDrawer').open)$('runSetupDrawer').close();}
$('closeRunBuilder').onclick=closeRunBuilder;
$('emptyNewRun').onclick=showRunBuilder;
$('runSetupDrawer').addEventListener('click',e=>{if(e.target!==e.currentTarget)return;const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeRunBuilder();});
$('starterBtn').onclick=showRunBuilder;$('resultStarter').onclick=showRunBuilder;
const endpointHardware=new EndpointHardware({api,refresh,changed:()=>{if(S)renderBuilder()},getModel:modelConfig,openSettings:()=>setPage('settings')});
function modelConfig(){return S?.model_configs.find(m=>m.name===$('model').value)}
function bankTasks(){return S?.tasks||[]}

function renderBuilder(){const m=modelConfig(),tasks=bankTasks();$('modelInfo').innerHTML=m?`<div>${esc(m.model)}</div><div>${esc(m.base_url)}</div><div>Inference machine: ${esc(endpointHardware.summary(m.base_url))} <button class="textbutton" id="configureEndpointHardware">Record hardware</button></div><div class="modelchips"><span>${m.output_budget==='pi'?`Pi output capacity: ${esc(m.max_tokens)} · sized per request`:m.output_budget==='server'?'Output: server controlled':`max_tokens ${esc(m.extra?.max_tokens??m.max_tokens??1024)}`}</span><span>${m.output_budget==='pi'?`Thinking: ${esc(m.pi_thinking_level||'Pi default')}`:'Historical request profile'}</span><span>temperature: ${esc(m.pi_model?.samplingParams?.temperature??'server default')}</span></div>${m.response_mode==='complete'?'<p class="help">Complete-response mode: reasoning and tool progress appear when each model response finishes.</p>':''}`:'No model is configured. Add one in Model settings.';if($('configureEndpointHardware'))$('configureEndpointHardware').onclick=()=>endpointHardware.open(m.base_url);const attempts=tasks.length;$('bankSummary').innerHTML=tasks.length?`<strong>${tasks.length} questions · full bank</strong>`:'No question bank is installed.';$('reviewRun').disabled=!tasks.length||!m||tasks.some(t=>t.issues.length);$('visionNote').textContent=m?.supports_vision===false?'This model has no vision support. Image questions count as zero and are not sent to the model.':'Vision support is detected from the endpoint response. Unsupported image questions count as zero automatically.';$('visionNote').classList.toggle('hidden',!tasks.some(t=>t.vision));$('checkModel').disabled=!m;renderEndpoint()}
function renderEndpoint(){const m=modelConfig(),c=m&&checked[m.name];$('endpointDetails').classList.add('hidden');$('endpointStatus').textContent=c?(c.reachable?(c.listed?'Endpoint reachable':'Model ID not listed'):'Endpoint unavailable'):'Connection not checked';$('endpointStatus').style.color=c?(c.reachable&&c.listed?'var(--green)':'var(--amber)'):'';if(c){$('endpointDetails').classList.remove('hidden');$('endpointDetails').classList.toggle('error',!c.reachable);$('endpointDetails').textContent=!c.reachable?`Could not reach this server. ${c.message}`:!c.listed?`Server responds, but “${m.model}” is not listed. Available: ${c.available.join(', ')||'(none)'}. Check the exact ID in Model settings.`:c.message}}
$('model').onchange=()=>{store.set('model',$('model').value);renderBuilder()};
$('checkModel').onclick=async()=>{const name=$('model').value,b=$('checkModel');b.disabled=true;b.textContent='Checking…';try{checked[name]=await api('/api/check-model',{model:name});renderEndpoint()}catch(e){toast(e.message)}finally{b.disabled=false;b.textContent='Check connection'}};
function dialog(title,html,actions=[]){$('dialogTitle').textContent=title;$('dialogBody').innerHTML=html;$('dialogActions').innerHTML='';for(const a of actions){const b=document.createElement('button');b.className='button '+(a.primary?'primary':'secondary');b.textContent=a.label;b.onclick=()=>a.click(b);$('dialogActions').append(b)}if(!$('dialog').open)$('dialog').showModal()}
$('closeDialog').onclick=()=>$('dialog').close();$('dialog').addEventListener('click',e=>{if(e.target===$('dialog')){const r=$('dialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('dialog').close()}});
function workspaceFilesHtml(t){return Object.entries(t.public_files||{}).map(([name,content])=>`<details><summary><code>${esc(name)}</code></summary><pre class="previewtext">${esc(content)}</pre></details>`).join('')}
async function preview(id){try{const t=await api('/api/task?id='+encodeURIComponent(id));dialog(`${id} · ${t.title}`,`<p class="help">Preview shows the question and public workspace files, not the answer key.</p><pre class="previewtext">${esc(t.prompt)}</pre><details><summary>${t.options.length} options</summary><pre class="previewtext">${esc(t.options.map(o=>typeof o==='string'?o:`${o.id} — ${o.text}`).join('\n'))}</pre></details><p class="help">Workspace: ${esc(t.files.join(', ')||'Question and attached assets')}</p>${workspaceFilesHtml(t)}`,[{label:'Close',click:()=>$('dialog').close()}])}catch(e){toast(e.message)}}
$('reviewRun').onclick=async()=>{
  const m=modelConfig(),tasks=bankTasks();
  const attempts=tasks.length;
  const request={model:m.name,tasks:tasks.map(t=>t.id),
    hardware_revision:S.endpoint_hardware?.revision,models_revision:S.models_revision,
    task_bundles:Object.fromEntries(tasks.map(t=>[t.id,t.task_bundle_sha])),
    ...(draftSourceRunId?{copy_from:draftSourceRunId}:{})};
  if(endpointHardware.dirty||endpointHardware.saving){endpointHardware.open(m.base_url);toast('Save or discard hardware edits before reviewing a run.');return;}
  let naming;
  try{naming=await api('/api/run-identity',{model:m.name})}catch(e){toast(e.message);return}
  request.identity={...naming.values};
  const values=naming.values,server=[values.server_name,values.server_version].filter(Boolean).join(' · ');
  const row=(label,value)=>`<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`;
  dialog('Review your run',`<dl class="reviewgrid">
    ${naming.identity.overridden?row('Configuration',naming.identity.name):''}
    ${row('Model',values.model_name||m.model)}
    ${server?row('Server / recipe',server):''}
    ${values.quantization?row('Quantization',values.quantization):''}
    ${row('Inference machine',values.hardware||endpointHardware.summary(m.base_url))}
    ${row('Endpoint',m.base_url)}
    ${row('Run length','One active hour; whole-bank rounds as time allows')}

    ${row('Output allowance',m.output_budget==='pi'?`Native Pi, up to the declared ${m.max_tokens}-token model capacity, sized to fit context`:m.output_budget==='server'?'Server controlled':`${m.extra?.max_tokens??m.max_tokens??1024} tokens, from saved settings`)}
    ${m.output_budget==='pi'?row('Pi session',`Thinking: ${m.pi_thinking_level||'Pi default (medium where supported)'}; automatic compaction; five-minute HTTP idle timeout`):''}
    <dt>Execution</dt><dd>Easy → medium → hard, rotating subjects, with a challenge after every four regular questions when available. Repository discovery follows every eight existing questions, cycling Games, Hourglass and DSG. Then repeat the whole bank: wrong answers → unfinished → correct, slowest first within each group using the latest attempt. Each attempt has 15 minutes; every attempt adds its award or penalty. One shared 60-minute clock.</dd>
  </dl><details><summary>Question order · ${tasks.length} questions</summary><ol class="reviewlist">${tasks.map(t=>`<li><strong>${esc(t.id)}</strong> · ${esc(t.title)}</li>`).join('')}</ol></details>
  <p id="startRunError" class="notice error" role="alert" tabindex="-1" hidden></p>
  <p class="help">${S.jobs.running.length||S.jobs.pending.length?'This run will wait for existing work to finish.':'Starting runs the complete bank in its rule-defined order.'}</p>`,[
    {label:'Back',click:()=>$('dialog').close()},
    {label:S.jobs.running.length?'Add to queue':'Start run',primary:true,click:async b=>{
      const label=b.textContent,error=$('startRunError');
      error.hidden=true;error.textContent='';b.disabled=true;b.textContent='Starting…';
      try{
        const r=await api('/api/run',request);
        selectLog(r.job,true);liveRunId=r.job;draftSourceRunId=null;$('dialog').close();closeRunBuilder();
        toast('Run added. Follow its progress here.');await refresh();$('liveRun').scrollIntoView({behavior:'smooth',block:'center'});
      }catch(e){
        error.textContent=e.message;error.hidden=false;error.focus();error.scrollIntoView({block:'nearest'});
        b.disabled=false;b.textContent=label;
      }
    }}]);
};
function renderJobs(){syncRunBuilder();renderLiveRun();const j=S.jobs,all=allJobs().slice(0,8);$('activityCaption').textContent=j.running.length?`Running ${j.running[0].current_task||'first question'} · ${j.pending.length} waiting`:j.pending.length?`${j.pending.length} waiting to start`:'Runs execute one at a time.';$('activityBadge').textContent=j.running.length?'Running':j.pending.length?'Queued':'Idle';$('activityBadge').className='statusbadge '+(j.running.length?'active':'');$('jobs').innerHTML=all.length?all.map(r=>`<div class="jobrow"><span class="statusbadge ${r.state==='error'?'bad':r.state==='completed'?'good':r.state==='running'?'active':''}">${esc(r.state)}</span><div class="joblabel"><strong>${esc(r.label)}</strong><small>${r.state==='running'?`${r.completed_tasks||0}/${r.total_tasks} questions complete · ${Math.floor(Date.now()/1000-r.started)}s elapsed`:r.error?esc(r.error):r.state==='completed'?(r.stopped_after?`Stopped after ${esc(r.stopped_after)}: ${r.stop_after_wrong??5} incorrect questions in a row. Remaining questions scored zero.`:`${r.total_tasks} questions completed · inspect Results for scores`):r.state==='cancelled'?'Removed before starting':'Waiting for its turn'}</small></div>${r.state==='running'?`<progress value="${r.completed_tasks||0}" max="${r.total_tasks}"></progress>`:''}${!['running','pending'].includes(r.state)?`<button class="textbutton" data-archive-run="${esc(r.id)}">${r.archived?'Restore run':'Archive run'}</button>`:''}${r.state==='running'?`<button class="textbutton" data-stop-run="${esc(r.id)}" ${r.stop_requested?'disabled':''}>${r.stop_requested?'Stopping…':'Stop run'}</button>`:''}${r.resume?.allowed?`<button class="textbutton" data-resume="${esc(r.id)}">Resume run</button>`:''}${r.state==='pending'?`<button class="textbutton" data-cancel="${esc(r.id)}">Remove</button>`:r.state!=='cancelled'?`<button class="textbutton" data-log="${esc(r.id)}">View log</button>`:''}</div>`).join(''):'<div class="activityempty">No runs yet. Choose a model and review the full-bank benchmark.</div>';$('jobs').querySelectorAll('[data-log]').forEach(b=>b.onclick=()=>{selectLog(b.dataset.log);loadLog()});$('jobs').querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async()=>{try{await api('/api/cancel',{job:b.dataset.cancel});toast('Waiting run removed.');refresh()}catch(e){toast(e.message)}});$('jobs').querySelectorAll('[data-resume]').forEach(b=>b.onclick=()=>reviewResume(b.dataset.resume));$('jobs').querySelectorAll('[data-archive-run]').forEach(b=>b.onclick=()=>archiveRun(b.dataset.archiveRun));$('jobs').querySelectorAll('[data-stop-run]').forEach(b=>b.onclick=()=>stopRun(b.dataset.stopRun));if(logId)loadLog()}
let logEpoch=0;
function selectLog(id,force=false){
  if(id===logId&&!force)return;
  logId=id;logEpoch++;$('jobLog').textContent='';$('jobLog').scrollTop=0;
  const job=allJobs().find(j=>j.id===id);
  $('logTitle').textContent=id?`Run log · ${job?.model||id} · ${id.slice(0,8)}`:'Run log';
  $('logWrap').classList.toggle('hidden',!id);
}
async function loadLog(){const id=logId,epoch=logEpoch;if(!id)return;try{const r=await fetch('/api/log?job='+encodeURIComponent(id));if(!r.ok)throw Error('Log unavailable');const t=await r.text();if(id!==logId||epoch!==logEpoch)return;$('logWrap').classList.remove('hidden');const atBottom=$('jobLog').scrollTop+$('jobLog').clientHeight>=$('jobLog').scrollHeight-40;$('jobLog').textContent=t;if(atBottom)$('jobLog').scrollTop=$('jobLog').scrollHeight}catch(e){if(id===logId&&epoch===logEpoch)$('jobLog').textContent=e.message}}

function filteredResults(){const q=$('resultSearch').value.toLowerCase(),sec=$('resultSection').value,status=$('resultStatus').value;const ids=new Set(allJobs().map(j=>j.id));return S.results.filter(r=>ids.has(r.evaluation_id)&&(!q||`${r.task} ${r.model}`.toLowerCase().includes(q))&&(!sec||sectionKey(r.section||S.tasks.find(t=>t.id===r.task)?.section)===sec)&&(!status||outcome(r)===status))}
function renderResults(){renderHourScores();const any=filteredResults().length>0;$('resultEmpty').classList.toggle('hidden',any);$('resultContent').classList.toggle('hidden',!any);if(!any)return;const rows=filteredResults(),scored=rows.filter(r=>outcome(r)!=='error'&&isFinalScore(r)),correct=scored.filter(r=>r.solved).length;$('statRuns').textContent=scored.length;$('statAccuracy').textContent=scored.length?`${(100*correct/scored.length).toFixed(1)}%`:'—';$('statTime').textContent=scored.length?seconds(median(scored.map(r=>r.duration_s||0))):'—';$('statErrors').textContent=rows.filter(r=>r.status==='error').length;const groups=new Map();for(const r of scored){const k=r.model+' @ '+(r.node||'?')+' · Hourglass '+version(r);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(r)}const stats=[...groups].map(([name,rs])=>({name,n:rs.length,acc:rs.filter(r=>r.solved).length/rs.length,time:median(rs.map(r=>r.duration_s||0))}));$('modelComparison').innerHTML=stats.length?stats.map(s=>`<tr><td>${esc(s.name)}</td><td>${s.n}</td><td>${(100*s.acc).toFixed(1)}%</td><td>${seconds(s.time)}</td></tr>`).join(''):'<tr><td colspan="4">No scored attempts in this filter.</td></tr>';drawScatter(efficiencyStats(Object.values(S.jobs).flat(),rows));$('resultRows').innerHTML=rows.slice().reverse().map((r,i)=>`<tr class="clickrow" data-result="${i}" tabindex="0" role="button" aria-label="Open ${esc(r.task)} result"><td><strong>${esc(r.task)}</strong><span class="questionmeta">Tier ${esc(r.tier)} · v${esc(version(r))}</span></td><td>${esc(r.model)}</td><td><span class="statusbadge ${outcome(r)==='correct'?'good':outcome(r)==='error'?'bad':''}">${esc(resultLabel(r))}</span>${caveatBadges(r.caveats)}</td><td>${seconds(r.duration_s||0)}</td><td>${r.tool_calls??'—'}</td><td>${esc(new Date(r.ts).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}))}</td></tr>`).join('');const reversed=rows.slice().reverse();$('resultRows').querySelectorAll('[data-result]').forEach(el=>{el.onclick=()=>resultDetail(reversed[+el.dataset.result]);el.onkeydown=e=>{if(e.key==='Enter')el.click()}})}
function efficiencyStats(jobs,rows){
  return jobs.map(j=>{
    const rs=rows.filter(r=>r.evaluation_id===j.id&&isFinalScore(r)&&r.status==='completed'&&r.termination!=='not_attempted'&&!['wrong_streak_limit','five_wrong_in_row'].includes(r.score_reason));
    if(!rs.length||rs.some(r=>typeof r.completion_tokens!=='number'||!Number.isFinite(r.completion_tokens)||r.completion_tokens<0))return null;
    return {name:j.model+' · '+(rs[0].node||'machine unknown')+' · '+(j.run_key||j.id).slice(0,6),model:j.model,n:rs.length,accuracy:rs.filter(r=>r.solved).length/rs.length,tokens:median(rs.map(r=>r.completion_tokens)),speed:!j.hour_timing_unknown&&scoreFor(j).elapsed_s>0?rs.length/(scoreFor(j).elapsed_s/60):null,state:j.state};
  }).filter(Boolean);
}
function drawScatter(stats){
  const omitted=stats.filter(s=>!(s.tokens>0)).length;stats=stats.filter(s=>s.tokens>0);
  const logAxis=tokenAxis(stats.map(s=>s.tokens));
  const left=80,right=1040,top=60,bottom=410,W=right-left,H=bottom-top;
  const fit=(values,fallback,minSpan,ceiling=Infinity)=>{
    if(!values.length)return fallback;
    const lo=Math.min(...values),hi=Math.max(...values),span=Math.max(hi-lo,minSpan);
    const pad=Math.max(span*.15,(span-(hi-lo))/2);
    const step=10**Math.floor(Math.log10(span/4));
    return [Math.max(0,Math.floor((lo-pad)/step)*step),Math.min(ceiling,Math.ceil((hi+pad)/step)*step)];
  };
  const tokenMin=logAxis.min,tokenMax=logAxis.max;
  const [accuracyMin,accuracyMax]=fit(stats.map(s=>s.accuracy),[0,1],.1,1);
  const x=t=>right-(Math.log10(t)-Math.log10(tokenMin))/(Math.log10(tokenMax)-Math.log10(tokenMin))*W,y=a=>bottom-(a-accuracyMin)/(accuracyMax-accuracyMin)*H,fmt=n=>Math.round(n).toLocaleString();
  const tokenGuide=logAxis.guide,accuracyGuide=(accuracyMin+accuracyMax)/2;
  const sx=x(tokenGuide),sy=y(accuracyGuide),colors=['#28674f','#4268b0','#ac6630','#98577d','#368893'];
  let html='<text x="80" y="27" fill="#505e56" font-size="14">Accuracy ↑</text>';
  const box=(bx,by,bw,bh,color)=>`<rect x="${bx}" y="${by}" width="${bw}" height="${bh}" fill="${color}"/>`;
  html+=box(left,top,sx-left,sy-top,'#fff3d9')+box(sx,top,right-sx,sy-top,'#e0f1e4')+box(left,sy,sx-left,bottom-sy,'#f9e2df')+box(sx,sy,right-sx,bottom-sy,'#e8edf8');
  html+=`<text x="${left+10}" y="${top+40}" fill="#876628" font-size="10">ACCURATE · MORE TOKENS</text><text x="${right-10}" y="${top+40}" text-anchor="end" fill="#28674f" font-size="10">ACCURATE · FEWER TOKENS ↗</text><text x="${left+10}" y="${bottom-12}" fill="#9a5048" font-size="10">LESS ACCURATE · MORE TOKENS</text><text x="${right-10}" y="${bottom-12}" text-anchor="end" fill="#506a94" font-size="10">LESS ACCURATE · FEWER TOKENS</text>`;
  for(let i=0;i<=4;i++){const accuracy=accuracyMin+(accuracyMax-accuracyMin)*i/4,yy=y(accuracy);html+=`<line x1="80" x2="1040" y1="${yy}" y2="${yy}" stroke="#ffffff" stroke-width="1.5"/><text x="64" y="${yy+5}" text-anchor="end" fill="#717b77" font-size="13">${(accuracy*100).toFixed(1)}%</text>`}
  html+=`<path d="M${sx} ${top}V${bottom}M${left} ${sy}H${right}" stroke="#9ca89e" stroke-dasharray="5 5"/>`;
  for(const tick of logAxis.ticks)html+=`<text x="${x(tick)}" y="442" text-anchor="middle" font-size="12" fill="#717b77">${tick.toLocaleString()}</text>`;
  html+='<text x="560" y="474" text-anchor="middle" font-size="14" fill="#505e56">Median output tokens per scored answer · log scale · fewer →</text>';
  const maxSpeed=Math.max(.000001,...stats.map(s=>s.speed||0));
  stats.map((s,i)=>({s,i})).sort((a,b)=>(b.s.speed||0)-(a.s.speed||0)).forEach(({s,i})=>{const color=colors[i%colors.length],px=x(s.tokens),py=y(s.accuracy),radius=s.speed?20*Math.sqrt(s.speed/maxSpeed):6;html+=`<circle cx="${px}" cy="${py}" r="${radius}" fill="${color}" fill-opacity=".75" stroke="white" stroke-width="3"><title>${esc(s.name)}: ${(s.accuracy*100).toFixed(1)}% correct, median ${fmt(s.tokens)} output tokens, ${s.n} scored answers, ${s.speed==null?'speed unavailable':s.speed.toFixed(2)+' answers/min'}</title></circle><text x="${px}" y="${py+5}" text-anchor="middle" font-size="14" font-weight="700" fill="white" stroke="${color}" stroke-width="2" paint-order="stroke" pointer-events="none">${i+1}</text>`});
  if(!stats.length)html+='<text x="560" y="220" text-anchor="middle" fill="#717b77">No scored runs with complete output-token records</text>';
  $('scatter').innerHTML=html;
  $('quadrantGuide').textContent=(omitted?`${omitted} run(s) with zero tokens omitted from the log axis. `:'')+`The token axis is logarithmic. Quadrants bisect the displayed ranges at ${(accuracyGuide*100).toFixed(1)}% accuracy and ${fmt(tokenGuide)} output tokens. Scales update with the data; these are relative regions, not pass/fail grades.`;
  $('scatterLegend').innerHTML=stats.map((s,i)=>`<div class="scatter-model"><span class="scatter-number" style="background:${colors[i%colors.length]}">${i+1}</span><div><strong>${esc(s.model)}</strong><span class="scatter-run">${esc(s.name)}</span><small>${(s.accuracy*100).toFixed(1)}% correct · median ${fmt(s.tokens)} output tokens · ${s.n} scored answers · ${s.speed==null?'speed unavailable':s.speed.toFixed(2)+' answers/min'} · ${esc(s.state)}</small></div></div>`).join('');
}

for(const id of ['resultSearch','resultSection','resultStatus'])$(id).addEventListener(id==='resultSearch'?'input':'change',()=>S&&renderResults());
function resultDetail(r){activeDetails=r;const n=r.opt_n||S.tasks.find(t=>t.id===r.task)?.options;dialog(`${r.task} · ${resultLabel(r)}`,`${r.repair_inherited?'<p class="notice">Retained from original run '+esc(r.repair_source_evaluation_id)+'. Original timing and artifacts are preserved.</p>':''}${caveatNotice(r.caveats)}<dl class="reviewgrid"><dt>Model</dt><dd>${esc(r.model)}</dd><dt>Hourglass version</dt><dd>${esc(version(r))}</dd><dt>Harness</dt><dd>${esc(r.harness==='pi'?`Frozen Pi ${r.pi_version}`:'Legacy harness')}</dd><dt>Temperature</dt><dd>${esc(r.temperature??'Not reported')} · ${esc(r.temperature_source??'Not recorded in this historical result')}</dd>${thinkingDetails(r)}<dt>Submitted answer</dt><dd><code>${esc(JSON.stringify(r.parsed_answer??{}))}</code></dd><dt>Elapsed time</dt><dd>${seconds(r.duration_s||0)}</dd><dt>Tokens</dt><dd>${r.prompt_tokens??0} input · ${r.completion_tokens??0} output</dd><dt>Tool calls</dt><dd>${r.tool_calls??0}</dd><dt>Evaluation</dt><dd>${r.mode==='numeric'?'Numeric tolerance':n?`Exact answer · ${n} options`:'Hidden verifier'}</dd></dl>${r.error?`<div class="notice error">${esc(r.error)}</div>`:''}<details><summary>Requested and reported settings</summary><h3>Requested by Hourglass</h3><pre class="previewtext">${esc(r.requested_settings?JSON.stringify(r.requested_settings,null,2):'Not captured in this historical attempt')}</pre><h3>Server-reported</h3><pre class="previewtext">${esc(r.server_settings?JSON.stringify(r.server_settings,null,2):'Not reported')}</pre><h3>User-reported run history</h3>${settingsHistory(r.user_settings||[])}<p class="help">These are dated observations, not verified effective values for this attempt.</p></details><div class="detailtabs"><button data-artifact="metrics.json">Metrics</button><button data-artifact="trace.json">Tool trace</button><button data-artifact="patch.diff">Code changes</button></div><pre id="artifact" class="previewtext">${esc(r.verified_output||'Choose an artifact above.')}</pre>`,[{label:'Close',click:()=>$('dialog').close()}]);document.querySelectorAll('[data-artifact]').forEach(b=>b.onclick=async()=>{const dir=r.artifact_dir||`results/${r.task}/${r.model}/run-${r.run}`;try{const res=await fetch('/api/file?path='+encodeURIComponent(dir+'/'+b.dataset.artifact));if(!res.ok)throw Error('Artifact not found');const text=await res.text();if(activeDetails===r)$('artifact').textContent=text||'(No changes)'}catch(e){$('artifact').textContent=e.message}})}
$('modelJson').oninput=()=>{dirty=true;$('dirtyBadge').classList.remove('hidden');$('saveStatus').textContent=''};$('discardModels').onclick=()=>{dirty=false;$('modelJson').value=S.models_json;editorBaseRevision=S.models_revision;$('dirtyBadge').classList.add('hidden');$('saveStatus').textContent='Edits discarded.'};$('saveModels').onclick=async()=>{const b=$('saveModels');b.disabled=true;$('saveStatus').textContent='Saving…';try{const r=await api('/api/models',{text:$('modelJson').value,revision:editorBaseRevision});dirty=false;checked={};$('dirtyBadge').classList.add('hidden');$('saveStatus').textContent='Saved. Previous settings backed up.';toast(`Saved; backup in ${r.backup}`);await refresh()}catch(e){$('saveStatus').textContent=e.message;toast(e.message)}finally{b.disabled=false}};$('probe').onclick=async()=>{const b=$('probe');b.disabled=true;b.textContent='Reading machine record…';try{const r=await api('/api/probe',{});if(!r.ok)throw Error(r.out);await refresh();toast('Machine record refreshed.')}catch(e){toast(e.message)}finally{b.disabled=false;b.textContent='Refresh provenance'}};
async function refresh(){if(refreshing)return;refreshing=true;try{const next=await api('/api/state');S=next;$('benchmarkVersion').textContent=`Hourglass v${S.benchmark_version} · New runs: net-hour-v3 · total points · whole-bank rounds.`;$('connectionError').classList.add('hidden');$('bankCount').textContent=S.tasks.length;$('resultCount').textContent=S.results.length;$('firstGuide').classList.toggle('hidden',S.results.length>0);$('page-bench').querySelector('h1').textContent=S.results.length?'Build your next run.':'Build your first run.';const ts=JSON.stringify(S.tasks);if(ts!==taskSignature){taskSignature=ts;for(const id of ['sectionFilter','resultSection']){const el=$(id),v=el.value;el.innerHTML='<option value="">All sections</option>'+[...new Set(S.tasks.map(t=>sectionKey(t.section)))].sort().map(s=>`<option value="${esc(s)}">${esc(sectionName(s))}</option>`).join('');el.value=v}renderLibrary()}const ms=JSON.stringify(S.model_configs);if(ms!==modelSignature){modelSignature=ms;const prev=$('model').value||store.get('model','');$('model').innerHTML=S.model_configs.map(m=>`<option value="${esc(m.name)}">${esc(m.name)}</option>`).join('');if(S.models.includes(prev))$('model').value=prev;checked={}}refreshLibraryStats();if(!dirty){$('modelJson').value=S.models_json;editorBaseRevision=S.models_revision;}modelPicker.sync();endpointHardware.sync(S.endpoint_hardware);renderBuilder();renderJobs();if(page==='results')renderResults();if(page==='current')renderCurrentQuestion();if(page==='publish'&&!$('publishFrame').getAttribute('src'))renderPublish();const p=S.provenance;$('provenance').textContent=JSON.stringify({node:p.node,chip:p.chip,ram_gb:p.ram_bytes&&!isNaN(+p.ram_bytes)?Math.round(+p.ram_bytes/2**30):undefined,python:p.python,pi_version:p.pi_version,captured_at:p.captured_at},null,2);$('lastUpdated').textContent='Connected · '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});if(S.model_errors.length){$('connectionError').textContent='Model configuration needs attention: '+S.model_errors.join('; ');$('connectionError').classList.remove('hidden')}}catch(e){$('connectionError').textContent='Cannot reach the Hourglass console. Check that its launcher is running. '+e.message;$('connectionError').classList.remove('hidden');$('lastUpdated').textContent='Disconnected'}finally{refreshing=false}}
const modelPicker=new ModelPicker({getState:()=>S,api,$,esc,dialog,refresh,toast,canOpen:()=>!!S&&!dirty});
setPage(location.hash.slice(1)||'bench');refresh();setInterval(refresh,2500);

$('copyFullLog').onclick=async()=>{
  const id=logId,b=$('copyFullLog');if(!id){toast('Open a run log first.');return}
  b.disabled=true;b.textContent='Copying…';
  try{
    const r=await fetch('/api/log/full?job='+encodeURIComponent(id));
    if(!r.ok)throw Error('The full log is not available yet.');
    const text=await r.text();
    await navigator.clipboard.writeText(text);
    toast(`Full log copied (${text.length.toLocaleString()} characters).`);
  }catch(e){toast('Could not copy: '+e.message)}
  finally{b.disabled=false;b.textContent='Copy full log'}
};

function scoreFor(job){if(job.hour_score?.score_version&&'resolved_available_points' in job.hour_score)return job.hour_score;const metadata=new Map(S.tasks.map(t=>[t.id,t]));const expected=(job.expected||job.tasks.map(task=>({task}))).map(t=>({...metadata.get(t.task),...t}));return hourScore(job,S.results,expected)}
function hourState(h){if(h.state==='unavailable'&&h.timing_note?.includes('results were reset'))return 'Results reset';return {final:'Final',in_progress:'In progress',partial:'Partial · ended before one hour',not_started:'Not started',unavailable:'Timing unavailable'}[h.state]}
function renderHourScores(){
  const jobs=allJobs();
  $('hourScoreRows').innerHTML=jobs.length?jobs.map(j=>{const h=scoreFor(j),v=n=>n===null?'—':n,w=n=>n==null?'—':Number(n).toFixed(1);return `<tr><td>${esc(j.model)}<span class="questionmeta">${h.total_questions} questions · ${esc((j.run_key||j.id).slice(0,6))}</span></td><td><strong>${(h.hourglass_score==null?'—':Number(h.hourglass_score).toFixed(1))}</strong><span class="questionmeta">${v(h.points)} correct</span></td><td>${w(h.breakdown.text.weighted_points)}</td><td>${w(h.breakdown.vision.weighted_points)}</td><td>${hourState(h)} ${caveatBadges(j.caveats)} <button class="textbutton" onclick="openPublish('${j.id}')">Record &amp; publish score</button></td></tr>`}).join(''):'<tr><td colspan="5">Start a run to record a one-hour score.</td></tr>';
}
function allJobs(){return [...S.jobs.running,...S.jobs.pending,...S.jobs.done.slice().reverse()].filter(j=>!!j.archived===archiveView)}
function renderLiveRun(){
  const jobs=allJobs();$('liveRun').classList.toggle('hidden',!jobs.length);if(!jobs.length){liveRunId=null;logId=null;$('logWrap').classList.add('hidden');return;}
  const job=jobs.find(j=>j.id===liveRunId)||jobs[0];liveRunId=job.id;
  $('liveRunSelect').innerHTML=jobs.map(j=>`<option value="${esc(j.id)}">${esc(j.run_identity?.name||j.run_details?.values?.run_name||j.run_details?.values?.model_name||j.model)} · ${j.tasks?.length===1?esc(j.tasks[0]):`${j.total_tasks??j.tasks?.length??0} questions`} · ${j.repair?'Repaired · ':''}${esc(j.state)} · ${esc(new Date(j.created*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}))} · ${esc((j.run_key||j.id).slice(0,6))}</option>`).join('');$('liveRunSelect').value=job.id;
  $('liveRunEditor').onclick=()=>openRunEditor(job.id);
  $('liveRunTitle').textContent=(job.run_identity?.name||job.run_details?.values?.run_name||job.run_details?.values?.model_name||job.model)+(job.repair?' · Repaired':'')+' · '+(job.tasks?.length===1?job.tasks[0]:`${job.total_tasks??job.tasks?.length??0} questions`);
  $('liveSettingsSummary').textContent=job.user_settings?.length?`${job.user_settings.length} user-reported settings record(s) · latest saved ${new Date(job.user_settings.at(-1).recorded_at*1000).toLocaleString()}`:'Server and hardware details are available in Run editor.';
  $('liveCaveats').innerHTML=caveatNotice(job.caveats);
  renderSpeed(job);
  const p=job.progress;
  $('liveStop').classList.toggle('hidden',job.state!=='running');$('liveStop').disabled=!!job.stop_requested;$('liveStop').textContent=job.stop_requested?'Stopping…':'Stop run';$('liveResume').classList.toggle('hidden',!job.resume?.allowed);$('liveArchive').classList.toggle('hidden',job.state==='running'||job.state==='pending');$('liveArchive').textContent=job.archived?'Restore run':'Archive run';
  if(!p){$('liveMetrics').textContent='Live statistics will appear when the updated backend is available.';return}
  const h=scoreFor(job), scoreValue=n=>n==null?'—':Number(n).toFixed(1);
  const displayedScore=h.hourglass_score,scoreLabel='Total points',forecastNote=h.state==='in_progress'?'Earned so far · one-hour clock running.':'',predicting=false;
  const scoreHelp='Total earned points minus wrong-answer penalties within one active hour. Each new round attempt counts. No area-under-curve scaling or forecast.';
  $('chartRepeats').disabled=chartView==='quadrants';$('chartRepeats').title=chartView==='quadrants'?'Accuracy and efficiency use individual measurements':'';
  const chartUrl=reportBase+'/chart.svg?job='+encodeURIComponent(job.id)+'&scope='+$('chartScope').value+'&view='+chartView+'&repeats='+$('chartRepeats').value+'&legend=none&v='+Math.floor(Date.now()/30000);
  const unavailable=h.state==='unavailable',chart=$('liveScoreChart'),chartNotice=$('liveScoreChartNotice');
  chart.hidden=unavailable||chartFailedUrl===chartUrl;chartNotice.hidden=!chart.hidden;
  chartNotice.textContent=unavailable?'The saved answers are retained, but this run’s clock could not be recovered. A timed comparison is unavailable.':'The comparison could not load. It will retry on the next chart refresh.';
  if(!unavailable)loadInlineChart(chartUrl);
  renderQuestionContext(job);
  renderTps(job);
  $('liveMetrics').innerHTML=`<div><span>${scoreLabel} <button type="button" class="metric-help" aria-label="How the Hourglass score works" data-help="${esc(scoreHelp)}">?</button></span><strong>${scoreValue(displayedScore)}</strong>${forecastNote?`<small class="score-forecast-note">${forecastNote}</small>`:''}<small>${h.points??"—"} correct · ${h.incorrect_questions} incorrect · ${h.abstained_questions||0} abstained · ${['net-hour-v1','net-hour-v2','net-hour-v3'].includes(h.scoring_policy)?'net · gross '+scoreValue(h.gross_points):'historical gross'} · ${hourState(h)} · ${h.completed_questions} completed within the hour</small></div><div><span>Scoring time remaining</span><strong>${unavailable?"—":seconds(h.remaining_s)}</strong><small>60 minutes of active time${job.question_timeout_s?' · 15 minutes per question · '+(p.timeouts||0)+' timed out':''}${job.state==='running'&&job.question_deadline_at?' · question: '+seconds(Math.max(0,job.question_deadline_at-Date.now()/1000))+' left':''}</small></div><div><span>Full-run accuracy</span><strong>${p.accuracy===null?'—':(p.accuracy*100).toFixed(1)+'%'}</strong><small>${p.correct_attempts} / ${p.scored_attempts} scored attempts, including after the hour</small></div><div><span>Active run time</span><strong>${unavailable?"—":seconds(p.elapsed_s)}</strong><small>Thinking, tools and retries included; pauses excluded</small></div>`;
  $('liveProgress').max=p.total_questions;$('liveProgress').value=p.finished_questions;
  $('liveProgressText').textContent=`Round ${job.round_number||1} · ${p.finished_questions} / ${p.total_questions} questions completed${p.not_attempted?' · '+p.not_attempted+' unattempted zeros':''}${p.errors?' · '+p.errors+' execution error'+(p.errors===1?'':'s')+' recorded':''}${job.state==='running'?(job.warmup?.status==='running'?' · Warming up model · scoring clocks have not started':' · Working on '+(job.current_task||'first question')):''}`;
  $('liveRunNotice').textContent=[h.state==='unavailable'?h.timing_note:h.elapsed_s>=3600?'The one-hour score is frozen. Any later recorded answers remain in full-run diagnostics.':'Correct questions earn 1–2 points by difficulty within the first 60 active minutes. The run stops after 60 active minutes and plays a completion chime.',job.timing_recoveries?.length?'Clock recovered from persisted shutdown evidence; completed answers retained.':null,job.error,job.resume?.version_warning,job.state==='error'&&!job.resume?.allowed?job.resume?.reason:null].filter(Boolean).join(' ');
}
$('newRun').onclick=showRunBuilder;
$('model').addEventListener('change',()=>{if(draftSourceRunId){draftSourceRunId=null;toast('Model changed; run-specific labels will not be copied.')}});

$('chartScope').onchange=$('chartRepeats').onchange=()=>renderLiveRun();
initializeChartTabs();
$('liveRunSelect').onchange=()=>{liveRunId=$('liveRunSelect').value;selectLog(liveRunId);loadLog();renderLiveRun()};
$('publishRunSelect').onchange=renderPublish;
$('liveResume').onclick=()=>reviewResume(liveRunId);
function reviewResume(id){
  const job=allJobs().find(j=>j.id===id);if(!job?.resume?.allowed)return;
  const p=job.resume;
  dialog('Resume '+job.model,`<p>Keep <strong>${p.preserved_attempts} completed attempts</strong> and retry or finish <strong>${p.remaining_attempts} attempts across ${p.remaining_questions} questions</strong>.</p><p>The current round and its saved order are retained. ${job.question_timeout_s?'15 minutes per round attempt, including tools and interrupted-resume time; timeouts score zero and advance.':'This historical run retains its original question policy.'} Previous logs and results remain available.</p>${p.version_warning?`<div class="notice">${esc(p.version_warning)}</div>`:''}`, [{label:'Back',click:()=>$('dialog').close()},{label:'Resume run',primary:true,click:async b=>{b.disabled=true;try{const r=await api('/api/resume',{job:id});liveRunId=r.job;selectLog(r.job,true);$('dialog').close();await refresh();toast('Run queued to resume.')}catch(e){toast(e.message);b.disabled=false}}}]);
}

$('liveArchive').onclick=async()=>{
  await archiveRun(liveRunId);
};
async function archiveRun(id){
  const job=allJobs().find(j=>j.id===id);if(!job)return;
  try{await api('/api/archive-run',{job:job.id,archived:!job.archived});liveRunId=null;await refresh();toast(job.archived?'Run restored.':'Run archived. Its answers, settings and logs are retained.')}catch(e){toast(e.message)}
};
function setWorkspaceView(view){
  workspaceView=view;
  if(view!=='questions'){archiveView=view==='archived';liveRunId=null;}
  document.querySelectorAll('[data-run-archive]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.runArchive===view)));
  $('questionLibrary').hidden=view!=='questions';
  for(const el of [$('liveRun'),$('firstGuide'),document.querySelector('.benchgrid'),document.querySelector('.jobssection')])el.hidden=view==='questions';
  if(S){renderJobs();if(view==='questions')renderLibrary();if(page==='results')renderResults();}
}
document.querySelectorAll('[data-run-archive]').forEach(b=>b.onclick=()=>setWorkspaceView(b.dataset.runArchive));
$('chooseQuestions').onclick=()=>{closeRunBuilder();setWorkspaceView('questions');};

function refreshLibraryStats(){
  const signature=JSON.stringify([S.results,S.tasks.map(t=>[t.id,t.task_sha,t.task_bundle_sha]),Object.values(S.jobs).flat().map(j=>j.id)]);
  if(signature===libraryHistorySignature)return;
  libraryHistorySignature=signature;
  const selectedModel=$('libraryModel').value,saved=new Set(Object.values(S.jobs).flat().map(j=>j.id));
  const models=[...new Set(S.results.filter(r=>saved.has(r.evaluation_id)).map(r=>r.model))].sort();
  $('libraryModel').innerHTML='<option value="">All models</option>'+models.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join('');
  if(models.includes(selectedModel))$('libraryModel').value=selectedModel;
  libraryStats=QuestionLibrary.summarize(S.tasks,S.results,S.jobs,$('libraryModel').value);
  renderLibrary();
}
$('libraryModel').onchange=()=>{libraryStats=QuestionLibrary.summarize(S.tasks,S.results,S.jobs,$('libraryModel').value);limit=20;renderLibrary();};
function updateLibrarySortHeaders(){
  document.querySelectorAll('[data-library-sort]').forEach(b=>{
    const active=b.dataset.librarySort===librarySort;
    b.closest('th').setAttribute('aria-sort',active?(libraryDirection==='asc'?'ascending':'descending'):'none');
    b.textContent=b.dataset.label+(active?(libraryDirection==='asc'?' ↑':' ↓'):' ↕');
  });
}
document.querySelectorAll('[data-library-sort]').forEach(b=>b.onclick=()=>{
  const key=b.dataset.librarySort;
  libraryDirection=librarySort===key?(libraryDirection==='desc'?'asc':'desc'):(key==='title'?'asc':'desc');
  librarySort=key;limit=20;renderLibrary();
});
$('libraryBankOrder').onclick=()=>{librarySort='order';limit=20;renderLibrary();};


$('liveStop').onclick=()=>stopRun(liveRunId);
async function stopRun(id){try{await api('/api/stop',{job:id});await refresh();toast('Stop requested. Completed results are retained.')}catch(e){toast(e.message)}}

function settingsHistory(records){
  return records.length?records.map(r=>`<div class="notice"><strong>User-reported · ${esc(new Date(r.recorded_at*1000).toLocaleString())}</strong><p>${r.applies_from==='run_start'?'Reported as applying from run start':'Settings changed'} · effective ${r.effective_at==null?'run start':esc(new Date(r.effective_at*1000).toLocaleString())}</p><p>${Object.entries(r.settings).map(([k,v])=>`${esc(k)}: <strong>${esc(v)}</strong>`).join(' · ')}</p>${r.note?`<p>${esc(r.note)}</p>`:''}</div>`).join(''):'<p class="help">No user-reported settings. Blank fields remain unknown.</p>';
}

function renderSpeed(job){
  const data=compareRunSpeed(S.results,job,$('speedLane').value,S.tasks),c=data.current;
  let html=c?`<p>Current: <strong>${seconds(c.seconds_per_attempt)} / attempt</strong> · ${c.attempts} completed · ${(c.accuracy*100).toFixed(1)}% correct · ${c.output_tokens_per_second.toFixed(1)} output tokens / wall second</p>`:'';
  if(!data.comparisons.length){$('liveSpeed').innerHTML=html+`<p class="help">${esc(data.reason)}</p>`;return}
  const max=Math.max(c.seconds_per_attempt,...data.comparisons.map(x=>x.seconds_per_attempt));
  html+=`<div class="speed-bar-row"><span>Current model</span><div class="speed-track"><div class="speed-bar current" style="width:${100*c.seconds_per_attempt/max}%"></div></div><strong>${seconds(c.seconds_per_attempt)}</strong></div>`;
  for(const r of data.comparisons){const ratio=r.current_speed_ratio;html+=`<div class="speed-bar-row"><span>${esc(r.model)}<small>${(r.accuracy*100).toFixed(1)}% correct · ${esc(new Date(r.ended*1000).toLocaleDateString())}</small></span><div class="speed-track"><div class="speed-bar" style="width:${100*r.seconds_per_attempt/max}%"></div></div><strong>${seconds(r.seconds_per_attempt)}</strong></div><p class="speed-ratio">Current model is <strong>${ratio.toFixed(2)}× as fast</strong> as ${esc(r.model)} on these ${c.attempts} attempts.</p>`}
  $('liveSpeed').innerHTML=html+'<p class="help">Bars show time per attempt; shorter is faster. Uses the latest matching run for each model.</p>';
}


function thinkingDetails(r){
  const t=r.thinking_settings||{},reportedDefault=t.server_reasoning_default??r.server_settings?.model?.capabilities?.reasoning?.default;
  const requests=r.requested_settings;
  const overrides=requests?.map(x=>Object.fromEntries(Object.entries(x.values||{}).filter(([k])=>['reasoning','reasoning_effort'].includes(k))));
  const sent=overrides?.length?[...new Set(overrides.map(x=>Object.keys(x).length?JSON.stringify(x):'No override — server default'))].join('; '):'Not captured';
  return `<dt>Pi thinking level</dt><dd>${esc(t.pi_thinking_level??'Not captured for this attempt')}<small>Pi’s internal setting; does not establish the server’s reasoning level.</small></dd><dt>Reasoning sent</dt><dd>${esc(sent)}</dd><dt>Server reasoning default</dt><dd>${esc(reportedDefault??'Not reported')}<small>Advertised default; effective reasoning level is not reported.</small></dd><dt>Thinking content observed</dt><dd>${t.thinking_content_observed===true?'Yes':t.thinking_content_observed===false?'No thinking content received':'Not captured'}</dd>`;
}


function questionReviewFlag(id){
  const flag=QUESTION_REVIEW_FLAGS[id];if(!flag)return '';
  const label=flag.status==='setup_candidate'?'Setup-check candidate':'Cut candidate';
  return ` <span class="question-review-flag">${label} <button type="button" class="metric-help" aria-label="Why ${esc(id)} is flagged" data-help="${esc(flag.reason+' Provisional review flag only. This question remains included and scored normally. Compare the 27B, 9B and 0.8B results before deciding.')}" >?</button></span>`;
}


async function renderCurrentQuestion(){
  const job=S?.jobs.running[0],tid=job?.current_task;
  if(!tid){currentQuestionKey='';currentQuestionRequest++;$('currentQuestionStatus').textContent=job?'Waiting for the first question…':'No question is running right now.';$('currentQuestionContent').classList.add('hidden');return}
  const finishedRepeats=(S.results||[]).filter(r=>r.evaluation_id===job.id&&r.task===tid).map(r=>r.run).join(',');
  const key=job.id+':'+tid+':'+finishedRepeats,changed=key!==currentQuestionKey;
  currentQuestionKey=key;const request=++currentQuestionRequest;
  if(changed){$('currentQuestionStatus').textContent=`${job.model} · ${tid} · Loading question…`;$('currentQuestionContent').classList.add('hidden')}
  try{
    let t=await api('/api/task?id='+encodeURIComponent(tid)+'&job='+encodeURIComponent(job.id));
    if(!t.presentation){
      // A staged UI can attach to an older active controller without a restart.
      // Only an exact, sanitized run preview is accepted as a fallback.
      if(job.repeat!==1)throw Error('Exact run options need an updated controller for repeated questions.');
      const attached=await api('/run-previews/'+encodeURIComponent(job.id)+'/'+encodeURIComponent(tid)+'.json');
      if(attached.presentation?.job!==job.id||attached.id!==tid||attached.presentation?.exact!==true)throw Error('Exact run options are not available yet.');
      t=attached;
    }
    if(t.presentation?.job!==job.id||t.id!==tid||t.presentation?.exact!==true)throw Error('Exact run options are not available yet.');
    const display=t.presentation.transport==='attachment'&&t.vision?await api('/question-assets/'+encodeURIComponent(tid)+'/display.json'):{images:t.images||[]};
    if(request!==currentQuestionRequest||S?.jobs.running[0]?.current_task!==tid||S?.jobs.running[0]?.id!==job.id)return;
    $('currentQuestionStatus').textContent=`${job.model} · ${tid} · Model’s actual question and options`;
    $('currentQuestionTitle').textContent=t.title||tid;$('currentQuestionPrompt').textContent=t.prompt;
    $('currentQuestionImages').innerHTML=(display.images||[]).map(url=>`<img src="${esc(url)}" alt="Chart supplied with ${esc(tid)}" loading="lazy">`).join('');
    const options=t.options.map(o=>typeof o==='string'?o:`${o.id} — ${o.text}`);
    $('currentOptionsHeading').textContent=options.length?`Answer options (${options.length})`:'Answer format';
    $('currentQuestionOptions').innerHTML=options.length?options.map(o=>`<li>${esc(o)}</li>`).join(''):'<li>This question uses a numeric answer or a tool submission; follow the prompt above.</li>';
    $('currentQuestionFiles').innerHTML=(t.files.length?`<p class="help">Workspace files: ${esc(t.files.join(', '))}</p>`:'')+workspaceFilesHtml(t);$('currentQuestionContent').classList.remove('hidden');
  }catch(e){if(request!==currentQuestionRequest)return;currentQuestionKey='';$('currentQuestionStatus').textContent='Could not load the current question: '+e.message}
}

function renderTps(job){$('liveTps').innerHTML=renderTpsPanel(job.telemetry||{},job.state);}

initializeQuestionContext();

function caveatBadges(caveats=[]){return caveats.map(c=>`<span class="statusbadge" style="background:#fff1cf;color:#805500" title="${esc(c.message)}">⚠ ${esc(c.label)}</span>`).join(' ')}
function caveatNotice(caveats=[]){return caveats.map(c=>`<div class="notice" style="border-left:4px solid #b57b11;background:#fff8e8"><strong>⚠ ${esc(c.label)}${c.questions?.length?' · '+esc(c.questions.join(', ')):''}</strong><p>${esc(c.message)}</p></div>`).join('')}
const caveatPanel=document.createElement('div');caveatPanel.id='liveCaveats';$('liveMetrics').before(caveatPanel);
function isFinalScore(r){if(r.status!=='completed')return false;return !['net-hour-v1','net-hour-v2','net-hour-v3'].includes(r.scoring_policy)||r.solved||!['unsupported_vision','abstained','question_timeout','not_attempted','turn_limit','stopped','unfinished','wrong_streak_limit','five_wrong_in_row'].includes(r.score_reason)&&!['not_attempted','abstained','stopped','unfinished','turn_limit'].includes(r.termination)}

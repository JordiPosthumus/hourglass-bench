'use strict';
function questionAt(model, seconds){
  const spans=model.spans||[],at=seconds==null?model.end_s:seconds;
  let span=spans.find(p=>at>=p.start_s&&at<p.end_s);
  if(!span&&at>=model.end_s)span=spans.at(-1);
  if(!span)return {summary:at===0?'Run starting':'No recorded question at this time',task:'',duration:0,status:at>model.end_s?'Run ended':'Not started'};
  const duration=Math.max(0,Math.min(at,span.end_s)-span.start_s);
  const status=at<span.end_s?'Working then':span.status;
  return {...span,duration,status};
}
function longestQuestion(model){
  return (model.spans||[]).reduce((best,p)=>!best||p.end_s-p.start_s>best.end_s-best.start_s?p:best,null);
}
let questionContextData=null,questionContextKey='',questionContextTime=null,questionContextHover=null,questionContextSelection='';
function renderQuestionContextRows(){
  const body=document.getElementById('questionContextRows');if(!body||!questionContextData)return;
  const selected=questionContextHover??questionContextTime;
  const opened=new Set([...body.querySelectorAll('details[open]')].map(x=>x.dataset.model));
  body.innerHTML=questionContextData.models.map(model=>{
    const point=model.members?{task:'',summary:'Expand for individual measurements'}:questionAt(model,selected),name=model.display_name||model.model;
    return `<tr><td><details data-model="${esc(model.id)}" ${opened.has(model.id)?'open':''}><summary><span class="model-line" style="--model-color:${esc(model.color)}"></span><span class="compact-model" title="${esc(name)}">${esc(name)}</span>${model.current?'<span class="current-dot" title="Current run">LIVE</span>':''}</summary><div class="model-disclosure">${esc(name)}${name!==model.model?'<br>'+esc(model.model):''}<br>${esc(model.hardware)}<br>${esc(model.rules)}<br>${Number(model.points).toFixed(2)} points · ${model.members?model.members.map(m=>`<p>${esc(m.run_date?new Date(m.run_date).toLocaleString():m.id.slice(0,8))} · ${Number(m.points).toFixed(2)} points · ${esc(questionAt(m,selected).summary)} <button type="button" class="textbutton" data-view-measurement="${esc(m.id)}">View run</button> <button type="button" class="textbutton" data-edit-configuration="${esc(m.id)}">Edit name</button></p>`).join(''):`<button type="button" class="textbutton" data-edit-configuration="${esc(model.id)}">Edit name</button>`}</div></details></td><td><span class="context-task">${esc(point.task)}</span>${esc(point.summary)}</td></tr>`;
  }).join('');
  body.querySelectorAll('[data-view-measurement]').forEach(b=>b.onclick=()=>{liveRunId=b.dataset.viewMeasurement;selectLog(liveRunId);loadLog();renderLiveRun()});
  body.querySelectorAll('[data-edit-configuration]').forEach(b=>b.onclick=()=>openRunEditor(b.dataset.editConfiguration));
  document.getElementById('questionContextMode').textContent=selected==null?'Current or last question':`Question at ${seconds(selected)} active time`;
  document.getElementById('questionTime').value=selected==null?Math.min(3600,Math.max(...questionContextData.models.map(m=>m.end_s),0)):selected;
  document.getElementById('questionTime').setAttribute('aria-valuetext',selected==null?'Showing each model’s current or last question':seconds(selected)+' active time');
  document.getElementById('questionFollow').disabled=questionContextTime==null;
}
function renderQuestionContext(job){
  const panel=document.getElementById('questionContext');if(!panel)return;
  panel.hidden=document.getElementById('chartView').value!=='comparison';if(panel.hidden)return;
  const selection=job.id+'|'+document.getElementById('chartScope').value+'|'+document.getElementById('chartRepeats').value;
  if(selection!==questionContextSelection){questionContextData=null;questionContextSelection=selection;questionContextTime=null;questionContextHover=null;document.getElementById('questionContextRows').innerHTML='<tr><td colspan="2">Loading question context…</td></tr>'}
  const key=selection+'|'+Math.floor(Date.now()/10000);
  if(key===questionContextKey){renderQuestionContextRows();return}
  questionContextKey=key;
  fetch(reportBase+'/api/question-context?job='+encodeURIComponent(job.id)+'&scope='+document.getElementById('chartScope').value+'&repeats='+document.getElementById('chartRepeats').value).then(async response=>{
    if(!response.ok)throw Error('Question context needs the updated controller. It will appear after the next restart.');
    const data=await response.json();if(questionContextKey!==key)return;
    if(!Array.isArray(data.models))throw Error('Question context is unavailable.');
    questionContextData=data;renderQuestionContextRows();
  }).catch(error=>{if(questionContextKey===key&&!questionContextData)document.getElementById('questionContextRows').innerHTML=`<tr><td colspan="2">${esc(error.message)}</td></tr>`});
}
function initializeQuestionContext(){
  const slider=document.getElementById('questionTime'),chart=document.getElementById('liveScoreChart');
  slider.oninput=()=>{questionContextTime=Number(slider.value);questionContextHover=null;renderQuestionContextRows()};
  document.getElementById('questionFollow').onclick=()=>{questionContextTime=null;questionContextHover=null;renderQuestionContextRows()};
  chart.addEventListener('pointermove',event=>{
    if(!questionContextData||document.getElementById('chartView').value!=='comparison')return;
    const box=chart.getBoundingClientRect(),x=(event.clientX-box.left)/box.width*1100,y=(event.clientY-box.top)/box.height*660;
    questionContextHover=x>=82&&x<=1030&&y>=132&&y<=560?(x-82)/(1030-82)*3600:null;
    renderQuestionContextRows();
  });
  chart.addEventListener('pointerleave',()=>{questionContextHover=null;renderQuestionContextRows()});
}
if(typeof module!=='undefined')module.exports={questionAt,longestQuestion};

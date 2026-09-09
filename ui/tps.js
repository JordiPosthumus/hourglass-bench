'use strict';
function renderTpsPanel(data, state, now=Date.now()/1000){
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const samples=(data.samples||[]).filter(s=>Number.isFinite(s.tps)&&Number.isFinite(s.at));
  const latest=samples.at(-1),status=data.status||(data.samples||[]).slice().reverse().find(s=>s.phase==='telemetry_status');
  const age=latest?Math.max(0,now-latest.at):null,statusAge=status?Math.max(0,now-status.at):Infinity;
  const tool=data.phase==='tool',error=status?.error||data.error;
  const eventAge=status?.last_server_event_at==null?Infinity:Math.max(0,now-status.last_server_event_at);
  const fresh=state==='running'&&age!==null&&age<=10&&!tool&&!error&&(!status||statusAge<=6&&status.server_phase==='decode'&&status.attribution!=='ambiguous');
  const overlapKnown=state==='running'&&statusAge<=6&&eventAge<=10&&!error&&Number.isInteger(status?.observed_requests);
  const overlap=overlapKnown?status.observed_requests:null;
  const phase=tool?'Tool execution':fresh?'Decode':statusAge<=6?status?.server_phase||data.phase:data.phase;
  const ago=seconds=>seconds<60?`${Math.floor(seconds)}s ago`:`${Math.floor(seconds/60)}m ${Math.floor(seconds%60)}s ago`;
  const headline=latest?`${latest.tps.toFixed(1)} <span>tokens/s</span>`:'Unavailable';
  const measurement=latest?`${fresh?'Live':'Last measured'} decode${latest.window_s?` · ${latest.window_s}s window`:''} · ${ago(age)}`:(error||'No measured decode samples. The telemetry source may not be connected.');
  const contention=overlap===null?'Unknown':overlap>1?'Overlap observed':'No overlap observed';
  let html=`<div class="telemetry-summary"><div><strong>${headline}</strong><p>${escape(measurement)}</p></div><div><strong>${overlap===null?'—':overlap} <span>observed request${overlap===1?'':'s'}</span></strong><p>${escape(contention)}${status&&(statusAge>6||eventAge>10)?' · no fresh server events':''}</p></div><div><strong class="telemetry-phase">${escape(phase||'No live phase')}</strong><p>${escape(status?.source||latest?.source||'Server log')} ${latest?.slot!==undefined?`· slot ${latest.slot}`:''}${latest?.request_avg_tps!==undefined?` · request average ${latest.request_avg_tps.toFixed(1)} t/s`:''}</p></div></div>`;
  html+=`<p class="help">${escape(status?.model_id||latest?.model_id||'')}${status?.model_id||latest?.model_id?' · ':''}Request counts cover the observed server only. Other GPU workloads are not measured.${status?.attribution==='ambiguous'?' Interleaved model requests prevent reliable attribution.':''}${error?' '+escape(error):''}</p>`;
  if(!samples.length)return html;
  const first=samples[0].at,last=samples.at(-1).at,max=Math.max(30,...samples.map(s=>s.tps));
  const x=t=>45+(t-first)/Math.max(1,last-first)*700,y=v=>155-v/max*120;
  const paths=[];let current=[];
  for(const sample of samples){const previous=current.at(-1);if(previous&&(sample.at-previous.at>10||sample.request_id!==previous.request_id||sample.slot!==previous.slot)){paths.push(current);current=[]}current.push(sample)}
  if(current.length)paths.push(current);
  html+=`<svg viewBox="0 0 800 185" role="img" aria-label="Measured decode tokens per second; separate lines for requests and gaps" style="width:100%;max-height:230px"><path d="M45 30V155H745" fill="none" stroke="#9aa9a0"/><text x="2" y="40" font-size="12">${max.toFixed(0)}</text><text x="15" y="155" font-size="12">0</text>${paths.map(path=>path.length===1?`<circle cx="${x(path[0].at).toFixed(1)}" cy="${y(path[0].tps).toFixed(1)}" r="2" fill="#207c59"/>`:`<polyline fill="none" stroke="#207c59" stroke-width="2" points="${path.map(s=>x(s.at).toFixed(1)+','+y(s.tps).toFixed(1)).join(' ')}"/>`).join('')}<text x="45" y="180" font-size="12">${escape(new Date(first*1000).toLocaleTimeString())}</text><text x="670" y="180" font-size="12">${escape(new Date(last*1000).toLocaleTimeString())}</text></svg>`;
  return html;
}
if(typeof module!=='undefined')module.exports={renderTpsPanel};

'use strict';
const ForecastTarget=(()=>{
  function position(value,right,ticks){
    if(!Number.isFinite(value)||!Number.isFinite(right)||ticks.length<2)return null;
    const sorted=ticks.slice().sort((a,b)=>a.value-b.value),lo=sorted[0],hi=sorted.at(-1);
    if(!(hi.value>lo.value)||![lo.y,hi.y].every(Number.isFinite))return null;
    const raw=lo.y+(value-lo.value)/(hi.value-lo.value)*(hi.y-lo.y);
    return {x:right,y:Math.max(hi.y,Math.min(lo.y,raw)),outside:value>hi.value?'above':value<lo.value?'below':null};
  }
  function render(chart,view){
    const svg=chart.querySelector('svg');if(!svg)return;
    svg.querySelector('[data-forecast-target]')?.remove();
    if(view!=='comparison'||!chart.dataset.forecast)return;
    const value=Number(chart.dataset.forecast),right=Number(svg.getAttribute('data-plot-right'));
    if(!svg.hasAttribute('data-plot-right'))return;
    // Read the rendered score axis, including negative scales and resized charts.
    const labels=[...svg.querySelectorAll('text[text-anchor="end"]')].filter(t=>Number.isFinite(Number(t.textContent))&&Number(t.getAttribute('x'))<right);
    const axisX=Math.min(...labels.map(t=>Number(t.getAttribute('x'))));
    const ticks=labels.filter(t=>Number(t.getAttribute('x'))===axisX).map(t=>({value:Number(t.textContent),y:Number(t.getAttribute('y'))-4}));
    const point=position(value,right,ticks);if(!point)return;
    const ns='http://www.w3.org/2000/svg',g=document.createElementNS(ns,'g');
    g.setAttribute('data-forecast-target','');g.setAttribute('transform',`translate(${point.x} ${point.y})`);
    g.setAttribute('tabindex','0');g.setAttribute('role','img');
    const label=`Predicted final score: ${value.toFixed(1)} points${point.outside?' · '+point.outside+' chart scale':''} (estimate)`;
    g.setAttribute('aria-label',label);
    const title=document.createElementNS(ns,'title');title.textContent=label;g.append(title);
    const circle=document.createElementNS(ns,'circle');circle.setAttribute('r','7');circle.setAttribute('fill','white');circle.setAttribute('stroke','#26735b');circle.setAttribute('stroke-width','2');g.append(circle);
    const cross=document.createElementNS(ns,'path');cross.setAttribute('d','M-11 0H11 M0 -11V11');cross.setAttribute('stroke','#26735b');cross.setAttribute('stroke-width','1.5');g.append(cross);
    if(point.outside){const arrow=document.createElementNS(ns,'path'),d=point.outside==='above'?-1:1;arrow.setAttribute('d',`M-4 ${d*15}L0 ${d*20}L4 ${d*15}`);arrow.setAttribute('fill','none');arrow.setAttribute('stroke','#26735b');g.append(arrow);}
    svg.append(g);
  }
  return {position,render};
})();
if(typeof module!=='undefined')module.exports=ForecastTarget;

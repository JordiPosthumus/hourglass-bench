'use strict';
let chartRequestKey='';
function initializeChartTabs(){
  const tabs=[...document.querySelectorAll('[data-chart-view]')];
  const activate=tab=>{
    chartView=tab.dataset.chartView;
    for(const item of tabs){item.setAttribute('aria-selected',String(item===tab));item.tabIndex=item===tab?0:-1}
    document.getElementById('chartPanel').setAttribute('aria-labelledby',tab.id);
    renderLiveRun();
  };
  for(const tab of tabs){
    tab.onclick=()=>activate(tab);
    tab.onkeydown=event=>{
      let index=tabs.indexOf(tab);
      if(event.key==='ArrowRight')index=(index+1)%tabs.length;
      else if(event.key==='ArrowLeft')index=(index+tabs.length-1)%tabs.length;
      else if(event.key==='Home')index=0;
      else if(event.key==='End')index=tabs.length-1;
      else return;
      event.preventDefault();tabs[index].focus();activate(tabs[index]);
    };
  }
  // Keep the existing speed chart available through the same visible tabs.
  const throughput=document.getElementById('liveTps')?.closest('section');
  if(throughput){throughput.id='throughputChartPanel';throughput.hidden=true;document.getElementById('chartPanel').append(throughput)}
  const resultTabs=[...document.querySelectorAll('[data-result-view]')];
  for(const button of resultTabs){button.onclick=()=>{for(const item of resultTabs){item.setAttribute('aria-selected',String(item===button));item.tabIndex=item===button?0:-1;document.getElementById(item.dataset.resultView).hidden=item!==button}};button.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const index=e.key==='Home'?0:e.key==='End'?resultTabs.length-1:(resultTabs.indexOf(button)+(e.key==='ArrowRight'?1:resultTabs.length-1))%resultTabs.length;resultTabs[index].focus();resultTabs[index].click()};}
  const speed=document.getElementById('liveSpeed')?.closest('section');
  if(speed){speed.id='speedChartPanel';speed.hidden=true;document.getElementById('chartPanel').append(speed)}
}
async function loadInlineChart(url){
  const chart=document.getElementById('liveScoreChart');
  const speed=document.getElementById('speedChartPanel');
  if(speed)speed.hidden=chartView!=='speed';
  const throughput=document.getElementById('throughputChartPanel');if(throughput)throughput.hidden=chartView!=='throughput';
  if(['speed','throughput'].includes(chartView)){chart.hidden=true;document.getElementById('liveScoreChartNotice').hidden=true;chartRequestKey='';return}
  if(chartRequestKey===url)return;
  chartRequestKey=url;
  try{
    const response=await fetch(url);if(!response.ok)throw Error('Chart unavailable');
    const doc=new DOMParser().parseFromString(await response.text(),'image/svg+xml');
    if(chartRequestKey!==url)return;
    const svg=doc.documentElement;
    if(svg.localName!=='svg'||doc.querySelector('parsererror'))throw Error('Invalid chart');
    // Reports are generated locally; keep embedding passive even if malformed.
    svg.querySelectorAll('script,foreignObject,iframe,object').forEach(x=>x.remove());
    for(const node of [svg,...svg.querySelectorAll('*')])for(const attr of [...node.attributes]){
      if(/^on/i.test(attr.name)||/href$/i.test(attr.name))node.removeAttribute(attr.name);
    }
    chart.replaceChildren(document.importNode(svg,true));chart.hidden=false;ForecastTarget.render(chart,chartView);
  }catch(error){
    if(chartRequestKey!==url)return;
    chartRequestKey='';chart.hidden=true;
    const notice=document.getElementById('liveScoreChartNotice');notice.hidden=false;notice.textContent='The chart could not load. It will retry automatically.';
  }
}

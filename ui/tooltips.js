'use strict';
(()=>{
  const tip=document.createElement('div');tip.id='metric-tooltip';tip.className='metric-tooltip';tip.setAttribute('role','tooltip');tip.hidden=true;document.body.append(tip);
  let active=null;
  function hide(){if(active)active.removeAttribute('aria-describedby');active=null;tip.hidden=true}
  function show(button){
    if(active!==button)hide();active=button;button.setAttribute('aria-describedby',tip.id);tip.textContent=button.dataset.help;tip.hidden=false;
    const r=button.getBoundingClientRect(),width=tip.offsetWidth,height=tip.offsetHeight;
    tip.style.left=Math.max(8,Math.min(r.left,window.innerWidth-width-8))+'px';
    tip.style.top=Math.max(8,r.bottom+height+12<window.innerHeight?r.bottom+8:r.top-height-8)+'px';
  }
  document.addEventListener('pointerover',e=>{const b=e.target.closest?.('.metric-help');if(b)show(b)});
  document.addEventListener('pointerout',e=>{if(e.target.closest?.('.metric-help')&&!e.relatedTarget?.closest?.('.metric-help')&&!tip.contains(e.relatedTarget)&&document.activeElement!==active)hide()});
  tip.addEventListener('pointerleave',()=>{if(document.activeElement!==active)hide()});
  document.addEventListener('focusin',e=>{if(e.target.matches('.metric-help'))show(e.target)});
  document.addEventListener('focusout',e=>{if(e.target===active)hide()});
  document.addEventListener('click',e=>{const b=e.target.closest?.('.metric-help');if(b)show(b);else if(!tip.contains(e.target))hide()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')hide()});
  window.addEventListener('resize',hide);document.addEventListener('scroll',hide,true);
})();

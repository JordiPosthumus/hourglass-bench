 'use strict';
function tokenAxis(values){
  values=values.filter(v=>typeof v==='number'&&Number.isFinite(v)&&v>0);
  const low=values.length?Math.floor(Math.log10(Math.min(...values))):0;
  const high=values.length?Math.max(low+1,Math.ceil(Math.log10(Math.max(...values)))):3;
  const ticks=[];
  for(let e=low;e<=high;e++)for(const m of (high-low<=3?[1,2,5]:[1])){const v=m*10**e;if(v>=10**low&&v<=10**high)ticks.push(v)}
  return {min:10**low,max:10**high,ticks,guide:10**((low+high)/2)};
}
if(typeof module!=='undefined')module.exports={tokenAxis};

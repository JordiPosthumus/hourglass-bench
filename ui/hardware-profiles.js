"use strict";
window.EndpointHardware = class {
  constructor({getModel,openSettings}) {
    this.getModel=getModel;this.openSettings=openSettings;this.el=id=>document.getElementById(id);
    this.el('hardwareModel').onchange=()=>this.fill();
    this.el('hardwareLabel').oninput=()=>{
      try {const doc=JSON.parse(this.el('modelJson').value),m=doc.models.find(m=>m.name===this.el('hardwareModel').value);if(!m)return;
        m.hardware=this.el('hardwareLabel').value;this.el('modelJson').value=JSON.stringify(doc,null,2);this.el('modelJson').dispatchEvent(new Event('input'));
      }catch(e){this.el('saveStatus').textContent='Fix the JSON before editing hardware.'}
    };
  }
  sync(data){this.data=data;this.fill()}
  fill(){
    try {const models=JSON.parse(this.el('modelJson').value).models,select=this.el('hardwareModel'),old=select.value||this.getModel()?.name;
      select.replaceChildren(...models.map(m=>new Option(m.name,m.name)));if(models.some(m=>m.name===old))select.value=old;
      const m=models.find(m=>m.name===select.value);const value=m?.hardware??this.data?.endpoints?.find(e=>e.base_url===m?.base_url)?.profile?.label??'';if(this.el('hardwareLabel').value!==value)this.el('hardwareLabel').value=value;
    }catch(e){}
  }
  summary(){const m=this.getModel();return m?.hardware||this.data?.endpoints?.find(e=>e.base_url===m?.base_url)?.profile?.label||'This computer · set hardware for an SSH tunnel'}
  open(){this.openSettings();this.el('hardwareModel').value=this.getModel()?.name;this.fill();this.el('hardwareLabel').focus();this.el('hardwareLabel').scrollIntoView({block:'center'})}
};

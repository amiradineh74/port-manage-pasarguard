'use strict';
const $=id=>document.getElementById(id);
let state=null;
let selectedProvider='__all__';
const fmt=n=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(n||0);
const traffic=n=>(n/1e9>=1?fmt(n/1e9)+' GB':fmt(n/1e6)+' MB');
const isRial=()=>['ریال','Rial','IRR'].includes(state?.currency);
const unit=()=>isRial()?'ریال':'تومان';
const multiplier=()=>isRial()?10:1;
const money=n=>fmt((n||0)*multiplier())+' '+unit();
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function age(s){if(!s)return '—'; const dt=new Date(s);return dt.toLocaleString('fa-IR',{timeZone:state.timezone,dateStyle:'short',timeStyle:'short'});}

function aggregateSeries(provider,period){
 const rows=(period==='hourly'?state.hourly_by_provider:state.daily_by_provider)||[];
 const byTime=new Map();
 for(const r of rows){
  if(provider!=='__all__'&&r.provider!==provider)continue;
  const v=byTime.get(r.period)||{period:r.period,down:0,up:0,billed:0,cost:0,historical_cost:0};
  for(const key of ['down','up','billed','cost','historical_cost'])v[key]+=Number(r[key]||0);
  byTime.set(r.period,v);
 }
 return [...byTime.values()].sort((a,b)=>a.period.localeCompare(b.period));
}
function drawTrend(target,points,kind){
 const el=$(target);
 if(!points.length){el.textContent='برای این بازه اطلاعاتی ثبت نشده است.';return;}
 const w=1000,h=265,left=57,right=28,top=20,bottom=55;
 const keys=kind==='traffic'?['down','up']:['cost'];
 const values=keys.flatMap(key=>points.map(r=>kind==='traffic'?r[key]/1e9:r[key]*multiplier()));
 const max=Math.max(0.0001,...values)*1.12;
 const xs=i=>left+(w-left-right)*(points.length===1?.5:i/(points.length-1));
 const ys=value=>h-bottom-(h-bottom-top)*value/max;
 let grid='';
 for(let i=0;i<=4;i++){
   const val=max*i/4,y=ys(val);
   grid+='<line x1="'+left+'" y1="'+y.toFixed(2)+'" x2="'+(w-right)+'" y2="'+y.toFixed(2)+'" stroke="#294059"/>';
   const label=kind==='traffic'?fmt(val)+' GB':fmt(val)+' '+unit();
   grid+='<text x="'+(left-7)+'" y="'+(y+4).toFixed(2)+'" text-anchor="end" fill="#9cafc5" font-size="12">'+escapeHtml(label)+'</text>';
 }
 const step=Math.max(1,Math.ceil(points.length/7));
 for(let i=0;i<points.length;i+=step){
   grid+='<text x="'+xs(i).toFixed(1)+'" y="'+(h-20)+'" text-anchor="middle" fill="#9cafc5" font-size="12">'+
     escapeHtml(points[i].period.slice(5).replace('T',' '))+'</text>';
 }
 const colors=['#62aefe','#42d5bd'];
 const paths=keys.map((key,j)=>{
  const coords=points.map((p,i)=>({x:xs(i),y:ys(kind==='traffic'?p[key]/1e9:p[key]*multiplier())}));
  const d=coords.map((c,i)=>(i?'L':'M')+c.x.toFixed(1)+' '+c.y.toFixed(1)).join(' ');
  const dots=coords.map(c=>'<circle cx="'+c.x.toFixed(1)+'" cy="'+c.y.toFixed(1)+'" r="3" fill="'+colors[j]+'"/>').join('');
  return '<path d="'+d+'" fill="none" stroke="'+colors[j]+'" stroke-width="3" stroke-linejoin="round"/>'+dots;
 }).join('');
 el.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+(kind==='traffic'?'روند مصرف':'هزینه تاریخی')+'">'+grid+paths+'</svg>';
}
function renderProviderPanels(){
 if(!state)return;
 const current=selectedProvider==='__all__'?state.total:state.providers[selectedProvider];
 if(!current){selectedProvider='__all__';return renderProviderPanels();}
 $('down').textContent=traffic(current.down);
 $('up').textContent=traffic(current.up);
 $('billed').textContent=traffic(current.billed);
 $('cost').textContent=money(current.cost);
 $('historical-cost').textContent='هزینه ثبت‌شده قبلی: '+money(current.historical_cost);
 const allLabel='همه ارائه‌دهنده‌ها';
 $('selected-provider-title').textContent='روند مصرف — '+(selectedProvider==='__all__'?allLabel:selectedProvider);
 $('provider-detail').textContent=(selectedProvider==='__all__'?'آمار تجمیعی تمام ارائه‌دهنده‌ها':('آمار اختصاصی '+selectedProvider))+
    ' | دانلود: '+traffic(current.down)+' | آپلود: '+traffic(current.up)+
    ' | هزینه با نرخ فعلی: '+money(current.cost)+' | هزینه ثبت‌شده قبلی: '+money(current.historical_cost);
 const entries=[['__all__',state.total],...Object.entries(state.providers).sort((a,b)=>b[1].cost-a[1].cost)];
 $('providers').innerHTML=entries.map(([name,v])=>{
  const active=name===selectedProvider;
  const title=name==='__all__'?allLabel:name;
  return '<button type="button" class="provider provider-button '+(active?'selected':'')+
    '" data-provider="'+escapeHtml(name)+'" aria-pressed="'+active+'"><strong>'+
    escapeHtml(title)+'</strong><small>دانلود: '+traffic(v.down)+' · آپلود: '+traffic(v.up)+
    '</small><small>مصرف مشمول هزینه: '+traffic(v.billed)+
    '</small><small>هزینه با نرخ فعلی: '+money(v.cost)+
    '</small><small>هزینه ثبت‌شده قبلی: '+money(v.historical_cost)+'</small></button>';
 }).join('');
 document.querySelectorAll('.provider-button').forEach(button=>button.addEventListener('click',()=>{
   selectedProvider=button.dataset.provider;render();
 }));
 const scale=$('chart-scale').value;
 const hourlyAllowed=Boolean(state.hourly_available);
 const hourly=scale==='hourly'?hourlyAllowed:(scale==='auto'&&hourlyAllowed&&
    ($('from').value===$('to').value));
 const trend=aggregateSeries(selectedProvider,hourly?'hourly':'daily');
 drawTrend('chart',trend,'traffic');
 $('traffic-chart-caption').textContent=(hourly?'نمای ساعتی':'نمای روزانه')+
   (scale==='hourly'&&!hourlyAllowed?'؛ بازه انتخابی بزرگ است، نمای روزانه نمایش داده می‌شود':'');
 drawTrend('cost-chart',aggregateSeries(selectedProvider,'daily'),'cost');
}

function render(){if(!state)return;
 $('title').textContent=state.title;
 const lr=state.last_run;
 $('status').className='notice'+(lr&&JSON.parse(lr.errors_json).length?' warn':'');
 $('status').textContent=lr?'آخرین نمونه‌برداری: '+age(lr.collected_at)+' | تعداد نمونه: '+fmt(lr.sample_count)+(JSON.parse(lr.errors_json).length?' | هشدار: '+JSON.parse(lr.errors_json).join('، '):''):'هنوز نمونه‌ای ثبت نشده؛ یک بار دستور collect را اجرا کنید.';
 renderProviderPanels();
 const q=$('search').value.trim().toLowerCase();
 const ports=state.ports.filter(p=>(selectedProvider==='__all__'||(p.provider||'بدون ارائه‌دهنده')===selectedProvider)&&(p.enabled||$('show_hidden').checked)&&[p.node_name,p.port,p.title,p.provider,p.tag].join(' ').toLowerCase().includes(q));
 $('ports').innerHTML=ports.map(p=>`<tr class="${p.enabled?'':'muted'}"><td><strong>${escapeHtml(p.node_name)}</strong><span class="sub">پورت ${p.port} · نود ${p.node_id}</span></td><td>${escapeHtml(p.title||'بدون نام دلخواه')}<span class="sub">${escapeHtml(p.provider||'تعرفه تعیین نشده')} · <span class="tag">${escapeHtml(p.tag)}</span></span></td><td>${traffic(p.down)}</td><td>${traffic(p.up)}</td><td class="money">${money(p.cost)}<span class="sub">قبلی: ${money(p.historical_cost)}</span></td><td>${age(p.last_seen)}</td><td><button class="editbtn" data-nid="${p.node_id}" data-port="${p.port}">ویرایش</button></td></tr>`).join('')||'<tr><td colspan="7">پورتی پیدا نشد.</td></tr>';
 document.querySelectorAll('.editbtn').forEach(btn=>btn.addEventListener('click',()=>openEdit(Number(btn.dataset.nid),Number(btn.dataset.port))));
 $('export').href='/api/export.csv?'+new URLSearchParams({from:$('from').value,to:$('to').value});
}


function checkedPorts(form){
 return [...form.querySelectorAll('input.port-box:checked')].map(x=>Number(x.value)).sort((a,b)=>a-b);
}
function syncManualInput(form){
 form.querySelector('.port-manual').value=checkedPorts(form).join(',');
}
function parseManualPorts(form){
 const raw=form.querySelector('.port-manual').value.trim();
 if(!raw)return [];
 const parts=raw.split(/[,،\s]+/).filter(Boolean);
 const available=new Set([...form.querySelectorAll('input.port-box')].map(x=>Number(x.value)));
 const picked=parts.map(v=>Number(v));
 if(picked.some(n=>!Number.isInteger(n)||n<1||n>65535||!available.has(n))||
    new Set(picked).size!==picked.length){
  throw Error('فقط شماره پورت‌های فهرست‌شده را بدون تکرار و با ویرگول وارد کنید.');
 }
 return picked.sort((a,b)=>a-b);
}
function renderManagement(){
 if(!state)return;
 const groups=new Map();
 for(const p of state.ports){
  if(!groups.has(p.node_id))groups.set(p.node_id,{name:p.node_name,ports:[]});
  groups.get(p.node_id).ports.push(p);
 }
 $('node-manager').innerHTML=[...groups.entries()].map(([id,group])=>
  '<article class="node-card"><h4>'+escapeHtml(group.name)+' (Node ID '+id+')</h4>'+
  '<p class="sub">پورت‌ها از Core این نود کشف شده‌اند، نه الزاماً پورت‌های اختصاصی آن. مصرف ثبت‌شده فقط برای پیشنهاد استفاده می‌شود.</p>'+
  '<form class="node-form" data-node="'+id+'"><div class="port-checks">'+group.ports.map(p=>
   '<label class="port-check" title="'+(p.total_down+p.total_up>0?'مصرف مشاهده‌شده':'بدون مصرف ثبت‌شده')+
   '"><input class="port-box" type="checkbox" value="'+p.port+'" '+(p.enabled?'checked':'')+
   '> '+p.port+(p.total_down+p.total_up>0?' ●':'')+'</label>').join('')+'</div>'+
  '<label class="manual-ports-label">یا پورت‌های این نود را با ویرگول وارد کنید'+
  '<input class="port-manual" inputmode="text" autocomplete="off" dir="ltr" placeholder="80,2053,47307" value="'+
  group.ports.filter(p=>p.enabled).map(p=>p.port).join(',')+'"></label>'+
  '<p class="sub">علامت ● یعنی این پورت از زمان شروع مانیتورینگ مصرف داشته است. مصرف صفر، دلیل غیرفعال‌بودن پورت نیست.</p>'+
  '<div class="buttons"><button type="button" class="minor bulk" data-action="observed">پیشنهاد پورت‌های مصرف‌دار</button>'+
  '<button type="button" class="minor bulk" data-action="all">انتخاب همه</button>'+
  '<button type="button" class="minor bulk" data-action="none">لغو همه</button>'+
  '<button class="primary" type="submit">ذخیره پورت‌های این نود</button></div></form></article>').join('');
 document.querySelectorAll('.node-form').forEach(form=>{
  form.addEventListener('submit',saveNodePorts);
  form.querySelectorAll('input.port-box').forEach(box=>box.addEventListener('change',()=>syncManualInput(form)));
  form.querySelectorAll('.bulk').forEach(button=>button.addEventListener('click',()=>{
   const group=groups.get(Number(form.dataset.node));
   const observed=new Set(group.ports.filter(p=>p.total_down+p.total_up>0).map(p=>p.port));
   form.querySelectorAll('input.port-box').forEach(box=>{
    const action=button.dataset.action;
    box.checked=action==='all'||(action==='observed'&&observed.has(Number(box.value)));
   });
   syncManualInput(form);
   if(button.dataset.action==='observed'){
    alert('این فقط یک پیشنهاد است. پورت‌های بدون مصرف ممکن است فعال باشند. فهرست را بررسی و سپس ذخیره کنید.');
   }
  }));
 });
 $('display-title').value=state.title;
 $('display-currency').value=state.currency;
 $('display-timezone').value=state.timezone;
}
async function sendUpdate(url,payload){
 if(!state)throw Error('آمار داشبورد هنوز آماده نیست.');
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(payload)});
 if(r.status===401){location.href='/login';throw Error('ابتدا وارد حساب شوید.');}
 const resp=await r.json();
 if(!r.ok)throw Error(resp.error||'خطا در ذخیره تنظیمات');
 return resp;
}
async function saveNodePorts(e){
 e.preventDefault();
 const form=e.currentTarget,nodeId=Number(form.dataset.node);
 let ports;
 try{ports=parseManualPorts(form);}catch(err){alert(err.message);return;}
 const button=form.querySelector('button[type=submit]');
 button.disabled=true;
 try{
  await sendUpdate('/api/visible-ports',{node_id:nodeId,visible_ports:ports});
  await reload();
  $('status').textContent='فهرست پورت‌های نود '+nodeId+' ذخیره شد.';
 }catch(err){alert(err.message);}
 finally{button.disabled=false;}
}
async function saveDisplaySettings(e){
 e.preventDefault();
 const form=e.currentTarget,button=form.querySelector('button[type=submit]');
 button.disabled=true;
 try{
  await sendUpdate('/api/display-settings',{
   title:$('display-title').value.trim(),currency:$('display-currency').value.trim(),
   timezone:$('display-timezone').value.trim()});
  await reload();
  $('status').textContent='تنظیمات نمایش ذخیره شد.';
 }catch(err){alert(err.message);}
 finally{button.disabled=false;}
}
function openEdit(node,port){const p=state.ports.find(x=>x.node_id===node&&x.port===port);if(!p)return;
 $('editing').textContent=p.port+' / '+p.node_name; $('node_id').value=node; $('port').value=port;
 $('port_title').value=p.title; $('provider').value=p.provider; $('rate').value=p.price_per_gb*multiplier();
 $('rate-unit').textContent=unit();
 $('direction').value=p.bill_direction;$('notes').value=p.notes;$('enabled').checked=!!p.enabled;
 $('since').value=p.billing_since?p.billing_since.slice(0,16):'';
 $('edit').showModal();}
async function reload(){try{
 const url='/api/dashboard?'+new URLSearchParams({from:$('from').value,to:$('to').value});
 const r=await fetch(url,{cache:'no-store'});
 if(r.status===401){location.href='/login';return;}
 const data=await r.json();if(!r.ok)throw Error(data.error||'خطا');state=data;render();renderManagement();
 }catch(e){$('status').className='notice warn';$('status').textContent=e.message;}}
async function save(e){e.preventDefault();try{
 const body={node_id:Number($('node_id').value),port:Number($('port').value),title:$('port_title').value,
  provider:$('provider').value,price_per_gb:Number($('rate').value)/multiplier(),bill_direction:$('direction').value,
  billing_since:$('since').value?new Date($('since').value+'Z').toISOString():'',
  notes:$('notes').value,enabled:$('enabled').checked};
 const r=await fetch('/api/metadata',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)});
 const resp=await r.json();if(!r.ok)throw Error(resp.error||'خطا');$('edit').close();await reload();
 }catch(e){alert(e.message);}}
function today(){const d=new Date();return d.toISOString().slice(0,10);}
const d=new Date();$('to').value=today();d.setDate(d.getDate()-6);$('from').value=d.toISOString().slice(0,10);
$('reload').addEventListener('click',reload);
$('chart-scale').addEventListener('change',renderProviderPanels);$('search').addEventListener('input',render);$('show_hidden').addEventListener('change',render);
$('display-form').addEventListener('submit',saveDisplaySettings);
$('editform').addEventListener('submit',save);$('cancel').addEventListener('click',()=>$('edit').close());
$('logout').addEventListener('click',async()=>{if(!state){location.href='/login';return;}await fetch('/api/logout',{method:'POST',headers:{'X-CSRF-Token':state.csrf}});location.href='/login';});
reload();

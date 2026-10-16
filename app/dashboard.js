'use strict';
const $=id=>document.getElementById(id);
let state=null;
let selectedProvider='__all__';
const fmt=n=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(n||0);
const volumeUnit=()=>state?.traffic_unit==='GB'?'GB':'GiB';
const smallerUnit=()=>volumeUnit()==='GB'?'MB':'MiB';
const bytesPerUnit=()=>volumeUnit()==='GB'?1e9:1024**3;
const bytesPerSmallUnit=()=>volumeUnit()==='GB'?1e6:1024**2;
const traffic=n=>(n/bytesPerUnit()>=1?fmt(n/bytesPerUnit())+' '+volumeUnit():fmt(n/bytesPerSmallUnit())+' '+smallerUnit());
const isRial=()=>['ریال','Rial','IRR'].includes(state?.currency);
const unit=()=>isRial()?'ریال':'تومان';
const multiplier=()=>isRial()?10:1;
const rialFormatter=new Intl.NumberFormat('fa-IR',{maximumFractionDigits:0,minimumFractionDigits:0});
const money=n=>(isRial()?rialFormatter.format(Math.round((Number(n)||0)*10)):fmt(n))+' '+unit();
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function age(s){if(!s)return '—'; const dt=new Date(s);return dt.toLocaleString('fa-IR',{timeZone:state.timezone,dateStyle:'short',timeStyle:'short'});}


let selectedNode='all';
// 20 distinct node colors shared by charts and legend.
const chartColors=['#578bce','#22c55e','#eaad52','#a78bfa','#29bdbd',
 '#e58f9d','#b7dc50','#f97316','#16a6c9','#e15bc0',
 '#9ca3af','#a7b82a','#d2695e','#8b5cf6','#32a488',
 '#f43f5e','#3b82f6','#b3a2eb','#bd8e28','#35b6e5'];
function visiblePaths(){
 return state.ports.filter(p=>p.enabled &&
  (selectedProvider==='__all__'||(p.provider||'بدون ارائه‌دهنده')===selectedProvider) &&
  (selectedNode==='all'||p.node_id===Number(selectedNode)));
}
function summarize(paths){
 const result={down:0,up:0,billed:0,cost:0,historical_cost:0};
 for(const p of paths)for(const key of Object.keys(result))result[key]+=Number(p[key]||0);
 return result;
}
function timeseries(period){
 const rows=(period==='hourly'?state.hourly_by_provider:state.daily_by_provider)||[];
 const buckets=new Map();
 for(const row of rows){
  if(selectedProvider!=='__all__'&&row.provider!==selectedProvider)continue;
  if(selectedNode!=='all'&&row.node_id!==Number(selectedNode))continue;
  const bucket=period==='monthly'
   ? (()=>{const [year,month]=Jalali.fromISO(row.period.slice(0,10));return 'J'+year+'/'+String(month).padStart(2,'0');})()
   : row.period;
  let group=buckets.get(bucket);
  if(!group){group=new Map();buckets.set(bucket,group);}
  let item=group.get(row.node_id);
  if(!item){item={node_id:row.node_id,node_name:row.node_name,down:0,up:0,cost:0,historical_cost:0};group.set(row.node_id,item);}
  for(const k of ['down','up','cost','historical_cost'])item[k]+=Number(row[k]||0);
 }
 return [...buckets.entries()].sort((a,b)=>a[0].localeCompare(b[0]))
  .map(([period,nodes])=>({period,nodes}));
}
const persianDigits=s=>String(s).replace(/[0-9]/g,d=>'۰۱۲۳۴۵۶۷۸۹'[Number(d)]);
const periodLabel=period=>{
 if(period.startsWith('J'))return persianDigits(period.slice(1));
 const date=Jalali.label(period.slice(0,10));
 return period.length>10?date.slice(5)+' '+period.slice(11,13)+':00':date.slice(5);
};
function stackedBars(id,groups,field){
 const element=$(id);
 if(!groups.length){element.textContent='در این بازه هنوز نمونه‌ای ثبت نشده است.';return;}
 const allNodes=new Map();
 for(const row of state.ports){if(!allNodes.has(row.node_id))allNodes.set(row.node_id,row.node_name);}
 const selectedIds=[...new Set(groups.flatMap(g=>[...g.nodes.keys()]))].sort((a,b)=>a-b);
 const colors=new Map([...allNodes.keys()].sort((a,b)=>a-b).map((id,i)=>[id,chartColors[i%chartColors.length]]));
 const left=90,right=24,top=20,bottom=55,h=305;
 const w=Math.min(5500,Math.max(760,groups.length*38+left+right));
 const barArea=w-left-right;
 const barWidth=Math.max(3,Math.min(65,barArea/groups.length*.68));
 const amounts=groups.map(g=>[...g.nodes.values()].reduce((acc,node)=>acc+(field==='traffic'?(node.down+node.up)/bytesPerUnit():node.cost*multiplier()),0));
 const max=Math.max(.0001,...amounts)*1.12;
 const y=val=>h-bottom-(h-bottom-top)*val/max;
 let svg='<svg class="stacked-chart" role="img" aria-label="'+(field==='traffic'?'نمودار ستونی حجم تفکیک نود':'نمودار ستونی هزینه تفکیک نود')+'" viewBox="0 0 '+w+' '+h+'" style="min-width:'+w+'px">';
 for(let k=0;k<=4;k++){
  const v=max*k/4,Y=y(v);
  svg+='<line x1="'+left+'" y1="'+Y+'" x2="'+(w-right)+'" y2="'+Y+'" stroke="var(--chart-grid,#294059)"/>';
  svg+='<text x="'+(left-8)+'" y="'+(Y+4)+'" text-anchor="end" fill="var(--chart-label,#a6b9d1)" font-size="12">'+
    escapeHtml((field==='traffic'?fmt(v):isRial()?rialFormatter.format(Math.round(v)):fmt(v))+(field==='traffic'?' '+volumeUnit():' '+unit()))+'</text>';
 }
 const step=Math.max(1,Math.ceil(groups.length/10));
 for(let i=0;i<groups.length;i++){
  const g=groups[i],x=left+(i+.5)*barArea/groups.length;
  let sum=0;
  for(const nid of selectedIds){
   const item=g.nodes.get(nid);if(!item)continue;
   const value=field==='traffic'?(item.down+item.up)/bytesPerUnit():item.cost*multiplier();
   if(value<=0)continue;
   const height=(h-bottom-top)*value/max,Y=y(sum+value);
   const title=periodLabel(g.period)+' | '+item.node_name+
      (field==='traffic'?' | دانلود '+traffic(item.down)+' | آپلود '+traffic(item.up):' | هزینه '+money(item.cost));
   svg+='<rect x="'+(x-barWidth/2).toFixed(2)+'" y="'+Y.toFixed(2)+'" width="'+barWidth.toFixed(2)+
     '" height="'+Math.max(0,height).toFixed(2)+'" rx="2" fill="'+colors.get(nid)+'"><title>'+
     escapeHtml(title)+'</title></rect>';
   sum+=value;
  }
  if(i%step===0||i===groups.length-1){
   svg+='<text x="'+x.toFixed(1)+'" y="'+(h-25)+'" text-anchor="middle" fill="#a6b9d1" font-size="12">'+escapeHtml(periodLabel(g.period))+'</text>';
  }
 }
 element.innerHTML=svg+'</svg>';
 if(id==='chart')$('node-legend').innerHTML=selectedIds.map(nid=>
  '<span class="legend-node"><i style="background:'+colors.get(nid)+'"></i>'+escapeHtml(allNodes.get(nid)||('Node '+nid))+'</span>').join('');
}
function renderProviderPanels(){
 if(!state)return;
 const paths=visiblePaths(),current=summarize(paths);
 $('down').textContent=traffic(current.down);
 $('up').textContent=traffic(current.up);
 $('billed').textContent=traffic(current.billed);
 $('cost').textContent=money(current.cost);
 renderExpenseCosts(current.cost);
 $('historical-cost').textContent='هزینه ثبت‌شده قبلی: '+money(current.historical_cost);
 const allLabel='همه ارائه‌دهنده‌ها';
 $('selected-provider-title').textContent='روند حجم مصرف — '+(selectedProvider==='__all__'?allLabel:selectedProvider);
 $('provider-detail').textContent=(selectedProvider==='__all__'?'مجموع ارائه‌دهنده‌ها':'ارائه‌دهنده: '+selectedProvider)+
    ' | دانلود '+traffic(current.down)+' | آپلود '+traffic(current.up)+
    ' | هزینه با نرخ فعلی '+money(current.cost);
 const names=new Map([['__all__',summarize(state.ports.filter(p=>p.enabled&&(selectedNode==='all'||p.node_id===Number(selectedNode))))]]);
 for(const p of state.ports){
  if(!p.enabled||(selectedNode!=='all'&&p.node_id!==Number(selectedNode)))continue;
  const key=p.provider||'بدون ارائه‌دهنده';
  if(!names.has(key))names.set(key,{down:0,up:0,billed:0,cost:0,historical_cost:0});
  const value=names.get(key);for(const col of Object.keys(value))value[col]+=Number(p[col]||0);
 }
 // Never make a linked wallet inaccessible because its ports were hidden.
 if(selectedNode==='all')for(const account of wallets()){
  if(account.provider&&!names.has(account.provider))
   names.set(account.provider,{down:0,up:0,billed:0,cost:0,historical_cost:0});
 }
 // Full-width compact rows avoid empty gaps when providers have unequal wallets.
 $('providers').innerHTML=[...names.entries()].map(([name,v])=>{
  const active=name===selectedProvider,title=name==='__all__'?allLabel:name;
  const count=state.ports.filter(p=>p.enabled&&
     (selectedNode==='all'||p.node_id===Number(selectedNode))&&
     (name==='__all__'||(p.provider||'بدون ارائه‌دهنده')===name)).length;
  const fixed=(state.fixed_expenses||[]).filter(e=>
    name==='__all__'
      ? (selectedNode==='all'||(e.scope==='node'&&e.node_id===Number(selectedNode)))
      : (selectedNode==='all'&&e.scope==='provider'&&e.provider===name)
    ).reduce((sum,e)=>sum+Number(e.period_rial||0),0)/10;
  const stats=[['دانلود',traffic(v.down)],['آپلود',traffic(v.up)],
               ['مشمول هزینه',traffic(v.billed)],['هزینه ترافیک',money(v.cost)]];
  return '<article class="provider-shell'+(active?' provider-shell-active':'')+'">'+
    '<div class="provider-overview">'+
    '<button type="button" class="provider provider-button '+(active?'selected':'')+
    '" data-provider="'+escapeHtml(name)+'" aria-pressed="'+active+'" aria-label="نمایش نمودار '+escapeHtml(title)+'">'+
    '<span class="provider-heading"><strong>'+escapeHtml(title)+'</strong>'+
    '<span class="provider-port-count">'+fmt(count)+' پورت</span></span>'+
    '<span class="provider-stats">'+stats.map(([label,value])=>
      '<span class="provider-stat"><small>'+label+'</small><b>'+value+'</b></span>').join('')+'</span>'+
    '<span class="provider-fixed-note">هزینه ثابت تخصیص‌یافته: '+money(fixed)+'</span>'+
    '</button>'+
    '<div class="provider-tools"><button class="minor provider-report-button" data-provider="'+escapeHtml(name)+'" type="button">جزئیات و گزارش پورت‌ها</button></div>'+
    '</div>'+providerWalletDetails(name)+'</article>';
 }).join('');
 document.querySelectorAll('.provider-button').forEach(b=>b.addEventListener('click',()=>{
  selectedProvider=b.dataset.provider;render();
 }));
 document.querySelectorAll('.provider-report-button').forEach(b=>
  b.addEventListener('click',()=>openProviderReport(b.dataset.provider)));
 document.querySelectorAll('.provider-account-fold').forEach(details=>
  details.addEventListener('toggle',()=>{
   if(details.open)expandedProviderAccounts.add(details.dataset.provider);
   else expandedProviderAccounts.delete(details.dataset.provider);
  }));
 wireProviderWalletActions();
 const scale=$('chart-scale').value;
 const hourly=state.hourly_available && (scale==='hourly'||(scale==='auto'&&$('from').value===$('to').value));
 const grouping=scale==='monthly'?'monthly':(hourly?'hourly':'daily');
 stackedBars('chart',timeseries(grouping),'traffic');
 $('traffic-chart-caption').textContent=(grouping==='monthly'?'تجمیع ماهانه شمسی':hourly?'تجمیع ساعتی':'تجمیع روزانه')+
   ' بر اساس UTC؛ برچسب تاریخ‌ها شمسی است'+
   (scale==='hourly'&&!state.hourly_available?' (برای بازه بیش از ۳۱ روز، تجمیع روزانه انجام شد)':'');
 stackedBars('cost-chart',timeseries(grouping),'cost');
}
function render(){if(!state)return;
 $('title').textContent=state.title;
 const lr=state.last_run;
 $('status').className='notice'+(lr&&JSON.parse(lr.errors_json).length?' warn':'');
 $('status').textContent=lr?'آخرین نمونه‌برداری: '+age(lr.collected_at)+' | تعداد نمونه: '+fmt(lr.sample_count)+(JSON.parse(lr.errors_json).length?' | هشدار: '+JSON.parse(lr.errors_json).join('، '):''):'هنوز نمونه‌ای ثبت نشده؛ یک بار دستور collect را اجرا کنید.';
 renderProviderPanels();
 renderExpenses();
 if($('provider-report-dialog').open)renderPortReport();
 $('export').href='/api/export.csv?'+new URLSearchParams({from:$('from').value,to:$('to').value});
 $('export-expenses').href='/api/expenses.csv?'+new URLSearchParams({from:$('from').value,to:$('to').value});
}


let reportProvider='__all__';
function openProviderReport(provider){
 reportProvider=provider;
 $('search').value='';
 $('show_hidden').checked=false;
 renderPortReport();
 $('provider-report-dialog').showModal();
}
function renderPortReport(){
 if(!state)return;
 const q=$('search').value.trim().toLowerCase();
 const ports=state.ports.filter(p=>(reportProvider==='__all__'||(p.provider||'بدون ارائه‌دهنده')===reportProvider)&&(selectedNode==='all'||p.node_id===Number(selectedNode))&&(p.enabled||$('show_hidden').checked)&&[p.node_name,p.port,p.title,p.provider,p.tag].join(' ').toLowerCase().includes(q));
 const totals=summarize(ports);
 $('provider-report-title').textContent='گزارش پورت‌ها — '+(reportProvider==='__all__'?'همه ارائه‌دهنده‌ها':reportProvider);
 $('provider-report-summary').textContent=ports.length+' پورت | دانلود '+traffic(totals.down)+' | آپلود '+traffic(totals.up)+' | هزینه '+money(totals.cost);
 $('ports').innerHTML=ports.map(p=>`<tr class="${p.enabled?'':'muted'}"><td><strong>${escapeHtml(p.node_name)}</strong><span class="sub">پورت ${p.port} · نود ${p.node_id}</span></td><td>${escapeHtml(p.title||'بدون نام دلخواه')}<span class="sub">${escapeHtml(p.provider||'تعرفه تعیین نشده')} · <span class="tag">${escapeHtml(p.tag)}</span></span></td><td>${traffic(p.down)}</td><td>${traffic(p.up)}</td><td class="money">${money(p.price_per_gb)} / ${volumeUnit()}</td><td class="money">${money(p.cost)}<span class="sub">قبلی: ${money(p.historical_cost)}</span></td><td>${age(p.last_seen)}</td><td><button class="editbtn" data-nid="${p.node_id}" data-port="${p.port}">ویرایش</button>${p.provider?' <button class="minor unassign-port" type="button" data-nid="'+p.node_id+'" data-port="'+p.port+'">حذف از ارائه‌دهنده</button>':''}</td></tr>`).join('')||'<tr><td colspan="8">پورتی پیدا نشد.</td></tr>';
 document.querySelectorAll('.editbtn').forEach(btn=>btn.addEventListener('click',()=>{ $('provider-report-dialog').close();openEdit(Number(btn.dataset.nid),Number(btn.dataset.port)); }));
 document.querySelectorAll('.unassign-port').forEach(btn=>btn.addEventListener('click',async()=>{
  const nodeId=Number(btn.dataset.nid),port=Number(btn.dataset.port);
  const entry=state.ports.find(p=>p.node_id===nodeId&&p.port===port);
  if(!entry?.provider)return;
  if(!confirm('پورت '+port+' از نود '+entry.node_name+' از ارائه‌دهنده «'+entry.provider+
     '» حذف و از گزارش پنهان شود؟\\nآمار خام حفظ می‌شود و PasarGuard تغییری نمی‌کند.'))return;
  btn.disabled=true;
  try{
   await sendUpdate('/api/metadata/unassign',{node_id:nodeId,port,provider:entry.provider});
   await reload();
  }catch(err){alert(err.message);btn.disabled=false;}
 }));

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

function expenseIsAssigned(expense){
 if(selectedNode==='all'&&selectedProvider==='__all__')return true;
 if(selectedNode!=='all'&&selectedProvider==='__all__')
  return expense.scope==='node'&&expense.node_id===Number(selectedNode);
 if(selectedNode==='all'&&selectedProvider!=='__all__')
  return expense.scope==='provider'&&expense.provider===selectedProvider;
 // Do not double-count an unallocated provider-wide bill as a node bill.
 return false;
}
function expenseName(expense){
 if(expense.scope==='general')return 'عمومی / پنل';
 if(expense.scope==='provider')return 'ارائه‌دهنده: '+expense.provider;
 const node=state.ports.find(p=>p.node_id===expense.node_id);
 return 'نود: '+(node?.node_name||expense.node_id);
}
function renderExpenseCosts(trafficCost){
 const listed=(state.fixed_expenses||[]).filter(expenseIsAssigned);
 const rial=listed.reduce((sum,e)=>sum+Number(e.period_rial||0),0);
 $('fixed-cost').textContent=money(rial/10);
 $('all-cost').textContent=money(trafficCost+rial/10);
 let context='تمام هزینه‌های ثبت‌شده';
 if(selectedNode!=='all'&&selectedProvider!=='__all__')context='هزینه‌های مشترک در نمای هم‌زمان نود و ارائه‌دهنده تخصیص داده نمی‌شوند';
 else if(selectedNode!=='all')context='فقط هزینه‌های اختصاصی این نود؛ عمومی و ارائه‌دهنده مشترک جدا باقی می‌مانند';
 else if(selectedProvider!=='__all__')context='فقط هزینه‌های مستقیم همین ارائه‌دهنده؛ هزینه مشترک نود یا پنل سرشکن نمی‌شود';
 $('expenses-scope-note').textContent='مبلغ ثابت در خلاصه بالا: '+money(rial/10)+' — '+context;
}
function walletAmount(value,kind){
 if(kind==='money')return rialFormatter.format(Math.round(isRial()?value:value/10))+' '+unit();
 return new Intl.NumberFormat('fa-IR',{maximumFractionDigits:3}).format(value/bytesPerUnit())+' '+volumeUnit();
}
function walletDate(utc){
 if(!utc)return '—';
 return new Intl.DateTimeFormat('fa-IR',{dateStyle:'short',timeStyle:'short',
  timeZone:state.timezone||'Asia/Tehran'}).format(new Date(utc));
}
function wallets(){return state?.wallets||[];}
function walletById(id){return wallets().find(x=>x.id===Number(id));}
function walletsForProvider(provider){
 return wallets().filter(a=>a.provider===provider);
}
function walletInputNumber(field,kind){
 const n=Number($(field).value);
 if(!Number.isFinite(n)||n<0)throw Error('مقدار معتبر وارد کن.');
 if(kind==='money'&&!Number.isInteger(n))throw Error('مبلغ پولی را به صورت عدد صحیح و مطابق واحد پول پنل وارد کن.');
 const amount=Math.round(n*(kind==='money'?(isRial()?1:10):bytesPerUnit()));
 if(!Number.isSafeInteger(amount)||amount<0)throw Error('مقدار خیلی بزرگ است.');
 return amount;
}
function walletMonth(time){
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:state.timezone||'Asia/Tehran',
    year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(time))
   .filter(p=>['year','month','day'].includes(p.type)).map(p=>[p.type,p.value]));
 const [y,m]=Jalali.fromISO(parts.year+'-'+parts.month+'-'+parts.day);
 return y+'/'+String(m).padStart(2,'0');
}
function walletReconciliationHistory(a){
 const history=a.reconciliation_history||[];
 const all=a.reconciliation_summary||{count:0,positive:0,negative:0,net:0};
 const months=new Map();
 for(const entry of history){
  const key=walletMonth(entry.checked_at);
  if(!months.has(key))months.set(key,{positive:0,negative:0,net:0,count:0});
  const m=months.get(key),delta=Number(entry.adjustment);
  m.positive+=Math.max(0,delta);m.negative+=Math.max(0,-delta);m.net+=delta;m.count++;
 }
 const row=m=>'<span>ربات بیشتر: +'+walletAmount(m.positive,a.kind)+'</span>'+
  '<span>ربات کمتر: −'+walletAmount(m.negative,a.kind)+'</span>'+
  '<span>اختلاف خالص: '+(m.net>0?'+':'')+walletAmount(m.net,a.kind)+'</span>';
 const monthRows=[...months.entries()].sort((x,y)=>y[0].localeCompare(x[0]))
   .map(([key,m])=>'<div class="wallet-month"><strong>'+escapeHtml(persianDigits(key))+
       ' · '+persianDigits(m.count)+' نوبت</strong>'+row(m)+'</div>').join('');
 const checks=history.map(h=>'<tr><td>'+escapeHtml(walletDate(h.checked_at))+
    '</td><td>'+walletAmount(h.estimated_before,a.kind)+'</td>'+
    '<td>'+walletAmount(h.reported_amount,a.kind)+'</td>'+
    '<td>'+ (h.adjustment>0?'+':'')+walletAmount(h.adjustment,a.kind)+'</td>'+
    '<td>'+escapeHtml(h.note||'—')+'</td></tr>').join('');
 return '<details class="wallet-reconciliations"><summary>تاریخچه همسان‌سازی ('+
   persianDigits(all.count)+' بار)</summary>'+
   '<p class="sub">اختلاف مثبت یعنی مانده ربات بیشتر بوده؛ منفی یعنی کمتر بوده. این اصلاحات، مصرف و شارژ قبلی را حذف نمی‌کنند.</p>'+
   '<div class="wallet-month"><strong>جمع کل همسان‌سازی‌ها</strong>'+row(all)+'</div>'+
   monthRows+
   '<div class="table-scroll"><table><thead><tr><th>تاریخ</th><th>مانده پیش از اصلاح</th>'+
   '<th>مانده ربات</th><th>اختلاف اصلاح‌شده</th><th>توضیح</th></tr></thead>'+
   '<tbody>'+ (checks||'<tr><td colspan="5">هنوز همسان‌سازی ثبت نشده است.</td></tr>')+
   '</tbody></table></div></details>';
}
// Preserve account disclosure state across refreshes and chart filtering.
const expandedProviderAccounts=new Set();
function providerWalletDetails(name){
 if(name==='__all__'||name==='بدون ارائه‌دهنده')return '';
 const accounts=walletsForProvider(name);
 const cards=accounts.map(a=>{
  const opening=a.kind==='money'?a.opening_rial:a.opening_bytes;
  const usage=a.kind==='money'?a.spent_rial:a.used_bytes;
  const reported=a.reported_balance===null?'':('<small>مانده اعلامی: '+
   walletAmount(a.reported_balance,a.kind)+' · اختلاف آخرین بررسی: '+
   walletAmount(a.comparison_gap,a.kind)+'</small>');
  const active=a.ports.filter(p=>!p.ended_at);
  return '<article class="provider-wallet-account">'+
   '<strong>'+escapeHtml(a.title)+'</strong><small>'+(a.kind==='money'?'حساب پولی':'حساب حجمی')+
   ' · '+escapeHtml(a.bot_handle||'')+'</small>'+
   '<div class="provider-credit-total"><span>مانده تخمینی</span><strong>'+
   walletAmount(a.estimated_balance,a.kind)+'</strong></div>'+
   '<small>ابتدا: '+walletAmount(opening,a.kind)+' · شارژ: '+walletAmount(a.credited,a.kind)+'</small>'+
   '<small>اصلاح موجودی: '+(a.adjustments>0?'+':'')+walletAmount(a.adjustments||0,a.kind)+'</small>'+
   '<small>کسر شده: '+walletAmount(usage,a.kind)+' · پورت‌های فعال: '+active.length+'</small>'+
   reported+
   '<div class="provider-credit-actions"><button class="minor provider-credit-edit" data-id="'+a.id+'" data-provider="'+escapeHtml(name)+'" type="button">مدیریت پورت‌ها</button>'+
   '<button class="minor provider-credit-topup" data-id="'+a.id+'" type="button">شارژ / خرید حجم</button>'+
   '<button class="minor provider-credit-check" data-id="'+a.id+'" type="button">همسان‌سازی موجودی</button></div>'+
   '<details class="wallet-history"><summary>سابقه پورت‌ها و تراکنش‌ها</summary>'+
    a.ports.map(p=>'<p class="sub">'+escapeHtml(p.node_name||('Node '+p.node_id))+' / '+p.port+
     (p.ended_at?' · اتصال پایان‌یافته':' · فعال')+
     ' · '+walletAmount(p.billed_bytes,'volume')+
     (a.kind==='money'?' · نرخ فعلی '+walletAmount(p.rate_rial_per_gb,'money')+'/'+volumeUnit():'')+'</p>').join('')+
    (a.credit_history||[]).map(t=>'<p class="sub">شارژ '+walletAmount(t.amount,a.kind)+' — '+escapeHtml(walletDate(t.created_at))+'</p>').join('')+
    (a.check_history||[]).map(t=>'<p class="sub">مقایسه · مانده ربات '+walletAmount(t.reported_amount,a.kind)+
     ' · اختلاف '+walletAmount(t.difference,a.kind)+' — '+escapeHtml(walletDate(t.checked_at))+'</p>').join('')+
   '</details>'+walletReconciliationHistory(a)+'</article>';
 }).join('');
 const preview=accounts.slice(0,2).map(a=>
   '<span class="provider-balance-chip"><span>'+escapeHtml(a.title)+'</span><strong>'+
   walletAmount(a.estimated_balance,a.kind)+'</strong></span>').join('');
 const more=accounts.length>2?'<span class="provider-more-accounts">+'+fmt(accounts.length-2)+' حساب دیگر</span>':'';
 return '<details class="provider-account-fold" data-provider="'+escapeHtml(name)+'"'+
   (expandedProviderAccounts.has(name)?' open':'')+'>'+
   '<summary class="provider-account-summary"><span class="provider-account-heading">'+
   '<strong>حساب‌های اعتبار</strong><small>'+fmt(accounts.length)+' حساب</small></span>'+
   '<span class="provider-balance-preview">'+(accounts.length?preview+more:'هنوز حسابی ثبت نشده')+'</span>'+
   '<span class="provider-account-chevron" aria-hidden="true">⌄</span></summary>'+
   '<div class="provider-credit">'+cards+
   '<button type="button" class="minor provider-credit-create" data-provider="'+escapeHtml(name)+'">+ حساب اعتبار جدید</button></div></details>';
}
function wireProviderWalletActions(){
 document.querySelectorAll('.provider-credit-create').forEach(b=>
  b.addEventListener('click',()=>openProviderWallet(b.dataset.provider)));
 document.querySelectorAll('.provider-credit-edit').forEach(b=>
  b.addEventListener('click',()=>openProviderWallet(b.dataset.provider,Number(b.dataset.id))));
 document.querySelectorAll('.provider-credit-topup').forEach(b=>
  b.addEventListener('click',()=>openWalletDialog('credit',Number(b.dataset.id))));
 document.querySelectorAll('.provider-credit-check').forEach(b=>
  b.addEventListener('click',()=>openWalletDialog('reported',Number(b.dataset.id))));
}
function refreshProviderWalletForm(){
 const mode=$('provider-wallet-mode').value;
 const quota=$('provider-wallet-kind').value==='volume';
 $('provider-wallet-existing-wrap').hidden=mode!=='existing';
 $('provider-wallet-new-wrap').hidden=mode!=='new';
 $('provider-wallet-title').required=mode==='new';
 $('provider-wallet-opening').required=mode==='new';
 $('provider-wallet-unit').textContent=quota?volumeUnit():unit();
 $('provider-wallet-opening').step=quota?'any':'1';
}
function activeProviderAssignment(nodeId,port){
 for(const a of wallets())for(const binding of a.ports){
  if(!binding.ended_at&&binding.node_id===nodeId&&binding.port===port)return a;
 }
 return null;
}
function renderProviderWalletPorts(provider,accountId){
 const available=state.ports.filter(p=>(p.provider||'بدون ارائه‌دهنده')===provider);
 const selected=walletById(accountId);
 const active=new Set((selected?.ports||[]).filter(p=>!p.ended_at).map(p=>p.node_id+':'+p.port));
 $('provider-wallet-ports').innerHTML=available.map(p=>{
  const key=p.node_id+':'+p.port,owner=activeProviderAssignment(p.node_id,p.port);
  const checked=active.has(key);
  return '<label class="wallet-port-option"><input type="checkbox" value="'+key+'" '+
   (checked?'checked':'')+'><span><strong>'+escapeHtml(p.node_name)+' / '+p.port+'</strong>'+
   '<small>'+escapeHtml(p.title||p.tag)+' · '+(owner?'در حساب «'+escapeHtml(owner.title)+'»':'بدون حساب')+
   ' · '+escapeHtml(p.bill_direction)+' · '+money((p.price_per_gb||0))+'/GB</small></span></label>';
 }).join('')||'<p class="sub">ابتدا پورت‌های این ارائه‌دهنده را در بخش مدیریت پورت‌ها تعریف کن.</p>';
}
function openProviderWallet(provider,accountId=null){
 const account=accountId?walletById(accountId):null;
 if(accountId&&!account){alert('حساب پیدا نشد');return;}
 $('provider-wallet-name').value=provider;
 $('provider-wallet-display').textContent=provider;
 $('provider-wallet-edit-id').value=account?String(account.id):'';
 $('provider-wallet-mode').value=account?'edit':'new';
 $('provider-wallet-mode').querySelector('option[value="edit"]').disabled=!account;
 $('provider-wallet-heading').textContent=account?'ویرایش پورت‌های '+account.title:'افزودن اعتبار جدید';
 $('provider-wallet-kind').value='money';
 $('provider-wallet-title').value=account?.title||'';
 $('provider-wallet-opening').value='';
 $('provider-wallet-handle').value='';
 const candidates=wallets().filter(a=>!a.provider);
 $('provider-wallet-existing').innerHTML=candidates.map(a=>
  '<option value="'+a.id+'">'+escapeHtml(a.title)+' ('+walletAmount(a.estimated_balance,a.kind)+')</option>').join('');
 $('provider-wallet-mode').querySelector('option[value="existing"]').disabled=!candidates.length;
 renderProviderWalletPorts(provider,accountId);
 refreshProviderWalletForm();
 $('provider-wallet-dialog').showModal();
}
function openWalletDialog(type,id){
 const a=walletById(id);if(!a)return;
 if(type==='credit'){
  $('wallet-credit-account').value=String(id);
  $('wallet-credit-unit').textContent=a.kind==='money'?unit():volumeUnit();
  $('wallet-credit-heading').textContent=a.kind==='money'?'ثبت شارژ جدید':'ثبت حجم خریداری‌شده جدید';
  $('wallet-credit-amount').value='';$('wallet-credit-note').value='';
  $('wallet-credit-dialog').showModal();
 }else if(type==='reported'){
  $('wallet-reported-account').value=String(id);
  $('wallet-reported-unit').textContent=a.kind==='money'?unit():volumeUnit();
  $('wallet-reported-amount').value='';
  $('wallet-reported-note').value='';
  $('wallet-reported-dialog').showModal();
 }
}
async function saveWalletRequest(event,url,read,dialog){
 event.preventDefault();
 const button=event.currentTarget.querySelector('button[type=submit]');
 button.disabled=true;
 try{await sendUpdate(url,read());$(dialog).close();await reload();}
 catch(err){alert(err.message);}finally{button.disabled=false;}
}
function installWalletForms(){
 $('provider-wallet-mode').addEventListener('change',()=>{
 refreshProviderWalletForm();
 const mode=$('provider-wallet-mode').value;
 const aid=mode==='edit'?Number($('provider-wallet-edit-id').value):
   mode==='existing'?Number($('provider-wallet-existing').value):null;
 renderProviderWalletPorts($('provider-wallet-name').value,aid);
});
 $('provider-wallet-kind').addEventListener('change',refreshProviderWalletForm);
 $('provider-wallet-existing').addEventListener('change',()=>{
  if($('provider-wallet-mode').value==='existing')
   renderProviderWalletPorts($('provider-wallet-name').value,Number($('provider-wallet-existing').value));
 });
 $('provider-wallet-cancel').addEventListener('click',()=>$('provider-wallet-dialog').close());
 $('provider-wallet-form').addEventListener('submit',e=>saveWalletRequest(e,'/api/providers/wallet',()=>{
  const mode=$('provider-wallet-mode').value,provider=$('provider-wallet-name').value;
  const ports=[...$('provider-wallet-ports').querySelectorAll('input[type=checkbox]:checked')]
    .map(x=>{const [node_id,port]=x.value.split(':').map(Number);return {node_id,port};});
  if(!ports.length&&!confirm('هیچ پورتی انتخاب نشده است؛ این حساب بدون کسر مصرف فعال بماند؟'))
    throw Error('لطفاً پورت‌ها را انتخاب کن');
  let transferred=false;
  const activeId=mode==='edit'?Number($('provider-wallet-edit-id').value):
                 mode==='existing'?Number($('provider-wallet-existing').value):0;
  for(const port of ports){
   const owner=activeProviderAssignment(port.node_id,port.port);
   if(owner&&owner.id!==activeId)transferred=true;
  }
  if(transferred&&!confirm('برخی پورت‌ها اکنون به حساب دیگری متصل‌اند. انتقال آنها از این لحظه انجام می‌شود؛ مصرف گذشته در حساب قبلی می‌ماند. ادامه می‌دهی؟'))
    throw Error('انتقال پورت لغو شد');
  const payload={provider,ports,confirm_transfer:transferred};
  if(mode==='edit')payload.account_id=activeId;
  else if(mode==='existing')payload.existing_account_id=activeId;
  else Object.assign(payload,{kind:$('provider-wallet-kind').value,
       title:$('provider-wallet-title').value,
       opening_amount:walletInputNumber('provider-wallet-opening',$('provider-wallet-kind').value),
       bot_handle:$('provider-wallet-handle').value});
  return payload;
 },'provider-wallet-dialog'));
 for(const name of ['wallet-credit','wallet-reported'])
  $(name+'-cancel').addEventListener('click',()=>$(name+'-dialog').close());
 $('wallet-credit-form').addEventListener('submit',e=>saveWalletRequest(e,'/api/wallets/credit',()=>{
  const a=walletById($('wallet-credit-account').value);if(!a)throw Error('حساب پیدا نشد');
  return {account_id:a.id,amount:walletInputNumber('wallet-credit-amount',a.kind),
   note:$('wallet-credit-note').value};
 },'wallet-credit-dialog'));
 $('wallet-reported-form').addEventListener('submit',e=>saveWalletRequest(e,'/api/wallets/reconcile',()=>{
  const a=walletById($('wallet-reported-account').value);if(!a)throw Error('حساب پیدا نشد');
  if(!confirm('مانده حساب «'+a.title+'» با مبلغ/حجم ربات همسان شود و اختلاف برای حسابرسی ذخیره شود؟'))throw Error('همسان‌سازی لغو شد');
  return {account_id:a.id,amount:walletInputNumber('wallet-reported-amount',a.kind),
   note:$('wallet-reported-note').value.trim()};
 },'wallet-reported-dialog'));
}
function renderExpenses(){
 if(!state)return;
 const items=state.fixed_expenses||[];
 const table=$('expenses-table');
 table.innerHTML=items.map(e=>{
  const bounds=Jalali.label(e.start_date)+(e.end_date?' تا '+Jalali.label(e.end_date):' — بدون پایان');
  const ratio=(e.breakdown||[]).map(x=>x.frequency==='once'
    ? 'یکباره در تاریخ پرداخت'
    : persianDigits(x.covered_days)+' روز از '+persianDigits(x.month_days)+
      ' روز ماه میلادی '+persianDigits(x.month)).join(' + ')||'خارج از بازه گزارش';
  return '<tr><td><strong>'+escapeHtml(e.label)+'</strong><span class="sub">'+escapeHtml(e.category)+
   (e.note?' · '+escapeHtml(e.note):'')+'</span></td><td>'+escapeHtml(expenseName(e))+'</td>'+
   '<td>'+(e.frequency==='monthly'?'ماهانه':'یکباره')+'</td>'+
   '<td class="money">'+money(e.amount_rial/10)+'</td>'+
   '<td class="money">'+money(e.period_rial/10)+'<span class="expense-prorate">'+
    escapeHtml(ratio)+'</span></td><td>'+escapeHtml(bounds)+'</td>'+
   '<td><div class="cost-actions"><button type="button" class="edit-expense minor" data-id="'+e.id+
   '">ویرایش</button><button type="button" class="delete-expense minor" data-id="'+e.id+
   '">حذف</button></div></td></tr>';
 }).join('')||'<tr><td colspan="7">هنوز هزینه‌ای ثبت نشده است.</td></tr>';
 table.querySelectorAll('.edit-expense').forEach(button=>button.addEventListener('click',()=>
  showExpense(Number(button.dataset.id))));
 table.querySelectorAll('.delete-expense').forEach(button=>button.addEventListener('click',async()=>{
  const id=Number(button.dataset.id),expense=items.find(x=>x.id===id);
  if(!expense||!confirm('هزینه «'+expense.label+'» از محاسبات همه بازه‌ها حذف شود؟ این تغییر فقط در دیتابیس مانیتورینگ است.'))return;
  try{await sendUpdate('/api/fixed-expense/delete',{id});await reload();}
  catch(err){alert(err.message);}
 }));
 $('expense-provider-list').innerHTML=Object.keys(state.providers).filter(x=>x!=='بدون ارائه‌دهنده')
   .map(x=>'<option value="'+escapeHtml(x)+'"></option>').join('');
 $('expense-node').innerHTML=[...new Map(state.ports.map(p=>[p.node_id,p.node_name])).entries()]
   .map(([id,name])=>'<option value="'+id+'">'+escapeHtml(name)+'</option>').join('');
}
function refreshExpenseForm(){
 const scope=$('expense-scope').value;
 $('expense-node-box').hidden=scope!=='node';
 $('expense-provider-box').hidden=scope!=='provider';
 const once=$('expense-frequency').value==='once';
 $('expense-end-box').hidden=once;
 $('expense-end-clear').hidden=once;
 if(once)expenseEndPicker.clear();
}
function showExpense(id){
 const e=(state.fixed_expenses||[]).find(x=>x.id===id);
 $('expense-heading').textContent=e?'ویرایش هزینه':'ثبت هزینه جدید';
 $('expense-id').value=e?.id||'';
 $('expense-title').value=e?.label||'';
 $('expense-category').value=e?.category||'other';
 if($('expense-category').selectedIndex<0)$('expense-category').value='other';
 $('expense-scope').value=e?.scope||'general';
 $('expense-frequency').value=e?.frequency||'monthly';
 $('expense-node').value=e?.node_id||'';
 $('expense-provider').value=e?.provider||'';
 $('expense-amount').value=e?(isRial()?e.amount_rial:e.amount_rial/10):'';
 $('expense-unit').textContent=unit();
 $('expense-amount').step=isRial()?'1':'0.1';
 expenseStartPicker.set(e?.start_date||initialDay);
 if(e?.end_date)expenseEndPicker.set(e.end_date);
 else expenseEndPicker.clear();
 $('expense-note').value=e?.note||'';
 refreshExpenseForm();
 $('expense-dialog').showModal();
}
async function saveExpense(event){
 event.preventDefault();
 const val=Number($('expense-amount').value);
 if(!Number.isFinite(val)||val<0){alert('مبلغ نامعتبر است');return;}
 const amountRial=Math.round(val*(isRial()?1:10));
 const obj={
  label:$('expense-title').value.trim(),category:$('expense-category').value,
  scope:$('expense-scope').value,node_id:$('expense-scope').value==='node'?Number($('expense-node').value):null,
  provider:$('expense-scope').value==='provider'?$('expense-provider').value.trim():'',
  frequency:$('expense-frequency').value,amount_rial:amountRial,
  start_date:$('expense-start').value,
  end_date:$('expense-frequency').value==='monthly'?$('expense-end').value:'',
  note:$('expense-note').value.trim()
 };
 if($('expense-id').value)obj.id=Number($('expense-id').value);
 const btn=$('expense-form').querySelector('button[type=submit]');btn.disabled=true;
 try{await sendUpdate('/api/fixed-expense',obj);$('expense-dialog').close();await reload();}
 catch(err){alert(err.message);}finally{btn.disabled=false;}
}
function openEdit(node,port){const p=state.ports.find(x=>x.node_id===node&&x.port===port);if(!p)return;
 $('editing').textContent=p.port+' / '+p.node_name; $('node_id').value=node; $('port').value=port;
 $('port_title').value=p.title; $('provider').value=p.provider; $('rate').value=p.price_per_gb*multiplier();
 $('rate-unit').textContent=unit(); $('rate-volume-unit').textContent=volumeUnit();
 $('rate').step=isRial()?'1':'0.01';
 if(isRial())$('rate').value=Math.round(p.price_per_gb*10);
 $('direction').value=p.bill_direction;$('notes').value=p.notes;$('enabled').checked=!!p.enabled;
 if(p.billing_since){sincePicker.set(p.billing_since.slice(0,10));$('since-time').value=p.billing_since.slice(11,16)||'00:00';}
 else{sincePicker.clear();$('since-time').value='00:00';}
 $('edit').showModal();}
async function reload(){try{
 const url='/api/dashboard?'+new URLSearchParams({from:$('from').value,to:$('to').value});
 const r=await fetch(url,{cache:'no-store'});
 if(r.status===401){location.href='/login';return;}
 const data=await r.json();if(!r.ok)throw Error(data.error||'خطا');state=data;
 const nodes=[...new Map(state.ports.map(p=>[p.node_id,p.node_name])).entries()].sort((a,b)=>a[0]-b[0]);
 $('node-filter').innerHTML='<option value="all">همه نودها</option>'+nodes.map(([id,name])=>'<option value="'+id+'">'+escapeHtml(name)+'</option>').join('');
 $('node-filter').value=selectedNode; if($('node-filter').selectedIndex<0){selectedNode='all';$('node-filter').value='all';}
 render();renderManagement();
 }catch(e){$('status').className='notice warn';$('status').textContent=e.message;}}
async function save(e){e.preventDefault();try{
 const body={node_id:Number($('node_id').value),port:Number($('port').value),title:$('port_title').value,
  provider:$('provider').value,price_per_gb:Number($('rate').value)/multiplier(),bill_direction:$('direction').value,
  billing_since:$('since').value?new Date($('since').value+'T'+($('since-time').value||'00:00')+':00Z').toISOString():'',
  notes:$('notes').value,enabled:$('enabled').checked};
 const r=await fetch('/api/metadata',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)});
 const resp=await r.json();if(!r.ok)throw Error(resp.error||'خطا');$('edit').close();await reload();
 }catch(e){alert(e.message);}}
function today(){const d=new Date();return d.toISOString().slice(0,10);}
const themes=new Set(['night','graphite','arctic','forest','sunset']);
function applyTheme(name){
 const key=themes.has(name)?name:'night';
 document.body.dataset.theme=key;
 $('theme-select').value=key;
 try{localStorage.setItem('pgtraffic-theme',key);}catch(e){}
}
let initialTheme='night';
try{initialTheme=localStorage.getItem('pgtraffic-theme')||'night';}catch(e){}
applyTheme(initialTheme);
$('theme-select').addEventListener('change',()=>applyTheme($('theme-select').value));
const initialDay=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tehran'}).format(new Date());
const sincePicker=Jalali.attach('since','since-date-label','since-calendar');
const expenseStartPicker=Jalali.attach('expense-start','expense-start-label','expense-start-calendar');
const expenseEndPicker=Jalali.attach('expense-end','expense-end-label','expense-end-calendar');
$('new-expense').addEventListener('click',()=>showExpense(null));
installWalletForms();
$('expense-scope').addEventListener('change',refreshExpenseForm);
$('expense-frequency').addEventListener('change',refreshExpenseForm);
$('expense-end-clear').addEventListener('click',()=>expenseEndPicker.clear());
$('expense-form').addEventListener('submit',saveExpense);
$('expense-cancel').addEventListener('click',()=>$('expense-dialog').close());

$('since-clear').addEventListener('click',()=>{sincePicker.clear();$('since-time').value='00:00';});
const rangeTo=Jalali.attach('to','to-label','to-calendar',reload);
const rangeFrom=Jalali.attach('from','from-label','from-calendar',reload);
rangeTo.set(initialDay);
rangeFrom.set(new Date(Date.parse(initialDay+'T00:00:00Z')-6*86400000).toISOString().slice(0,10));
$('reload').addEventListener('click',reload);
$('node-filter').addEventListener('change',()=>{selectedNode=$('node-filter').value;render();});
$('chart-scale').addEventListener('change',renderProviderPanels);$('search').addEventListener('input',renderPortReport);$('show_hidden').addEventListener('change',renderPortReport);
$('provider-report-close').addEventListener('click',()=>$('provider-report-dialog').close());
$('display-form').addEventListener('submit',saveDisplaySettings);
$('editform').addEventListener('submit',save);$('cancel').addEventListener('click',()=>$('edit').close());
$('logout').addEventListener('click',async()=>{if(!state){location.href='/login';return;}await fetch('/api/logout',{method:'POST',headers:{'X-CSRF-Token':state.csrf}});location.href='/login';});

function setNavigationOpen(open){
 const nav=$('main-nav');
 nav.dataset.open=open?'true':'false';
 $('nav-toggle').setAttribute('aria-expanded',String(open));
 $('nav-toggle').textContent=open?'✕ بستن':'☰ بخش‌ها';
 $('nav-backdrop').hidden=!open;
}
function highlightSection(href){
 document.querySelectorAll('.section-nav a').forEach(link=>{
  if(link.getAttribute('href')===href)link.setAttribute('aria-current','location');
  else link.removeAttribute('aria-current');
 });
}
$('nav-toggle').addEventListener('click',()=>setNavigationOpen($('main-nav').dataset.open!=='true'));
$('nav-backdrop').addEventListener('click',()=>setNavigationOpen(false));
document.querySelectorAll('.section-nav a').forEach(link=>{
 link.addEventListener('click',()=>{
  highlightSection(link.getAttribute('href'));
  setNavigationOpen(false);
 });
});
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&$('main-nav').dataset.open==='true')setNavigationOpen(false);
});
setNavigationOpen(false);
highlightSection(location.hash||'#overview');

reload();

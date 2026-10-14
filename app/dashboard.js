'use strict';
const $=id=>document.getElementById(id);
let state=null;
const fmt=n=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(n||0);
const traffic=n=>(n/1e9>=1?fmt(n/1e9)+' GB':fmt(n/1e6)+' MB');
const money=n=>fmt(n)+' '+(state?.currency||'تومان');
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function age(s){if(!s)return '—'; const dt=new Date(s);return dt.toLocaleString('fa-IR',{timeZone:state.timezone,dateStyle:'short',timeStyle:'short'});}
function chart(points){if(!points.length){$('chart').textContent='برای این بازه هنوز داده‌ای ثبت نشده است.';return;}
 const w=1000,h=240,pad=35,max=Math.max(1,...points.flatMap(x=>[x.down,x.up]));
 const xs=i=>pad+(w-2*pad)*i/Math.max(1,points.length-1),ys=y=>h-pad-(h-2*pad)*y/max;
 const line=(key,color)=>`<path d="${points.map((v,i)=>(i?'L':'M')+xs(i).toFixed(1)+' '+ys(v[key]).toFixed(1)).join(' ')}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
 let grid='';for(let i=0;i<=4;i++){const y=pad+(h-2*pad)*i/4;grid+=`<line x1="${pad}" y1="${y}" x2="${w-pad}" y2="${y}" stroke="#294059" stroke-width="1"/>`;}
 $('chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="نمودار دانلود و آپلود روزانه">${grid}${line('down','#62aefe')}${line('up','#42d5bd')}</svg>`;
}
function render(){if(!state)return;
 $('title').textContent=state.title;
 $('down').textContent=traffic(state.total.down);
 $('up').textContent=traffic(state.total.up);
 $('billed').textContent=traffic(state.total.billed);
 $('cost').textContent=money(state.total.cost);
 const lr=state.last_run;
 $('status').className='notice'+(lr&&JSON.parse(lr.errors_json).length?' warn':'');
 $('status').textContent=lr?'آخرین نمونه‌برداری: '+age(lr.collected_at)+' | تعداد نمونه: '+fmt(lr.sample_count)+(JSON.parse(lr.errors_json).length?' | هشدار: '+JSON.parse(lr.errors_json).join('، '):''):'هنوز نمونه‌ای ثبت نشده؛ یک بار دستور collect را اجرا کنید.';
 chart(state.daily);
 $('providers').innerHTML=Object.entries(state.providers).sort((a,b)=>b[1].cost-a[1].cost).map(([name,p])=>`<div class="provider"><strong>${escapeHtml(name)}</strong><small>مصرف مشمول هزینه: ${traffic(p.billed)}</small><small>هزینه: ${money(p.cost)}</small></div>`).join('')||'<p>آماری وجود ندارد.</p>';
 const q=$('search').value.trim().toLowerCase();
 const ports=state.ports.filter(p=>(p.enabled||$('show_hidden').checked)&&[p.node_name,p.port,p.title,p.provider,p.tag].join(' ').toLowerCase().includes(q));
 $('ports').innerHTML=ports.map(p=>`<tr class="${p.enabled?'':'muted'}"><td><strong>${escapeHtml(p.node_name)}</strong><span class="sub">پورت ${p.port} · نود ${p.node_id}</span></td><td>${escapeHtml(p.title||'بدون نام دلخواه')}<span class="sub">${escapeHtml(p.provider||'تعرفه تعیین نشده')} · <span class="tag">${escapeHtml(p.tag)}</span></span></td><td>${traffic(p.down)}</td><td>${traffic(p.up)}</td><td class="money">${money(p.cost)}</td><td>${age(p.last_seen)}</td><td><button class="editbtn" data-nid="${p.node_id}" data-port="${p.port}">ویرایش</button></td></tr>`).join('')||'<tr><td colspan="7">پورتی پیدا نشد.</td></tr>';
 document.querySelectorAll('.editbtn').forEach(btn=>btn.addEventListener('click',()=>openEdit(Number(btn.dataset.nid),Number(btn.dataset.port))));
 $('export').href='/api/export.csv?'+new URLSearchParams({from:$('from').value,to:$('to').value});
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
  '<form class="node-form" data-node="'+id+'"><div class="port-checks">'+group.ports.map(p=>
   '<label class="port-check"><input type="checkbox" value="'+p.port+'" '+(p.enabled?'checked':'')+
   '> '+p.port+'</label>').join('')+'</div>'+
  '<div class="buttons"><button type="button" class="minor bulk" data-action="all">انتخاب همه</button>'+
  '<button type="button" class="minor bulk" data-action="none">لغو همه</button>'+
  '<button class="primary" type="submit">ذخیره پورت‌های این نود</button></div></form></article>').join('');
 document.querySelectorAll('.node-form').forEach(form=>{
  form.addEventListener('submit',saveNodePorts);
  form.querySelectorAll('.bulk').forEach(button=>button.addEventListener('click',()=>{
   form.querySelectorAll('input[type=checkbox]').forEach(box=>{box.checked=button.dataset.action==='all';});
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
 const ports=[...form.querySelectorAll('input[type=checkbox]:checked')].map(x=>Number(x.value));
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
 $('port_title').value=p.title; $('provider').value=p.provider; $('rate').value=p.price_per_gb;
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
  provider:$('provider').value,price_per_gb:Number($('rate').value),bill_direction:$('direction').value,
  billing_since:$('since').value?new Date($('since').value+'Z').toISOString():'',
  notes:$('notes').value,enabled:$('enabled').checked};
 const r=await fetch('/api/metadata',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)});
 const resp=await r.json();if(!r.ok)throw Error(resp.error||'خطا');$('edit').close();await reload();
 }catch(e){alert(e.message);}}
function today(){const d=new Date();return d.toISOString().slice(0,10);}
const d=new Date();$('to').value=today();d.setDate(d.getDate()-6);$('from').value=d.toISOString().slice(0,10);
$('reload').addEventListener('click',reload);$('search').addEventListener('input',render);$('show_hidden').addEventListener('change',render);
$('display-form').addEventListener('submit',saveDisplaySettings);
$('editform').addEventListener('submit',save);$('cancel').addEventListener('click',()=>$('edit').close());
$('logout').addEventListener('click',async()=>{if(!state){location.href='/login';return;}await fetch('/api/logout',{method:'POST',headers:{'X-CSRF-Token':state.csrf}});location.href='/login';});
reload();

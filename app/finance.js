'use strict';
/* Daily business ledger: Gregorian ISO in SQLite, Persian calendar for display.
   Read-only cost report; only a deliberate authenticated sales POST writes data. */
const Finance=(()=>{
 const el=id=>document.getElementById(id);
 const moneyFa=new Intl.NumberFormat('fa-IR',{maximumFractionDigits:0});
 const daysOfWeek=['شنبه','یکشنبه','دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه'];
 const monthFormat=new Intl.DateTimeFormat('fa-IR-u-ca-persian',
    {calendar:'persian',month:'long',year:'numeric',timeZone:'UTC'});
 let report=null,selected=null,month=null;
 const todayGuess=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tehran'}).format(new Date());
 function shiftISO(day,amount){
  const ms=Date.parse(day+'T00:00:00Z')+amount*86400000;
  return new Date(ms).toISOString().slice(0,10);
 }
 function nextMonth(y,m,delta){const i=y*12+m-1+delta;return [Math.floor(i/12),((i%12)+12)%12+1];}
 function monthSpan(){
  const first=Jalali.toISO(month[0],month[1],1);
  const next=nextMonth(month[0],month[1],1);
  const last=shiftISO(Jalali.toISO(next[0],next[1],1),-1);
  return {first,last};
 }
 function weekStart(day){
  const dow=new Date(day+'T00:00:00Z').getUTCDay();
  return shiftISO(day,-((dow+1)%7));
 }
 function formatRial(amount){
  if(amount===null||amount===undefined)return '—';
  const rial=!(report&&['تومان','Toman'].includes(report.display_currency));
  return moneyFa.format(Math.round(rial?amount:amount/10))+(rial?' ریال':' تومان');
 }
 function rowFor(day){return report?.days.find(item=>item.day===day)||null;}
 function totals(rows){
  const relevant=rows.filter(r=>r&&r.status!=='future'&&r.status!=='before_tracking');
  const sales=relevant.reduce((n,r)=>n+(r.sales_rial??0),0);
  const accounts=relevant.reduce((n,r)=>n+(r.accounts_sold??0),0);
  const traffic=relevant.reduce((n,r)=>n+r.traffic_rial,0);
  const fixed=relevant.reduce((n,r)=>n+r.fixed_rial,0);
  const missing=relevant.filter(r=>r.sales_rial===null).length;
  const recorded=relevant.length-missing;
  return {sales,accounts,traffic,fixed,expenses:traffic+fixed,
    profit:recorded>0&&missing===0?sales-traffic-fixed:null,missing,recorded};
 }
 function summaryCard(title,rows,period){
  const t=totals(rows);
  const stat=t.missing?'<span class="finance-summary-warning">'+moneyFa.format(t.missing)+' روز ثبت‌نشده</span>':
     t.recorded?'<span class="finance-summary-ok">اطلاعات کامل</span>':
     '<span class="finance-summary-muted">هنوز داده‌ای نیست</span>';
  return '<article class="finance-summary-card"><div class="finance-summary-title">'+
   '<strong>'+title+'</strong><span>'+period+'</span></div>'+
   '<div class="finance-summary-sale">'+formatRial(t.sales)+'</div>'+
   '<span class="finance-summary-caption">فروش ثبت‌شده · '+moneyFa.format(t.accounts)+' اکانت</span>'+
   '<div class="finance-summary-details"><span>ترافیک <b>'+formatRial(t.traffic)+'</b></span>'+
   '<span>سهم هزینه ثابت <b>'+formatRial(t.fixed)+'</b></span>'+
   '<span class="finance-net">سود برآوردی <b>'+formatRial(t.profit)+'</b></span></div>'+stat+'</article>';
 }
 function renderSummary(){
  if(!report||!selected)return;
  const {first,last}=monthSpan();
  const start=weekStart(selected);
  const weekEnd=shiftISO(start,6);
  const days=report.days;
  el('finance-summary').innerHTML=
    summaryCard('روز انتخاب‌شده',days.filter(r=>r.day===selected),Jalali.label(selected))+
    summaryCard('هفته انتخابی',days.filter(r=>r.day>=start&&r.day<=weekEnd),
                Jalali.label(start)+' تا '+Jalali.label(weekEnd))+
    summaryCard('ماه انتخابی',days.filter(r=>r.day>=first&&r.day<=last),
                monthFormat.format(new Date(first+'T12:00:00Z')));
 }
 function renderCalendar(){
  if(!report||!month)return;
  const {first,last}=monthSpan();
  const length=Math.round((Date.parse(last)-Date.parse(first))/86400000)+1;
  const firstOffset=(new Date(first+'T00:00:00Z').getUTCDay()+1)%7;
  el('finance-month-title').textContent=monthFormat.format(new Date(first+'T12:00:00Z'));
  let html=daysOfWeek.map(d=>'<span class="finance-weekday">'+d+'</span>').join('');
  for(let i=0;i<firstOffset;i++)html+='<span class="finance-calendar-empty"></span>';
  for(let d=1;d<=length;d++){
   const day=shiftISO(first,d-1),r=rowFor(day),status=r?.status||'future';
   let badge='—';
   if(status==='recorded')badge=formatRial(r.sales_rial);
   if(status==='missing')badge='ثبت نشده';
   if(status==='pending_today')badge='امروز';
   if(status==='before_tracking')badge='قبل از مانیتور';
   if(status==='future')badge='آینده';
   html+='<button type="button" class="finance-day finance-day-'+status+
     (selected===day?' finance-day-selected':'')+
     '" data-finance-day="'+day+'" aria-pressed="'+(selected===day?'true':'false')+'"'+
     (status==='future'?' disabled':'')+'><strong>'+moneyFa.format(d)+'</strong>'+
     '<small>'+badge+'</small><span class="finance-day-dot" aria-hidden="true"></span></button>';
  }
  el('finance-calendar').innerHTML=html;
  el('finance-calendar').querySelectorAll('[data-finance-day]').forEach(btn=>
   btn.addEventListener('click',()=>pickDay(btn.dataset.financeDay)));
  const missed=report.days.filter(r=>r.day>=first&&r.day<=last&&r.status==='missing').length;
  const warn=[];
  if(report.yesterday_missing)warn.push('فروش دیروز هنوز ثبت نشده است.');
  if(missed)warn.push(moneyFa.format(missed)+' روز گذشته از این ماه ثبت نشده.');
  if(report.today===selected&&rowFor(selected)?.status==='pending_today')warn.push('فروش امروز هنوز ثبت نشده است.');
  el('finance-alert').hidden=!warn.length;
  el('finance-alert').textContent=warn.join(' ');
 }
 function renderWeek(){
  if(!report||!selected)return;
  const start=weekStart(selected),end=shiftISO(start,6);
  el('finance-week-range').textContent=Jalali.label(start)+' تا '+Jalali.label(end);
  const rows=report.days.filter(r=>r.day>=start&&r.day<=end);
  el('finance-week-rows').innerHTML=rows.map(r=>{
   const sale=r.sales_rial===null?(r.status==='future'?'آینده':r.status==='before_tracking'?'قبل از مانیتور':'ثبت نشده'):formatRial(r.sales_rial);
   return '<tr'+(r.day===selected?' class="finance-row-selected"':'')+'>'+
    '<td><button class="finance-day-link" type="button" data-finance-day="'+r.day+'"'+
      (r.status==='future'?' disabled':'')+'>'+Jalali.label(r.day)+'</button></td>'+
    '<td>'+sale+'</td><td>'+(r.accounts_sold===null?'—':moneyFa.format(r.accounts_sold))+'</td>'+
    '<td>'+formatRial(r.traffic_rial)+'</td><td>'+formatRial(r.fixed_rial)+'</td>'+
    '<td class="'+(r.profit_rial===null?'finance-unknown':'finance-result')+'">'+formatRial(r.profit_rial)+'</td></tr>';
  }).join('')||'<tr><td colspan="6">آماری موجود نیست</td></tr>';
  el('finance-week-rows').querySelectorAll('[data-finance-day]').forEach(btn=>
    btn.addEventListener('click',()=>pickDay(btn.dataset.financeDay)));
 }
 function renderEditor(){
  const item=rowFor(selected);
  el('finance-selected-day').textContent=selected?Jalali.label(selected):'—';
  el('finance-amount').value=item?.sales_rial??'';
  el('finance-accounts').value=item?.accounts_sold??'';
  el('finance-note').value=item?.note||'';
  const future=!item||item.status==='future';
  for(const id of ['finance-amount','finance-accounts','finance-note','finance-save'])
    el(id).disabled=future;
  el('finance-save').textContent=item?.sales_rial===null?'ثبت فروش این روز':'اصلاح فروش ثبت‌شده';
  el('finance-save-status').textContent=future?'برای آینده نمی‌توان فروش ثبت کرد.':
    item?.sales_rial===null?'برای روز بدون فروش، صفر ریال و صفر اکانت ثبت کن.':
    'فروش این روز قبلاً ثبت شده؛ می‌توانی آن را ویرایش کنی.';
  el('finance-day-breakdown').innerHTML=item?
    '<h3>هزینه‌های روز انتخاب‌شده</h3>'+
    '<p><span>هزینه ترافیک</span><strong>'+formatRial(item.traffic_rial)+'</strong></p>'+
    '<p><span>سهم هزینه ثابت و جانبی</span><strong>'+formatRial(item.fixed_rial)+'</strong></p>'+
    '<p class="finance-breakdown-net"><span>سود برآوردی</span><strong>'+formatRial(item.profit_rial)+'</strong></p>':'';
 }
 function pickDay(day){
  selected=day;
  renderCalendar();renderSummary();renderWeek();renderEditor();
 }
 async function loadMonth(){
  const {first,last}=monthSpan();
  el('finance-save-status').textContent='در حال دریافت گزارش...';
  try{
   const from=shiftISO(first,-6),to=shiftISO(last,6);
   const res=await fetch('/api/finance/report?'+new URLSearchParams({from,to}),{cache:'no-store'});
   if(res.status===401){location.href='/login';return;}
   const json=await res.json();if(!res.ok)throw Error(json.error||'خطای گزارش فروش');
   report=json;
   if(!selected||selected<first||selected>last)
    selected=(json.today>=first&&json.today<=last)?json.today:first;
   renderCalendar();renderSummary();renderWeek();renderEditor();
  }catch(err){
   el('finance-alert').hidden=false;
   el('finance-alert').textContent='بارگذاری گزارش فروش ناموفق بود: '+err.message;
   el('finance-save-status').textContent='گزارش بارگذاری نشد.';
  }
 }
 async function submit(event){
  event.preventDefault();
  const amount=Number(el('finance-amount').value);
  const accounts=Number(el('finance-accounts').value);
  if(!Number.isSafeInteger(amount)||amount<0||!Number.isSafeInteger(accounts)||accounts<0){
   el('finance-save-status').textContent='مبلغ ریالی و تعداد اکانت باید عدد صحیح و نامنفی باشند.';
   return;
  }
  // The main authenticated dashboard provides the same CSRF token; never save
  // through GET or without a deliberate user submit.
  const btn=el('finance-save');btn.disabled=true;
  try{
   const token=state?.csrf;
   if(!token)throw Error('جلسه ورود آماده نیست؛ صفحه را تازه‌سازی کن.');
   const res=await fetch('/api/finance/sale',{method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':token},
    body:JSON.stringify({day:selected,amount_rial:amount,accounts_sold:accounts,note:el('finance-note').value})});
   const json=await res.json();if(!res.ok)throw Error(json.error||'ثبت فروش انجام نشد');
   await loadMonth();
   el('finance-save-status').textContent='فروش روز '+Jalali.label(selected)+' با موفقیت ذخیره شد.';
  }catch(err){el('finance-save-status').textContent='خطا: '+err.message;}
  finally{btn.disabled=false;}
 }
 function moveMonth(delta){
  const [y,m]=nextMonth(month[0],month[1],delta);
  if(y<1280||y>1497)return;
  month=[y,m];selected=null;loadMonth();
 }
 function start(){
  const today=todayGuess();selected=today;month=Jalali.fromISO(today).slice(0,2);
  el('finance-prev').addEventListener('click',()=>moveMonth(-1));
  el('finance-next').addEventListener('click',()=>moveMonth(1));
  el('finance-go-today').addEventListener('click',()=>{
   month=Jalali.fromISO(report?.today||todayGuess()).slice(0,2);
   selected=report?.today||todayGuess();loadMonth();
  });
  el('finance-form').addEventListener('submit',submit);
  loadMonth();
 }
 return {start,shiftISO,weekStart,totals};
})();
Finance.start();

'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const Jalali=require('../app/jalali.js');
const html=fs.readFileSync(path.join(__dirname,'../app/dashboard.html'),'utf8');
const css=fs.readFileSync(path.join(__dirname,'../app/style.css'),'utf8');
for(const id of ['finance','finance-form','finance-amount','finance-accounts','finance-calendar',
                  'finance-summary','finance-week-rows','finance-alert'])
 assert.ok(html.includes('id="'+id+'"'),'missing UI '+id);
assert.ok(html.includes('src="/finance.js"'));
assert.ok(css.includes('.finance-layout'));
assert.ok(css.includes('@media(max-width:580px)'));
const elements=new Map();
function el(id){
 if(!elements.has(id))elements.set(id,{
  id,textContent:'',innerHTML:'',value:'',hidden:false,disabled:false,
  listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},
  querySelectorAll(){return[];},
 });
 return elements.get(id);
}
function isoShift(day,n){return new Date(Date.parse(day+'T00:00:00Z')+n*86400000).toISOString().slice(0,10)}
const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tehran'}).format(new Date());
const yesterday=isoShift(today,-1);
const before=isoShift(today,-2);
const entries=new Map([[before,{amount_rial:90000,accounts_sold:3,note:'okay'}]]);
const requests=[];
const state={csrf:'test-csrf'};
const context={document:{getElementById:el},Intl,Date,URLSearchParams,Jalali,
  location:{href:''},console,state,
  fetch:async(url,options={})=>{
   requests.push({url,options});
   if(String(url).startsWith('/api/finance/sale')){
    assert.equal(options.method,'POST');
    assert.equal(options.headers['X-CSRF-Token'],state.csrf);
    const value=JSON.parse(options.body);
    entries.set(value.day,value);
    return {ok:true,status:200,json:async()=>({ok:true})};
   }
   assert.ok(String(url).startsWith('/api/finance/report?'));
   const u=new URL(String(url),'http://example.org');
   const from=u.searchParams.get('from'),to=u.searchParams.get('to');
   const days=[];
   for(let d=from;d<=to;d=isoShift(d,1)){
    const sale=entries.get(d);
    days.push({day:d,status:d>today?'future':sale?'recorded':d<before?'before_tracking':
      d===today?'pending_today':'missing',sales_rial:sale?sale.amount_rial:null,
      accounts_sold:sale?sale.accounts_sold:null,note:sale?sale.note:'',
      fixed_rial:1000,traffic_rial:500,expenses_rial:1500,
      profit_rial:sale?sale.amount_rial-1500:null});
   }
   return {ok:true,status:200,json:async()=>({
    days,today,display_currency:'Rial',yesterday_missing:!entries.has(yesterday),
    tracking_started_on:before
   })};
  }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/finance.js'),'utf8'),context);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 assert.ok(el('finance-calendar').innerHTML.includes('finance-day-recorded'));
 assert.ok(el('finance-calendar').innerHTML.includes('finance-day-missing'));
 assert.ok(el('finance-summary').innerHTML.includes('روز انتخاب‌شده'));
 assert.ok(el('finance-summary').innerHTML.includes('هفته انتخابی'));
 assert.ok(el('finance-summary').innerHTML.includes('ماه انتخابی'));
 assert.ok(el('finance-alert').textContent.includes('دیروز'));
 assert.equal(vm.runInContext("Finance.weekStart('2026-10-16')",context),'2026-10-10');
 assert.equal(vm.runInContext("Finance.totals([{status:'missing',sales_rial:null,accounts_sold:null,traffic_rial:0,fixed_rial:0}]).profit",context),null);
 assert.equal(vm.runInContext("Finance.totals([{status:'recorded',sales_rial:0,accounts_sold:0,traffic_rial:100,fixed_rial:200}]).profit",context),-300);
 el('finance-amount').value='0';
 el('finance-accounts').value='0';
 await el('finance-form').listeners.submit({preventDefault(){}});
 assert.ok(entries.has(today),'zero sale was not posted');
 assert.equal(entries.get(today).amount_rial,0);
 assert.equal(entries.get(today).accounts_sold,0);
 assert.ok(el('finance-save-status').textContent.includes('موفقیت'));
 assert.ok(el('finance-calendar').innerHTML.includes('finance-day-recorded'));
 console.log('Daily finance calendar and mobile sales entry tests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const realJalali=require('../app/jalali.js');
const elements=new Map();
function elem(id){
 if(!elements.has(id)){
  elements.set(id,{id,value:'',innerHTML:'',textContent:'',checked:false,dataset:{},
   attributes:{},setAttribute(k,v){this.attributes[k]=String(v);},
   removeAttribute(k){delete this.attributes[k];},
   getAttribute(k){return this.attributes[k]||null;},
   addEventListener(){},querySelectorAll(){return[];},showModal(){},close(){},selectedIndex:0});
 }
 return elements.get(id);
}
const Jalali={...realJalali,attach(field,displayId){
  return {
    set(value){elem(field).value=value;elem(displayId).value=realJalali.label(value);},
    clear(){elem(field).value='';elem(displayId).value='';},
    get(){return elem(field).value;}
  };
}};
const dashboardTemplate=fs.readFileSync(path.join(__dirname,'../app/dashboard.html'),'utf8');
const navigationLabels=['نمای کلی','حساب‌ها و ارائه‌دهندگان','پورت‌ها','هزینه‌های ثابت','تنظیمات'];
for(const name of navigationLabels)assert.ok(dashboardTemplate.includes('>'+name+'</a>'),'missing navigation: '+name);
assert.ok(dashboardTemplate.indexOf('id="expenses"')>dashboardTemplate.indexOf('id="manage"'),
 'Fixed costs must follow management/settings section');
assert.ok(dashboardTemplate.includes('class="expense-formula"'));
assert.ok(dashboardTemplate.includes('class="workspace-hero"'));
assert.ok(dashboardTemplate.includes('id="reconciliation-overview"'));
assert.ok(dashboardTemplate.includes('class="finance-report-details"'));
assert.ok(dashboardTemplate.includes('class="analysis-disclosure provider-trends"'));
assert.ok(dashboardTemplate.includes('class="panel workspace-view" id="settings-section"'));
assert.ok(dashboardTemplate.includes('id="manage"') && !dashboardTemplate.includes('<div class="prefs" id="settings-section"'));
assert.ok(dashboardTemplate.includes('id="main-nav"'));
assert.ok(dashboardTemplate.includes('id="nav-toggle"'));
assert.ok(dashboardTemplate.includes('id="nav-backdrop"'));
assert.ok(dashboardTemplate.includes('id="provider-report-dialog"'));
assert.ok(dashboardTemplate.includes('id="provider-rename-form"'));
assert.ok(dashboardTemplate.includes('id="wallet-identity-form"'));
assert.ok(dashboardTemplate.includes('<th>قیمت واحد (فعلی)</th>'));
assert.ok(dashboardTemplate.includes('<tbody id="ports"><tr><td colspan="8">'));
assert.ok(dashboardTemplate.includes('id="rate-volume-unit"'));
assert.ok(!dashboardTemplate.includes('تعرفه هر GB (یک میلیارد بایت)'))
assert.ok(!dashboardTemplate.includes('id="ports-section"'));
for(const id of ['provider-wallet-dialog','provider-wallet-name','provider-wallet-opening','wallet-credit-dialog','wallet-reported-dialog']){
 assert.ok(dashboardTemplate.includes('id="'+id+'"'),'missing supplier UI: '+id);
}
const css=fs.readFileSync(path.join(__dirname,'../app/style.css'),'utf8');
assert.ok(css.includes('position:fixed;inset:16px 16px 16px auto'));
assert.ok(css.includes('.section-nav[data-open="true"]'));
assert.ok(css.includes('v2.1 provider directory'));
assert.ok(css.includes('.provider-account-fold[open]'));
assert.ok(css.includes('.providers{\n display:flex;flex-direction:column'));
assert.ok(css.includes('.workspace-view[hidden]{display:none!important}'));
assert.ok(css.includes('.reconciliation-overview{'));

const storage=new Map();
const daily=[
 {period:'2026-10-14',node_id:3,node_name:'Turkey',provider:'A',down:2000000000,up:500000000,cost:120.234,historical_cost:15},
 {period:'2026-10-15',node_id:7,node_name:'Germany',provider:'A',down:3000000000,up:100000000,cost:250.5,historical_cost:25},
 {period:'2026-11-14',node_id:3,node_name:'Turkey',provider:'A',down:1000000000,up:0,cost:90,historical_cost:20}
];
const ports=[
 {node_id:3,node_name:'Turkey',port:8443,provider:'A',title:'A',tag:'t',down:3000000000,up:500000000,billed:3500000000,cost:210.234,historical_cost:35,total_down:1,total_up:1,enabled:1,price_per_gb:850,bill_direction:'both',notes:'',billing_since:'2026-10-14T00:00:00Z'},
 {node_id:7,node_name:'Germany',port:2053,provider:'A',title:'B',tag:'g',down:3000000000,up:100000000,billed:3100000000,cost:250.5,historical_cost:25,total_down:1,total_up:1,enabled:1,price_per_gb:1200,bill_direction:'both',notes:'',billing_since:''}
];
const data={ports,daily_by_provider:daily,hourly_by_provider:[],hourly_available:true,
 providers:{A:{down:6000000000,up:600000000,billed:6600000000,cost:460.734,historical_cost:60}},
 total:{down:6000000000,up:600000000,billed:6600000000,cost:460.734,historical_cost:60},
 last_run:null,currency:'ریال',title:'Traffic',timezone:'Asia/Tehran',csrf:'testing',period:{from:'2026-10-14',to:'2026-11-14'}};
const ctx={document:{body:{dataset:{}},getElementById:elem,querySelectorAll(){return[];},addEventListener(){}},
 Jalali,Intl,Date,URLSearchParams,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
 fetch:async()=>({ok:true,status:200,json:async()=>data}),
 location:{href:''},console,setTimeout,clearTimeout};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/dashboard.js'),'utf8'),ctx,{filename:'dashboard.js'});
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 elem('provider-wallet-opening').value='2437750';
 assert.equal(vm.runInContext("walletInputNumber('provider-wallet-opening','money')",ctx),2437750);
 vm.runInContext("state.currency='تومان'",ctx);
 elem('provider-wallet-opening').value='243775';
 assert.equal(vm.runInContext("walletInputNumber('provider-wallet-opening','money')",ctx),2437750);
 vm.runInContext("state.currency='ریال'",ctx);
 elem('provider-wallet-opening').value='9.5';
 assert.equal(vm.runInContext("walletInputNumber('provider-wallet-opening','volume')",ctx),Math.round(9.5*1024**3));
 // All new traffic display and wallet accounting use IEC GiB.
 assert.equal(vm.runInContext('traffic(1073741824)',ctx),'۱ GiB');
 assert.equal(vm.runInContext("walletAmount(1073741824,'volume')",ctx),'۱ GiB');
 vm.runInContext("state.traffic_unit='GB'",ctx);
 assert.equal(vm.runInContext('traffic(1000000000)',ctx),'۱ GB');
 vm.runInContext('openEdit(3,8443)',ctx);
 assert.equal(elem('rate-volume-unit').textContent,'GB');
 assert.equal(vm.runInContext("walletAmount(1000000000,'volume')",ctx),'۱ GB');
 elem('provider-wallet-opening').value='9.5';
 assert.equal(vm.runInContext("walletInputNumber('provider-wallet-opening','volume')",ctx),9500000000);
 vm.runInContext("state.traffic_unit='GiB'",ctx);
 vm.runInContext('openEdit(3,8443)',ctx);
 assert.equal(elem('rate-volume-unit').textContent,'GiB');

 assert.throws(()=>vm.runInContext("walletInputNumber('provider-wallet-opening','money')",ctx));
 vm.runInContext("state.wallets=[{id:11,provider:'A',title:'A',kind:'money',bot_handle:'@sample',estimated_balance:2422750,opening_rial:2437750,opening_bytes:0,credited:0,spent_rial:15000,used_bytes:1250000000,reported_balance:null,started_at:'2026-10-14T00:00:00+00:00',ports:[],credit_history:[],check_history:[]}];renderProviderPanels()",ctx);
 assert.ok(elem('providers').innerHTML.includes('۲٬۴۲۲٬۷۵۰'));
 assert.ok(elem('providers').innerHTML.includes('provider-credit'));
 assert.ok(elem('providers').innerHTML.includes('wallet-identity-edit'));
 assert.ok(elem('providers').innerHTML.includes('provider-rename-button'));
 assert.ok(elem('providers').innerHTML.includes('provider-overview'));
 assert.ok(elem('providers').innerHTML.includes('provider-stats'));
 assert.ok(elem('providers').innerHTML.includes('provider-balance-chip'));
 assert.ok(elem('providers').innerHTML.includes('provider-account-summary'));
 assert.ok(elem('providers').innerHTML.includes('۲ پورت'));
 assert.ok(elem('providers').innerHTML.includes('۲٬۴۲۲٬۷۵۰ ریال'));
 vm.runInContext("expandedProviderAccounts.add('A');renderProviderPanels()",ctx);
 assert.ok(elem('providers').innerHTML.includes('class="provider-account-fold" data-provider="A" open'));
 vm.runInContext("selectedProvider='A';renderProviderPanels()",ctx);
 assert.ok(elem('providers').innerHTML.includes('class="provider-account-fold" data-provider="A" open'));
 vm.runInContext("selectedProvider='__all__'",ctx);
 vm.runInContext("state.wallets[0].reconciliation_summary={count:3,positive:150000,negative:100000,net:50000};state.wallets[0].reconciliation_history=[{id:3,checked_at:'2026-10-17T12:00:00+00:00',estimated_before:2300000,reported_amount:2250000,adjustment:-50000,note:'third'}, {id:2,checked_at:'2026-10-16T12:00:00+00:00',estimated_before:2150000,reported_amount:2300000,adjustment:150000,note:'second'},{id:1,checked_at:'2026-10-14T12:00:00+00:00',estimated_before:2300000,reported_amount:2250000,adjustment:-50000,note:'first'}];renderProviderPanels()",ctx);
 vm.runInContext("state.wallets[0].latest_active_reconciliation_id=3;renderProviderPanels()",ctx);
 assert.ok(elem('providers').innerHTML.includes('wallet-reconcile-undo'));
 assert.ok(elem('providers').innerHTML.includes('data-reconciliation="3"'));
 assert.ok(!elem('providers').innerHTML.includes('data-reconciliation="2"'));
 vm.runInContext("state.wallets[0].reconciliation_history[0].voided_at='2026-10-17T13:00:00+00:00';state.wallets[0].reconciliation_history[0].void_reason='اشتباه وارد شد';state.wallets[0].latest_active_reconciliation_id=2;renderProviderPanels()",ctx);
 assert.ok(elem('providers').innerHTML.includes('لغوشده'));
 assert.ok(elem('providers').innerHTML.includes('اشتباه وارد شد'));
 assert.ok(!elem('providers').innerHTML.includes('data-reconciliation="3"'));
 assert.ok(elem('providers').innerHTML.includes('data-reconciliation="2"'));
 assert.ok(elem('providers').innerHTML.includes('تاریخچه همسان‌سازی'));
 assert.ok(elem('providers').innerHTML.includes('اختلاف خالص'));
 assert.ok(elem('providers').innerHTML.includes('second'));
 assert.ok(elem('providers').innerHTML.includes('first'));
 assert.ok(elem('providers').innerHTML.includes('گزارش پورت‌ها'));
 assert.ok(elem('providers').innerHTML.includes('provider-quick-create'));
 assert.ok(elem('reconciliation-overview').innerHTML.includes('آخرین مغایرت‌های ثبت‌شده'));
 assert.ok(elem('reconciliation-overview').innerHTML.includes('مشاهده حساب'));

 vm.runInContext("openProviderReport('A')",ctx);
 assert.ok(elem('provider-report-title').textContent.includes('A'));
 assert.ok(elem('ports').innerHTML.includes('unassign-port'));
 assert.ok(elem('ports').innerHTML.includes('حذف از ارائه‌دهنده'));
 // Each port displays its own CURRENT rate; formatting follows global unit
 // chosen during installation and currency currently shown in the panel.
 assert.ok(elem('ports').innerHTML.includes('۸٬۵۰۰ ریال / GiB'));
 assert.ok(elem('ports').innerHTML.includes('۱۲٬۰۰۰ ریال / GiB'));
 vm.runInContext("state.currency='تومان';renderPortReport()",ctx);
 assert.ok(elem('ports').innerHTML.includes('۸۵۰ تومان / GiB'));
 assert.ok(elem('ports').innerHTML.includes('۱٬۲۰۰ تومان / GiB'));
 vm.runInContext("state.traffic_unit='GB';renderPortReport()",ctx);
 assert.ok(elem('ports').innerHTML.includes('۸۵۰ تومان / GB'));
 assert.ok(elem('ports').innerHTML.includes('۱٬۲۰۰ تومان / GB'));
 vm.runInContext("state.currency='ریال';state.traffic_unit='GiB';renderPortReport()",ctx);

 assert.ok(elem('ports').innerHTML.includes('Germany'));
 assert.ok(elem('ports').innerHTML.includes('Turkey'));
 vm.runInContext("state.wallets=[];renderProviderPanels()",ctx);
 assert.ok(elem('providers').innerHTML.includes('حساب اعتبار جدید'));
 assert.equal(elem('main-nav').dataset.open,'false');
 assert.equal(elem('nav-toggle').attributes['aria-expanded'],'false');
 vm.runInContext('setNavigationOpen(true)',ctx);
 assert.equal(elem('main-nav').dataset.open,'true');
 assert.equal(elem('nav-toggle').attributes['aria-expanded'],'true');
 assert.equal(elem('nav-backdrop').hidden,false);
 vm.runInContext('setNavigationOpen(false)',ctx);
 assert.equal(elem('main-nav').dataset.open,'false');
 assert.equal(elem('nav-backdrop').hidden,true);
 // One task-focused workspace is visible at a time; no counters or wallets reset.
 assert.equal(elem('workspace-overview').hidden,false);
 assert.equal(elem('overview').hidden,false);
 for(const page of ['finance','providers-section','manage','expenses','settings-section'])
  assert.equal(elem(page).hidden,true);
 vm.runInContext("activateWorkspace('#providers-section')",ctx);
 assert.equal(elem('providers-section').hidden,false);
 assert.equal(elem('overview').hidden,false);
 assert.equal(elem('workspace-overview').hidden,true);
 assert.equal(elem('finance').hidden,true);
 vm.runInContext("activateWorkspace('#finance')",ctx);
 assert.equal(elem('finance').hidden,false);
 assert.equal(elem('overview').hidden,true);
 assert.equal(elem('providers-section').hidden,true);
 vm.runInContext("activateWorkspace('#settings-section')",ctx);
 assert.equal(elem('settings-section').hidden,false);
 assert.equal(elem('manage').hidden,true);
 vm.runInContext("activateWorkspace('#not-a-page')",ctx);
 assert.equal(elem('workspace-overview').hidden,false);

 const n=vm.runInContext('chartColors.length',ctx);
 const unique=vm.runInContext('new Set(chartColors).size',ctx);
 assert.equal(n,20);assert.equal(unique,20);
 assert.equal(vm.runInContext('timeseries("monthly").length',ctx),2);
 assert.equal(vm.runInContext('timeseries("monthly")[0].nodes.get(3).down',ctx),2000000000);
 assert.equal(vm.runInContext('timeseries("monthly")[0].nodes.get(7).down',ctx),3000000000);
 assert.equal(vm.runInContext('timeseries("monthly")[1].nodes.get(3).down',ctx),1000000000);
 assert.equal(vm.runInContext('timeseries("daily").length',ctx),3);
 assert.equal(vm.runInContext('money(1234.567)',ctx).includes('٫'),false);
 assert.equal(vm.runInContext('money(1234.567)',ctx).includes('.'),false);
 assert.equal(vm.runInContext('money(1234.567)',ctx).endsWith(' ریال'),true);
 elem('chart-scale').value='monthly';
 vm.runInContext('renderProviderPanels()',ctx);
 assert.ok(elem('chart').innerHTML.includes('<rect'));
 assert.ok(elem('chart').innerHTML.includes(' GiB'));
 assert.ok(elem('down').textContent.includes('GiB'));
 assert.ok(elem('node-legend').innerHTML.includes('Turkey'));
 assert.ok(elem('node-legend').innerHTML.includes('Germany'));
 assert.ok(elem('cost-chart').innerHTML.includes('نمودار ستونی'));
 vm.runInContext("state.fixed_expenses=[{id:1,scope:'general',period_rial:1000},{id:2,scope:'node',node_id:3,period_rial:4000},{id:3,scope:'provider',provider:'A',period_rial:6000}];renderProviderPanels()",ctx);
 assert.equal(elem('fixed-cost').textContent,vm.runInContext('money(1100)',ctx));
 assert.equal(elem('all-cost').textContent,vm.runInContext('money(1560.734)',ctx));
 vm.runInContext("selectedNode='3';selectedProvider='__all__';renderProviderPanels()",ctx);
 assert.equal(elem('fixed-cost').textContent,vm.runInContext('money(400)',ctx));
 vm.runInContext("selectedNode='all';selectedProvider='A';renderProviderPanels()",ctx);
 assert.equal(elem('fixed-cost').textContent,vm.runInContext('money(600)',ctx));
 vm.runInContext("selectedNode='3';selectedProvider='A';renderProviderPanels()",ctx);
 assert.equal(elem('fixed-cost').textContent,vm.runInContext('money(0)',ctx));
 vm.runInContext("selectedNode='all';selectedProvider='__all__';renderProviderPanels()",ctx);
 for(const theme of ['night','graphite','arctic','forest','sunset']){
  vm.runInContext("applyTheme('"+theme+"')",ctx);
  assert.equal(ctx.document.body.dataset.theme,theme);
  assert.equal(storage.get('pgtraffic-theme'),theme);
 }
 vm.runInContext('applyTheme("untrusted")',ctx);assert.equal(ctx.document.body.dataset.theme,'night');
 vm.runInContext('openEdit(3,8443)',ctx);
 assert.equal(elem('since-date-label').value,'۱۴۰۵/۰۷/۲۲');
 assert.equal(elem('since-time').value,'00:00');
 console.log('Frontend smoke tests: 20 colors, Jalali monthly grouping, Rial rounding, themes, modal Jalali date.');
})().catch(e=>{console.error(e);process.exitCode=1;});

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
const navigationLabels=['نمای کلی','نمودار و ارائه‌دهندگان','گزارش پورت‌ها','مدیریت پورت‌ها','هزینه‌های ثابت','تنظیمات'];
for(const name of navigationLabels)assert.ok(dashboardTemplate.includes('>'+name+'</a>'),'missing navigation: '+name);
assert.ok(dashboardTemplate.indexOf('id="expenses"')>dashboardTemplate.indexOf('id="manage"'),
 'Fixed costs must follow management/settings section');
assert.ok(dashboardTemplate.includes('class="expense-formula"'));
const storage=new Map();
const daily=[
 {period:'2026-10-14',node_id:3,node_name:'Turkey',provider:'A',down:2000000000,up:500000000,cost:120.234,historical_cost:15},
 {period:'2026-10-15',node_id:7,node_name:'Germany',provider:'A',down:3000000000,up:100000000,cost:250.5,historical_cost:25},
 {period:'2026-11-14',node_id:3,node_name:'Turkey',provider:'A',down:1000000000,up:0,cost:90,historical_cost:20}
];
const ports=[
 {node_id:3,node_name:'Turkey',port:8443,provider:'A',title:'A',tag:'t',down:3000000000,up:500000000,billed:3500000000,cost:210.234,historical_cost:35,total_down:1,total_up:1,enabled:1,price_per_gb:850,bill_direction:'both',notes:'',billing_since:'2026-10-14T00:00:00Z'},
 {node_id:7,node_name:'Germany',port:2053,provider:'A',title:'B',tag:'g',down:3000000000,up:100000000,billed:3100000000,cost:250.5,historical_cost:25,total_down:1,total_up:1,enabled:1,price_per_gb:850,bill_direction:'both',notes:'',billing_since:''}
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

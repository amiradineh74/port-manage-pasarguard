'use strict';
/* Persian calendar is UI-only. SQLite/HTTP use Gregorian ISO dates. */
const Jalali=(()=>{
const parser=new Intl.DateTimeFormat('en-US-u-ca-persian',{calendar:'persian',numberingSystem:'latn',timeZone:'UTC',year:'numeric',month:'numeric',day:'numeric'});
const monthName=new Intl.DateTimeFormat('fa-IR-u-ca-persian',{calendar:'persian',timeZone:'UTC',month:'long'});
const utcDay=n=>new Date(n*86400000),start=Date.UTC(1900,0,1)/86400000,end=Date.UTC(2120,0,1)/86400000;
function extract(n){const p=Object.fromEntries(parser.formatToParts(utcDay(n)).filter(x=>['year','month','day'].includes(x.type)).map(x=>[x.type,Number(x.value)]));return [p.year,p.month,p.day];}
const compare=(a,b)=>a[0]!==b[0]?a[0]-b[0]:a[1]!==b[1]?a[1]-b[1]:a[2]-b[2];
const iso=n=>utcDay(n).toISOString().slice(0,10);
function fromISO(s){if(!/^\d{4}-\d{2}-\d{2}$/.test(s))throw Error('Bad date');const n=Date.parse(s+'T00:00:00Z')/86400000;if(!Number.isFinite(n)||iso(n)!==s)throw Error('Bad date');return extract(n);}
function toISO(y,m,d){
 if(![y,m,d].every(Number.isInteger)||y<1279||y>1498||m<1||m>12||d<1||d>31)throw Error('Invalid Persian date');
 let lo=start,hi=end,target=[y,m,d];
 while(lo<hi){const mid=Math.floor((lo+hi)/2);if(compare(extract(mid),target)<0)lo=mid+1;else hi=mid;}
 if(compare(extract(lo),target))throw Error('Invalid Persian date');
 return iso(lo);
}
function shift(y,m,n){let k=y*12+m-1+n;return [Math.floor(k/12),(k%12+12)%12+1];}
const pad=n=>String(n).padStart(2,'0');
const fa=n=>String(n).replace(/[0-9]/g,d=>'۰۱۲۳۴۵۶۷۸۹'[Number(d)]);
const label=s=>{const [y,m,d]=fromISO(s);return fa(y+'/'+pad(m)+'/'+pad(d));};
function attach(field,displayId,popoverId,onChange){
 const hidden=document.getElementById(field),display=document.getElementById(displayId),popup=document.getElementById(popoverId);
 let showing=[1405,7],open=false;
 function set(s){hidden.value=s;display.value=label(s);const p=fromISO(s);showing=[p[0],p[1]];}
 function render(){
  const [y,m]=showing,first=toISO(y,m,1),firstDay=Date.parse(first+'T00:00:00Z')/86400000;
  const next=shift(y,m,1),last=Date.parse(toISO(next[0],next[1],1)+'T00:00:00Z')/86400000;
  const offset=(utcDay(firstDay).getUTCDay()+1)%7;
  let html='<div class="jnav"><button type="button" data-shift="-1" aria-label="ماه قبل">‹</button><strong>'+monthName.format(new Date(first+'T12:00:00Z'))+' '+fa(y)+'</strong><button type="button" data-shift="1" aria-label="ماه بعد">›</button></div>';
  html+='<div class="jgrid">'+['ش','ی','د','س','چ','پ','ج'].map(x=>'<span class="jweekday">'+x+'</span>').join('');
  for(let i=0;i<offset;i++)html+='<span></span>';
  for(let d=1;d<=last-firstDay;d++){const value=iso(firstDay+d-1);html+='<button type="button" class="jday '+(hidden.value===value?'chosen':'')+'" data-iso="'+value+'">'+fa(d)+'</button>';}
  popup.innerHTML=html+'</div>';
  popup.querySelectorAll('[data-shift]').forEach(b=>b.addEventListener('click',()=>{showing=shift(showing[0],showing[1],Number(b.dataset.shift));render();}));
  popup.querySelectorAll('[data-iso]').forEach(b=>b.addEventListener('click',()=>{set(b.dataset.iso);popup.hidden=true;open=false;if(onChange)onChange();}));
 }
 display.addEventListener('click',()=>{open=!open;popup.hidden=!open;if(open)render();});
 document.addEventListener('pointerdown',e=>{if(open&&!popup.contains(e.target)&&e.target!==display){open=false;popup.hidden=true;}});
 return {set,get:()=>hidden.value};
}
return {attach,label,fromISO,toISO};
})();

if(typeof module==='object'&&module.exports)module.exports=Jalali;

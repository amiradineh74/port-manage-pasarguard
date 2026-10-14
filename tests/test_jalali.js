'use strict';
const assert=require('node:assert/strict');
const j=require('../app/jalali.js');
assert.deepEqual(j.fromISO('2026-10-14'),[1405,7,22]);
assert.equal(j.toISO(1405,7,22),'2026-10-14');
assert.equal(j.toISO(1403,12,30),'2025-03-20');
assert.equal(j.label('2026-10-14'),'۱۴۰۵/۰۷/۲۲');
assert.throws(()=>j.toISO(1404,12,30));
assert.throws(()=>j.fromISO('2026-02-30'));
for(const date of ['2026-10-14','2024-03-20','2025-03-20','2030-01-01','2000-02-29','2050-06-01']){
 const [y,m,d]=j.fromISO(date);
 assert.equal(j.toISO(y,m,d),date);
}
console.log('Jalali conversion and leap-year tests passed');

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], {
  textContent: '', disabled: true, handlers: {},
  addEventListener(type, handler) { this.handlers[type] = handler; },
  classList: {add(){}, remove(){}, toggle(){}},
  showModal(){}, close(){}
}]));
const get = id => { assert(elements.has(id), `Missing HTML element: ${id}`); return elements.get(id); };
const initial = {ip:'8.8.8.8',family:'IPv4',location:'Mountain View, California, United States',isp:'Google LLC',asn:'AS15169 · Routing organisation',ua:'Browser test'};
for (const [id, value] of Object.entries(initial)) get(id).textContent = value;
let copied;
const updated = {ip:'2606:4700:4700::1111',family:'IPv6',location:'Montreal, Quebec, Canada',isp:'Cloudflare, Inc.',asn_label:'AS13335 · Routing organisation',user_agent:'Refreshed agent',note:'Connection note',database_note:''};
const context = vm.createContext({document:{getElementById:get},navigator:{clipboard:{writeText:async text=>{copied=text;}}},window:{isSecureContext:true},setTimeout:()=>1,clearTimeout(){},AbortSignal,fetch:async()=>({ok:true,json:async()=>updated})});
vm.runInContext(fs.readFileSync(new URL('../site/app.js', import.meta.url),'utf8'),context);
for (const field of ['ip','family','location','isp','asn','ua']) {
  assert.equal(get('copy-'+field).disabled,false);
  await get('copy-'+field).handlers.click();
  assert.equal(copied,initial[field],field+' copies only its own displayed value');
}
await get('refresh').handlers.click();
for (const [field,key] of Object.entries({ip:'ip',family:'family',location:'location',isp:'isp',asn:'asn_label',ua:'user_agent'})) {
  await get('copy-'+field).handlers.click();
  assert.equal(copied,updated[key],field+' copies refreshed value');
}
await get('copy-all').handlers.click();
assert(copied.includes(updated.ip));assert(copied.includes(updated.location));assert(copied.includes(updated.user_agent));
updated.location='Not available';updated.isp='Not available';updated.asn_label='Network record not available';
await get('refresh').handlers.click();
for (const field of ['location','isp','asn']) assert.equal(get('copy-'+field).disabled,true);
assert.equal(get('copy-ip').disabled,false);
console.log('Clipboard contracts passed: six individual fields, refreshed values, Copy all and unavailable fields.');

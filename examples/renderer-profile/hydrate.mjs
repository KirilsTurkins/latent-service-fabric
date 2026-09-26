import {chromium} from 'playwright-core';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const html=await readFile('dist/wasmtime-rendered.html');
const client=await readFile('dist/client.js');
const origin='https://renderer.invalid';
const browser=await chromium.launch({executablePath:process.argv[2],headless:true});
try {
 const page=await browser.newPage();
 const errors=[];page.on('pageerror',e=>{if(errors.length<16) errors.push(String(e).slice(0,512));});
 await page.route('**/*',route=>{
   const url=route.request().url();
   if(url===origin+'/') return route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:html});
   if(url===origin+'/client.js') return route.fulfill({status:200,contentType:'text/javascript; charset=utf-8',body:client});
   return route.abort();
 });
 await page.goto(origin,{waitUntil:'domcontentloaded',timeout:15000});
 await page.waitForFunction(()=>globalThis.lsfHydrated===true,null,{timeout:15000});
 const reused=await page.evaluate(()=>globalThis.serverHeading===document.getElementById('greeting'));
 assert.equal(reused,true);
 assert.equal(await page.locator('#greeting').textContent(),'Hello Alice <unsafe>');
 assert.equal(await page.locator('#count').textContent(),'Count 0');
 await page.locator('#count').click();
 await page.waitForFunction(()=>document.getElementById('count').textContent==='Count 1',null,{timeout:15000});
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({browser:browser.version(),hydrated:true,originalDomReused:reused,escapedInputText:true,clickUpdatedSignal:true,errors}));
} finally {await browser.close();}

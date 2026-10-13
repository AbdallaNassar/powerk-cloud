const {test} = require('node:test');
const assert = require('node:assert/strict');
const {browser, response, state} = require('./web_harness.cjs');
const mac = 'AABBCCDDEEFF';
const strip = role => ({mac, role, name:'Desk', label:'', online:true, outlets:[{n:1,on:false,temp_c:30,power_w:0}], currency:'USD',price_kwh:5,budget:10,month_cost:5,month_kwh:1});
const tick = () => new Promise(setImmediate);

test('new account offers a claim with localized instructions and physical toggle warning', async () => {
  const b = await browser();
  assert.match(b.element('app').innerHTML, /Add a strip/);
  b.run('openClaim(true)');
  assert.match(b.element('dlgForm').innerHTML, /TONLY_TAP_XXXXXXX/);
  assert.match(b.element('dlgForm').innerHTML, /maxlength=7/);
  b.context.form = {elements:{code:{value:'cddeeff'}},querySelector:()=>({disabled:false})};
  b.serve(async () => response(200,{claim_id:'private-id',expires_in:60}));
  await b.run('beginClaim(form)');
  assert.equal(JSON.parse(b.calls[0].options.body).code, 'CDDEEFF');
  assert.match(b.element('dlgForm').innerHTML, /Pressing a button switches an outlet/);
  assert.equal(b.run('claimSeconds()'), 60);
  b.run("lang='ar';openClaim()");
  assert.match(b.element('dlgForm').innerHTML, /الضغط على الزر/);
  b.serve(async p => response(200,p.includes('claim/')?{status:'done',mac}:{...state,devices:[strip('owner')]}));
  await b.run('pollClaim()');
  assert.equal(b.run('claimState.status'),'done');
  assert.match(b.element('dlgForm').innerHTML, /المشترك اتضاف/);
  b.run("$('dlg').close();openClaim(true)");
  assert.equal(b.run('claimState'),null);
});

test('claim timeout stops polling; failed claim leaves an actionable error', async () => {
  const b = await browser();
  b.run("claimState={claim_id:'old',status:'pending',deadline:Date.now()-1};openClaim()");
  assert.equal(b.run('claimSeconds()'),0);
  b.serve(async()=>response(200,{status:'expired'}));
  await b.run('pollClaim()');
  await b.run('pollClaim()');
  assert.equal(b.calls.length,1);
  assert.match(b.element('dlgForm').innerHTML,/Time expired/);
  b.run('openClaim(true)');
  b.context.form={elements:{code:{value:'CDDEEFF'}},querySelector:()=>({disabled:false})};
  b.serve(async()=>response(409,{error:'claim already pending'}));
  await b.run('beginClaim(form)');
  assert.match(b.element('claimError').textContent,/already claiming/);
  b.run('showAuth()');
  assert.equal(b.run('claimState'),null);
});

test('roles gate outlet/name/rule and sharing controls while retaining readings', async () => {
  const b=await browser();
  for(const role of ['owner','control','viewer']){
    b.context.devices=[strip(role)];b.run('S={devices,unread_alerts:0};plugs()');
    const html=b.element('app').innerHTML;
    assert.match(html,new RegExp('>'+role[0].toUpperCase()+role.slice(1)+'</span>'));
    assert.equal(html.includes('class=edit'),role!=='viewer');
    assert.equal(html.includes('data-action="people"'),role==='owner');
    assert.equal(html.includes('data-action="leave"'),role!=='owner');
    if(role==='viewer')assert.match(html,/class=tap[^>]*disabled/);
    b.serve(async()=>response(200,{rules:[{id:'r_test',kind:'timer',mac,outlets:[1],on:true,enabled:true,fire_at:1800000000}]}));
    await b.run('rules()');
    assert.equal(b.element('app').innerHTML.includes('data-action="rule-delete"'),role!=='viewer');
    assert.equal(b.element('app').innerHTML.includes('data-action="rule-add"'),role!=='viewer');
  }
  b.calls.length=0;b.run(`cmd('${mac}',1,true);rename('${mac}',0)`);
  assert.equal(b.calls.length,0);
});

test('unclaim requires the exact displayed name; transfer requires confirmation',async()=>{
  const b=await browser();b.context.devices=[strip('owner')];b.run('S={devices}');
  b.context.form={elements:{confirmation:{value:'wrong'}},querySelector:()=>({disabled:false})};
  b.serve(async()=>response(200,state));
  await b.run(`submitUnclaim(form,'${mac}')`);
  assert.equal(b.calls.length,0);assert.match(b.element('unclaimError').textContent,/does not match/);
  b.context.form.elements.confirmation.value='Desk';
  await b.run(`submitUnclaim(form,'${mac}')`);
  assert.equal(b.calls[0].p,`api/strips/${mac}`);assert.equal(b.calls[0].options.method,'DELETE');
  b.run(`peopleMac='${mac}';peopleList=[{user_id:2,phone:'+201000000002'}]`);
  b.calls.length=0;await b.run('transferStrip(2)');assert.equal(b.calls.length,0);
  b.context.confirm=()=>true;await b.run('transferStrip(2)');
  assert.equal(b.calls[0].p,`api/strips/${mac}/transfer`);
  assert.deepEqual(JSON.parse(b.calls[0].options.body),{phone:'+201000000002'});
});

test('settings use only owner strips and current-user notification paths; token stays write-only',async()=>{
  const b=await browser();b.context.devices=[strip('owner'),{...strip('viewer'),mac:'112233445566'}];b.run('S={devices}');
  b.serve(async p=>response(200,p.endsWith('/sessions')?{sessions:[]}:p.endsWith('/settings')?strip('owner'):{ntfy_url:'',telegram_chat:'',telegram_configured:true,alerts:{[mac]:{offline:true,online:false}}}));
  await b.run('settings()');
  assert.ok(b.calls.some(c=>c.p===`api/strips/${mac}/settings`));
  assert.ok(b.calls.some(c=>c.p==='api/me/notifications'));
  assert.ok(!b.calls.some(c=>c.p==='api/settings'||c.p==='api/strips/112233445566/settings'));
  assert.match(b.element('app').innerHTML,/class=alertpref.*data-code="offline" checked/);
  b.context.document.querySelectorAll=()=>[{dataset:{mac,code:'offline'},checked:false}];
  b.element('s_ntfy_url').value='https://ntfy.sh/mine';b.element('s_telegram_chat').value='42';
  b.serve(async p=>response(200,p.endsWith('/state')?{...state,devices:b.context.devices}:p.endsWith('/sessions')?{sessions:[]}:{}));
  b.run('saveSettings()');await tick();await tick();
  const saved=b.calls.find(c=>c.options.method==='PUT');
  assert.equal(saved.p,'api/me/notifications');
  assert.deepEqual(JSON.parse(saved.options.body),{ntfy_url:'https://ntfy.sh/mine',telegram_chat:'42',alerts:{[mac]:{offline:false}}});
});

test('energy uses the selected strip currency and budget, not another strip totals',async()=>{
  const b=await browser();b.context.devices=[strip('owner')];b.run("S={devices,currency:'EGP',month_cost:9999,budget:1};energyMac=null");
  b.serve(async()=>response(200,{currency:'USD',total_cost:5,total_kwh:1,unit:'day',buckets:[{t:1800000000,kwh:1,cost:5}],per_outlet:[{n:1,kwh:1}]}));
  await b.run('energy()');
  const html=b.element('app').innerHTML;
  assert.match(html,/5 USD/);assert.match(html,/50% of/);assert.doesNotMatch(html,/EGP|9,999/);
});

test('people escapes phone content and posts only control/viewer roles',async()=>{
  const b=await browser();b.context.devices=[strip('owner')];b.run('S={devices}');
  b.serve(async()=>response(200,{access:[{user_id:2,phone:'<img src=x>',role:'viewer'}]}));
  await b.run(`people('${mac}')`);
  assert.doesNotMatch(b.element('dlgForm').innerHTML,/<img/);
  assert.doesNotMatch(b.element('dlgForm').innerHTML,/<option value=owner/);
  b.context.form={elements:{phone:{value:'+201000000002'},role:{value:'control'}},querySelector:()=>({disabled:false})};
  await b.run('shareStrip(form)');
  const saved=b.calls.find(c=>c.options.method==='POST');
  assert.deepEqual(JSON.parse(saved.options.body),{phone:'+201000000002',role:'control'});
  // All flows share one dialog; a previous share submit handler must not hijack rename.
  b.run(`$('dlg').close();rename('${mac}',0)`);
  assert.equal(b.run('dialogSubmit'),null);
  b.element('dlgIn').value='Renamed';b.element('dlg').returnValue='ok';
  b.serve(async p=>response(200,p.endsWith('/state')?{...state,devices:b.context.devices}:{ok:true}));
  b.dispatch('close',b.element('dlg'));await tick();
  assert.equal(b.calls[0].p,'api/name');
});

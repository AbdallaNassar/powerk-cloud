const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {browser, response} = require('./web_harness.cjs');

test('public page and generated views contain no inline executable content or styles', () => {
  const html = readFileSync(join(__dirname, '../powerk/web/index.html'), 'utf8');
  assert.doesNotMatch(html, /<style\b|\son\w+\s*=|\sstyle\s*=/i);
  for (const script of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    assert.match(script[1], /src=["']?\/?app\.js/);
    assert.equal(script[2].trim(), '');
  }
  assert.match(html, /<form\b[^>]*id=dlgForm[^>]*data-action="dialog"/);
  const script = readFileSync(join(__dirname, '../powerk/web/app.js'), 'utf8');
  assert.doesNotMatch(script, /\son(?:click|change|input|submit)\s*=|\sstyle\s*=/);
});

// Tokenize actual HTML opening tags, respecting quoted attribute values. Entity
// text stays text: decoding it before tokenization would simulate a false attack.
function safeMarkup(html) {
  const tags = html.match(/<[a-z][a-z0-9-]*(?:\s+(?:[^\s"'<>/=]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*\s*\/?\s*>/gi) || [];
  for (const tag of tags) {
    assert.doesNotMatch(tag, /^<(?:img|script|iframe|object|embed)\b/i, tag);
    const bare = tag.replace(/"[^"]*"|'[^']*'/g, '""');
    assert.doesNotMatch(bare, /\s(?:on\w+|style|autofocus|data-pwn)\s*(?:=|>)/i, tag);
  }
  assert.doesNotMatch(html, /<script|<img|<iframe/i);
}

test('delegation routes clicks, changes, submit and dialog close without evaluating data', async () => {
  const b = await browser();
  const captured = [];
  b.context.capture = (...args) => captured.push(args);
  b.run('rename=(...args)=>capture(...args);submitAuth=()=>capture("auth");dialogSubmit=()=>capture("dialog");dialogClose=()=>capture("close")');
  let prevented = 0;
  const send = (type, dataset) => {
    const button = {dataset, closest() {return this}};
    b.listeners.get(type)({type,target:button,preventDefault() {prevented++}});
  };
  send('click', {action:'rename', mac:"');globalThis.injected=true;//", outlet:'3'});
  send('click', {action:'authenticate'}); // A button inside a form must not submit twice.
  send('submit', {action:'authenticate'});
  send('submit', {action:'dialog'});
  b.dispatch('close', b.element('dlg'));
  send('click', {action:'constructor'});
  assert.deepEqual(captured, [["');globalThis.injected=true;//",3],['auth'],['dialog'],['close']]);
  assert.equal(prevented, 2);
  assert.equal(b.context.injected, undefined);
  b.run('dialogSubmit=null');
  send('submit', {action:'dialog'});
  assert.equal(prevented, 2); // Native method=dialog still closes rename/claim receipts.
});

test('every rendered action is registered; numeric chart CSSOM dimensions are finite', async () => {
  const b = await browser();
  const height = {dataset:{height:'25.5'},style:{}};
  const width = {dataset:{width:'NaN'},style:{}};
  b.context.document.querySelectorAll = selector => selector==='[data-height]'?[height]:selector==='[data-width]'?[width]:[];
  b.context.data={devices:[{mac:'AABBCCDDEEFF',role:'owner',label:'Desk',currency:'EGP',budget:10,month_cost:9,price_kwh:2,outlets:[]}]};
  b.run('S=data');
  b.serve(async p=>response(200,p.includes('history')?{total_kwh:1,total_cost:2,buckets:[{t:1,kwh:1,cost:2}],per_outlet:[]}:p.includes('rules')?{rules:[]}:p.includes('sessions')?{sessions:[]}:p.includes('access')?{access:[{user_id:1,role:'viewer',phone:'+12345678'}]}:{}));
  await b.run('energy()');
  assert.equal(height.style.height,'25.5%');assert.equal(width.style.width,'0%');
  for (const view of ['plugs()', 'rules()', 'settings()', 'renderAuth()', "people('AABBCCDDEEFF')", 'openClaim(true)']) {
    await b.run(view);
    for(const html of [b.element('app').innerHTML,b.element('dlgForm').innerHTML,b.element('nav').innerHTML]){
      for(const [,action] of html.matchAll(/data-action="([^"]+)"/g)){
        b.context.action=action;
        assert.equal(b.run('Object.hasOwn(ACTIONS,action)||action==="dialog"'),true,action);
      }
    }
  }
});

for (const payload of ['<img src=x onerror=alert(1)>', '"><script>alert(1)</script>', '" autofocus data-pwn="yes']) {
  for (const language of ['en', 'ar']) for (const theme of ['kraft', 'clean', 'night']) {
    test(`all views escape ${JSON.stringify(payload)} (${language}/${theme})`, async () => {
      const b = await browser();
      const mac = 'AABBCCDDEEFF';
      const d = {mac, name:payload, label:payload, role:'owner', online:true, currency:payload,
        price_kwh:2, budget:10, month_cost:2, rssi:-50, ip:payload, model:payload, fw:payload,
        outlets:[{n:1,name:payload,on:true,temp_c:payload,power_w:1,alarms:[payload]}], alarms:[payload]};
      b.context.data = {devices:[d,{...d, mac:'112233445566'}], unread_alerts:1};
      b.context.attack = payload;
      b.run(`S=data;lang='${language}';setTheme('${theme}');currentUser={id:1,phone:attack};signedIn=true;plugs()`);
      safeMarkup(b.element('app').innerHTML);
      b.run(`rename('${mac}',0)`);safeMarkup(b.element('dlgForm').innerHTML);
      b.run(`unclaimDialog('${mac}')`);safeMarkup(b.element('dlgForm').innerHTML);
      b.serve(async p => response(200,
        p === 'api/rules' ? {rules:['schedule','timer','cycle','autooff'].map(kind=>({kind,id:payload,mac,label:payload,outlets:[1],at:payload,days:[0],on_min:payload,off_min:payload,below_w:payload,for_min:payload,enabled:true,fire_at:1800000000}))} :
        p.includes('/access') ? {access:[{user_id:payload,phone:payload,role:'viewer'}]} :
        p.includes('/history') ? {currency:payload,total_cost:2,total_kwh:1,unit:'day',buckets:[{t:1800000000,kwh:payload,cost:payload}],per_outlet:[{n:1,kwh:1}]} :
        p.includes('/sessions') ? {sessions:[{id:payload,user_agent:payload,ip:payload,current:false,created_at:1,last_used_at:1}]} :
        p.startsWith('api/events') ? {events:[{id:1,level:payload,code:'unknown',text:payload,mac,outlet:payload,ts:1,params:{actor:payload}}, ...['temp_high','power_high','budget','autooff'].map(code=>({id:2,code,level:'warn',ts:1,params:{temp_c:payload,watts:payload,pct:payload}}))]} :
        {currency:payload, ntfy_url:payload,telegram_chat:payload,telegram_configured:true,alerts:{[mac]:{[payload]:true}}}));
      for (const view of ['rules()', 'energy()', 'alerts()', 'settings()']) {
        await b.run(view);safeMarkup(b.element('app').innerHTML);
      }
      await b.run(`people('${mac}')`);safeMarkup(b.element('dlgForm').innerHTML);
      b.run('authMessage=attack;renderAuth()');safeMarkup(b.element('app').innerHTML);
      b.run("tab='rules';signedIn=true");b.serve(async()=>response(400,{error:payload}));
      await b.run('draw(true)');safeMarkup(b.element('app').innerHTML);
    });
  }
}

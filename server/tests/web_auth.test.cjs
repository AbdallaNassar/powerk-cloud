// Exercise the bundled browser script with a controlled DOM and HTTP boundary; no npm dependencies.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {browser, response, user, state} = require('./web_harness.cjs');

test('cookie writes send JSON and the double-submit header, including DELETE and push tests', async () => {
  const b = await browser();
  b.serve(async () => response(200, {ok: true, sent: [], failed: [], error: 'no push channel configured'}));
  await b.run("api('api/auth/sessions/owned','DELETE',undefined,true)");
  const request = b.calls[0];
  assert.equal(request.options.headers['X-CSRF-Token'], 'csrf-value');
  assert.equal(request.options.headers['Content-Type'], 'application/json');
  assert.equal(request.options.credentials, 'same-origin');
  await b.run('testPush()');
  await new Promise(setImmediate);
  assert.equal(b.calls[1].options.headers['X-CSRF-Token'], 'csrf-value');
});

test('concurrent 401s share rotation and each retries only once', async () => {
  const b = await browser();
  let rotated = false, rotations = 0;
  b.serve(async p => {
    if (p.endsWith('/refresh')) {rotations++; await new Promise(setImmediate); rotated = true; return response(200, {user, expires_in: 900})}
    return rotated ? response(200, {ok: true}) : response(401, {error: 'session required'});
  });
  const result = await b.run("Promise.all([api('api/settings'),api('api/rules')])");
  assert.equal(result.length, 2);
  assert.equal(rotations, 1);
  assert.equal(b.calls.length, 5);
});

test('failed refresh shows login, hides controls, and does not loop', async () => {
  const b = await browser();
  b.serve(async () => response(401, {error: 'session required'}));
  await assert.rejects(b.run("api('api/settings')"));
  assert.equal(b.calls.length, 2);
  assert.equal(b.element('nav').hidden, true);
  assert.equal(b.element('logoutBtn').hidden, true);
  assert.match(b.element('app').innerHTML, /id=authForm/);
  assert.equal(b.run('S'), null);
});

test('a late 401 reuses the completed rotation', async () => {
  const b = await browser();
  let rotations = 0, release;
  const delayed = new Promise(resolve => {release = resolve});
  let slowCalls = 0;
  b.serve(async p => {
    if (p.endsWith('/refresh')) {rotations++; return response(200, {user, expires_in: 900})}
    if (p.endsWith('/slow') && slowCalls++ === 0) {await delayed; return response(401, {error: 'session required'})}
    return rotations ? response(200, {ok: true}) : response(401, {error: 'session required'});
  });
  const slow = b.run("api('api/slow')");
  await b.run("api('api/fast')");
  release();
  await slow;
  assert.equal(rotations, 1);
});

test('network failure during refresh also returns to login', async () => {
  const b = await browser();
  b.serve(async p => {
    if (p.endsWith('/refresh')) throw new TypeError('network unavailable');
    return response(401, {error: 'session required'});
  });
  await assert.rejects(b.run("api('api/settings')"));
  assert.match(b.element('app').innerHTML, /id=authForm/);
});

test('tabs with Web Locks reuse cookies rotated by another tab', async () => {
  const b = await browser();
  let calls = 0, locks = 0;
  b.context.navigator.locks = {async request(name, fn) {assert.equal(name, 'powerk-refresh'); locks++; return fn()}};
  b.serve(async p => {
    if (p.endsWith('/me')) return response(200, {user});
    return ++calls === 1 ? response(401, {error: 'session required'}) : response(200, {ok: true});
  });
  await b.run("api('api/settings')");
  assert.equal(locks, 1);
  assert.equal(b.calls.filter(c => c.p.endsWith('/refresh')).length, 0);
});

test('login and registration screens localize and expose appropriate password autocomplete', async () => {
  const b = await browser();
  b.run("showAuth('register');setLang('ar')");
  assert.match(b.element('app').innerHTML, /autocomplete=new-password/);
  assert.match(b.element('app').innerHTML, /إنشاء حساب/);
  b.run("showAuth('login');setLang('en')");
  assert.match(b.element('app').innerHTML, /autocomplete=current-password/);
  const field = b.element('authPassword'), button = b.element('showPassword');
  b.context.testButton = button;
  b.run("togglePassword('authPassword',testButton)");
  assert.equal(field.type, 'text');
  b.run("togglePassword('authPassword',testButton)");
  assert.equal(field.type, 'password');
});

test('credentials go to the chosen endpoint and errors stay on the form', async () => {
  const b = await browser();
  b.run("showAuth('login')");
  const button = {disabled: false};
  const form = {querySelector: () => button, elements: {phone: {value: '01001234567'}, authPassword: {value: 'a wrong password'}}};
  b.context.testForm = form;
  b.serve(async () => response(401, {error: 'wrong phone or password'}));
  await b.run('submitAuth(testForm)');
  assert.equal(b.calls.length, 1);
  assert.equal(b.calls[0].p, 'api/auth/login');
  assert.equal(JSON.parse(b.calls[0].options.body).phone, '01001234567');
  assert.equal(b.element('authError').textContent, 'Wrong phone number or password.');
  assert.equal(button.disabled, false);
  b.run("showAuth('register')");
  b.serve(async p => p.endsWith('/register') ? response(201, {user, expires_in: 900}) : response(200, state));
  await b.run('submitAuth(testForm)');
  assert.equal(b.calls[0].p, 'api/auth/register');
  assert.equal(form.elements.authPassword.value, '');
  assert.equal(b.element('logoutBtn').hidden, false);
  assert.equal(b.element('nav').hidden, false);
});

test('logout clears the screen even if an older API response arrives afterwards', async () => {
  const b = await browser();
  let release;
  const pending = new Promise(resolve => {release = resolve});
  b.serve(async p => {
    if (p.endsWith('/settings')) {await pending; return response(200, {currency: 'EGP'})}
    return response(200, {ok: true});
  });
  const old = b.run("api('api/settings')");
  await b.run('logout()');
  await new Promise(setImmediate);
  release();
  await assert.rejects(old);
  assert.match(b.element('app').innerHTML, /id=authForm/);
  assert.equal(b.element('nav').hidden, true);
  assert.equal(b.run('currentUser'), null);
});

test('session descriptions escape untrusted user agents and IPs', async () => {
  const b = await browser();
  const markup = b.run("accountSettings([{id:'own',user_agent:'<img src=x onerror=alert(1)>',ip:'<script>',created_at:1800000000,last_used_at:1800000010,current:false}])");
  assert.doesNotMatch(markup, /<img|<script>/);
  assert.match(markup, /&#60;img/);
});

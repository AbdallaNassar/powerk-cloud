const {test} = require('node:test');
const assert = require('node:assert/strict');
const {browser, response, state, user} = require('./web_harness.cjs');

function sockets() {
  const opened = [];
  class WebSocket {
    constructor(url) {this.url = url; opened.push(this)}
    close() {this.closed = true; this.onclose?.({code: 1000})}
    message(packet) {this.onmessage?.({data: JSON.stringify(packet)})}
  }
  return {opened, WebSocket};
}

test('socket snapshot suspends polling; failure restores polling and schedules jittered reconnect', async () => {
  const network = sockets(), b = await browser(network);
  assert.equal(network.opened.length, 1);
  const ws = network.opened[0];
  assert.equal(ws.url, 'wss://powerk.example/api/ws');
  ws.message({...state, type: 'state'});
  b.calls.length = 0;
  await b.intervals.get(2000)();
  assert.equal(b.calls.filter(c => c.p === 'api/state').length, 0);
  ws.onclose({code: 1006});
  await new Promise(setImmediate);
  b.calls.length = 0;
  await b.intervals.get(2000)();
  assert.equal(b.calls.filter(c => c.p === 'api/state').length, 1);
  const retry = [...b.timers.values()].find(t => t.ms >= 750 && t.ms <= 1500);
  assert.ok(retry, 'first reconnect is delayed with jitter');
  await retry.fn();
  assert.equal(network.opened.length, 2);
});

test('live strip role changes are applied, access invalidation fetches state, and logout stops reconnects', async () => {
  const network = sockets(), b = await browser(network);
  const ws = network.opened[0];
  const strip = {mac: 'AABBCCDDEEFF', name: 'Desk', role: 'owner', outlets: [], alarms: [], currency: 'EGP'};
  ws.message({...state, devices: [strip], type: 'state'});
  ws.message({type: 'strip', strip: {...strip, role: 'viewer'}});
  assert.equal(b.run('S.devices[0].role'), 'viewer');
  b.serve(async p => response(200, p.endsWith('/me') ? {user} : state));
  ws.message({type: 'access'});
  await new Promise(setImmediate);
  assert.equal(b.run('S.devices.length'), 0);
  assert.ok(b.calls.some(c => c.p === 'api/state'));
  b.run('showAuth()');
  assert.ok(ws.closed);
  const count = network.opened.length;
  for (const timer of [...b.timers.values()]) await timer.fn();
  assert.equal(network.opened.length, count);
});

test('absent WebSocket keeps the existing polling path', async () => {
  const b = await browser();
  b.calls.length = 0;
  await b.intervals.get(2000)();
  assert.ok(b.calls.some(c => c.p === 'api/state'));
});

test('a strip frame arriving during a state fetch cannot hide other strips or roll back readings', async () => {
  const network = sockets(), b = await browser(network), ws = network.opened[0];
  const strip = {mac: 'AABBCCDDEEFF', name: 'Desk', role: 'owner', outlets: [], alarms: [], currency: 'EGP', power_w: 0};
  ws.message({...state, devices: [strip], type: 'state'});
  let release;
  b.serve(() => new Promise(resolve => {release = resolve}));
  ws.message({type: 'access'});
  const added = {...strip, mac: '112233445566', power_w: 40};
  ws.message({type: 'strip', strip: added});
  release(response(200, {...state, devices: [strip, {...added, power_w: 1}]}));
  await new Promise(setImmediate);
  assert.equal(b.run('S.devices.length'), 2);
  assert.equal(b.run('S.devices[1].power_w'), 40);
});

test('4401 refreshes once and failed refresh returns to login without a reconnect loop', async () => {
  const network = sockets(), b = await browser(network), ws = network.opened[0];
  ws.message({...state, type: 'state'});
  b.serve(async () => response(401, {error: 'invalid refresh token'}));
  await ws.onclose({code: 4401});
  assert.equal(b.calls.filter(c => c.p === 'api/auth/refresh').length, 1);
  assert.equal(b.run('signedIn'), false);
  for(const timer of [...b.timers.values()]) await timer.fn();
  assert.equal(network.opened.length, 1);
});

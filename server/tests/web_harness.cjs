// Controlled DOM/HTTP boundary for the actual bundled script; no browser dependencies.
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../powerk/web/app.js'), 'utf8');
const user = {id: 1, phone: '+201001234567', created_at: 1800000000};
const state = {devices: [], unread_alerts: 0, currency: 'EGP'};
const response = (status, body) => ({status, ok: status < 400, json: async () => body});

async function browser(options = {}) {
  const elements = new Map();
  const listeners = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: '', textContent: '', hidden: false, value: '', type: 'password', open: false, dataset: {}, style: {},
      classList: {add() {}, remove() {}}, close() {this.open = false}, showModal() {this.open = true},
      setAttribute(k, v) {this[k] = v}, focus() {}, select() {},
    });
    return elements.get(id);
  };
  let transport = async p => response(200, p.endsWith('/me') ? {user} : state);
  const calls = [];
  const timers = new Map(), intervals = new Map();
  let timerId = 0;
  const context = vm.createContext({
    document: {cookie: 'powerk_csrf=csrf-value', hidden: false, getElementById: element,
      addEventListener(type, fn) {listeners.set(type, fn)},
      documentElement: {dataset: {}}, querySelectorAll: () => []},
    navigator: {language: 'en'}, location: {hash: '', protocol: 'https:', host: 'powerk.example'}, history: {replaceState() {}},
    WebSocket: options.WebSocket,
    localStorage: {getItem() {return null}, setItem() {}},
    getComputedStyle: () => ({getPropertyValue: () => '#c9a46e'}),
    matchMedia: () => ({addEventListener() {}}), scrollTo() {}, confirm() {return false},
    setTimeout(fn, ms) {const id = ++timerId; timers.set(id, {fn, ms}); return id},
    clearTimeout(id) {timers.delete(id)}, setInterval(fn, ms) {intervals.set(ms, fn)},
    fetch: async (p, options) => {calls.push({p, options}); return transport(p, options)},
  });
  vm.runInContext(source, context);
  await new Promise(setImmediate);
  return {context, element, calls, listeners, timers, intervals, run: script => vm.runInContext(script, context),
    dispatch(type, target) {return listeners.get(type)({type, target, preventDefault() {}})},
    serve(fn) {transport = fn; calls.length = 0}};
}
module.exports = {browser, response, user, state};

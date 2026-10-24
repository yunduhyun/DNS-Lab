/** DOM 대체 객체로 삭제 확인 입력, 실패 표시 및 성공 후 목록 갱신을 검증한다. */
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.events = {}; this.dataset = {};
    this.textContent = ''; this.value = ''; this.open = false; this.className = '';
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  addEventListener(name, handler) { (this.events[name] ||= []).push(handler); }
  emit(name, event = {}) { return Promise.all((this.events[name] || []).map(fn => fn(event))); }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit('close'); }
  focus() { this.focused = true; }
}
const descendants = node => [node, ...node.children.flatMap(descendants)];
const tick = () => new Promise(resolve => setImmediate(resolve));

test('도메인 확인 후만 삭제하며 실패 시 유지하고 성공하면 목록을 갱신한다', async () => {
  const nodes = new Map();
  const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) nodes.set(id, new Element());
  const get = id => { assert.ok(nodes.has(id), `없는 화면 ID: ${id}`); return nodes.get(id); };
  const row = { domain: 'example.com', status: 'review', report_s3_key: 'reports/example.com/job.json' };
  const requests = [];
  let succeed = false;
  const document = {
    getElementById: get, createElement: tag => new Element(tag), body: new Element(),
    querySelector: () => new Element('h1'),
    querySelectorAll: selector => descendants(get('rows')).filter(node => node.className.includes(selector.slice(1)))
  };
  const context = vm.createContext({ document, console, fetch: async (path, options) => {
    if (!options) return { ok: true, json: async () => ({ items: [row], cursor: null, mode: 'demo' }) };
    requests.push({ path, options });
    return { ok: succeed, json: async () => succeed ? { domain: row.domain } : { error: 'S3 삭제 실패' } };
  } });
  vm.runInContext(await readFile(new URL('../public/app.js', import.meta.url), 'utf8'), context);
  await tick();
  assert.equal(get('rows').children[0].children.length, 7);
  await document.querySelectorAll('.delete-button')[0].emit('click');
  assert.equal(get('delete-modal').open, true);
  assert.equal(get('delete-domain').textContent, row.domain);
  assert.equal(get('delete-key').textContent, row.report_s3_key);
  assert.equal(get('confirm-delete').disabled, true);
  await get('delete-form').emit('submit', { preventDefault() {} });
  assert.equal(requests.length, 0);
  get('delete-confirmation').value = row.domain;
  await get('delete-confirmation').emit('input');
  assert.equal(get('confirm-delete').disabled, false);
  await get('delete-form').emit('submit', { preventDefault() {} });
  assert.equal(get('delete-modal').open, true);
  assert.equal(get('delete-error').textContent, 'S3 삭제 실패');
  assert.equal(get('total').textContent, 1);
  assert.equal(requests[0].options.method, 'DELETE');
  assert.equal(requests[0].options.headers['X-Requested-With'], 'DNSAdmin');
  const body = JSON.parse(requests[0].options.body);
  assert.equal(body.confirmation, row.domain);
  assert.equal(body.expected.updated_at, null);
  assert.equal(body.expected.report_s3_key, row.report_s3_key);
  succeed = true;
  await get('delete-form').emit('submit', { preventDefault() {} });
  assert.equal(get('delete-modal').open, false);
  assert.equal(get('total').textContent, 0);
  assert.match(get('list-message').textContent, /삭제 완료/);
  assert.equal(get('search').focused, true);
});

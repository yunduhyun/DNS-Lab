import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from './app.js';
import { createStore } from './store.js';

test('stored DNS names with underscores support report, cursor and review decision', async () => {
  const store = createStore({ DATA_MODE: 'demo' });
  const records = (await store.list()).items;
  const domain = '_https._tcp.esm.ubuntu.com';
  records.push({ ...records[0], domain, report_s3_key: `reports/${domain}/demo-001.json` });
  const server = createApp({ store, username: 'test', password: 'test-password-only' }).listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const headers = { Authorization: `Basic ${Buffer.from('test:test-password-only').toString('base64')}` };
  try {
    const response = await fetch(`${base}/api/report?domain=${encodeURIComponent(domain)}`, { headers });
    assert.equal(response.status, 200, 'existing underscore DNS name must remain readable');
    const report = await response.json();
    assert.equal(report.domain, domain);
    assert.equal(report.review_snapshot.status, 'review');
    assert.equal((await fetch(`${base}/api/domains?cursor=${encodeURIComponent(domain)}`, { headers })).status, 200);
    const decision = await fetch(`${base}/api/decision`, {
      method: 'PATCH',
      headers: { ...headers, 'Content-Type': 'application/json', 'X-Requested-With': 'DNSAdmin' },
      body: JSON.stringify({ domain, status: 'allow', expected: report.review_snapshot })
    });
    assert.equal(decision.status, 200);
    assert.equal((await decision.json()).item.status, 'allow');
    for (const invalid of ['https://example.com/', 'example.com/path', 'example com', 'user@example.com', 'example.com?x=1']) {
      assert.equal((await fetch(`${base}/api/report?domain=${encodeURIComponent(invalid)}`, { headers })).status, 400);
    }
  } finally { await new Promise(resolve => server.close(resolve)); }
});

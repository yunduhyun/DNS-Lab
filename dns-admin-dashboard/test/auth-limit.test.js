/** 로그인 실패 제한이 정상 관리자와 인증 후 API 오류를 막지 않는지 확인한다. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../app.js';

const valid = 'Basic ' + Buffer.from('admin:test-password-12345').toString('base64');
const invalid = 'Basic ' + Buffer.from('admin:wrong-password').toString('base64');

async function withServer(run) {
  const store = {
    mode: 'demo',
    async list() { return { items: [], cursor: null }; },
    async report() { throw new Error('test service failure'); }
  };
  const server = createApp({ store, username: 'admin', password: 'test-password-12345' }).listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  try { await run(`http://127.0.0.1:${server.address().port}`); }
  finally { await new Promise(resolve => server.close(resolve)); }
}

test('로그인 실패 20회 후 잘못된 인증은 제한하되 정상 관리자는 접속할 수 있다', async () => {
  await withServer(async base => {
    for (let i = 0; i < 20; i++) {
      const response = await fetch(base + '/api/domains', { headers: { Authorization: invalid } });
      assert.equal(response.status, 401);
      await response.text();
    }
    const blocked = await fetch(base + '/api/domains', { headers: { Authorization: invalid } });
    assert.equal(blocked.status, 429);
    assert.ok(blocked.headers.get('retry-after'));
    await blocked.text();
    const response = await fetch(base + '/api/domains', { headers: { Authorization: valid } });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).mode, 'demo');
  });
});

test('인증 후 잘못된 API 요청이 반복되어도 정상 조회를 제한하지 않는다', async () => {
  await withServer(async base => {
    for (let i = 0; i < 25; i++) {
      const response = await fetch(base + '/api/not-found', { headers: { Authorization: valid } });
      assert.equal(response.status, 404);
      await response.text();
    }
    const response = await fetch(base + '/api/domains', { headers: { Authorization: valid } });
    assert.equal(response.status, 200);
  });
});

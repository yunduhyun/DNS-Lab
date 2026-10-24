/** 실제 AWS 삭제 없이 인증, 삭제 순서, 동시 변경, 부분 실패를 검증한다. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { DynamoDBDocumentClient } from '@aws-sdk/lib-dynamodb';
import { S3Client } from '@aws-sdk/client-s3';
import { createApp } from '../app.js';
import { createStore } from '../store.js';

const env = { DATA_MODE: 'aws', DYNAMODB_TABLE: 'domains', S3_BUCKET: 'reports' };
const domain = 'example.com';
const item = { domain, status: 'review', created_at: '2026-10-25T00:00:00Z', updated_at: '2026-10-25T00:01:00Z', report_s3_key: 'reports/example.com/job.json' };
const snapshot = row => Object.fromEntries(['status', 'created_at', 'updated_at', 'report_s3_key'].map(field => [field, row[field] ?? null]));
const fail = name => Object.assign(new Error('test error'), { name });

function mockAWS(context, row = item, s3Error, dbError) {
  const calls = [];
  context.mock.method(DynamoDBDocumentClient.prototype, 'send', async command => {
    calls.push(command);
    if (command.constructor.name === 'GetCommand') return { Item: row };
    assert.equal(command.constructor.name, 'DeleteCommand');
    if (dbError) throw dbError;
    return {};
  });
  context.mock.method(S3Client.prototype, 'send', async command => {
    calls.push(command);
    if (s3Error) throw s3Error;
    return {};
  });
  return calls;
}

test('S3 보고서를 먼저 삭제하고 같은 스냅샷의 DynamoDB 항목을 삭제한다', async context => {
  const calls = mockAWS(context);
  const result = await createStore(env).remove(domain, snapshot(item));
  assert.deepEqual(calls.map(c => c.constructor.name), ['GetCommand', 'DeleteObjectCommand', 'DeleteCommand']);
  assert.deepEqual(calls[1].input, { Bucket: 'reports', Key: item.report_s3_key });
  const request = calls[2].input;
  assert.equal(request.TableName, 'domains');
  assert.deepEqual(request.Key, { domain });
  assert.match(request.ConditionExpression, /attribute_exists\(#domain\)/);
  for (const [i, name] of ['status', 'created_at', 'updated_at', 'report_s3_key'].entries()) {
    assert.equal(request.ExpressionAttributeNames[`#field${i}`], name);
    assert.equal(request.ExpressionAttributeValues[`:value${i}`], item[name]);
  }
  assert.deepEqual(result, { domain, report_deleted: true });
});

test('보고서가 없으면 S3를 호출하지 않으며 없는 필드는 조건으로 보호한다', async context => {
  const row = { domain, status: 'Queued' };
  const calls = mockAWS(context, row);
  assert.equal((await createStore(env).remove(domain, snapshot(row))).report_deleted, false);
  assert.deepEqual(calls.map(c => c.constructor.name), ['GetCommand', 'DeleteCommand']);
  assert.match(calls[1].input.ConditionExpression, /attribute_not_exists\(#field3\)/);
});

test('없는 도메인은 삭제하지 않는다', async context => {
  const calls = mockAWS(context, undefined);
  // 기본 인자 대신 응답 자체를 교체하여 실제 항목 부재를 표현한다.
  context.mock.method(DynamoDBDocumentClient.prototype, 'send', async () => ({ }));
  await assert.rejects(createStore(env).remove(domain, snapshot(item)), { status: 404 });
  assert.equal(calls.length, 0);
});

test('목록 조회 후 변경된 항목은 S3 삭제 전에 중단한다', async context => {
  const calls = mockAWS(context, { ...item, updated_at: 'changed' });
  await assert.rejects(createStore(env).remove(domain, snapshot(item)), { status: 409 });
  assert.equal(calls.length, 1);
});

test('다른 도메인의 경로는 삭제하지 않는다', async context => {
  const row = { ...item, report_s3_key: 'reports/other.com/job.json' };
  const calls = mockAWS(context, row);
  await assert.rejects(createStore(env).remove(domain, snapshot(row)), { status: 422 });
  assert.equal(calls.length, 1);
});

test('S3 삭제 실패 시 DynamoDB 항목을 보존한다', async context => {
  const calls = mockAWS(context, item, fail('AccessDenied'));
  await assert.rejects(createStore(env).remove(domain, snapshot(item)), error => {
    assert.equal(error.status, 502); assert.match(error.message, /DynamoDB 항목은 삭제하지 않았습니다/); return true;
  });
  assert.equal(calls.length, 2);
});

for (const name of ['AccessDeniedException', 'ConditionalCheckFailedException']) {
  test(`S3 성공 후 ${name} 발생 시 부분 실패를 알린다`, async context => {
    mockAWS(context, item, null, fail(name));
    await assert.rejects(createStore(env).remove(domain, snapshot(item)), error => {
      assert.equal(error.status, name === 'ConditionalCheckFailedException' ? 409 : 502);
      assert.match(error.message, /S3 보고서/); return true;
    });
  });
}

test('demo 삭제는 실제 AWS와 다른 demo 인스턴스에 영향을 주지 않는다', async () => {
  const store = createStore({ DATA_MODE: 'demo' });
  const row = (await store.list()).items[0];
  await store.remove(row.domain, snapshot(row));
  assert.equal((await store.list()).items.length, 2);
  await assert.rejects(store.report(row.domain), { status: 404 });
  assert.equal((await createStore({ DATA_MODE: 'demo' }).list()).items.length, 3);
});

test('삭제 API는 인증과 사용자 정의 헤더 및 도메인 확인을 요구한다', async () => {
  let removed = 0;
  const app = createApp({ username: 'admin', password: 'test-password-12345', store: {
    async remove(received, expected) {
      assert.equal(received, domain); assert.deepEqual(expected, snapshot(item));
      removed++; return { domain, report_deleted: true };
    }
  } });
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const authorization = 'Basic ' + Buffer.from('admin:test-password-12345').toString('base64');
  const body = { domain, confirmation: domain, expected: snapshot(item) };
  const request = (headers, data = body) => fetch(base + '/api/domains', { method: 'DELETE', headers, body: JSON.stringify(data) });
  try {
    assert.equal((await request({ 'Content-Type': 'application/json' })).status, 401);
    assert.equal((await request({ Authorization: authorization, 'Content-Type': 'application/json' })).status, 403);
    const headers = { Authorization: authorization, 'Content-Type': 'application/json', 'X-Requested-With': 'DNSAdmin' };
    assert.equal((await request({ ...headers, 'Sec-Fetch-Site': 'cross-site' })).status, 403);
    assert.equal((await request(headers, { ...body, confirmation: 'other.com' })).status, 400);
    assert.equal((await request(headers, { ...body, domain: '../secret', confirmation: '../secret' })).status, 400);
    assert.equal((await request(headers, { domain, confirmation: domain })).status, 400);
    assert.equal(removed, 0);
    const response = await request(headers);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { domain, report_deleted: true });
    assert.equal(removed, 1);
    assert.equal((await fetch(base + '/api/domains', { method: 'DELETE', headers, body: '{bad' })).status, 400);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

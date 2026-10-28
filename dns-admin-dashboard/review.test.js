import test from 'node:test';
import assert from 'node:assert/strict';
import { DynamoDBDocumentClient } from '@aws-sdk/lib-dynamodb';
import { S3Client } from '@aws-sdk/client-s3';
import { Readable } from 'node:stream';
import { createStore } from './store.js';
import { createApp } from './app.js';

const snapshot = item => Object.fromEntries(['status', 'created_at', 'updated_at', 'report_s3_key'].map(key => [key, item[key] ?? null]));

test('demo: review can be decided once, preserving report and creation time', async () => {
  const store = createStore({ DATA_MODE: 'demo' });
  const item = (await store.list()).items.find(item => item.status === 'review');
  const expected = snapshot(item);
  await store.decide(item.domain, 'blocked', expected);
  const changed = (await store.list()).items.find(row => row.domain === item.domain);
  assert.equal(changed.status, 'blocked');
  assert.equal(changed.created_at, expected.created_at);
  assert.equal(changed.report_s3_key, expected.report_s3_key);
  assert.notEqual(changed.updated_at, expected.updated_at);
  await assert.rejects(store.decide(item.domain, 'allow', expected), { status: 409 });
});

test('demo: stale report snapshot and invalid decision are refused', async () => {
  const store = createStore({ DATA_MODE: 'demo' });
  const item = (await store.list()).items[0];
  await assert.rejects(store.decide(item.domain, 'allow', { ...snapshot(item), report_s3_key: 'other' }), { status: 409 });
  await assert.rejects(store.decide(item.domain, 'Queued', snapshot(item)), { status: 400 });
  assert.equal(item.status, 'review');
});

test('AWS: conditional UpdateItem checks reviewed snapshot and translates conflicts', async () => {
  const original = DynamoDBDocumentClient.prototype.send;
  let input;
  DynamoDBDocumentClient.prototype.send = async command => { input = command.input; return { Attributes: { domain: 'example.com', status: 'allow' } }; };
  try {
    const store = createStore({ DATA_MODE: 'aws', DYNAMODB_TABLE: 'test', S3_BUCKET: 'test' });
    const expected = { status: 'review', created_at: 'created', updated_at: 'updated', report_s3_key: 'reports/example.com/test.json' };
    await store.decide('example.com', 'allow', expected);
    assert.equal(input.Key.domain, 'example.com');
    assert.equal(input.ExpressionAttributeValues[':review'], 'review');
    assert.equal(input.ExpressionAttributeValues[':status'], 'allow');
    assert.match(input.ConditionExpression, /#updated = :expected_updated/);
    assert.match(input.ConditionExpression, /#report = :expected_report/);
    DynamoDBDocumentClient.prototype.send = async () => { throw Object.assign(new Error(), { name: 'ConditionalCheckFailedException' }); };
    await assert.rejects(store.decide('example.com', 'blocked', expected), { status: 409 });
  } finally { DynamoDBDocumentClient.prototype.send = original; }
});

test('AWS: collection-failure report with null data remains readable with snapshot', async () => {
  const originalDb = DynamoDBDocumentClient.prototype.send;
  const originalS3 = S3Client.prototype.send;
  const item = { domain: '인스타그램.com', status: 'review', created_at: 'created', updated_at: 'updated', report_s3_key: 'reports/인스타그램.com/test.json' };
  DynamoDBDocumentClient.prototype.send = async () => ({ Item: item });
  S3Client.prototype.send = async command => {
    assert.equal(command.input.Key, item.report_s3_key);
    return { Body: Readable.from([Buffer.from(JSON.stringify({ domain: item.domain, analysis: '수집에 실패했다.', collected_data: null }))]) };
  };
  try {
    const store = createStore({ DATA_MODE: 'aws', DYNAMODB_TABLE: 'test', S3_BUCKET: 'test' });
    const report = await store.report(item.domain);
    assert.equal(report.collected_data, null);
    assert.deepEqual(report.review_snapshot, snapshot(item));
  } finally {
    DynamoDBDocumentClient.prototype.send = originalDb;
    S3Client.prototype.send = originalS3;
  }
});

test('API: authenticated review decision, cross-site refusal, unicode domain and validation', async () => {
  const store = createStore({ DATA_MODE: 'demo' });
  const calls = [];
  const original = store.decide;
  store.decide = async (...args) => { calls.push(args); return original(...args); };
  const server = createApp({ store, username: 'admin', password: 'test-password-only' }).listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const url = `http://127.0.0.1:${server.address().port}/api/decision`;
  const item = (await store.list()).items[0];
  const body = JSON.stringify({ domain: item.domain, status: 'allow', expected: snapshot(item) });
  const headers = { Authorization: `Basic ${Buffer.from('admin:test-password-only').toString('base64')}`, 'Content-Type': 'application/json', 'X-Requested-With': 'DNSAdmin' };
  try {
    assert.equal((await fetch(url, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body })).status, 401);
    assert.equal((await fetch(url, { method: 'PATCH', headers: { ...headers, 'Sec-Fetch-Site': 'cross-site' }, body })).status, 403);
    assert.equal(calls.length, 0);
    assert.equal((await fetch(url, { method: 'PATCH', headers, body })).status, 200);
    assert.equal((await fetch(url, { method: 'PATCH', headers, body })).status, 409);
    assert.equal((await fetch(url, { method: 'PATCH', headers, body: JSON.stringify({ domain: item.domain, status: 'blocked' }) })).status, 400);
    const unicode = await fetch(url, { method: 'PATCH', headers, body: JSON.stringify({ domain: '인스타그램.com', status: 'allow', expected: { ...snapshot(item), status: 'review' } }) });
    assert.equal(unicode.status, 404);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

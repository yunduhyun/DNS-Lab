/** DynamoDB 목록과 S3 보고서를 조회하고 선택한 도메인의 기록을 삭제한다. demo 모드는 AWS를 호출하지 않는다. */
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, GetCommand, ScanCommand, DeleteCommand, UpdateCommand } from '@aws-sdk/lib-dynamodb';
import { S3Client, GetObjectCommand, DeleteObjectCommand } from '@aws-sdk/client-s3';

export class AppError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const samples = [
  { domain: 'portal.example.com', created_at: '2026-10-24T12:00:00Z', status: 'review', updated_at: '2026-10-25T00:20:00Z', report_s3_key: 'reports/portal.example.com/demo-001.json' },
  { domain: 'docs.example.org', created_at: '2026-10-24T12:05:00Z', status: 'Analyzing', updated_at: '2026-10-25T00:22:00Z' },
  { domain: 'news.example.net', created_at: '2026-10-24T12:10:00Z', status: 'Queued', updated_at: '2026-10-25T00:23:00Z' }
];

function demoReport(domain) {
  return {
    domain, job_id: 'demo-001', analyzed_at: '2026-10-25T00:20:00Z',
    analysis: '이 보고서는 화면 확인을 위한 샘플입니다. 실제 도메인 분석 결과가 아닙니다.\n\n제공된 자료만으로 악성 여부를 판단할 수 없습니다. 관리자 검토가 필요합니다.',
    collected_data: {
      title: '샘플 서비스 로그인', final_url: `https://${domain}/login`,
      dns: { A: { status: 'ok', records: ['192.0.2.10'] }, AAAA: { status: 'NoAnswer', records: [] } },
      headers: 'HTTP/2 200\ncontent-type: text/html; charset=utf-8',
      body_text: '샘플 서비스에 로그인하세요. 화면 시연용 자료입니다.',
      links: [{ text: '도움말', url: `https://${domain}/help` }],
      forms: [{ action: '/login', url: `https://${domain}/login`, method: 'POST' }], script_urls: []
    }
  };
}

const snapshotFields = ['status', 'created_at', 'updated_at', 'report_s3_key'];

function checkSnapshot(item, expected) {
  if (!snapshotFields.every(field => (item[field] ?? null) === expected[field])) {
    throw new AppError(409, '항목이 변경되었습니다. 목록을 새로고침한 뒤 다시 확인해주세요.');
  }
}

function reportKey(domain, key) {
  if (typeof key !== 'string' || !key.startsWith(`reports/${domain}/`) || !key.endsWith('.json')) {
    throw new AppError(422, '등록된 보고서 경로를 확인해주세요.');
  }
  return key;
}

export function createStore(env) {
  if (env.DATA_MODE === 'demo') {
    let records = samples.map(item => ({ ...item }));
    return {
      mode: 'demo',
      async list() { return { items: records, cursor: null }; },
      async report(domain) {
        const item = records.find(row => row.domain === domain);
        if (!item) throw new AppError(404, '등록된 도메인이 없습니다.');
        if (!item.report_s3_key) throw new AppError(409, '보고서 위치가 아직 등록되지 않았습니다.');
        return { ...demoReport(domain), review_snapshot: Object.fromEntries(snapshotFields.map(field => [field, item[field] ?? null])) };
      },
      async decide(domain, status, expected) {
        if (!['blocked', 'allow'].includes(status)) throw new AppError(400, '차단 또는 허용을 선택해주세요.');
        const item = records.find(row => row.domain === domain);
        if (!item) throw new AppError(404, '등록된 도메인이 없습니다.');
        checkSnapshot(item, expected);
        if (item.status !== 'review') throw new AppError(409, '검토 대기 항목만 결정할 수 있습니다. 목록을 새로고침해주세요.');
        item.status = status;
        item.updated_at = new Date().toISOString();
        return { item: { ...item } };
      },
      async remove(domain, expected) {
        const item = records.find(row => row.domain === domain);
        if (!item) throw new AppError(404, '등록된 도메인이 없습니다.');
        checkSnapshot(item, expected);
        records = records.filter(row => row.domain !== domain);
        return { domain, report_deleted: Boolean(item.report_s3_key) };
      }
    };
  }
  if (env.DATA_MODE !== 'aws') throw new Error('DATA_MODE는 demo 또는 aws여야 합니다.');
  if (!env.DYNAMODB_TABLE || !env.S3_BUCKET) throw new Error('테이블과 버킷 설정이 필요합니다.');
  // EC2에서는 SDK 기본 인증 체인이 인스턴스 IAM 역할을 사용한다.
  const config = { region: env.AWS_REGION || 'ap-northeast-2' };
  const db = DynamoDBDocumentClient.from(new DynamoDBClient(config));
  const s3 = new S3Client(config);
  return {
    mode: 'aws',
    async list(cursor) {
      // shortcut: MVP는 Scan을 사용한다. 목록 규모가 커지면 상태별 GSI 조회로 전환한다.
      const page = await db.send(new ScanCommand({
        TableName: env.DYNAMODB_TABLE, Limit: 50,
        ExclusiveStartKey: cursor ? { domain: cursor } : undefined,
        ProjectionExpression: '#domain, created_at, report_s3_key, #status, updated_at',
        ExpressionAttributeNames: { '#domain': 'domain', '#status': 'status' }
      }));
      return { items: page.Items || [], cursor: page.LastEvaluatedKey?.domain || null };
    },
    async report(domain) {
      const { Item: item } = await db.send(new GetCommand({
        TableName: env.DYNAMODB_TABLE, Key: { domain }, ConsistentRead: true
      }));
      if (!item) throw new AppError(404, '등록된 도메인이 없습니다.');
      if (!item.report_s3_key) throw new AppError(409, '보고서 위치가 아직 등록되지 않았습니다.');
      // 브라우저가 임의의 S3 키를 지정하지 못하도록 DB의 도메인별 경로만 사용한다.
      const key = reportKey(domain, item.report_s3_key);
      let result;
      try {
        result = await s3.send(new GetObjectCommand({ Bucket: env.S3_BUCKET, Key: key }));
      } catch (error) {
        if (error.name === 'NoSuchKey') throw new AppError(404, 'S3에 해당 보고서가 없습니다.');
        throw error;
      }
      // 큰 보고서로 메모리를 소진하지 않도록 읽는 도중에도 크기를 제한한다.
      const chunks = [];
      let size = 0;
      for await (const chunk of result.Body) {
        size += chunk.length;
        if (size > 5 * 1024 * 1024) {
          result.Body.destroy();
          throw new AppError(413, '보고서가 조회 한도인 5MB를 초과했습니다.');
        }
        chunks.push(chunk);
      }
      let report;
      try { report = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch { throw new AppError(422, '보고서 JSON을 해석할 수 없습니다.'); }
      if (!report || report.domain !== domain || typeof report.analysis !== 'string' ||
          (report.collected_data !== null && (typeof report.collected_data !== 'object' || Array.isArray(report.collected_data)))) {
        throw new AppError(422, '보고서 형식이나 도메인이 일치하지 않습니다.');
      }
      return { ...report, review_snapshot: Object.fromEntries(snapshotFields.map(field => [field, item[field] ?? null])) };
    },
    async decide(domain, status, expected) {
      if (!['blocked', 'allow'].includes(status)) throw new AppError(400, '차단 또는 허용을 선택해주세요.');
      if (expected.status !== 'review') throw new AppError(409, '검토 대기 항목만 결정할 수 있습니다.');
      try {
        const result = await db.send(new UpdateCommand({
          TableName: env.DYNAMODB_TABLE,
          Key: { domain },
          UpdateExpression: 'SET #status = :status, #updated = :updated',
          ConditionExpression: 'attribute_exists(#domain) AND #status = :review AND #created = :expected_created AND #updated = :expected_updated AND #report = :expected_report',
          ExpressionAttributeNames: {
            '#domain': 'domain', '#status': 'status', '#created': 'created_at',
            '#updated': 'updated_at', '#report': 'report_s3_key'
          },
          ExpressionAttributeValues: {
            ':status': status, ':updated': new Date().toISOString(), ':review': 'review',
            ':expected_created': expected.created_at, ':expected_updated': expected.updated_at,
            ':expected_report': expected.report_s3_key
          },
          ReturnValues: 'ALL_NEW'
        }));
        return { item: result.Attributes };
      } catch (error) {
        if (error.name === 'ConditionalCheckFailedException') {
          throw new AppError(409, '항목이 변경되었습니다. 목록을 새로고침한 뒤 보고서를 다시 확인해주세요.');
        }
        throw error;
      }
    },
    async remove(domain, expected) {
      const { Item: item } = await db.send(new GetCommand({
        TableName: env.DYNAMODB_TABLE, Key: { domain }, ConsistentRead: true
      }));
      if (!item) throw new AppError(404, '등록된 도메인이 없습니다.');
      checkSnapshot(item, expected);
      const hasReport = item.report_s3_key !== undefined && item.report_s3_key !== null;
      if (hasReport) {
        const key = reportKey(domain, item.report_s3_key);
        try {
          await s3.send(new DeleteObjectCommand({ Bucket: env.S3_BUCKET, Key: key }));
        } catch {
          throw new AppError(502, 'S3 보고서 삭제에 실패했습니다. DynamoDB 항목은 삭제하지 않았습니다.');
        }
      }
      // 두 서비스의 삭제는 원자적이지 않으므로 S3 실패 시 DB의 경로를 보존하고, DB 동시 변경은 거절한다.
      const names = { '#domain': 'domain' };
      const values = {};
      const conditions = ['attribute_exists(#domain)'];
      for (const [index, field] of snapshotFields.entries()) {
        const name = `#field${index}`;
        names[name] = field;
        if (item[field] === undefined) conditions.push(`attribute_not_exists(${name})`);
        else {
          const value = `:value${index}`;
          values[value] = item[field];
          conditions.push(`${name} = ${value}`);
        }
      }
      try {
        await db.send(new DeleteCommand({
          TableName: env.DYNAMODB_TABLE, Key: { domain },
          ConditionExpression: conditions.join(' AND '),
          ExpressionAttributeNames: names,
          ...(Object.keys(values).length ? { ExpressionAttributeValues: values } : {})
        }));
      } catch (error) {
        const reason = error.name === 'ConditionalCheckFailedException'
          ? '항목이 변경되어 DynamoDB 삭제를 중단했습니다.'
          : 'DynamoDB 항목 삭제에 실패했습니다.';
        const partial = hasReport ? ' S3 보고서 삭제는 완료됐습니다.' : '';
        throw new AppError(error.name === 'ConditionalCheckFailedException' ? 409 : 502,
          reason + partial + ' 목록을 새로고침하고 상태를 확인해주세요.');
      }
      return { domain, report_deleted: hasReport };
    }
  };
}

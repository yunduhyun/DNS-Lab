/** 관리자 인증, 정적 화면 제공, 조회 및 삭제 API와 오류 응답을 담당한다. */
import express from 'express';
import { domainToASCII } from 'node:url';
import helmet from 'helmet';
import { rateLimit } from 'express-rate-limit';
import { createHash, timingSafeEqual } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { AppError } from './store.js';
import { renderAnalysis } from './markdown.js';

const digest = value => createHash('sha256').update(value).digest();
const validDomain = value => typeof value === 'string' && value.length <= 253 &&
  /^(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(domainToASCII(value)) && !/[\s/@:#?\\]/.test(value);

export function createApp({ store, username, password }) {
  if (!username || username.includes(':') || !password || password.length < 12) {
    throw new Error('관리자 사용자명과 12자 이상의 비밀번호를 설정해주세요.');
  }
  const app = express();
  app.disable('x-powered-by');
  app.use(helmet({ strictTransportSecurity: false, contentSecurityPolicy: {
    directives: { 'upgrade-insecure-requests': null }
  } }));
  app.use((req, res, next) => { res.set('Cache-Control', 'no-store'); next(); });
  const authLimiter = rateLimit({ windowMs: 15 * 60 * 1000, limit: 20,
    message: { error: '로그인 시도가 많습니다. 잠시 후 다시 시도해주세요.' } });
  app.use((req, res, next) => {
    const header = req.get('authorization') || '';
    const raw = header.startsWith('Basic ') ? Buffer.from(header.slice(6), 'base64').toString('utf8') : '';
    const split = raw.indexOf(':');
    const userMatch = timingSafeEqual(digest(raw.slice(0, split)), digest(username));
    const passMatch = timingSafeEqual(digest(raw.slice(split + 1)), digest(password));
    if (split < 0 || !userMatch || !passMatch) {
      // 인증 실패만 집계한다. API 오류나 다른 접속자의 실패가 정상 관리자를 차단하지 않도록 한다.
      return authLimiter(req, res, () => {
        res.set('WWW-Authenticate', 'Basic realm="DNS Admin", charset="UTF-8"');
        res.status(401).send('관리자 인증이 필요합니다.');
      });
    }
    next();
  });
  app.get('/api/domains', async (req, res) => {
    if (req.query.cursor !== undefined && !validDomain(req.query.cursor)) {
      throw new AppError(400, '페이지 커서가 올바르지 않습니다.');
    }
    res.json({ ...await store.list(req.query.cursor), mode: store.mode });
  });
  app.get('/api/report', async (req, res) => {
    if (!validDomain(req.query.domain)) throw new AppError(400, '도메인 형식이 올바르지 않습니다.');
    const report = await store.report(req.query.domain);
    res.json({ ...report, analysis_html: renderAnalysis(report.analysis) });
  });
  app.patch('/api/decision', express.json({ limit: '4kb' }), async (req, res) => {
    if (req.get('X-Requested-With') !== 'DNSAdmin' || req.get('Sec-Fetch-Site') === 'cross-site') {
      throw new AppError(403, '대시보드에서 검토 결정을 요청해주세요.');
    }
    const { domain, status, expected } = req.body || {};
    if (!validDomain(domain) || !['blocked', 'allow'].includes(status)) {
      throw new AppError(400, '도메인과 차단 또는 허용 결정을 확인해주세요.');
    }
    const fields = ['status', 'created_at', 'updated_at', 'report_s3_key'];
    if (!expected || !fields.every(field => typeof expected[field] === 'string' && expected[field].length > 0 && expected[field].length <= 2048)) {
      throw new AppError(400, '검토 대상 정보가 올바르지 않습니다. 보고서를 다시 확인해주세요.');
    }
    if (expected.status !== 'review') throw new AppError(409, '검토 대기 항목만 결정할 수 있습니다.');
    res.json(await store.decide(domain, status, expected));
  });
  app.delete('/api/domains', express.json({ limit: '4kb' }), async (req, res) => {
    // 브라우저의 교차 출처 요청은 사용자 정의 헤더가 있는 DELETE 요청을 전송할 수 없다.
    if (req.get('X-Requested-With') !== 'DNSAdmin' || req.get('Sec-Fetch-Site') === 'cross-site') {
      throw new AppError(403, '대시보드에서 삭제를 요청해주세요.');
    }
    const { domain, confirmation, expected } = req.body || {};
    if (!validDomain(domain) || confirmation !== domain) {
      throw new AppError(400, '삭제할 도메인을 정확히 입력해주세요.');
    }
    const fields = ['status', 'created_at', 'updated_at', 'report_s3_key'];
    if (!expected || !fields.every(field => Object.hasOwn(expected, field) &&
        (expected[field] === null || (typeof expected[field] === 'string' && expected[field].length <= 2048)))) {
      throw new AppError(400, '삭제 대상 정보가 올바르지 않습니다. 목록을 새로고침해주세요.');
    }
    res.json(await store.remove(domain, expected));
  });
  app.use(express.static(fileURLToPath(new URL('./public/', import.meta.url))));
  app.use((req, res) => res.status(404).json({ error: '요청한 경로가 없습니다.' }));
  app.use((error, req, res, next) => {
    if (error.type === 'entity.parse.failed' || error.type === 'entity.too.large') {
      return res.status(400).json({ error: '요청 본문이 올바르지 않습니다.' });
    }
    if (!(error instanceof AppError)) console.error('요청 오류:', error.name);
    res.status(error instanceof AppError ? error.status : 502).json({
      error: error instanceof AppError ? error.message : 'AWS 요청에 실패했습니다. 서버 권한과 설정을 확인해주세요.'
    });
  });
  return app;
}

/** 관리자 인증, 정적 화면 제공, 읽기 전용 API와 오류 응답을 담당한다. */
import express from 'express';
import helmet from 'helmet';
import { rateLimit } from 'express-rate-limit';
import { createHash, timingSafeEqual } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { AppError } from './store.js';

const digest = value => createHash('sha256').update(value).digest();
const validDomain = value => typeof value === 'string' && value.length <= 253 &&
  /^(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(value);

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
  const authLimiter = rateLimit({ windowMs: 15 * 60 * 1000, limit: 20, skipSuccessfulRequests: true,
    message: '로그인 시도가 많습니다. 잠시 후 다시 시도해주세요.' });
  app.use(authLimiter);
  app.use((req, res, next) => {
    const header = req.get('authorization') || '';
    const raw = header.startsWith('Basic ') ? Buffer.from(header.slice(6), 'base64').toString('utf8') : '';
    const split = raw.indexOf(':');
    const userMatch = timingSafeEqual(digest(raw.slice(0, split)), digest(username));
    const passMatch = timingSafeEqual(digest(raw.slice(split + 1)), digest(password));
    if (split < 0 || !userMatch || !passMatch) {
      res.set('WWW-Authenticate', 'Basic realm="DNS Admin", charset="UTF-8"');
      return res.status(401).send('관리자 인증이 필요합니다.');
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
    res.json(await store.report(req.query.domain));
  });
  app.use(express.static(fileURLToPath(new URL('./public/', import.meta.url))));
  app.use((req, res) => res.status(404).json({ error: '요청한 경로가 없습니다.' }));
  app.use((error, req, res, next) => {
    if (!(error instanceof AppError)) console.error('조회 오류:', error.name);
    res.status(error instanceof AppError ? error.status : 502).json({
      error: error instanceof AppError ? error.message : 'AWS 조회에 실패했습니다. 서버 권한과 설정을 확인해주세요.'
    });
  });
  return app;
}

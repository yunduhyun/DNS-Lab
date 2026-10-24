/** 환경변수를 읽어 대시보드 서버를 시작한다. 기본 주소는 로컬 전용이다. */
import { createApp } from './app.js';
import { createStore } from './store.js';

const app = createApp({
  store: createStore(process.env),
  username: process.env.ADMIN_USER,
  password: process.env.ADMIN_PASSWORD
});
const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || 3000);
app.listen(port, host, () => console.log(`DNS 대시보드 실행: http://${host}:${port} (${process.env.DATA_MODE})`));

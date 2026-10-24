/** Markdown 서식과 분석 자료에서 유래할 수 있는 HTML 삽입을 함께 검증한다. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { renderAnalysis } from '../markdown.js';
import { createApp } from '../app.js';

test('굵게, 제목, 목록, 표와 코드 블록을 렌더링한다', () => {
  const html = renderAnalysis('# 분석 결과\n\n**주의** 및 *설명*\n\n- 항목\n\n> 인용\n\n```js\nconst x = 1;\n```\n\n| 항목 | 값 |\n| --- | --- |\n| 결과 | 검토 |');
  for (const tag of ['h1', 'strong', 'em', 'ul', 'li', 'blockquote', 'pre', 'code', 'table']) {
    assert.ok(html.includes(`<${tag}>`), tag);
  }
});

test('스크립트, 이벤트 속성, 이미지와 활성 링크를 제거한다', () => {
  const html = renderAnalysis('**정상**\n\n<script>alert(1)</script><img src="https://evil.example/x" onerror="alert(1)"><iframe src="https://evil.example"></iframe><svg onload="alert(1)"></svg><p id="report-modal" style="position:fixed" onclick="alert(1)">내용</p>\n\n[클릭](javascript:alert%281%29)\n\n[외부 링크](https://evil.example)');
  assert.match(html, /<strong>정상<\/strong>/);
  assert.match(html, /내용/);
  assert.match(html, /외부 링크/);
  assert.doesNotMatch(html, /<script|<img|<iframe|<svg|<a\b|onclick|onerror|onload|javascript:|style=|id=/i);
});

test('보고서 API는 원문과 정제된 표시용 HTML을 함께 반환한다', async () => {
  const analysis = '**판단 불가**<script>alert(1)</script>';
  const app = createApp({ username: 'admin', password: 'test-password-12345',
    store: { async report() { return { domain: 'example.com', analysis, collected_data: {} }; } }
  });
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/report?domain=example.com`, {
      headers: { Authorization: 'Basic ' + Buffer.from('admin:test-password-12345').toString('base64') }
    });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.analysis, analysis);
    assert.match(body.analysis_html, /<strong>판단 불가<\/strong>/);
    assert.doesNotMatch(body.analysis_html, /<script|alert/);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

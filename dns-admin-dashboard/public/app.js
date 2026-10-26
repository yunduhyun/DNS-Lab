/** AI 분석은 서버가 정제한 Markdown HTML로 표시하고, 수집 자료는 textContent로 표시한다. */
const $ = id => document.getElementById(id);
const labels = { pending_enqueue: '전송 대기', Queued: '분석 대기', Analyzing: '분석 중', review: '검토 대기', no_block: '차단하지 않음', block_pending: '차단 반영 대기', blocked: '차단 적용 완료', failed: '처리 실패', faild: '처리 실패' };
let items = [], cursor = null, selected = null, requestId = 0;
let deleteTarget = null, deleting = false, listing = false, listRequestId = 0;
const date = value => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }) : '—';
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function api(path, options) {
  const res = await fetch(path, options);
  if (res.status === 401) throw new Error('관리자 인증이 필요합니다. 페이지를 새로고침해주세요.');
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || '조회에 실패했습니다.');
  return data;
}
function registrationTime(item) {
  const time = Date.parse(item.created_at);
  return Number.isNaN(time) ? -Infinity : time;
}
function render() {
  const keyword = $('search').value.trim().toLowerCase();
  const status = $('status').value;
  const visible = items
    .filter(item => item.domain?.includes(keyword) && (!status || item.status === status))
    .sort((a, b) => registrationTime(b) - registrationTime(a));
  $('total').textContent = items.length;
  $('processing').textContent = items.filter(x => ['Queued', 'Analyzing', 'pending_enqueue'].includes(x.status)).length;
  $('reviews').textContent = items.filter(x => x.status === 'review').length;
  $('reports').textContent = items.filter(x => x.report_s3_key).length;
  $('count').textContent = `${visible.length}개`;
  $('rows').replaceChildren();
  for (const item of visible) {
    const row = element('tr');
    if (item.domain === selected) row.className = 'selected';
    row.append(element('td', item.domain), element('td', date(item.created_at)));
    const keyCell = element('td', item.report_s3_key || '—', 'report-key');
    keyCell.title = item.report_s3_key || '';
    row.append(keyCell);
    const statusCell = element('td');
    const badge = element('span', labels[item.status] || item.status || '미등록', 'badge');
    if (Object.hasOwn(labels, item.status)) badge.classList.add(item.status);
    statusCell.append(badge);
    row.append(statusCell, element('td', date(item.updated_at)));
    const cell = element('td');
    if (item.report_s3_key) {
      const button = element('button', '확인', 'report-button');
      button.setAttribute('aria-label', `${item.domain} 보고서 확인`);
      button.dataset.domain = item.domain;
      button.addEventListener('click', () => openReport(item.domain));
      cell.append(button);
    } else cell.append(element('span', item.status === 'Analyzing' ? '분석 진행 중' : '보고서 위치 미등록', 'unavailable'));
    const deleteCell = element('td');
    const deleteButton = element('button', '삭제', 'button delete-button');
    deleteButton.dataset.domain = item.domain;
    deleteButton.disabled = deleting || listing;
    deleteButton.setAttribute('aria-label', `${item.domain} 삭제`);
    deleteButton.addEventListener('click', () => openDelete(item));
    deleteCell.append(deleteButton);
    row.append(cell, deleteCell);
    $('rows').append(row);
  }
  if (!visible.length) {
    const cell = element('td', items.length ? '조건에 맞는 도메인이 없습니다.' : '등록된 도메인이 없습니다.');
    cell.colSpan = 7;
    const row = element('tr'); row.append(cell); $('rows').append(row);
  }
}
async function load(reset = false) {
  if (deleting) return;
  const id = ++listRequestId;
  listing = true;
  render();
  $('refresh').disabled = true; $('more').disabled = true;
  $('list-message').textContent = '목록을 불러오는 중입니다...';
  try {
    const data = await api(`/api/domains${!reset && cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (id !== listRequestId) return;
    items = reset ? data.items : [...new Map([...items, ...data.items].map(item => [item.domain, item])).values()];
    cursor = data.cursor;
    $('more').hidden = !cursor;
    $('mode').textContent = data.mode === 'demo'
      ? '샘플 데이터'
      : 'AWS 연결';
    $('list-message').textContent = '';
    render();
  } catch (error) { $('list-message').textContent = error.message; }
  finally {
    if (id === listRequestId) {
      listing = false;
      $('refresh').disabled = deleting; $('more').disabled = deleting;
      render();
    }
  }
}
function addSection(parent, title, text) {
  const section = element('section', undefined, 'report-section');
  section.append(element('h3', title), element('pre', text)); parent.append(section);
}
async function openReport(domain) {
  const id = ++requestId;
  selected = domain; render();
  $('modal-title').textContent = `${domain} 분석 보고서`;
  if (!$('report-modal').open) $('report-modal').showModal();
  document.body.classList.add('modal-open');
  $('detail').replaceChildren(element('p', '보고서를 불러오는 중입니다...', 'report-content'));
  try {
    const report = await api(`/api/report?domain=${encodeURIComponent(domain)}`);
    if (id !== requestId || !$('report-modal').open) return;
    const data = report.collected_data;
    const content = element('div', undefined, 'report-content');
    content.append(element('p', `분석 시각 ${date(report.analyzed_at)} KST`, 'report-date'));
    const section = element('section');
    const analysis = element('div', undefined, 'analysis markdown');
    // 서버에서 허용한 서식만 남긴 HTML을 사용하며, 원본 분석 문자열은 HTML로 삽입하지 않는다.
    if (typeof report.analysis_html === 'string') analysis.innerHTML = report.analysis_html;
    else analysis.textContent = report.analysis;
    section.append(element('h4', 'AI 분석 결과'), analysis);
    content.append(section);
    const facts = element('dl', undefined, 'facts');
    for (const [name, value] of [['페이지 제목', data.title], ['최종 URL', data.final_url], ['작업 ID', report.job_id]]) {
      facts.append(element('dt', name), element('dd', value || '—'));
    }
    const factsSection = element('section', undefined, 'report-section'); factsSection.append(facts); content.append(factsSection);
    addSection(content, 'DNS 조회 결과', JSON.stringify(data.dns || {}, null, 2));
    addSection(content, '수집한 본문', data.body_text || '본문이 없습니다.');
    for (const [label, value] of [['링크', data.links], ['폼', data.forms], ['스크립트 주소', data.script_urls], ['응답 헤더', data.headers]]) {
      const details = element('details');
      details.append(element('summary', label), element('pre', typeof value === 'string' ? value : JSON.stringify(value || [], null, 2)));
      content.append(details);
    }
    $('detail').replaceChildren(content);
  } catch (error) {
    if (id === requestId) $('detail').replaceChildren(element('p', error.message, 'report-content'));
  }
}
// 네이티브 dialog가 포커스 이동과 Escape 닫기를 처리한다.
$('close-report').addEventListener('click', () => $('report-modal').close());
$('report-modal').addEventListener('click', event => {
  const rect = $('report-modal').getBoundingClientRect();
  if (event.target === $('report-modal') &&
      (event.clientX < rect.left || event.clientX > rect.right ||
       event.clientY < rect.top || event.clientY > rect.bottom)) {
    $('report-modal').close();
  }
});
$('report-modal').addEventListener('close', () => {
  // 닫은 보고서의 늦은 응답이 다음 모달 내용을 덮어쓰지 못하도록 무효화한다.
  requestId++;
  const previousDomain = selected;
  selected = null;
  document.body.classList.remove('modal-open');
  render();
  const trigger = [...document.querySelectorAll('.report-button')]
    .find(button => button.dataset.domain === previousDomain);
  (trigger || $('search')).focus();
});
function openDelete(item) {
  if (deleting || listing) return;
  deleteTarget = { ...item };
  $('delete-domain').textContent = item.domain;
  $('delete-key').textContent = item.report_s3_key || '등록된 보고서 없음';
  $('delete-confirmation').value = '';
  $('delete-error').textContent = '';
  $('confirm-delete').disabled = true;
  $('delete-modal').showModal();
  document.body.classList.add('modal-open');
}
$('delete-confirmation').addEventListener('input', () => {
  $('confirm-delete').disabled = deleting || $('delete-confirmation').value !== deleteTarget?.domain;
});
$('close-delete').addEventListener('click', () => { if (!deleting) $('delete-modal').close(); });
$('delete-modal').addEventListener('cancel', event => { if (deleting) event.preventDefault(); });
$('delete-modal').addEventListener('close', () => {
  const domain = deleteTarget?.domain;
  deleteTarget = null;
  if (!$('report-modal').open) document.body.classList.remove('modal-open');
  const trigger = [...document.querySelectorAll('.delete-button')].find(button => button.dataset.domain === domain);
  (trigger || $('search')).focus();
});
$('delete-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!deleteTarget || deleting || $('delete-confirmation').value !== deleteTarget.domain) return;
  const target = deleteTarget;
  deleting = true;
  $('confirm-delete').disabled = true;
  $('confirm-delete').textContent = '삭제 중';
  $('close-delete').disabled = true;
  $('delete-confirmation').disabled = true;
  $('refresh').disabled = true; $('more').disabled = true;
  $('delete-error').textContent = '';
  render();
  try {
    const expected = Object.fromEntries(['status', 'created_at', 'updated_at', 'report_s3_key']
      .map(field => [field, target[field] ?? null]));
    await api('/api/domains', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'DNSAdmin' },
      body: JSON.stringify({ domain: target.domain, confirmation: $('delete-confirmation').value, expected })
    });
    items = items.filter(item => item.domain !== target.domain);
    render();
    $('list-message').textContent = `${target.domain} 삭제 완료`;
    $('delete-modal').close();
  } catch (error) {
    $('delete-error').textContent = error.message;
  } finally {
    deleting = false;
    $('confirm-delete').textContent = '삭제';
    $('confirm-delete').disabled = $('delete-confirmation').value !== deleteTarget?.domain;
    $('close-delete').disabled = false;
    $('delete-confirmation').disabled = false;
    $('refresh').disabled = false; $('more').disabled = false;
    render();
  }
});
$('search').addEventListener('input', render);
$('status').addEventListener('change', render);
$('refresh').addEventListener('click', () => load(true));
$('more').addEventListener('click', () => load());
for (const [id, value] of [['all-view', ''], ['review-view', 'review']]) {
  $(id).addEventListener('click', () => {
    $('status').value = value;
    $('all-view').classList.toggle('active', !value);
    $('review-view').classList.toggle('active', !!value);
    $('all-view').setAttribute('aria-pressed', String(!value));
    $('review-view').setAttribute('aria-pressed', String(!!value));
    document.querySelector('h1').textContent = value ? '검토 대상' : '도메인 현황';
    render();
  });
}
load(true);

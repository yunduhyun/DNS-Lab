# browser_mcp_server.py 설명

2026-10-28의 로컬 코드를 기준으로 작성한다.

## 역할

- MCP의 `investigate_url` 도구를 제공한다.
- 창이 보이는 Google Chrome을 실행하고 nodriver로 연결한다.
- 기존 FlareSolverr API 호출은 제거한다.
- 현재 실행 환경은 Google Chrome이 설치된 macOS와 프로젝트 가상환경의 nodriver를 전제로 한다.

## 실행 순서

1. 클라이언트에서 받은 URL의 앞뒤 공백을 제거한다.
2. HTTP 또는 HTTPS인지, 호스트 이름이 존재하는지, 사용자 정보가 포함되지 않았는지 확인한다.
3. 조사 전용 임시 프로필과 로컬 제어 포트를 준비한다.
4. Chrome을 빈 페이지로 실행하고 제어 연결이 준비될 때까지 기다린다.
5. nodriver를 실행된 Chrome에 연결하고 파일 다운로드를 거부한다.
6. 메인 페이지의 문서 요청과 응답을 기록하도록 등록한다.
7. 경로와 쿼리를 포함한 입력 URL에 접속한다.
8. 자동 조사에서는 접속 후 10초, 수동 확인에서는 120초 동안 관찰한다.
9. 관찰 종료 시점의 URL, 제목과 화면 본문을 읽는다.
10. 수집 상태를 분류하고 결과를 반환한다.
11. 정상 반환과 오류 여부에 관계없이 이번 조사에서 실행한 Chrome을 종료하고 임시 프로필을 정리한다.

## 함수와 변수

- `collect_browser_data(url, observation_seconds)`는 Chrome 실행, 페이지 조사와 종료를 담당하는 비동기 함수다.
- `url`은 접속할 전체 URL이며 쿼리 문자열을 보존한다.
- `observation_seconds`는 최초 접속 뒤 추가로 관찰할 시간이다.
- `profile`은 이번 조사에서만 사용하는 임시 프로필 경로다.
- `port`는 현재 컴퓨터에서 Chrome 제어에 사용할 포트 번호다.
- `browser`는 nodriver의 브라우저 연결 객체다.
- `process`는 직접 실행한 Chrome 프로세스다.
- `frame_id`는 기록할 메인 페이지의 식별값이다.
- `navigation_history`는 메인 문서의 HTTP 리다이렉트 응답과 문서 응답 기록이다.
- `response_state`는 가장 최근 메인 문서 요청의 HTTP 상태와 인증 헤더를 보관한다.
- `investigate_url(url, manual_verification=False)`는 입력 검사, 조사 시간 제한과 결과 분류를 담당하는 MCP 도구다.
- 전체 조사에는 150초 제한을 적용하며 종료 정리에는 추가 시간이 필요할 수 있다.

## 반환값

| 항목 | 의미 |
|---|---|
| status | 수집 상태다. 사이트의 유해성 판정이 아니다. |
| reason | 수집 상태를 설명하는 정중한 문장이다. |
| needs_human_review | success가 아니면 참이다. 관리자 작업 생성 기능은 아니다. |
| requested_url | 입력한 전체 URL이다. |
| final_url | 관찰 종료 시점의 URL이다. |
| http_status | Chrome 네트워크 이벤트에서 확인한 메인 문서 응답 상태다. 미확인 시 null이다. |
| navigation_history | 메인 문서 응답 기록이다. iframe과 이미지 요청은 제외한다. |
| title | 관찰 종료 시점의 제목이다. |
| body_text | 화면 본문 전체다. 200글자 미리보기는 worker에서 처리한다. |

## 수집 상태

- `challenge`는 인증 헤더 또는 알려진 인증 제목과 Cloudflare 본문이 확인된 경우다.
- `limit_exceeded`는 메인 문서 응답 기록이 10개를 초과한 경우다.
- `incomplete`는 HTTP 응답을 확인하지 못했거나 본문이 비어 있는 경우다.
- `http_error`는 최종 메인 문서 응답이 2xx가 아닌 경우다.
- `success`는 위 조건에 해당하지 않고 본문을 확보한 경우다.
- `error`는 URL 거부, 전체 조사 시간 초과 또는 실행 오류가 발생한 경우다.

## 연결과 한계

- 기존 클라이언트의 도구 이름, 인자와 주요 반환 필드를 유지한다.
- MCP 표준 출력에는 임의의 진행 메시지를 출력하지 않는다.
- 쿠키와 개인 Chrome 프로필은 반환하거나 재사용하지 않는다.
- URL 전체를 입력받으면 경로와 쿼리를 유지하지만 DNS 로그에서 없는 경로를 복원하지는 않는다.
- `success`라도 원본 사이트 대신 다른 사이트에 도착했을 수 있으므로 최종 URL과 본문을 함께 판단해야 한다.
- 알려진 인증 문구 검사만으로 모든 인증 화면을 탐지한다고 보장하지 않는다.
- Chrome 창에서 수동 인증이 가능하지만 자동 클릭이나 로그인은 구현하지 않는다.
- 이 서버는 Gemma 호출, S3 저장, DynamoDB 갱신과 RPZ 반영을 수행하지 않는다.

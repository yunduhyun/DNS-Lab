# DNS 분석 작업 파일 안내

2026년 10월 28일의 로컬 소스 코드를 기준으로 작성한 설명서다. 각 설명서의 예시는 동작 이해를 위한 가상 자료이며 실제 AWS 실행 결과가 아니다.

## 파일 구성과 읽는 순서

```text
python_file/
├── README.md
├── analysis_worker/
│   ├── main.py
│   ├── main.md
│   ├── collector.py
│   ├── collector.md
│   ├── analyzer.py
│   ├── analyzer.md
│   ├── rules.md
│   └── .env
└── mcp_tools/
    ├── browser_mcp_client.py
    ├── browser_mcp_client.md
    ├── browser_mcp_server.py
    └── browser_mcp_server.md
```

1. [main.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/main.md)에서 전체 작업 순서, AWS 상태 갱신과 보고서 저장을 확인한다.
2. [collector.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/collector.md)에서 DNS 조회와 HTML 정보 추출을 확인한다.
3. [analyzer.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/analyzer.md)에서 정책 전달, 젬마 호출과 응답 검증을 확인한다.
4. [browser_mcp_client.md](/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_client.md)에서 로컬 MCP 서버 연결을 확인한다.
5. [browser_mcp_server.md](/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_server.md)에서 브라우저 접속, 이동 관찰과 결과 분류를 확인한다.
6. [rules.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/rules.md)에서 실제 AI 판단 정책을 확인한다. 이 파일 자체가 정책 문서이므로 별도 사본을 만들지 않는다.

## 현재 실행 흐름

```text
main.py 실행
  → AWS 클라이언트와 각 객체 준비
  → SQS 메시지 최대 1개 수신
  → collector.py에서 DNS 조회와 curl 수집
  → DynamoDB의 기존 도메인을 Analyzing으로 갱신
  → analyzer.py에서 젬마 1회 호출
  → needs_investigation이 true이면 MCP 클라이언트 실행
      → 로컬 MCP 서버 실행과 investigate_url 도구 호출
      → Playwright로 접속하고 관찰 결과 반환
      → collected_data에 mcp_investigation 추가
  → 최초 AI 보고서와 수집 자료를 S3에 저장
  → DynamoDB에 S3 객체 키 기록
  → SQS 메시지 삭제 후 종료
```

- SQS에 메시지가 없으면 최대 20초 기다린 뒤 종료한다. 반복해서 큐를 읽는 무한 반복문은 없다.
- collector가 `None`을 반환하면 현재 코드는 해당 메시지를 삭제하고 종료한다. 이 경로에서는 AI 호출과 보고서 저장을 하지 않는다.
- 수집 자료가 존재하는 경로에서는 분석, MCP 호출 또는 저장 중 예외가 발생하면 이후 단계로 진행하지 않는다.
- MCP 호출은 Python worker가 수행한다. 젬마는 JSON 응답으로 추가 조사 필요 여부와 URL을 제시한다.

## 구현된 범위와 남은 연결

- DNS의 A, AAAA, CNAME과 정적 HTML 정보 수집을 구현한 상태다.
- HTTP 리다이렉션은 collector의 `curl -L`도 따라간다. JavaScript 실행과 브라우저를 이용한 최종 페이지 관찰은 MCP 서버가 담당한다.
- 젬마가 추가 조사를 요청하면 MCP를 최대 한 번 호출하고 결과를 저장한다.
- analyzer에는 MCP 결과가 입력에 포함된 경우 최종 판단을 요청하는 지시문이 있다. 다만 현재 main은 MCP 이후 analyzer를 다시 호출하지 않는다. 따라서 현재 저장되는 `analysis`는 최초 AI 보고서다.
- FlareSolverr의 별도 성공 사례를 확인했으나 이 설명 대상 코드에는 연동되어 있지 않다.
- `needs_human_review`는 MCP 결과의 표시값이다. 관리자 작업 생성, 알림과 검토 화면 연결은 구현되어 있지 않다.
- AI의 `block` 판정은 분석 결과다. RPZ 파일 수정과 DNS 서버 반영은 이 코드에 구현되어 있지 않다.
- DynamoDB의 분석 완료 상태 갱신도 아직 없다. 현재 코드는 `Analyzing`과 보고서 위치를 기록한다.

## worker 실행

```bash
cd /Users/yunduhyun/Desktop/dns_project
source .venv/bin/activate
cd python_file/analysis_worker
python main.py
```

1. 첫 명령은 프로젝트 최상위 폴더로 이동한다.
2. `source`는 현재 셸에 가상환경 설정을 적용한다. 이후 `python`은 해당 가상환경의 Python을 사용한다.
3. 다음 명령은 실행 파일이 있는 폴더로 이동한다.
4. 마지막 명령은 SQS 메시지 하나를 실제로 처리한다. AWS 조회와 쓰기, 외부 사이트 수집 및 유료 AI 요청이 발생할 수 있다.

환경 구성은 다음 위치를 기준으로 확인한다.

- AWS 프로필 이름은 `dns-project`이며 리전은 `ap-northeast-2`다. 큐, 테이블과 버킷 설정은 [main.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/main.py)에 있다.
- `BAZE_API_KEY`와 `BAZE_MODEL`은 analyzer와 같은 폴더의 `.env` 또는 환경변수로 설정한다. 이 설명서는 실제 설정값을 포함하지 않는다.
- `rules.md`는 analyzer와 같은 폴더에서 읽는다.
- collector는 Python 패키지 `dnspython`, `beautifulsoup4`와 시스템의 `curl`을 사용한다.
- worker와 analyzer는 `boto3`, `python-dotenv`를 사용한다.
- MCP는 `mcp`, `playwright`, `playwright-stealth`와 설치된 Google Chrome을 사용한다. 현재 서버는 `channel="chrome"`을 지정한다.

## MCP만 따로 확인

```bash
/Users/yunduhyun/Desktop/dns_project/.venv/bin/python \
  /Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_client.py \
  https://example.com/
```

- 가상환경의 Python 경로를 직접 지정하므로 현재 폴더와 관계없이 실행한다.
- `example.com`은 호출 형식 설명용 주소다. 실행하면 해당 주소에 실제 브라우저 접속을 수행한다.
- 클라이언트가 서버를 실행하므로 서버를 별도 터미널에서 미리 실행할 필요가 없다.
- 출력의 `status`와 `reason`, `final_url`, `title`, `body_text`를 함께 확인한다. 수집 성공 여부와 사이트 유해성 판정은 별개다.

## 문서 갱신 기준

- main의 처리 순서나 AWS 저장 형식을 바꾸면 main 설명서와 이 안내서의 실행 흐름을 갱신한다.
- 수집 필드를 바꾸면 collector 설명서와 판단 정책의 확인 필드를 함께 검토한다.
- AI 응답 구조를 바꾸면 analyzer의 검증과 main의 사용 부분을 함께 확인한다.
- MCP 인자나 결과 상태를 바꾸면 클라이언트와 서버 설명서를 함께 갱신한다.
- 이번 작업은 문서 작성이며 외부 서비스의 현재 연결 상태나 배포 상태를 검증하지 않는다.

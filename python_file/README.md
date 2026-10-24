# DNS 분석 프로그램 구조 및 실행 안내

## 1. 정리 목적

기존 `sqs_worker.py`에 모여 있던 기능을 역할별로 분리한다. 실행 파일에는 전체 처리 순서를 남기고, 자료 수집과 AI 분석, 저장 코드는 각각의 파일에서 관리한다. 기존 처리 방식과 AWS 자원 이름은 유지한다.

## 2. 폴더 구성

```text
dns_project/
├── sqs_worker.py    # SQS 수신과 전체 실행 순서
├── collector.py     # DNS 조회와 웹 자료 수집
├── analyzer.py      # 로컬 Ollama 분석 요청
├── storage.py       # DynamoDB 갱신과 S3 보고서 저장
├── README.md        # 구조와 실행 방법 설명
└── .venv/           # 기존 Python 가상환경
```

모든 Python 파일은 같은 폴더에 배치한다. 새 패키지를 추가하지 않고 기존 가상환경을 사용한다. Python 들여쓰기는 단계마다 공백 2칸을 사용한다.

## 3. 전체 실행 흐름

```text
SQS에서 메시지 하나 수신
  → Body에서 domain과 job_id 추출
  → DNS와 웹 자료 수집
  → DynamoDB 상태를 Analyzing으로 변경
  → Ollama에 분석 요청
  → 분석 결과 출력
  → 수집 자료와 분석 결과를 S3에 저장
  → 프로그램 종료
```

실행 한 번에 메시지 하나만 처리한다. 메시지가 없으면 최대 20초 동안 수신을 기다린 뒤 종료한다. 웹 수집에 실패하면 AI 분석과 보고서 저장을 진행하지 않는다.

`Analyzing`은 AI 호출 직전에 기록하는 처리 상태다. Ollama 서버가 요청을 수락했다는 확인이나 분석 완료를 의미하지 않는다.

## 4. 파일별 역할

| 파일 | 주요 함수 | 입력 | 반환값과 역할 |
|---|---|---|---|
| `sqs_worker.py` | `main()` | SQS 메시지 | 각 기능을 순서대로 호출한다. |
| `collector.py` | `collect_data(domain, job_id)` | 도메인과 작업 ID | 수집 자료 딕셔너리를 반환하며, 웹 수집 실패 시 `None`을 반환한다. |
| `analyzer.py` | `analyze_data(collected_data)` | 수집 자료 | AI 분석 본문 문자열을 반환한다. |
| `storage.py` | `mark_analyzing(dynamodb, domain)` | DynamoDB 클라이언트와 도메인 | 기존 항목의 상태와 갱신 시각을 변경한다. |
| `storage.py` | `save_report(s3, domain, job_id, collected_data, analysis)` | S3 클라이언트와 보고서 자료 | 보고서를 저장하고 객체 키를 반환한다. |

### 자료 수집

`collector.py`는 최초 도메인의 A와 AAAA 레코드를 조회한다. DNS 유형별 조회 시간은 5초로 설정한다. 조회 실패도 자료에 기록한다.

웹페이지는 HTTPS로 먼저 요청하며, 기존에 지정한 curl 종료 코드에서만 HTTP로 한 번 재시도한다. 요청별 제한 시간은 15초, 리다이렉트는 최대 5회, 본문 크기 제한 설정은 2,000,000바이트다.

응답 헤더, 최종 URL, 제목, 외부 스크립트 주소, 링크, 폼, 본문 텍스트를 추출한다. 링크와 폼의 상대 주소는 최종 URL과 HTML의 `base` 태그를 기준으로 해석한다. 스크립트 주소는 기존처럼 원본 값을 보관한다.

JavaScript를 실행하거나 링크를 방문하거나 폼을 제출하지 않는다. 스크립트와 스타일 제거는 분석용 자료 정리이며, HTML을 안전하게 표시하기 위한 보안 정제 기능은 아니다.

### AI 분석

`analyzer.py`는 수집 자료를 `http://localhost:11434/api/chat`으로 전달한다. 모델은 `qwen3.5:9b`이며, `stream=False`와 `timeout=300` 설정을 유지한다.

수집 자료의 지시문을 따르지 않고, 확인 사실과 판단의 한계를 설명하도록 기존 프롬프트를 유지한다. 악성 판단 룰, 위험 점수, 자동 차단 기준은 이번 작업에서 추가하지 않는다.

### 상태 갱신과 보고서 저장

`mark_analyzing()`은 수신한 `domain`을 PK로 지정하고 다음 값을 갱신한다.

| 속성 | 기록 내용 |
|---|---|
| `status` | `Analyzing`을 기록한다. |
| `updated_at` | UTC 기준 ISO 형식 시각을 기록한다. |

`attribute_exists` 조건으로 기존 항목만 갱신한다. 해당 도메인이 없으면 오류를 발생시키며, 새 항목을 만들지 않는다.

`save_report()`는 다음 구조의 JSON을 UTF-8로 저장한다. JSON 들여쓰기는 공백 2칸을 사용한다.

| 보고서 필드 | 내용 |
|---|---|
| `domain` | 분석 대상 도메인을 기록한다. |
| `job_id` | SQS 메시지의 작업 ID를 기록한다. |
| `analyzed_at` | 보고서 생성 시각을 UTC로 기록한다. |
| `collected_data` | DNS 정보와 웹 수집 자료를 기록한다. |
| `analysis` | AI 분석 본문을 기록한다. |

객체 키는 `reports/{domain}/{job_id}.json` 형식이다. 같은 도메인과 작업 ID로 다시 저장하면 동일한 키로 업로드한다. 별도의 로컬 보고서 파일은 생성하지 않는다.

## 5. 설정 위치

다음 값은 모듈화 이전 실제 작업 파일에서 확인한 코드 설정이다. AWS 콘솔의 현재 자원이나 권한 상태를 직접 조회한 결과는 아니다.

| 설정 | 위치 | 현재 값 |
|---|---|---|
| AWS 프로필 | `sqs_worker.py` | `dns-project`다. |
| AWS 리전 | `sqs_worker.py` | `ap-northeast-2`다. |
| SQS URL | `sqs_worker.py` | `https://sqs.ap-northeast-2.amazonaws.com/994899741506/dns-domain-analysis.fifo`다. |
| DynamoDB 테이블 | `storage.py` | `dns-domain-analysis`다. |
| S3 버킷 | `storage.py` | `dns-analysis-reports-994899741506-ap-northeast-2-an`이다. |
| AI 모델과 API 주소 | `analyzer.py` | `qwen3.5:9b`와 로컬 Ollama 주소를 사용한다. |

실제 코드의 버킷 이름은 대화 초기에 제안한 이름보다 길다. 기존 값을 유지하므로 IAM 정책의 S3 리소스도 실제 이름과 일치해야 한다. 보고서 업로드 대상 ARN은 다음과 같다.

```text
arn:aws:s3:::dns-analysis-reports-994899741506-ap-northeast-2-an/reports/*
```

로컬 프로그램은 기존 `dns-project` 프로필로 클라이언트를 생성한다. 현재 처리에 사용하는 권한은 `sqs:ReceiveMessage`, `dynamodb:UpdateItem`, `s3:PutObject`다. 이번 작업은 IAM 정책을 변경하지 않는다.

## 6. 실행 방법

터미널에서 다음 명령을 실행한다.

```bash
cd /Users/yunduhyun/Desktop/dns_project
.venv/bin/python sqs_worker.py
```

직접 실행하면 `main()`을 호출한다. 다른 파일에서 모듈을 가져오기만 할 때는 메시지를 수신하거나 AWS를 갱신하지 않는다.

정상 처리 시 수집 자료 출력 이후 다음 메시지가 순서대로 나타난다.

```text
DynamoDB 상태 변경 완료: Analyzing
로컬 AI 분석 중...
AI 분석 결과:
분석 본문
S3 보고서 저장 완료: reports/도메인/작업ID.json
```

DynamoDB에서 해당 도메인의 `status`와 `updated_at`을 확인하고, S3 버킷의 `reports/` 아래에서 JSON 보고서를 확인한다. 이 절차는 실제 환경에서 사용자가 실행할 확인 방법이다.

## 7. 검증 결과와 현재 한계

구문 검사와 모듈 가져오기 검사를 수행한다. AWS, DNS, curl, Ollama 호출을 테스트용 응답으로 대체하여 기존 코드와 다음 8가지 상황의 결과 및 호출 순서를 비교한 결과가 모두 일치한다.

정상 처리, 메시지 없음, HTTP 재시도, 웹 수집 실패, DNS 조회 실패, DynamoDB 갱신 실패, AI 요청 실패, S3 저장 실패를 검증한다. 실제 AWS 자원과 Ollama를 호출하는 통합 실행은 수행하지 않는다.

현재 동작의 한계는 다음과 같다.

- S3 저장 후 DynamoDB에 보고서 위치와 완료 상태를 기록하는 기능은 아직 구현하지 않는다.
- SQS 메시지 삭제와 표시 제한 시간 연장 기능은 아직 구현하지 않는다. 따라서 재수신이 발생할 수 있다.
- AI 요청이나 S3 저장이 실패하면 프로그램이 오류로 종료하며, 이미 기록한 `Analyzing` 상태는 유지한다.
- 수집 대상의 사설 IP 접근 방지와 리다이렉트별 대상 검증은 아직 구현하지 않는다.

다음 단계는 S3 저장 성공 후 DynamoDB에 보고서 위치와 완료 상태를 기록하는 것이다. 이후 저장 완료를 확인한 작업의 SQS 메시지를 삭제하는 순서로 구현한다.

# DNS 분석 프로그램 구조 및 실행 안내

## 폴더 구성

```text
python_file/
├── main.py          # 단일 진입점과 객체 생성
├── sqs_worker.py    # SQSWorker 클래스
├── collector.py     # DomainCollector 클래스
├── analyzer.py      # GemmaAnalyzer 클래스
├── storage.py       # ReportStorage 클래스
├── test_worker.py   # 외부 호출 없는 처리 순서 검증
└── .env             # BAZE_API_KEY와 BAZE_MODEL 설정
```

기존 파일별 역할은 유지하고 함수들을 해당 클래스의 메서드로 옮긴다. 메서드는 객체에 속한 함수다. Python 들여쓰기는 단계마다 공백 2칸을 사용한다.

## 실행 방법

프로젝트 루트에서 터미널 명령을 실행한다.

```bash
cd /Users/yunduhyun/Desktop/dns_project
.venv/bin/python python_file/main.py
```

진입점은 `main.py`다. 기존 `sqs_worker.py`는 클래스 정의를 제공하며 직접 실행해도 작업을 시작하지 않는다. 실행 한 번에 메시지 하나만 처리하고 종료한다. 메시지가 없으면 최대 20초 동안 기다린 뒤 종료한다.

## 실행 순서와 코드 변경

기존 진입점의 주요 호출은 다음과 같다.

```python
collected_data = collect_data(domain, job_id)
mark_analyzing(dynamodb, domain)
analysis = analyze_data(collected_data)
report_s3_key = save_report(s3, dynamodb, domain, job_id, collected_data, analysis)
```

새 진입점은 다음 순서로 객체를 생성한다.

```python
session = boto3.Session(profile_name=AWS_PROFILE)
sqs = session.client("sqs", region_name=AWS_REGION)
dynamodb = session.client("dynamodb", region_name=AWS_REGION)
s3 = session.client("s3", region_name=AWS_REGION)
collector = DomainCollector()
analyzer = GemmaAnalyzer()
storage = ReportStorage(s3, dynamodb)
worker = SQSWorker(sqs, collector, analyzer, storage)
worker.run()
```

1. `session`은 기존 `dns-project` AWS 프로필을 사용하는 세션이다. 세션은 같은 인증 설정으로 AWS 서비스에 접근할 때 사용하는 객체다.
2. `sqs`, `dynamodb`, `s3`에는 각각 큐 수신, 항목 갱신, 보고서 저장을 요청할 클라이언트가 들어간다. 리전은 기존 `ap-northeast-2`다.
3. `collector = DomainCollector()`는 수집 객체를 만든다. 클래스 이름 뒤의 괄호는 해당 클래스로 객체를 생성한다는 뜻이다.
4. `analyzer = GemmaAnalyzer()`는 분석 객체를 만들고 이 파일 옆의 `.env`를 읽는다. API 키와 모델명은 분석 요청 때 확인한다.
5. `storage = ReportStorage(s3, dynamodb)`는 저장 객체를 만들면서 사용할 클라이언트를 전달한다. 생성 메서드인 `__init__`가 `self.s3`, `self.dynamodb`에 보관한다. `self`는 현재 객체를 가리킨다.
6. `worker = SQSWorker(sqs, collector, analyzer, storage)`는 앞서 만든 객체들을 워커에 전달한다. 워커는 전달받은 객체를 속성에 보관하므로 실행 중 새 클라이언트를 만들 필요가 없다.
7. `worker.run()`은 메시지 하나를 받아 아래 순서로 처리한다.

```python
collected_data = self.collector.collect_data(domain, job_id)
self.storage.mark_analyzing(domain)
analysis = self.analyzer.analyze_data(collected_data)
report_s3_key = self.storage.save_report(domain, job_id, collected_data, analysis)
```

1. 메시지가 `{"domain": "example.com", "job_id": "job-001"}`이면 `domain`에는 `example.com`, `job_id`에는 `job-001`이 들어간다. 수집 결과는 `collected_data` 딕셔너리에 들어가며, 웹 수집 실패로 `None`이 반환되면 SQS 메시지를 삭제하고 분석과 저장 없이 종료한다. 이 경우 DynamoDB 상태는 갱신하지 않는다.
2. `self.storage.mark_analyzing(domain)`은 기존 DynamoDB 항목의 상태를 `Analyzing`으로 바꾼다. 기존 함수와 달리 매번 클라이언트를 인자로 전달하지 않고 저장 객체에 보관한 클라이언트를 사용한다.
3. `self.analyzer.analyze_data(collected_data)`는 기존 Gemma API에 수집 자료를 전달한다. 반환된 분석 본문 문자열이 `analysis`에 들어간다. 프롬프트, 300초 제한 시간과 빈 응답 검증을 유지한다.
4. `self.storage.save_report(...)`는 수집 자료와 분석 결과를 S3에 저장하고 DynamoDB에 보고서 위치를 기록한다. 위 예시의 반환값은 `reports/example.com/job-001.json`이며 `report_s3_key`에 들어간다.
5. 웹 수집 실패로 `None`이 반환된 경우 외에는 저장 메서드가 정상 반환된 뒤에만 워커가 SQS 메시지를 삭제한다. 수집 중 예외, 상태 갱신, 분석, S3 저장 또는 보고서 위치 갱신에서 오류가 발생하면 예외를 전달하며 메시지를 삭제하지 않는다. SQS 삭제 요청 자체가 실패해도 예외를 전달한다.

```python
if __name__ == "__main__":
  main()
```

`main.py`를 직접 실행하면 `__name__`에 `"__main__"`이 들어가므로 `main()`을 호출한다. 다른 파일에서 가져오면 이 조건이 거짓이므로 AWS 작업을 시작하지 않는다.

## 설정과 기존 동작

| 위치 | 설정 |
|---|---|
| `sqs_worker.py` | 기존 AWS 프로필, 리전과 SQS URL을 유지한다. |
| `storage.py` | 기존 DynamoDB 테이블과 S3 버킷을 유지한다. |
| `analyzer.py` | 기존 BAZE Gemma API 주소를 유지한다. |
| `.env` | `BAZE_API_KEY`와 `BAZE_MODEL`을 사용한다. |

수집 코드는 DNS 조회, HTTPS 우선 요청, 지정된 오류에서 HTTP 재시도, 문자 인코딩 처리와 HTML 추출 방식을 유지한다. 저장 보고서의 필드와 경로도 유지한다. `Analyzing` 이후 완료 상태를 기록하거나 SQS 표시 제한 시간을 연장하는 기능은 이번 구조 변경에 포함하지 않는다.

## 로컬 검증 방법

```bash
.venv/bin/python -B -m unittest discover -s python_file -p 'test_*.py' -v
```

AWS, DNS, 웹사이트와 Gemma API를 호출하지 않고 테스트용 객체로 처리 순서와 실패 시 메시지 보존을 확인한다. 실제 AWS 자원과 API를 사용하는 통합 실행은 별도 확인이 필요하다.

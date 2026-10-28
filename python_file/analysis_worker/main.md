# main.py 설명

대상 소스는 [main.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/main.py)다. AWS 연결, 작업 수신, 수집과 분석 요청, 보고서 저장을 한 파일에서 연결한다. 기존 `sqs_worker.py`와 `storage.py`의 클래스가 이 파일에 포함되어 있다.

## 1. 실행 시작과 객체 준비

```python
if __name__ == "__main__":
  main()
```

- Python이 파일을 직접 실행하면 `__name__`에 `"__main__"`이 들어간다. 이 경우에만 `main()`을 호출한다.
- 다른 파일에서 import하면 함수와 클래스 정의를 읽지만 이 조건문의 `main()`은 실행하지 않는다.

```python
def main():
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

1. `Session`은 `dns-project` 프로필을 사용하는 AWS 연결 설정을 준비한다.
2. `session.client()`는 각 AWS 서비스에 요청할 객체를 만든다. 세 객체의 리전은 `ap-northeast-2`다.
3. `DomainCollector()`는 수집 객체를 만든다. 생성만으로 사이트에 접속하지 않는다.
4. `GemmaAnalyzer()`는 분석 객체를 만들며 이때 analyzer 옆의 `.env`를 읽는다.
5. `ReportStorage(s3, dynamodb)`는 위에서 만든 AWS 객체를 보관한다.
6. `SQSWorker(...)`는 필요한 객체를 보관하고 `worker.run()`에서 실제 처리를 시작한다.

클래스의 `self`는 만들어진 객체 자신을 가리킨다. 예를 들어 `self.sqs = sqs`는 받은 SQS 객체를 나중에 `run()`에서도 사용할 수 있게 보관한다.

## 2. SQS 메시지 하나 수신

```python
response = self.sqs.receive_message(
  QueueUrl=self.queue_url,
  MaxNumberOfMessages=1,
  WaitTimeSeconds=20
)

messages = response.get("Messages", [])

if not messages:
  print("수신할 메시지가 없습니다.")
  return

message = messages[0]
task = json.loads(message["Body"])

domain = task["domain"]
job_id = task["job_id"]
```

- `QueueUrl`은 `QUEUE_URL`에 지정한 FIFO 큐 주소다.
- `MaxNumberOfMessages=1`은 최대 하나를 요청한다. 반드시 하나가 반환된다는 뜻은 아니다.
- `WaitTimeSeconds=20`은 메시지가 없을 때 최대 20초 동안 기다리는 설정이다.
- `.get("Messages", [])`는 키가 없으면 빈 리스트를 사용한다. `if not messages`는 리스트가 비었는지 확인한다.
- `return`은 이번 `run()`을 종료한다. 이 코드에는 다음 메시지를 계속 읽는 반복문이 없다.
- `[0]`은 첫 메시지를 꺼낸다. `json.loads()`는 메시지 본문의 JSON 문자열을 딕셔너리로 바꾼다.

예를 들어 메시지 본문이 `{"domain":"example.com","job_id":"demo-job"}`이면 `domain`은 `"example.com"`, `job_id`는 `"demo-job"`이 된다. 이 값은 이후 예시에서도 사용한다.

## 3. DNS와 웹페이지 수집

```python
collected_data = self.collector.collect_data(domain, job_id)
if collected_data is None:
  self.sqs.delete_message(
    QueueUrl=self.queue_url,
    ReceiptHandle=message["ReceiptHandle"]
  )
  print(f"웹 정보 수집 실패로 SQS 메시지 삭제 완료: {domain}")
  return
```

- collector는 성공 시 딕셔너리, 웹 수집 실패 시 `None`을 반환한다. 세부 동작은 [collector.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/collector.md)에 설명한다.
- `is None`은 반환값이 실패를 나타내는 `None`인지 확인한다.
- 현재 구현은 수집 실패 메시지를 삭제하고 종료한다. 이 경로에서는 보고서를 저장하지 않는다.
- `ReceiptHandle`은 이번 수신에 대한 삭제용 값이다. 도메인이나 `job_id`를 대신 넣지 않는다.

## 4. DynamoDB 상태 갱신 후 AI 요청

```python
self.storage.mark_analyzing(domain)
analysis_result = self.analyzer.analyze_data(collected_data)
```

- 먼저 DynamoDB 갱신을 완료한다. 실패하면 다음 AI 요청을 실행하지 않는다.
- 이후 `analyze_data()`에 수집 자료를 전달한다. 반환값은 `decision`, `needs_investigation`, `investigation_url`, `reason`, `report`를 가진 딕셔너리다.
- AI 요청 과정은 [analyzer.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/analyzer.md)에 설명한다.

`mark_analyzing()`의 AWS 요청에서 핵심 부분은 다음과 같다.

```python
Key={"domain": {"S": domain}},
UpdateExpression="SET #status = :status, updated_at = :updated_at",
ConditionExpression="attribute_exists(#domain)",
ExpressionAttributeNames={"#status": "status", "#domain": "domain"},
ExpressionAttributeValues={
  ":status": {"S": "Analyzing"},
  ":updated_at": {"S": datetime.now(timezone.utc).isoformat()}
}
```

- 이 코드는 함수 전체가 아니라 `update_item()`에 전달하는 인자 발췌다.
- `Key`는 `domain="example.com"`인 항목을 지정한다. `S`는 문자열 타입을 뜻한다.
- `UpdateExpression`은 상태와 갱신 시간을 설정하는 문장이다.
- `#status`, `#domain`은 실제 속성 이름을 대신하는 이름이고 `:status`, `:updated_at`은 실제 값을 대신하는 이름이다.
- `attribute_exists(#domain)`은 기존 항목이 있을 때만 갱신하게 한다. `www.example.com`과 `example.com`은 다른 키다.
- `datetime.now(timezone.utc).isoformat()`은 현재 UTC 시각을 문자열로 만든다. 해당 키가 없으면 조건 실패 예외가 발생한다.

## 5. 필요한 경우 MCP 조사

```python
if analysis_result["needs_investigation"]:
  investigation_url = analysis_result["investigation_url"]

  python_directory = Path(__file__).resolve().parent.parent
  client_path = python_directory / "mcp_tools" / "browser_mcp_client.py"
```

- `needs_investigation`이 `True`일 때만 실행한다. `False`이면 바로 보고서 저장 단계로 이동한다.
- 예를 들어 `investigation_url`에는 `"https://example.com/welcome"`이 들어간다.
- `__file__`은 현재 소스 파일의 위치다. `resolve()`는 절대 경로를 구하고 `.parent.parent`는 두 단계 위인 `python_file`을 가리킨다.
- `Path`의 `/`는 폴더와 파일 이름을 결합한다. 이 계산으로 MCP 클라이언트의 절대 경로를 얻는다.

```python
result = subprocess.run(
  [sys.executable, str(client_path), investigation_url],
  capture_output=True,
  text=True,
  check=True,
  timeout=200
)

investigation = json.loads(result.stdout)

if not isinstance(investigation, dict):
  raise RuntimeError("MCP 조사 결과가 딕셔너리 형식이 아니었습니다.")

collected_data["mcp_investigation"] = investigation
```

- `subprocess.run()`은 별도 Python 프로세스로 기존 MCP 클라이언트를 실행하고 끝날 때까지 기다린다.
- `sys.executable`은 worker를 실행한 Python 경로다. worker가 가상환경에서 실행 중이면 클라이언트도 같은 Python을 사용한다.
- `str(client_path)`는 경로 객체를 명령 인자로 사용할 문자열로 바꾼다. 리스트의 마지막 값은 조사할 URL이다.
- `capture_output=True`는 표준 출력과 오류 출력을 `result`에 담는다. `text=True`는 이를 문자열로 받게 한다.
- `check=True`는 프로세스 종료 코드가 0이 아닐 때 예외를 발생시킨다. `timeout=200`은 이 프로세스 실행을 최대 200초 기다리게 한다.
- `result.stdout`에는 클라이언트가 출력한 JSON이 들어간다. `json.loads()`로 딕셔너리로 읽는다.
- `isinstance(..., dict)`는 객체 종류를 확인한다. 딕셔너리가 아니면 예외로 중단한다.
- `mcp_investigation` 키로 결과를 추가하여 이후 S3 보고서에도 보관한다.

현재 이 단계 뒤에 젬마를 다시 호출하는 코드는 없다. 예를 들어 MCP가 최종 URL을 찾아도 저장되는 AI 보고서는 최초 분석 결과다.

## 6. S3 보고서 저장 후 DynamoDB에 위치 기록

```python
analysis = analysis_result["report"]
report_s3_key = self.storage.save_report(domain, job_id, collected_data, analysis)
```

- `analysis`는 전체 AI 딕셔너리가 아닌 `report` 문자열이다.
- `save_report()`는 보고서 생성, S3 업로드, DynamoDB 위치 기록을 순서대로 수행한다.

```python
report = {
  "domain": domain,
  "job_id": job_id,
  "analyzed_at": datetime.now(timezone.utc).isoformat(),
  "collected_data": collected_data,
  "analysis": analysis
}

report_s3_key = f"reports/{domain}/{job_id}.json"
```

- `report`에는 수집 자료 전체와 AI 보고서를 담는다. 추가 조사를 수행했다면 수집 자료 안에 `mcp_investigation`도 들어간다.
- `f"..."`는 중괄호 안의 변숫값을 문자열에 넣는다. 예시의 S3 객체 키는 `reports/example.com/demo-job.json`이다.
- S3 객체 키는 버킷 안에서 보고서를 식별하는 이름이다. 로컬 파일 경로가 아니다.
- `json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")`는 보고서를 한글을 유지한 JSON 문자열로 만들고 업로드할 바이트로 바꾼다.
- `s3.put_object()`가 성공한 다음 `dynamodb.update_item()`으로 `report_s3_key`와 `updated_at`을 기록한다. 이 갱신도 기존 항목이 있어야 성공한다.
- 완료 상태를 설정하거나 `decision`을 별도 속성으로 기록하는 코드는 없다. 분석 상태는 이 코드에서 `Analyzing`으로만 설정한다.

## 7. 처리한 SQS 메시지 삭제

```python
self.sqs.delete_message(
  QueueUrl=self.queue_url,
  ReceiptHandle=message["ReceiptHandle"]
)
```

- 수집 자료가 있는 정상 경로에서는 보고서 저장과 DynamoDB 갱신이 모두 성공한 뒤 삭제한다.
- AI 요청, MCP 프로세스 실행, 응답 해석 또는 저장에서 예외가 발생하면 이 줄에 도달하지 않는다.
- 다만 앞서 설명한 collector의 `None` 반환 경로는 보고서 저장 없이 별도로 삭제한다.
- 현재 코드는 SQS 메시지의 숨김 시간을 지정하거나 연장하지 않는다. 실제 큐 설정은 이 파일만으로 확인할 수 없다.

## 설정과 수정 위치

- `AWS_PROFILE`, `AWS_REGION`, `QUEUE_URL`은 AWS 연결 대상 설정이다.
- `TABLE_NAME`과 `REPORT_BUCKET`은 상태와 보고서 저장 대상 설정이다.
- 처리 순서는 `SQSWorker.run()`에서 수정한다.
- 저장 형식은 `ReportStorage.save_report()`에서 수정한다.
- MCP 뒤 AI 재판단, FlareSolverr 연결, HITL 작업 생성과 RPZ 반영은 앞으로 연결할 기능이다.

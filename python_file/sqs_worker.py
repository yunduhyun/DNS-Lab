"""SQS 작업 하나를 수신하여 수집, 분석, 저장과 메시지 삭제를 조정한다."""

import json

AWS_PROFILE = "dns-project"
AWS_REGION = "ap-northeast-2"
QUEUE_URL = "https://sqs.ap-northeast-2.amazonaws.com/994899741506/dns-domain-analysis.fifo"


class SQSWorker:
  def __init__(self, sqs, collector, analyzer, storage, queue_url=QUEUE_URL):
    self.sqs = sqs
    self.collector = collector
    self.analyzer = analyzer
    self.storage = storage
    self.queue_url = queue_url

  def run(self):
    """메시지 하나를 처리하며 웹 수집 실패 또는 저장 성공 시 큐에서 삭제한다."""
    # 메시지가 없으면 최대 20초 동안 기다리며, 한 번에 하나만 수신한다.
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

    collected_data = self.collector.collect_data(domain, job_id)
    if collected_data is None:
      self.sqs.delete_message(
        QueueUrl=self.queue_url,
        ReceiptHandle=message["ReceiptHandle"]
      )
      print(f"웹 정보 수집 실패로 SQS 메시지 삭제 완료: {domain}")
      return

    print(json.dumps(collected_data, ensure_ascii=False, indent=2))

    # 상태 갱신이 성공한 뒤 AI를 호출하며, 오류는 그대로 전달하여 실행을 중단한다.
    self.storage.mark_analyzing(domain)
    print("DynamoDB 상태 변경 완료: Analyzing")
    print("Gemma 분석 중...")
    analysis = self.analyzer.analyze_data(collected_data)

    print("AI 분석 결과:")
    print(analysis)

    report_s3_key = self.storage.save_report(domain, job_id, collected_data, analysis)
    print(f"S3 저장 및 DynamoDB 보고서 위치 기록 완료: {report_s3_key}")

    # 보고서 저장과 DynamoDB 갱신이 성공한 작업만 큐에서 삭제한다.
    self.sqs.delete_message(
      QueueUrl=self.queue_url,
      ReceiptHandle=message["ReceiptHandle"]
    )
    print(f"SQS 메시지 삭제 완료: {domain}")

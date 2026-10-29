"""AWS 클라이언트를 준비하고 DNS 수집, AI 분석, 보고서 저장을 순서대로 실행한다."""

import json
import subprocess
import sys
import time 

from datetime import datetime, timezone
from pathlib import Path

import boto3
from analyzer import GemmaAnalyzer
from collector import DomainCollector

TABLE_NAME = "dns-domain-analysis"
REPORT_BUCKET = "dns-analysis-reports-994899741506-ap-northeast-2-an"


class ReportStorage:
  def __init__(self, s3, dynamodb):
    self.s3 = s3
    self.dynamodb = dynamodb

  def mark_analyzing(self, domain):
    """기존 항목만 Analyzing으로 갱신하고 UTC 시각을 기록한다."""
    # AI 요청 직전에 도메인의 상태와 갱신 시각을 기록한다.
    self.dynamodb.update_item(
      TableName=TABLE_NAME,
      Key={
        "domain": {"S": domain}
      },
      UpdateExpression="SET #status = :status, updated_at = :updated_at",
      ConditionExpression="attribute_exists(#domain)",
      ExpressionAttributeNames={
        "#status": "status",
        "#domain": "domain"
      },
      ExpressionAttributeValues={
        ":status": {"S": "Analyzing"},
        ":updated_at": {"S": datetime.now(timezone.utc).isoformat()}
      }
    )


  def save_report(self, domain, job_id, collected_data, analysis, decision):
    """S3에 보고서를 저장하고 DynamoDB에 최종 상태와 보고서 위치를 기록한다."""
    if decision == "block":
      status = "blocked"
    elif decision in ["review", "allow"]:
      status = decision
    else:
      raise RuntimeError("저장할 최종 판정이 유효하지 않았습니다.")

    report = {
      "domain": domain,
      "job_id": job_id,
      "analyzed_at": datetime.now(timezone.utc).isoformat(),
      "collected_data": collected_data,
      "analysis": analysis
    }

    report_s3_key = f"reports/{domain}/{job_id}.json"

    # JSON 보고서를 UTF-8 바이트로 변환하여 S3에 저장한다.
    self.s3.put_object(
      Bucket=REPORT_BUCKET,
      Key=report_s3_key,
      Body=json.dumps(
        report,
        ensure_ascii=False,
        indent=2
      ).encode("utf-8"),
      ContentType="application/json; charset=utf-8"
    )

  
    # S3 저장이 성공한 뒤 보고서 위치와 갱신 시각을 기록한다.
        # S3 저장이 성공한 뒤 최종 상태와 보고서 위치 및 갱신 시각을 기록한다.
    self.dynamodb.update_item(
      TableName=TABLE_NAME,
      Key={
        "domain": {"S": domain}
      },
      UpdateExpression="SET #status = :status, report_s3_key = :key, updated_at = :updated_at",
      ConditionExpression="attribute_exists(#domain)",
      ExpressionAttributeNames={
        "#domain": "domain",
        "#status": "status"
      },
      ExpressionAttributeValues={
        ":status": {"S": status},
        ":key": {"S": report_s3_key},
        ":updated_at": {"S": datetime.now(timezone.utc).isoformat()}
      }
    )

    return report_s3_key


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
      # AI를 호출하지 않고 수집 실패 보고서를 작성한다.
      analysis = f"""### 판정
      review
      
      ### 대상 도메인
      {domain}
      
      ### 검토 사유
      웹 정보 수집에 실패하여 실제 콘텐츠를 확인하지 못했다.
      
      ### 판단의 한계
      접속 실패만으로 사이트의 유해 여부를 판단할 수 없다.
      관리자의 추가 확인이 필요하다.
      """

      print("\n---- [RESULT] ----")
      print(analysis)

      report_s3_key = self.storage.save_report(
        domain,
        job_id,
        collected_data,
        analysis,
        "review"
      )
      print(f"S3 저장 및 DynamoDB review 갱신 완료: {report_s3_key}")

      # 보고서 저장과 DynamoDB 갱신이 성공한 뒤 메시지를 삭제한다.
      self.sqs.delete_message(
        QueueUrl=self.queue_url,
        ReceiptHandle=message["ReceiptHandle"]
      )
      print(f"SQS 메시지 삭제 완료: {domain}")
      return

    domain_unicode = collected_data["domain_unicode"]

    print(json.dumps(collected_data, ensure_ascii=False, indent=2))

    # 상태 갱신이 성공한 뒤 AI를 호출하며, 오류는 그대로 전달하여 실행을 중단한다.
    self.storage.mark_analyzing(domain)
    print("DynamoDB 상태 변경 완료: Analyzing")
    print("Gemma 분석 중...")
    
    analysis_result = self.analyzer.analyze_data(collected_data)

    print("\n---- [INITIAL] ----")
    print(f"대상 도메인: {domain_unicode}")
    print(f"초기 판단: {analysis_result['decision']}")
    print(f"판단 이유: {analysis_result['reason']}")
    print()
    print(analysis_result["report"])

    if analysis_result["needs_investigation"]:
      investigation_url = analysis_result["investigation_url"]

      python_directory = Path(__file__).resolve().parent.parent
      client_path = python_directory / "mcp_tools" / "browser_mcp_client.py"

      print("\n---- [INFORMATION] ----")
      print(f"{investigation_url} 에 대한 추가 조사를 위해 MCP를 사용합니다.")

      result = subprocess.run(
        [sys.executable, str(client_path), investigation_url], # MCP Client를 호출하여 추가 조사를 진행
        capture_output=True,  # 클라이언트의 출력과 오류를 결과에 보관한다.
        text=True,  # 출력 내용을 문자열로 받는다.
        check=True,  # 클라이언트 실행이 실패하면 예외를 발생시킨다.
        timeout=200  # 클라이언트 실행을 최대 200초 기다린다.
      )

      investigation = json.loads(result.stdout)

      if not isinstance(investigation, dict):
        raise RuntimeError("MCP 조사 결과가 딕셔너리 형식이 아니었습니다.")

      collected_data["mcp_investigation"] = investigation

      print("MCP 추가 조사 결과를 받았습니다.")
      investigation_body = investigation.get("body_text", "")
      investigation_preview = investigation_body[:200]

      print("조사 본문 미리보기:")
      if investigation_preview:
        print(investigation_preview)
      else:
        print("수집된 본문이 없습니다.")

      # 최초 수집 자료와 MCP 조사 결과를 함께 전달하여 다시 분석한다.
      print("수집한 추가 정보를 바탕으로 Gemma 재판단을 요청하겠습니다.")
      analysis_result = self.analyzer.analyze_data(collected_data)

      print("\n---- [RESULT] ----")
      print(f"최종 판단: {analysis_result['decision']}")
      print(f"판단 이유: {analysis_result['reason']}")
      print()
      print(analysis_result["report"])

    # 기존 저장 함수에는 보고서 문자열을 전달한다.
    analysis = analysis_result["report"]

    print("\n---- [추가 정보] ----")
    report_s3_key = self.storage.save_report(
      domain,
      job_id,
      collected_data,
      analysis,
      analysis_result["decision"]
    )
    print(f"S3 저장 및 DynamoDB 보고서 위치 기록 완료: {report_s3_key}")

    # 보고서 저장과 DynamoDB 갱신이 성공한 작업만 큐에서 삭제한다.
    self.sqs.delete_message(
      QueueUrl=self.queue_url,
      ReceiptHandle=message["ReceiptHandle"]
    )
    print(f"SQS 메시지 삭제 완료: {domain}")


def main():
  session = boto3.Session(profile_name=AWS_PROFILE)
  sqs = session.client("sqs", region_name=AWS_REGION)
  dynamodb = session.client("dynamodb", region_name=AWS_REGION)
  s3 = session.client("s3", region_name=AWS_REGION)

  collector = DomainCollector()
  analyzer = GemmaAnalyzer()
  storage = ReportStorage(s3, dynamodb)
  worker = SQSWorker(sqs, collector, analyzer, storage)
  
  try:
    while True:
      try:
        worker.run()
      except Exception as error:
        print(f"작업 처리 오류: {type(error).__name__}")
        print("5초 후 다음 메시지 수신을 시도합니다.")
        time.sleep(5)
  except KeyboardInterrupt:
    print("\nworker를 종료합니다.")


if __name__ == "__main__":
  main()

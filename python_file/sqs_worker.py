"""SQS에서 작업 하나를 수신하여 수집, AI 분석, 보고서 저장을 실행한다.

실행 순서: SQS 수신 → 자료 수집 → Analyzing 갱신 → AI 분석 → S3 저장 → 보고서 위치 갱신 → SQS 삭제다.
수신할 메시지가 없거나 웹 수집에 실패하면 종료한다.
실행 한 번에 메시지 하나만 처리하며, 저장과 갱신이 모두 성공한 메시지만 삭제한다.
"""

import json

import boto3
from analyzer import analyze_data
from collector import collect_data
from storage import mark_analyzing, save_report

AWS_PROFILE = "dns-project"
AWS_REGION = "ap-northeast-2"
QUEUE_URL = "https://sqs.ap-northeast-2.amazonaws.com/994899741506/dns-domain-analysis.fifo"


def main():
  """같은 AWS 프로필로 클라이언트를 생성하고 작업 하나를 처리한다."""
  session = boto3.Session(profile_name=AWS_PROFILE)
  sqs = session.client("sqs", region_name=AWS_REGION)
  dynamodb = session.client("dynamodb", region_name=AWS_REGION)
  s3 = session.client("s3", region_name=AWS_REGION)

  # 메시지가 없으면 최대 20초 동안 기다리며, 한 번에 하나만 수신한다.
  response = sqs.receive_message(
    QueueUrl=QUEUE_URL,
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

  collected_data = collect_data(domain, job_id)
  if collected_data is None:
    return

  print(json.dumps(collected_data, ensure_ascii=False, indent=2))

  # 상태 갱신이 성공한 뒤 AI를 호출하며, 오류는 그대로 전달하여 실행을 중단한다.
  mark_analyzing(dynamodb, domain)
  print("DynamoDB 상태 변경 완료: Analyzing")
  print("로컬 AI 분석 중...")
  analysis = analyze_data(collected_data)

  print("AI 분석 결과:")
  print(analysis)

  report_s3_key = save_report(s3, dynamodb, domain, job_id, collected_data, analysis)
  print(f"S3 저장 및 DynamoDB 보고서 위치 기록 완료: {report_s3_key}")

  # 보고서 저장과 DynamoDB 갱신이 성공한 작업만 큐에서 삭제한다.
  sqs.delete_message(
    QueueUrl=QUEUE_URL,
    ReceiptHandle=message["ReceiptHandle"]
  )
  print(f"SQS 메시지 삭제 완료: {domain}")

# 다른 파일에서 import할 때는 작업을 시작하지 않고, 직접 실행할 때만 호출한다.
if __name__ == "__main__":
  main()

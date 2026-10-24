"""DynamoDB의 분석 상태를 갱신하고 JSON 보고서를 S3에 저장한다.

기존 도메인의 status와 updated_at을 갱신한다.
수집 자료와 AI 분석 결과를 reports/도메인/job_id.json 경로에 저장한다.
S3 저장 후 DynamoDB에 보고서 위치를 기록한다.
분석 완료 상태는 아직 갱신하지 않으며, SQS 삭제는 호출한 실행 파일에서 수행한다.
"""

import json
from datetime import datetime, timezone

TABLE_NAME = "dns-domain-analysis"
REPORT_BUCKET = "dns-analysis-reports-994899741506-ap-northeast-2-an"


def mark_analyzing(dynamodb, domain):
  """기존 항목만 Analyzing으로 갱신하고 UTC 시각을 기록한다."""
  # AI 요청 직전에 도메인의 상태와 갱신 시각을 기록한다.
  dynamodb.update_item(
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


def save_report(s3, dynamodb, domain, job_id, collected_data, analysis):
  """S3에 보고서를 저장하고 DynamoDB에 위치를 기록한 뒤 객체 키를 반환한다."""
  report = {
    "domain": domain,
    "job_id": job_id,
    "analyzed_at": datetime.now(timezone.utc).isoformat(),
    "collected_data": collected_data,
    "analysis": analysis
  }

  report_s3_key = f"reports/{domain}/{job_id}.json"

  # JSON 보고서를 UTF-8 바이트로 변환하여 S3에 저장한다.
  s3.put_object(
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
  dynamodb.update_item(
    TableName=TABLE_NAME,
    Key={
      "domain": {"S": domain}
    },
    UpdateExpression="SET report_s3_key = :key, updated_at = :updated_at",
    ConditionExpression="attribute_exists(#domain)",
    ExpressionAttributeNames={
      "#domain": "domain"
    },
    ExpressionAttributeValues={
      ":key": {"S": report_s3_key},
      ":updated_at": {"S": datetime.now(timezone.utc).isoformat()}
    }
  )  

  return report_s3_key

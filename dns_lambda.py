import base64
import gzip
import json
import re
import boto3
import os
import hashlib

from datetime import datetime, timezone
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("dns-domain-analysis")

sqs = boto3.client("sqs")
queue_url = os.environ["SQS_QUEUE_URL"]

def enqueue_pending(domain):
    # enqueue_pending 상태인 항목을 sqs에 전송하는 로직
    response = table.get_item(
        Key={"domain": domain},
        ConsistentRead=True
    )

    item = response.get("Item")

    if not item or item.get("status") != "pending_enqueue":
        return

    # 현재는 최초 등록 시각을 이용해 작업 ID를 일정하게 유지한다.
    job_id = hashlib.sha256(
        f"{domain}|{item['created_at']}".encode("utf-8")
    ).hexdigest()

    group_id = hashlib.sha256(
        domain.encode("utf-8")
    ).hexdigest()

    result = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            "domain": domain,
            "job_id": job_id
        }),
        MessageGroupId=group_id,
        MessageDeduplicationId=job_id
    )

    # pending_enqueue을 queued로 변경
    try:
        table.update_item(
            Key={"domain": domain},

            # 변경할 내용을 지정하는 구문
            # 여기서 #status, :queued, :now는 실제 이름과 값을 대신하는 자리표시자
            UpdateExpression="SET #status = :queued, updated_at = :now",

            # 변경 조건
            ConditionExpression=(
                "#status = :pending AND created_at = :created"
            ),

            ExpressionAttributeNames={
                "#status": "status"
            },

            ExpressionAttributeValues={
                ":queued": "Queued",
                ":pending": "pending_enqueue",
                ":created": item["created_at"],
                ":now": datetime.now(timezone.utc).isoformat()
            }
        )

    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

        print(f"전송 후 상태가 이미 변경된 도메인: {domain}")

    print(f"SQS 전송 완료: {domain}, MessageId={result['MessageId']}")


def lambda_handler(event, context):
  # cloudwatch 구독 필터 파싱
  compressed_data = base64.b64decode(event["awslogs"]["data"])
  decompressed_data = gzip.decompress(compressed_data)
  log_data = json.loads(decompressed_data)

  # 로그에서 도메인 추출 
  if log_data["messageType"] == "CONTROL_MESSAGE": # 메시지 타입이 로그가 아닌경우
    return {"status":"ok"}

  # 중복된 값을 허용하지 않는 set을 사용한다. 
  domains = set()
  
  for log_event in log_data["logEvents"]:
    message = log_event["message"]

    # query와 IN 사이의 도메인을 찾는다
    # 로그 형식 query: example1.com IN A +E(0)K (10.0.1.42) 
    match = re.search(r"\bquery:\s+(\S+)\s+IN\s+", message)

    if match:
      # 도메인 정규화 
      domain = match.group(1).lower().strip(".")
      domains.add(domain)
  
  # dynamodb 조회를 통해 이미 등록된 도메인인지 확인
  for domain in sorted(domains):
    # get_item은 키가 일치하는 항목 하나를 찾아낸다. 항목이 없다면 응답에 Item이 포함되지 않는다.
    # ConsistentRead=True는 조회 시점에 앞서 완료된 쓰기를 반영하도록 하는 설정이다. 
    response = table.get_item(
      Key={"domain":domain},
      ConsistentRead=True
    )

    if "Item" in response:
      print(f"기존 도메인 : {domain}")
    else:
      now = datetime.now(timezone.utc).isoformat()

      try:
        table.put_item(
          Item={
            "domain":domain,
            "status" : "pending_enqueue",
            "created_at" : now,
            "updated_at" : now
          },
          # 같은 키의 항목이 없다는 것을 확인
          # #domain은 속성 이름 domain을 대신하는 별칭이다. 
          ConditionExpression="attribute_not_exists(#domain)",
          ExpressionAttributeNames = {
            "#domain" : "damain"
          }
        )
        print(f"신규 도메인 등록 완료: {domain}")

      except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
          print(f"다른 실행에서 이미 등록된 도메인 : {domain}")

        else:
          raise

  for domain in sorted(domains):
    enqueue_pending(domain)

  return {"status":"ok"}
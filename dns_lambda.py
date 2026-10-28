import base64
import csv
import gzip
import hashlib
import io  # s3에서 받은 문자열을 파일처럼 읽게 해줌
import json
import os
import re
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("dns-domain-analysis")

sqs = boto3.client("sqs")
queue_url = os.environ["SQS_QUEUE_URL"]

s3 = boto3.client("s3")

list_bucket = os.environ["DOMAIN_LIST_BUCKET"]

blocklist_key = os.environ["BLOCKLIST_KEY"]
allowlist_key = os.environ["ALLOWLIST_KEY"]

# 도메인을 보관할 집합 생성 
blocklist_cache = set()
allowlist_cache = set()

# 아직 목록을 읽지 않았다는 표시
cache_loaded_at = None
cache_refresh_seconds = 3600

# key에는 s3 버킷 안의 파일 경로를 받는다
def load_domain_csv(key):
    response = s3.get_object(
        Bucket=list_bucket,
        Key=key
    )

    body = response["Body"]

    try:
        csv_bytes = body.read()
    finally:
        body.close()


    csv_text = csv_bytes.decode("utf-8-sig")
    # io.StringIO는 문자열을 메모리 안에서 파일처럼 읽을 수 있는 객체로 만들어줌
    csv_file = io.StringIO(csv_text)

    # 첫 줄을 열 이름으로 사용하고 각 행을 딕셔너리로 읽는다 
    # domain      
    # naver.com            {"domain": "naver.com"}
    # GOOGLE.COM.  ---->   {"domain": "GOOGLE.COM."}
    # naver.com            {"domain": "naver.com"}
    reader = csv.DictReader(csv_file)
    print(f"CSV 헤더 확인: {reader.fieldnames!r}")

    if reader.fieldnames != ["domain"]:
        raise ValueError(f"CSV에 domain 열 하나가 필요합니다: {key}")

    domains = set()

    for row in reader:
        domain = row["domain"].strip().lower().rstrip(".")

        if not domain:
            continue

        domains.add(domain)

    if not domains:
        raise ValueError(f"도메인 목록이 비어 있습니다: {key}")

    # 완성된 집합을 호출한 곳에 돌려줌
    return domains

def refresh_domain_cache():
    global blocklist_cache
    global allowlist_cache
    global cache_loaded_at

    # monotonic은 경과 시간을 계산하는 시계이다. 
    now = time.monotonic()

    if cache_loaded_at is not None:
        elapsed_seconds = now - cache_loaded_at

        if elapsed_seconds < cache_refresh_seconds:
            return

    new_blocklist = load_domain_csv(blocklist_key)
    new_allowlist = load_domain_csv(allowlist_key)

    blocklist_cache = new_blocklist
    allowlist_cache = new_allowlist
    cache_loaded_at = time.monotonic()

    print(
        f"캐시 로딩 완료: "
        f"차단 {len(blocklist_cache):,}개, "
        f"허용 {len(allowlist_cache):,}개"
    )

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

  if not domains:
    return {"status": "ok"}

  refresh_domain_cache()
  analysis_domains = set()

  for domain in sorted(domains):
    if domain in blocklist_cache:
      print(f"차단 목록에 있어 분석 생략 : {domain}")
      continue

    if domain in allowlist_cache:
      print(f"허용목록에 있어 분석 생략 : {domain}")
      continue

    # DynamoDB와 SQS에서 사용할 도메인을 읽을 수 있는 표기로 변환한다.
    domain_unicode = domain

    try:
      domain_bytes = domain.encode("ascii")
      domain_unicode = domain_bytes.decode("idna")
    except UnicodeError:
      domain_unicode = domain

    analysis_domains.add(domain_unicode)
    

  # dynamodb 조회를 통해 이미 등록된 도메인인지 확인
  for domain in sorted(analysis_domains):
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
            "#domain" : "domain"
          }
        )
        print(f"신규 도메인 등록 완료: {domain}")

      except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
          print(f"다른 실행에서 이미 등록된 도메인 : {domain}")

        else:
          raise

  for domain in sorted(analysis_domains):
    enqueue_pending(domain)

  return {"status":"ok"}
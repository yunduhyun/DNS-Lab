"""클래스와 AWS 클라이언트를 연결하여 DNS 분석 작업 하나를 실행한다."""

import boto3

from analyzer import GemmaAnalyzer
from collector import DomainCollector
from sqs_worker import AWS_PROFILE, AWS_REGION, SQSWorker
from storage import ReportStorage

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


if __name__ == "__main__":
  main()

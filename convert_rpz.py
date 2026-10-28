import csv
from pathlib import Path


input_path = Path("stevenblack.rpz")
output_path = Path("stevenblack_domains.csv")

domains = []

# RPZ 파일에서 차단 도메인을 추출한다.
with input_path.open(encoding="utf-8") as source:
    for line in source:
        fields = line.split()

        if len(fields) == 4 and fields[1:] == ["IN", "CNAME", "."]:
            domain = fields[0].lower()
            domains.append(domain)

# 추출한 도메인을 CSV로 저장한다.
with output_path.open("w", encoding="utf-8", newline="") as destination:
    writer = csv.writer(destination)
    writer.writerow(["domain"])

    for domain in domains:
        writer.writerow([domain])

# 저장한 결과를 다시 읽어 추출 목록과 비교한다.
with output_path.open(encoding="utf-8", newline="") as result:
    reader = csv.DictReader(result)
    restored_domains = []

    for row in reader:
        restored_domains.append(row["domain"])

if restored_domains != domains:
    raise ValueError("CSV 저장 결과가 추출한 목록과 다릅니다.")

print(f"CSV 저장 완료: {output_path}")
print(f"저장된 도메인: {len(domains):,}개")

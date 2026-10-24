"""도메인의 DNS 정보와 웹페이지 자료를 수집한다.

A와 AAAA 레코드, 응답 헤더, 최종 URL, 제목, 링크, 폼, 본문을 반환한다.
HTTPS를 우선 사용하며, 정해진 연결 오류에서만 HTTP로 한 번 재시도한다.
웹 수집에 실패하면 None을 반환한다. JavaScript 실행과 링크 방문은 수행하지 않는다.
"""

import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import dns.exception
import dns.resolver
from bs4 import BeautifulSoup


def collect_data(domain, job_id):
  """수신한 도메인을 수집하고 AI에 전달할 딕셔너리를 반환한다."""
  # 최초 요청 도메인의 IPv4와 IPv6를 조회한다.
  dns_data = {}

  for record_type in {"A", "AAAA"}:
    try:
      answers = dns.resolver.resolve(
        domain.rstrip(".") + ".",
        record_type,
        lifetime=5,
        search=False
      )

      dns_data[record_type] = {
        "status": "ok",
        "records": [answer.to_text() for answer in answers]
      }

    except dns.exception.DNSException as error:
      # 조회 실패나 레코드 부재를 기록하고 다른 유형의 조회를 계속한다.
      dns_data[record_type] = {
        "status": type(error).__name__,
        "records": [],
        "error": str(error)
      }

  for scheme in ("https", "http"):
    url = f"{scheme}://{domain}/"

    with tempfile.TemporaryDirectory() as temp_dir:
      header_path = Path(temp_dir) / "headers.txt"

      result = subprocess.run(
        [
          "curl",
          "-q",
          "-sS",
          "-L",
          "-D", str(header_path),
          "--proto", "=http,https",
          "--proto-redir", "=http,https",
          "--max-redirs", "5",
          "--max-time", "15",
          "--max-filesize", "2000000",

          # 요청 완료 후 HTML 끝에 줄바꿈과 최종 도착 URL을 추가 출력한다.
          # %{url_effective}는 curl이 리다이렉트를 따라간 최종 URL이다.
          "--write-out", "\n%{url_effective}",
          url
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace"
      )

      headers_data = header_path.read_text(
        encoding="utf-8",
        errors="replace"
      ) if header_path.exists() else ""

    if result.returncode == 0:
      # 출력의 마지막 줄바꿈을 기준으로 본문과 최종 URL을 한 번만 분리한다.
      # web_data에는 HTML 전체를, final_url에는 최종 URL을 저장한다.
      # HTML 내부의 줄바꿈은 그대로 유지한다.
      web_data, final_url = result.stdout.rsplit("\n", 1)

      # HTML을 해석하여 필요한 정보를 추출한다.
      soup = BeautifulSoup(web_data, "html.parser")

      script_urls = []
      # 태그를 제거하기 전에 외부 스크립트 주소를 먼저 보관한다.
      for script in soup.find_all("script", src=True):
        # src 속성에서 앞뒤 공백을 제거한다.
        src = script["src"].strip()

        if src:
          script_urls.append(src)

      # 분석용 텍스트를 정리하며, 브라우저 실행용 HTML 정제는 수행하지 않는다.
      for tag in soup.find_all(["script", "style"]):
        tag.decompose()

      for tag in soup.find_all("link", rel="stylesheet"):
        tag.decompose()

      for tag in soup.find_all(style=True):
        del tag["style"]

      base_url = final_url
      base_tag = soup.find("base", href=True)

      if base_tag:
        # 페이지에 있는 상대 주소를 브라우저와 같은 기준으로 해석하기 위해 base를 사용한다.
        base_url = urljoin(final_url, base_tag["href"].strip())

      # 링크의 표시 문구와 원본 주소, 전체 URL을 수집한다.
      links = []

      # href 속성이 있는 a 태그만 처리한다.
      for tag in soup.find_all("a", href=True):

        # href 값의 앞뒤 공백을 제거한다.
        href = tag["href"].strip()

        # 링크 정보를 딕셔너리로 묶어 목록에 추가한다.
        links.append({
          # 태그 내부의 텍스트를 추출한다.
          # 텍스트 조각을 공백으로 연결하고 앞뒤 공백은 제거한다.
          "text": tag.get_text(" ", strip=True),

          # HTML에 적혀 있던 원본 주소를 보관한다.
          "href": href,

          # 상대 주소는 기준 URL과 결합하고, 전체 주소는 그대로 사용한다.
          "url": urljoin(base_url, href)
        })

      # 폼의 전송 주소와 HTTP 메서드를 수집한다.
      forms = []

      # HTML에 있는 모든 form 태그를 하나씩 처리한다.
      for tag in soup.find_all("form"):
        # action은 폼 전송 주소이며, 없으면 빈 문자열을 사용한다.
        action = tag.get("action", "").strip()

        forms.append({
          # HTML에 적힌 원본 전송 주소를 보관한다.
          "action": action,
          # 상대 주소는 기준 URL과 결합하고, 비어 있으면 현재 페이지로 지정한다.
          "url": urljoin(base_url, action) if action else final_url,

          # method가 없으면 GET을 사용하고, 표기를 대문자로 통일한다.
          "method": tag.get("method", "get").upper()
        })

      # 제목과 본문을 추출하고, body가 없으면 전체 HTML에서 텍스트를 얻는다.
      title = soup.title.get_text(" ", strip=True) if soup.title else ""

      if soup.body is not None:
        body = soup.body
      else:
        body = soup

      body_text = body.get_text("\n", strip=True)

      collected_data = {
        "domain": domain,
        "job_id": job_id,
        "dns": dns_data,
        "requested_url": url,
        "final_url": final_url,
        "headers": headers_data,
        "title": title,
        "script_urls": script_urls,
        "links": links,
        "forms": forms,
        "body_text": body_text
      }

      return collected_data

    print(f"요청 실패: curl 종료 코드 {result.returncode}")
    print(result.stderr)

    # 연결과 TLS 관련 오류에 한해서 HTTPS에서 HTTP로 한 번 재시도한다.
    if scheme == "https" and result.returncode in (7, 28, 35, 52, 56, 60):
      print("HTTP로 재시도합니다.")
    else:
      break

  print("웹 정보를 수집하지 못했습니다:", domain)
  return None

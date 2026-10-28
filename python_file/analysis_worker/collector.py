"""
도메인 정보 수집 모듈 (DNS 및 웹페이지 파싱)

대상 도메인의 DNS 레코드(A, AAAA, CNAME), HTTP 응답 헤더, 최종 URL, 링크, 폼(Form) 및 본문 텍스트를 추출한다.
- 응답 헤더와 HTML 메타 태그를 바탕으로 인코딩(charset)을 자동 감지한다.
- HTTPS를 우선 접속하며, 지정된 연결/TLS 오류 발생 시 HTTP로 1회 재시도(Fallback)한다.
- 브라우저 렌더링(JavaScript 실행) 및 재귀적인 링크 탐색은 수행하지 않는다.
"""

import codecs
import subprocess
import tempfile
from email.message import Message
from pathlib import Path
from urllib.parse import urljoin

import dns.exception
import dns.resolver
from bs4 import BeautifulSoup


class DomainCollector:
  def collect_data(self, domain, job_id):
    """도메인을 분석하여 AI 판정에 필요한 웹 데이터를 딕셔너리로 반환한다."""

    # 화면과 보고서에 표시할 유니코드 도메인을 준비한다.
    domain_unicode = domain

    try:
      domain_bytes = domain.encode("ascii")
      domain_unicode = domain_bytes.decode("idna")
    except UnicodeError:
      domain_unicode = domain
      
    # DNS 조회와 웹 접속에 사용할 도메인을 ASCII 표기로 변환한다.
    domain_bytes = domain.encode("idna")
    domain = domain_bytes.decode("ascii")

    # 1. DNS 레코드 조회 (IPv4, IPv6, CNAME)
    dns_data = {}
    record_types = ["A", "AAAA", "CNAME"]
    query_domain = domain.rstrip(".")
    query_domain = query_domain + "."

    for record_type in record_types:
      try:
        answers = dns.resolver.resolve(
          query_domain,
          record_type,
          lifetime=5,
          search=False
        )
        records = []

        for answer in answers:
          record_text = answer.to_text()
          records.append(record_text)

        dns_data[record_type] = {
          "status": "ok",
          "records": records
        }
      except dns.exception.DNSException as error:
        # 특정 레코드가 없거나 조회에 실패해도 중단하지 않고 상태만 기록한다.
        dns_data[record_type] = {
          "status": type(error).__name__,
          "records": [],
          "error": str(error)
        }

    # 2. 웹 데이터 수집 (HTTPS 우선 시도)
    schemes = ["https", "http"]

    for scheme in schemes:
      url = f"{scheme}://{domain}/"

      with tempfile.TemporaryDirectory() as temp_dir:
        header_path = Path(temp_dir) / "headers.txt"

        # curl을 통한 원본 바이트 추출
        curl_command = [
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
          # 중간 리다이렉트 응답과의 혼선을 막기 위해 본문 끝에 최종 URL과 Content-Type을 강제 출력한다.
          "--write-out", "\n%{url_effective}\n%{content_type}",
          url
        ]

        result = subprocess.run(
          curl_command,
          capture_output=True
        )

        if header_path.exists():
          headers_data = header_path.read_text(
            encoding="utf-8",
            errors="replace"
          )
        else:
          headers_data = ""

      # 3. 데이터 분리 및 인코딩(Charset) 해석
      if result.returncode == 0:
        # curl이 덧붙인 마지막 두 줄(최종 URL, Content-Type)만 분리하여 HTML 본문을 보존한다.
        response_parts = result.stdout.rsplit(b"\n", 2)
        web_data = response_parts[0]
        final_url_bytes = response_parts[1]
        content_type_bytes = response_parts[2]
        final_url = final_url_bytes.decode("utf-8", errors="replace")

        # HTTP 헤더 문법을 이용해 Content-Type에서 charset을 추출한다.
        content_type_text = content_type_bytes.decode("latin-1")
        content_type = Message()
        content_type["Content-Type"] = content_type_text
        charset = content_type.get_content_charset()

        # 파이썬에서 지원하지 않는 인코딩인 경우 BS4의 자동 감지에 위임한다.
        if charset:
          try:
            codecs.lookup(charset)
          except LookupError:
            charset = None

        # 헤더에 charset이 없을 경우 HTML meta 태그를 기반으로 디코딩을 시도한다.
        soup = BeautifulSoup(web_data, "html.parser", from_encoding=charset)

        # 메타 태그의 속성을 수집 
        metadata = []
        meta_tags = soup.find_all("meta")

        for meta_tag in meta_tags:
          meta_name = meta_tag.get("name", "")
          meta_name = meta_name.strip()

          meta_property = meta_tag.get("property", "")
          meta_property = meta_property.strip()

          meta_http_equiv = meta_tag.get("http-equiv", "")
          meta_http_equiv = meta_http_equiv.strip()

          meta_content = meta_tag.get("content", "")
          meta_content = meta_content.strip()

          if meta_name or meta_property or meta_http_equiv or meta_content:
            meta_data = {
              "name": meta_name,
              "property": meta_property,
              "http_equiv": meta_http_equiv,
              "content": meta_content
            }

            metadata.append(meta_data)

        # 4. HTML 파싱 및 노이즈 제거
        script_urls = []

        # 노이즈 태그 삭제 전, 외부 스크립트 소스(src) 주소를 먼저 확보한다.
        for script in soup.find_all("script", src=True):
          src = script["src"]
          src = src.strip()

          if src:
            script_urls.append(src)

        # 분석을 방해하는 동적/시각적 태그와 인라인 스타일을 제거한다.
        for tag in soup.find_all(["script", "style"]):
          tag.decompose()

        for tag in soup.find_all("link", rel="stylesheet"):
          tag.decompose()

        for tag in soup.find_all(style=True):
          del tag["style"]

        # 5. 기준 주소(Base URL) 설정
        base_url = final_url
        base_tag = soup.find("base", href=True)

        if base_tag:
          base_href = base_tag["href"]
          base_href = base_href.strip()
          base_url = urljoin(final_url, base_href)

        frames = []
        frame_tags = soup.find_all(["iframe", "frame"])

        for frame_tag in frame_tags:
          frame_type = frame_tag.name

          frame_src = frame_tag.get("src", "")
          frame_src = frame_src.strip()

          frame_title = frame_tag.get("title", "")
          frame_title = frame_title.strip()

          # has_attr은 해당 속성이 있는지 확인하는 함수이다. 
          has_srcdoc = frame_tag.has_attr("srcdoc")

          if frame_src:
            frame_url = urljoin(base_url, frame_src)
          else:
            frame_url = ""

          frame_data = {
            "tag": frame_type,
            "src": frame_src,
            "url": frame_url,
            "title": frame_title,
            "has_srcdoc": has_srcdoc
          }
        
          frames.append(frame_data)

        # 6. 하이퍼링크(<a>) 추출
        links = []

        for tag in soup.find_all("a", href=True):
          href = tag["href"]
          href = href.strip()
          link_text = tag.get_text(" ", strip=True)
          link_url = urljoin(base_url, href)

          link_data = {
            "text": link_text,
            "href": href,
            "url": link_url
          }

          links.append(link_data)

        # 7. 폼(Form) 구조 추출 (로그인/피싱 탐지용)
        forms = []

        for tag in soup.find_all("form"):
          action = tag.get("action", "")
          action = action.strip()

          if action:
            form_url = urljoin(base_url, action)
          else:
            form_url = final_url

          method = tag.get("method", "get")
          method = method.upper()

          form_data = {
            "action": action,
            "url": form_url,
            "method": method
          }

          forms.append(form_data)

        # 8. 페이지 제목 및 본문 텍스트 추출
        title_tag = soup.title

        if title_tag:
          title = title_tag.get_text(" ", strip=True)
        else:
          title = ""

        # 비표준 HTML(<body> 태그 누락 등)인 경우 전체 HTML에서 텍스트를 추출한다.
        body_tag = soup.body

        if body_tag is not None:
          body = body_tag
        else:
          body = soup

        body_text = body.get_text("\n", strip=True)

        collected_data = {
          "domain": domain,
          "domain_unicode": domain_unicode,
          "job_id": job_id,
          "dns": dns_data,
          "requested_url": url,
          "final_url": final_url,
          "headers": headers_data,
          "title": title,
          "metadata":metadata,
          "script_urls": script_urls,
          "links": links,
          "forms": forms,
          "frames": frames,
          "body_text": body_text
        }

        return collected_data

      # 9. 요청 실패 및 재시도(Fallback) 처리
      print(f"요청 실패: curl 종료 코드 {result.returncode}")
      error_message = result.stderr.decode("utf-8", errors="replace")
      print(error_message)

      # 연결 거부, 타임아웃, TLS 인증서 오류 등에 한정하여 HTTP로 1회 재시도한다.
      if scheme == "https" and result.returncode in (7, 28, 35, 52, 56, 60):
        print("HTTP로 재시도 진행..")
      else:
        break

    print("웹 정보를 수집 실패:", domain)
    return None

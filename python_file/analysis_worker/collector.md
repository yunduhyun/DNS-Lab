# collector.py 설명

대상 소스는 [collector.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/collector.py)다. `DomainCollector.collect_data(domain, job_id)`는 DNS와 정적 웹페이지 정보를 수집해 딕셔너리로 반환한다. 판단은 [analyzer.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/analyzer.py)가 수행한다.

## 1. 입력과 DNS 조회

```python
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
```

- 예시 입력은 `domain="example.com"`, `job_id="demo-job"`이다. 작업 ID는 이후 결과에 그대로 보관한다.
- `{}`는 빈 딕셔너리다. `dns_data`에는 레코드 유형별 결과를 넣는다.
- `A`는 IPv4 주소, `AAAA`는 IPv6 주소, `CNAME`은 다른 이름을 가리키는 별칭 레코드다.
- `rstrip(".")`는 끝의 점을 제거한 다음 하나를 붙여 `query_domain="example.com."`으로 만든다. DNS 조회에 사용할 완전한 이름을 만드는 과정이다.
- `for`는 세 레코드를 순서대로 조회한다. `lifetime=5`는 각 조회의 제한 시간을 5초로 설정하고 `search=False`는 검색 도메인을 붙이는 동작을 사용하지 않게 한다.
- 반환된 각 응답은 `answer.to_text()`로 문자열로 바꿔 `records` 리스트에 추가한다.
- `DNSException`이 발생하면 해당 유형의 `status`에 예외 이름, `records`에 빈 리스트, `error`에 오류 문자열을 보관한다. 다른 유형 조회와 웹 수집은 계속 진행한다.
- `NoAnswer`는 해당 레코드 응답이 없었다는 뜻이다. AAAA나 CNAME이 없다는 이유만으로 악성이라고 판단하지 않는다.

## 2. HTTPS 우선 요청과 임시 헤더 파일

```python
schemes = ["https", "http"]

for scheme in schemes:
  url = f"{scheme}://{domain}/"

  with tempfile.TemporaryDirectory() as temp_dir:
    header_path = Path(temp_dir) / "headers.txt"
```

- 첫 시도의 `url`은 `"https://example.com/"`이다. HTTP 시도는 아래에서 설명하는 지정 오류일 때만 진행한다.
- `f"..."`는 변숫값을 문자열 안에 넣는다.
- `TemporaryDirectory()`는 임시 폴더를 만들고 `with` 블록이 끝나면 정리한다.
- `header_path`는 curl이 응답 헤더를 저장할 임시 파일이다. 현재 작업 폴더에 고정 파일을 만들지 않는다.

```python
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
  "--write-out", "\n%{url_effective}\n%{content_type}",
  url
]

result = subprocess.run(curl_command, capture_output=True)
```

- `curl`은 외부 프로그램이다. `subprocess.run()`이 명령을 실행하고 완료를 기다린다.
- `-q`는 curl 기본 설정 파일을 읽지 않도록 하고 `-sS`는 진행 표시를 숨기면서 오류는 출력하게 한다.
- `-L`은 HTTP 리다이렉션을 따라간다. JavaScript와 메타 태그의 이동 코드는 실행하지 않는다.
- `-D`는 응답 헤더를 지정한 파일에 쓴다. 중간 응답이 있으면 여러 헤더 블록이 들어갈 수 있다.
- 두 `--proto` 설정은 요청과 이동에 HTTP 및 HTTPS를 허용한다.
- `--max-redirs`는 HTTP 이동을 최대 5회로 제한한다.
- `--max-time`은 curl 요청의 최대 시간을 15초로 설정한다.
- `--max-filesize`는 다운로드 크기를 2,000,000바이트로 제한하는 설정이다.
- `--write-out`은 받은 본문 뒤에 줄바꿈, 최종 URL, 줄바꿈, Content-Type을 덧붙인다.
- `capture_output=True`는 표준 출력과 오류 출력을 결과에 보관한다. `text=True`가 없으므로 `result.stdout`과 `result.stderr`는 바이트다.
- curl은 `-f` 옵션 없이 실행되므로 HTTP 403이나 500 응답도 curl 종료 코드가 0일 수 있다. 종료 코드 0을 사이트 안전성이나 HTTP 200으로 해석하지 않는다.

## 3. 본문과 최종 URL 분리

```python
if result.returncode == 0:
  response_parts = result.stdout.rsplit(b"\n", 2)
  web_data = response_parts[0]
  final_url_bytes = response_parts[1]
  content_type_bytes = response_parts[2]
  final_url = final_url_bytes.decode("utf-8", errors="replace")
```

- `returncode`는 curl 프로세스의 종료 코드다.
- `rsplit(..., 2)`는 뒤에서부터 두 번 분리한다. HTML 본문에 있던 줄바꿈은 본문에 남긴다.
- 예를 들어 출력이 `HTML본문\nhttps://example.com/home\ntext/html; charset=utf-8`이면 본문, 최종 URL, 응답 형식의 세 부분으로 나눈다.
- `b"\n"`은 바이트 형태의 줄바꿈이고 `decode()`는 바이트를 문자열로 바꾼다. `errors="replace"`는 해석할 수 없는 문자를 대체 문자로 표시한다.
- `headers_data`는 임시 파일에서 별도로 읽는다. 최종 응답만 구조화한 값이 아닌 전체 헤더 문자열이다.

## 4. 글자 인코딩 판단과 HTML 해석

```python
content_type_text = content_type_bytes.decode("latin-1")
content_type = Message()
content_type["Content-Type"] = content_type_text
charset = content_type.get_content_charset()
```

- 인코딩은 바이트를 어떤 문자로 읽을지 정하는 방식이다. 예를 들어 `charset=utf-8`이면 `charset`에 `"utf-8"`이 들어간다.
- `Message()`로 Content-Type의 속성을 읽는다. 헤더에 인코딩이 없으면 `None`을 얻는다.
- `codecs.lookup(charset)`으로 Python이 지원하는 인코딩인지 확인한다. 지원하지 않으면 `charset=None`으로 바꾼다.

```python
soup = BeautifulSoup(web_data, "html.parser", from_encoding=charset)
```

- BeautifulSoup은 HTML을 태그별로 찾을 수 있는 구조로 읽는다. 이를 파싱이라고 한다.
- `web_data`를 바이트 상태로 전달하므로 지정 인코딩이나 HTML의 메타 정보 등을 참고해 문자를 해석한다. 인코딩 감지가 항상 정확하다는 뜻은 아니다.
- `soup`는 브라우저가 아니다. JavaScript를 실행하거나 화면을 실제로 그리지 않는다.

## 5. 메타데이터와 외부 스크립트 주소

```python
meta_tags = soup.find_all("meta")
```

- `find_all()`은 조건에 맞는 모든 태그를 리스트처럼 반환한다.
- 각 메타 태그에서 `name`, `property`, `http-equiv`, `content`를 읽고 앞뒤 공백을 제거한다.
- `.get("name", "")`는 속성이 없으면 빈 문자열을 사용한다. 네 값 중 하나라도 있으면 `metadata`에 넣는다.
- HTML 속성 이름 `http-equiv`는 결과 딕셔너리에서 `http_equiv`라는 키로 보관한다.
- `<meta http-equiv="refresh" content="0;url=/welcome">`는 이동 정황으로 수집한다. collector는 그 주소로 추가 이동하지 않는다.

```python
for script in soup.find_all("script", src=True):
  src = script["src"]
  src = src.strip()

  if src:
    script_urls.append(src)
```

- `src=True`는 `src` 속성이 있는 script 태그를 찾는다. 주소가 비어 있지 않으면 리스트에 넣는다.
- 예를 들어 `src="/app.js"`는 `"/app.js"`로 보관한다. 이 목록은 현재 코드에서 절대 URL로 바꾸지 않는다.
- 이후 script와 style 태그, 스타일시트 link 태그와 인라인 style 속성을 제거한다. 스크립트 내용은 본문 텍스트에서 제외된다.

## 6. 상대주소의 기준 설정

```python
base_url = final_url
base_tag = soup.find("base", href=True)

if base_tag:
  base_href = base_tag["href"]
  base_href = base_href.strip()
  base_url = urljoin(final_url, base_href)
```

- 기본 기준 주소는 최종 URL이다. `find()`는 첫 번째 base 태그를 찾는다.
- base 태그가 있으면 그 주소를 기준으로 링크와 iframe의 상대주소를 해석한다.
- `urljoin("https://example.com/home", "/login")`의 결과는 `"https://example.com/login"`이다. 주소를 계산할 뿐 접속하지 않는다.

## 7. iframe과 frame, 링크, 폼 추출

```python
frame_tags = soup.find_all(["iframe", "frame"])
```

- iframe과 기존 frame 태그를 모두 찾아 `frames`에 보관한다.
- 각 항목은 태그 종류인 `tag`, 원래 `src`, 변환한 `url`, `title`, `has_srcdoc`을 가진다.
- `has_attr("srcdoc")`은 HTML을 태그 속성에 직접 넣은 경우인지 확인한다. `srcdoc` 본문은 수집하지 않는다.
- iframe 내부 페이지에 별도 접속하거나 그 내용을 분석하지 않는다.

```python
href = tag["href"]
href = href.strip()
link_text = tag.get_text(" ", strip=True)
link_url = urljoin(base_url, href)
```

- 이 발췌는 `href`가 있는 a 태그를 순회하는 블록 안에서 실행한다.
- `get_text(" ", strip=True)`는 링크 안의 글자를 공백으로 연결하고 가장자리 공백을 제거한다.
- `<a href="/login">로그인</a>`이면 `text="로그인"`, `href="/login"`, `url="https://example.com/login"`을 보관한다.

```python
action = tag.get("action", "")
action = action.strip()

if action:
  form_url = urljoin(base_url, action)
else:
  form_url = final_url

method = tag.get("method", "get")
method = method.upper()
```

- 이 발췌는 form 태그를 순회하는 블록 안에서 실행한다.
- `action`이 있으면 목적지 주소를 계산하고 없으면 최종 페이지 주소를 사용한다.
- method가 없으면 `GET`이며 `post`는 `POST`로 바꾼다.
- 폼마다 `action`, `url`, `method`를 저장한다. 비밀번호 입력칸이나 입력 항목 목록은 현재 수집하지 않으며 폼도 제출하지 않는다.

## 8. 제목과 본문 추출 후 반환

```python
body_text = body.get_text("\n", strip=True)
```

- title 태그가 있으면 제목을 추출하고 없으면 빈 문자열을 사용한다.
- body 태그가 있으면 그 안에서, 없으면 HTML 전체에서 텍스트를 추출한다.
- `"\n"`은 여러 텍스트를 줄바꿈으로 구분한다. 브라우저에서 숨겨진 요소인지까지 판단하는 수집은 아니다.
- 성공 결과는 `domain`, `job_id`, `dns`, `requested_url`, `final_url`, `headers`, `title`, `metadata`, `script_urls`, `links`, `forms`, `frames`, `body_text`를 가진다.
- DNS 오류가 있더라도 웹 수집이 성공하면 해당 오류를 포함한 딕셔너리를 반환한다.

## 9. 실패 시 HTTP 재시도와 종료

```python
if scheme == "https" and result.returncode in (7, 28, 35, 52, 56, 60):
  print("HTTP로 재시도 진행..")
else:
  break
```

- HTTPS 요청에서 지정한 연결, 시간 초과, TLS 관련 오류 등이 발생했을 때만 다음 반복의 HTTP 요청으로 넘어간다.
- 그 외 오류는 `break`로 반복문을 끝낸다. HTTP 시도까지 실패해도 더 시도하지 않는다.
- 최종적으로 `None`을 반환하면 main은 현재 구현대로 SQS 메시지를 삭제한다.
- JavaScript 이동, 인증 화면 이후 조사와 최종 브라우저 주소 관찰은 [browser_mcp_server.py](/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_server.py)의 역할이다. FlareSolverr 호출은 collector에도 연결되어 있지 않다.

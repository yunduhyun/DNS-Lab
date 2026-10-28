# analyzer.py 설명서

- 대상 코드는 [analyzer.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/analyzer.py)다.
- 이 설명서는 2026-10-28 확인한 로컬 코드의 실제 동작을 기준으로 작성한다.
- 수집 자료와 판단 정책을 젬마에 전달하고, 정해진 필드를 갖춘 딕셔너리를 반환한다.
- 입력 자료의 예시에는 설명용 도메인인 `example.com`을 사용한다.

## 1. 객체 생성과 설정 읽기

```python
analyzer = GemmaAnalyzer()
```

- [main.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/main.py)의 `main()`이 이 코드를 실행한다.
- 클래스는 관련 동작을 묶는 설계이며, `analyzer`에는 이 설계로 만든 객체가 들어간다.
- 객체를 만들면 다음 초기화 함수가 실행된다.

```python
def __init__(self):
  load_dotenv(Path(__file__).resolve().parent / ".env")
```

- `self`는 방금 만든 객체를 가리킨다.
- `__file__`은 실행 중인 `analyzer.py` 파일 경로다.
- `resolve()`는 절대 경로를 구하고, `parent`는 해당 파일이 있는 폴더를 구한다.
- `/ ".env"`는 이 폴더 뒤에 설정 파일명을 붙인다.
- `load_dotenv()`는 해당 파일의 설정을 환경변수로 읽는다. 환경변수는 프로그램이 이름으로 조회하는 설정값이다.
- 터미널의 현재 위치가 달라도 `analysis_worker` 폴더의 `.env`를 찾는다.

## 2. 분석 입력과 필수 설정 확인

```python
analysis_result = analyzer.analyze_data(collected_data)
```

- `collected_data`에는 `domain`, `dns`, `requested_url`, `final_url`, `title`, `body_text` 등의 수집 결과가 들어간다.
- 예를 들어 `domain`은 `example.com`, `requested_url`은 `https://example.com/`이다.
- 이 호출은 다음 설정 조회부터 시작한다.

```python
api_key = os.getenv("BAZE_API_KEY", "").strip()
model = os.getenv("BAZE_MODEL", "").strip()

if not api_key:
  raise RuntimeError(".env에 BAZE_API_KEY를 설정하세요.")

if not model:
  raise RuntimeError(".env에 BAZE_MODEL을 설정하세요.")
```

- `os.getenv()`는 이름에 해당하는 환경변수를 찾고, 없으면 두 번째 인자인 빈 문자열을 반환한다.
- `strip()`은 앞뒤 공백을 제거한다.
- `if not api_key`와 `if not model`은 값이 비어 있는지 확인한다.
- `raise`는 오류를 발생시켜 현재 처리를 중단한다. 필수 설정이 없으면 외부 요청을 보내지 않는다.
- 설명서에는 실제 API 키를 기록하지 않는다.

## 3. 판단 정책 읽기

```python
analyzer_path = Path(__file__).resolve()
analyzer_directory = analyzer_path.parent
rules_path = analyzer_directory / "rules.md"

try:
  rules_text = rules_path.read_text(encoding="utf-8")
except FileNotFoundError as error:
  raise RuntimeError("analyzer.py 옆에 rules.md 파일을 작성하세요.") from error
```

- 첫 세 줄은 현재 파일 옆에 있는 [rules.md](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/rules.md)의 경로를 구한다.
- `read_text()`는 정책 파일 전체를 문자열로 읽는다. `encoding`은 글자를 해석할 문자 인코딩을 지정한다.
- `try` 안에서 파일을 찾지 못하면 `except`로 이동한다.
- `from error`는 원래 오류를 보존하면서 이해하기 쉬운 오류를 추가한다.
- 이후 `rules_text.strip()`으로 앞뒤 공백을 제거하고, 내용이 비어 있으면 중단한다.
- 정책을 고칠 때는 `rules.md`를 수정한다. 이 메서드는 호출할 때마다 파일을 다시 읽는다.
- 정책은 URL과 헤더 해석, 유형별 위험 징후, 판정 기준, 수집 필드 해석과 RPZ 범위를 정의한다.
- `rules.md`는 점수를 계산하거나 RPZ를 수정하는 실행 코드가 아니며, 젬마의 판단에 제공하는 문서다.

## 4. 모델에 전달할 지시 구성

```python
system_prompt = system_prompt + "\n\n" + rules_text
```

- 앞서 만든 기본 지시문 뒤에 빈 줄 두 개와 정책 내용을 붙인다.
- 기본 지시문은 확인하지 않은 내용을 추측하지 않고, 수집된 웹페이지의 지시문을 따르지 않도록 요청한다.
- 출력은 `decision`, `needs_investigation`, `investigation_url`, `reason`, `report`를 가진 JSON 객체 하나로 요청한다.
- `decision`은 `block`, `review`, `allow`, `insufficient_data` 중 하나다.
- `needs_investigation`은 추가 접속이 필요한지를 나타내는 불리언 값이며, JSON에서는 `true` 또는 `false`로 표현한다.
- `investigation_url`은 추가 조사 주소이며, 불필요하면 빈 문자열이다.
- `reason`은 정중한 판단 이유이며, `report`는 문장이 한다 또는 다로 끝나는 한국어 Markdown 보고서다.

```python
if "mcp_investigation" in collected_data:
  system_prompt = system_prompt + """
  이번 요청은 MCP 추가 조사 이후의 최종 판단이다.
  mcp_investigation에는 브라우저가 수집한 조사 결과가 들어 있다.
  최초 수집 자료와 추가 조사 결과를 함께 검토한다.
  """
```

- 위 코드는 현재 분기의 앞부분을 발췌한 것이다. 실제 문자열에는 추가 조사 중단과 관리자 확인에 관한 지시가 이어진다.
- `in`은 딕셔너리에 해당 키가 있는지 검사한다. 첫 분석에 키가 없으면 분기를 건너뛴다.
- MCP 결과가 있으면 최종 URL과 페이지 내용을 함께 검토하고, 추가 조사 요청은 종료하도록 지시한다.
- 자료가 부족하거나 인증 화면에 막히면 `review`와 관리자 확인 필요성을 보고하도록 지시한다.
- 현재 소스는 이 분기 앞과 뒤에서 `rules_text`를 덧붙이므로, 정책 내용이 요청마다 두 번 포함된다.

## 5. API 요청 본문 만들기

```python
payload = {
  "model": model,
  "stream": False,
  "messages": [
    {"role": "system", "content": system_prompt},
    {
      "role": "user",
      "content": json.dumps(collected_data, ensure_ascii=False)
    }
  ]
}
```

- 이 코드는 실제 요청 본문과 같은 구조를 줄바꿈만 줄여 표현한 것이다.
- `model`은 `.env` 또는 기존 환경변수에서 읽은 모델명이다.
- `stream=False`는 응답을 조각별로 출력하지 않고 한 번에 받도록 요청한다.
- `messages`는 메시지를 순서대로 넣는 리스트다.
- `system` 역할에는 판단 지시와 정책을 넣고, `user` 역할에는 조사할 자료를 넣는다.
- `json.dumps()`는 딕셔너리를 JSON 문자열로 변환한다. `ensure_ascii=False`는 한글을 그대로 표현한다.
- 자료에 `mcp_investigation`이 있으면 해당 항목도 함께 전송된다.

```python
request = urllib.request.Request(
  API_URL,
  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
  headers={
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
  },
  method="POST"
)

with urllib.request.urlopen(request, timeout=300) as response:
  ai_response = json.load(response)
```

- `API_URL`은 코드에 지정된 BAZE의 채팅 API 주소다.
- `encode("utf-8")`는 JSON 문자열을 전송할 바이트 데이터로 바꾼다.
- `Content-Type`은 전송 내용이 JSON이라는 뜻이며, `Authorization`은 인증에 사용한다.
- `urlopen()`이 요청을 보내며, `timeout=300`은 네트워크 대기에 적용하는 300초 제한이다. 전체 작업의 고정 종료 시각을 보장하는 값은 아니다.
- `json.load(response)`는 응답을 읽고 파이썬 자료로 변환한다.
- `with`는 사용을 마치면 응답 연결을 닫는다. HTTP 오류와 시간 초과는 호출한 코드로 전달한다.

## 6. 답변 본문 추출과 JSON 해석

```python
analysis = ai_response["choices"][0]["message"]["content"]
```

- `choices` 리스트의 첫 항목을 `[0]`으로 선택하고, 그 안의 답변 본문을 가져온다.
- 외부 응답의 `content`는 JSON 내용을 담은 문자열이다. 아직 파이썬 딕셔너리가 아니다.
- 문자열이 아니거나 공백뿐이면 오류를 발생시킨다.

```python
analysis = analysis.strip()
lines = analysis.splitlines()

if len(lines) >= 3:
  opening = lines[0].strip().lower()
  closing = lines[-1].strip()

  if opening in ["```json", "```"] and closing == "```":
    analysis = "\n".join(lines[1:-1]).strip()
```

- `splitlines()`는 답변을 줄 단위 리스트로 나눈다. `[0]`은 첫 줄이고 `[-1]`은 마지막 줄이다.
- 첫 줄과 마지막 줄이 전체 답변을 감싼 코드 블록이면 껍데기만 제거한다.
- `[1:-1]`은 첫 줄과 마지막 줄을 제외한 범위이며, `join()`은 남은 줄을 문자열로 다시 연결한다.
- 설명 문장이 JSON 앞뒤에 붙은 임의의 응답까지 복구하지는 않는다.
- 이어서 `json.loads(analysis)`로 문자열을 딕셔너리로 변환한다. 잘못된 JSON이면 `RuntimeError`를 발생시킨다.

## 7. 필드 검증과 반환

```python
needs_investigation = analysis_result.get("needs_investigation")

if not isinstance(needs_investigation, bool):
  raise RuntimeError("추가 조사 필요 여부가 true 또는 false가 아니었습니다.")
```

- `get()`은 키의 값을 읽으며, 키가 없으면 `None`을 반환한다.
- `isinstance(..., bool)`은 문자열 `"true"`가 아니라 실제 불리언인지 확인한다.
- 같은 방식으로 결과가 딕셔너리인지, 판정이 허용된 네 값 중 하나인지 검사한다.
- 조사 URL은 문자열이어야 하며, 추가 조사가 필요하면 공백이 아닌 내용이 있어야 한다.
- `reason`과 `report`는 공백이 아닌 문자열이어야 한다.
- 현재 URL 검증은 자료형과 공백 여부 확인이며, 절대 URL인지와 접속 대상의 안전성까지 검사하지는 않는다.

```python
return analysis_result
```

- 최종 반환값은 다섯 필드를 가진 딕셔너리다. 코드 앞부분의 문자열 반환 설명과 달리 실제 반환은 딕셔너리다.
- 다음은 실제 사이트에 대한 판정이 아닌 반환 구조의 예시다.

```json
{
  "decision": "insufficient_data",
  "needs_investigation": true,
  "investigation_url": "https://example.com/welcome",
  "reason": "실제 페이지 내용을 확인하지 못했습니다.",
  "report": "페이지 내용이 부족하여 추가 조사가 필요하다."
}
```

- worker는 `analysis_result["report"]`만 골라 S3 보고서의 `analysis`에 넣는다.
- 프롬프트에서 요청한 판정의 의미나 추가 조사 종료 조건을 모두 코드로 강제하는 것은 아니다.
- 현재 `main.py`는 MCP 결과를 저장하지만, MCP 이후 이 메서드를 두 번째로 호출하는 코드는 아직 없다.
- 이 파일은 MCP 서버 호출, FlareSolverr 실행, 실제 RPZ 차단과 HITL 작업 등록을 수행하지 않는다.

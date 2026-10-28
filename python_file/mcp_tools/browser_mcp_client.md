# browser_mcp_client.py 설명

- 기준일은 2026-10-28이다.
- 설명 대상은 [browser_mcp_client.py](/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_client.py)이다.
- 이 파일은 로컬 MCP 서버를 실행하고 URL 조사 결과를 받는 클라이언트다.
- 클라이언트는 도구를 요청하는 프로그램이며, 서버는 실제 브라우저 조사를 수행하는 프로그램이다.

## 1. 명령줄에서 실행을 시작한다

```python
if __name__ == "__main__":
  asyncio.run(main())
```

- `__name__`은 Python이 현재 파일을 직접 실행했는지 구분할 때 사용하는 값이다.
- 직접 실행하면 값이 `"__main__"`이 되어 `asyncio.run(main())`을 실행한다.
- `asyncio.run()`은 비동기 함수 `main()`을 실행할 준비를 하고 끝날 때까지 기다린다.
- 비동기는 기다리는 동안 다른 작업도 실행할 수 있는 방식이며, 이 코드가 여러 URL을 동시에 조사한다는 뜻은 아니다.

```bash
/Users/yunduhyun/Desktop/dns_project/.venv/bin/python \
  /Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_client.py \
  https://example.com/
```

- 위 명령은 터미널에서 실행하는 예시다.
- 프로젝트 가상환경의 Python으로 클라이언트를 실행하고 조사할 URL 하나를 전달한다.
- 명령을 실제 실행하면 해당 URL에 브라우저로 접속한다.

## 2. 전달받은 URL을 확인한다

```python
async def main():
  if len(sys.argv) != 2:
    raise SystemExit(
      "사용법: python browser_mcp_client.py https://example.com/"
    )

  url = sys.argv[1]
  investigation = await request_investigation(url)
```

- `async def`는 함수 안에서 `await`를 사용할 수 있는 비동기 함수를 정의한다.
- `sys.argv`는 실행 파일 이름과 뒤에 전달한 값을 담는 리스트다.
- 예시에서는 `sys.argv[0]`이 클라이언트 파일 경로이며 `sys.argv[1]`이 `"https://example.com/"`이다.
- `len(sys.argv) != 2`는 URL을 하나만 전달했는지 확인한다. 다른 개수이면 사용법을 출력하고 종료한다.
- `url = sys.argv[1]`은 두 번째 값을 `url` 변수에 넣는다.
- `await request_investigation(url)`은 URL 조사를 요청하고 결과가 돌아온 뒤 다음 줄로 진행한다.

## 3. 같은 폴더의 서버 실행 경로를 만든다

```python
async def request_investigation(url: str) -> dict:
  client_directory = Path(__file__).resolve().parent
  server_path = client_directory / "browser_mcp_server.py"
```

- `url: str`은 URL에 문자열을 전달하도록 표시한 것이다. 이 표시 자체가 값을 검사하지는 않는다.
- `-> dict`는 조사 결과를 딕셔너리로 반환한다는 표시다.
- `__file__`은 현재 클라이언트 파일의 위치다.
- `resolve()`는 절대 경로를 구하고, `.parent`는 파일이 들어 있는 폴더를 구한다.
- `client_directory`에는 `/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools`가 들어간다.
- `Path` 사이의 `/`는 경로를 연결한다. `server_path`에는 같은 폴더의 서버 파일 경로가 들어간다.

## 4. 현재 Python으로 서버를 실행하도록 설정한다

```python
  server  = StdioServerParameters(
    command = sys.executable,
    args = [str(server_path)],
    cwd = str(client_directory)
  )
```

- `StdioServerParameters`는 서버 프로세스를 실행할 명령과 작업 폴더를 보관한다.
- `sys.executable`은 클라이언트를 실행한 Python의 절대 경로다. 가상환경으로 실행했다면 같은 가상환경의 Python으로 서버를 실행한다.
- `args`는 Python 명령 뒤에 붙일 인자 리스트다. 여기에는 서버 파일 경로 하나를 넣는다.
- `str()`은 `Path` 객체를 실행 명령에 사용할 문자열로 바꾼다.
- `cwd`는 서버 실행의 기준 폴더를 지정한다.
- `stdio`는 표준 입력과 출력으로 두 프로그램이 통신하는 방식이다. 별도 HTTP 포트를 열도록 설정한 코드가 아니다.

## 5. MCP 도구를 호출한다

```python
  async with Client(server, read_timeout_seconds=180) as client:
    result = await client.call_tool(
      "investigate_url",
      arguments={
        "url": url,
        "manual_verification": False
      }
    )
```

- `async with`는 MCP 연결을 열고, 블록을 벗어나면 연결을 정리한다.
- `read_timeout_seconds=180`은 MCP 응답 읽기 제한을 180초로 설정한다.
- `call_tool()`은 서버에 등록된 도구를 이름으로 요청한다.
- `"investigate_url"`은 서버 함수 이름이다.
- `arguments`는 서버 함수에 전달하는 딕셔너리다. 예시의 `url`에는 `"https://example.com/"`이 들어간다.
- `manual_verification=False`이므로 서버는 창을 숨기는 자동 조사 경로를 사용한다.
- 현재 명령줄에는 수동 확인 옵션이 없다. URL 뒤에 인자를 하나 더 붙여도 수동 확인으로 바뀌지 않는다.
- 젬마가 로컬 프로그램을 직접 실행하지는 않는다. worker가 젬마의 응답을 읽고 이 클라이언트를 실행한다.

## 6. MCP 응답에서 실제 조사 데이터를 꺼낸다

```python
    if result.is_error:
      raise RuntimeError("MCP 도구 실행 중 오류가 발생했습니다.")

    investigation = result.structured_content

    if investigation is None:
      for content in result.content:
        if content.type == "text":
          investigation = json.loads(content.text)
          break
```

- `result.is_error`는 MCP 도구 호출이 오류로 반환됐는지 확인한다. 참이면 예외를 발생시킨다.
- `structured_content`에 구조화된 결과가 있으면 그대로 사용한다.
- `is None`은 구조화된 결과가 없는 경우를 확인한다.
- `for`는 MCP 응답의 내용 항목을 차례대로 확인한다.
- `content.type == "text"`이면 텍스트 항목이며, `json.loads()`로 JSON 문자열을 딕셔너리 등 Python 값으로 바꾼다.
- `break`는 첫 텍스트 항목을 해석한 뒤 반복문을 끝낸다.
- 서버가 반환한 `{"status": "challenge"}`는 조사 결과 안의 상태다. MCP 통신 자체의 `result.is_error`와 별도 값이다.

```python
    if not isinstance(investigation, dict):
      raise RuntimeError("MCP 조사 결과가 딕셔너리 형식이 아니었습니다.")

    return investigation
```

- `isinstance()`는 실제 값이 지정한 자료형인지 확인한다.
- 조사 결과가 딕셔너리가 아니면 오류를 발생시킨다.
- 딕셔너리이면 호출한 `main()`으로 반환한다.
- 현재 검사는 딕셔너리 여부까지다. `final_url` 등 개별 필드의 유효성을 모두 검사하지는 않는다.

## 7. 결과를 JSON으로 출력한다

```python
  print(json.dumps(investigation, ensure_ascii=False, indent=2))
```

- `json.dumps()`는 딕셔너리를 JSON 문자열로 바꾼다.
- `ensure_ascii=False`는 한국어가 읽을 수 있는 문자로 표시되게 한다.
- `indent=2`는 두 칸 들여쓰기로 출력한다.
- worker는 이 표준 출력을 `result.stdout`으로 받아 `json.loads()`로 읽는다.
- 현재 이 파일에서 출력하는 조사 결과 외의 안내문을 같은 표준 출력에 추가하면 worker의 JSON 해석에 영향을 줄 수 있다.

다음은 반환값을 이해하기 위한 가상 예시다.

```json
{
  "status": "success",
  "reason": "관찰 시점의 페이지 정보를 수집했습니다.",
  "needs_human_review": false,
  "requested_url": "https://example.com/",
  "final_url": "https://example.com/home",
  "http_status": 200,
  "navigation_history": [],
  "title": "Example",
  "body_text": "예시 페이지다."
}
```

- `requested_url`은 조사 요청 주소이며, `final_url`은 브라우저에서 관찰한 최종 주소다.
- `status`는 브라우저 조사 상태이며 사이트의 안전 판정이 아니다.
- 상태 분류의 상세 조건은 [서버 설명서](/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_server.md)에 정리한다.

## 연결 범위

- 호출 순서는 [main.py](/Users/yunduhyun/Desktop/dns_project/python_file/analysis_worker/main.py)의 worker, 이 클라이언트, [browser_mcp_server.py](/Users/yunduhyun/Desktop/dns_project/python_file/mcp_tools/browser_mcp_server.py)의 조사 도구 순서다.
- 이 클라이언트에는 FlareSolverr 요청 코드가 없다.
- 이 클라이언트는 조사 결과를 젬마에게 직접 전달하지 않는다.
- `needs_human_review` 결과가 있어도 관리자에게 자동으로 전송하는 기능은 없다.

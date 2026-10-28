import asyncio
import sys
import json
from pathlib import Path
from mcp import Client, StdioServerParameters

async def request_investigation(url: str) -> dict:
  """ 로컬 MCP 서버에 URL 조사를 요청하고 결과를 반환한다 """

  client_directory = Path(__file__).resolve().parent
  server_path = client_directory / "browser_mcp_server.py"

  server  = StdioServerParameters( # 표준 입력과 출력으로 통신할 MCP 서버의 실행 설정을 만듦
    command = sys.executable, # 현재 클라이언트 코드를 실행중인 Python의 실행 경로가 들어감
    args = [str(server_path)], # args는 실행 명령 뒤에 붙일 인자를 리스트로 전달한다.
    cwd = str(client_directory) # cwd는 서버가 실행될 때 기준으로 사용할 작업 폴더이다. 
  )

  async with Client(server, read_timeout_seconds=180) as client:
    # call_tool을 이용하여 MCP 서버의 도구를 호출한다.
    # await는 호출 결과가 돌아올 때 까지 이 함수의 다음 코드 실행을 대기한다. 
    # 그동안 다른 비동기 작업이 있다면 실행 가능 
    result = await client.call_tool(
      "investigate_url",
      arguments={
        "url": url,
        "manual_verification": False
      }
    )

    if result.is_error:
      raise RuntimeError("MCP 도구 실행 중 오류가 발생했습니다.")

    # 실제 조사 데이터를 investigation에 담는다. 
    investigation = result.structured_content

    # 구조화된 조사 결과가 없는 경우, 텍스트로 받은 JSON에서 조사 데이터를 꺼내는 보완 코드.
    if investigation is None:
      for content in result.content:
        if content.type == "text":
          investigation = json.loads(content.text)
          break

    if not isinstance(investigation, dict):
      raise RuntimeError("MCP 조사 결과가 딕셔너리 형식이 아니었습니다.")

    return investigation
async def main():
  """명령줄에서 받은 URL로 MCP 호출을 시험한다."""

  # python 이후 인자값이 2개가 아닌경우. 여기서 argv는 명령줄에서 전달한 값을 담은 리스트이다. 
  if len(sys.argv) != 2:
    raise SystemExit(
      "사용법: python browser_mcp_client.py https://example.com/"
    )

  url = sys.argv[1]
  investigation = await request_investigation(url)

  print(json.dumps(investigation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  asyncio.run(main())
import asyncio
import sys
import json
from pathlib import Path
from mcp import Client, StdioServerParameters

async def request_investigation(url: str) -> dict:
  """ 로컬 MCP 서버에 URL 조사를 요청하고 결과를 반환한다 """

  client_directory = Path(__file__).resolve().parent
  server_path = client_directory / "browser_mcp_server.py"

  server  = StdioServerParameters( 
    command = sys.executable, 
    args = [str(server_path)], 
    cwd = str(client_directory) 
  )

  async with Client(server, read_timeout_seconds=180) as client:
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
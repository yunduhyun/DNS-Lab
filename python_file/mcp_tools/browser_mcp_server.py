import asyncio
import socket
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlparse

import nodriver as uc
from nodriver import cdp
from mcp.server import MCPServer

mcp = MCPServer("domain-investigation")


async def collect_browser_data(url, observation_seconds):
  """조사 전용 Chrome을 실행하고 메인 페이지의 응답과 본문을 수집한다."""
  browser = None
  process = None

  with tempfile.TemporaryDirectory(prefix="dns-investigation-") as profile:
    try:
      with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

      process = subprocess.Popen(
        [
          "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
          "--no-first-run",
          "--no-default-browser-check",
          "--user-data-dir=" + profile,
          "--remote-debugging-address=127.0.0.1",
          "--remote-debugging-port=" + str(port),
          "about:blank"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
      )

      # Chrome이 제어 요청을 받을 준비가 될 때까지 기다린다.
      for attempt in range(30):
        if process.poll() is not None:
          raise RuntimeError("조사 전용 Chrome이 시작 중 종료되었습니다.")
        try:
          with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version",
            timeout=1
          ):
            break
        except OSError:
          await asyncio.sleep(0.5)
      else:
        raise RuntimeError("조사 전용 Chrome에 연결하지 못했습니다.")

      browser = await uc.start(host="127.0.0.1", port=port, user_data_dir=profile)
      tab = await browser.get("about:blank")
      await tab.send(cdp.browser.set_download_behavior(behavior="deny"))
      tree = await tab.get_frame_tree()
      frame_id = tree.frame.id_
      navigation_history = []
      response_state = {"http_status": None, "cf_mitigated": ""}

      async def record_request(event):
        if event.frame_id != frame_id or event.type_ != cdp.network.ResourceType.DOCUMENT:
          return

        if event.redirect_response is not None:
          navigation_history.append({
            "url": event.redirect_response.url,
            "http_status": int(event.redirect_response.status)
          })

        response_state["http_status"] = None
        response_state["cf_mitigated"] = ""

      async def record_response(event):
        if event.frame_id != frame_id or event.type_ != cdp.network.ResourceType.DOCUMENT:
          return

        response_state["http_status"] = int(event.response.status)
        response_state["cf_mitigated"] = event.response.headers.get("cf-mitigated", "")
        navigation_history.append({
          "url": event.response.url,
          "http_status": int(event.response.status)
        })

      tab.add_handler(cdp.network.RequestWillBeSent, record_request)
      tab.add_handler(cdp.network.ResponseReceived, record_response)
      await tab.send(cdp.network.enable())
      await tab.get(url)
      await asyncio.sleep(observation_seconds)

      final_url = await tab.evaluate("location.href")
      title = await tab.evaluate("document.title")
      body_text = ""
      has_body = await tab.evaluate("document.body !== null")
      if has_body:
        body_text = await tab.evaluate("document.body.innerText")

      return {
        "final_url": final_url,
        "http_status": response_state["http_status"],
        "cf_mitigated": response_state["cf_mitigated"],
        "navigation_history": navigation_history,
        "title": title,
        "body_text": body_text
      }
    finally:
      # 정상 종료와 오류 여부에 관계없이 이번 조사에서 실행한 Chrome만 종료한다.
      try:
        if browser is not None:
          browser.stop()
          await asyncio.sleep(0)
      finally:
        if process is not None:
          if process.poll() is None:
            process.terminate()
          try:
            process.wait(timeout=5)
          except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@mcp.tool()
async def investigate_url(url: str, manual_verification: bool = False) -> dict:
  """창이 보이는 Chrome으로 URL을 조사하고 최종 페이지 정보를 반환한다."""
  url = url.strip()
  result = {
    "status": "error",
    "reason": "",
    "needs_human_review": True,
    "requested_url": url,
    "final_url": "",
    "http_status": None,
    "navigation_history": [],
    "title": "",
    "body_text": ""
  }

  try:
    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    has_credentials = parsed_url.username is not None
  except ValueError:
    result["reason"] = "URL을 해석하지 못했습니다."
    return result

  if parsed_url.scheme not in ["http", "https"] or not hostname or has_credentials:
    result["reason"] = "URL 형식 또는 포함된 인증정보가 허용 조건에 맞지 않아 요청을 거부했습니다."
    return result

  observation_seconds = 10
  if manual_verification:
    observation_seconds = 120

  try:
    data = await asyncio.wait_for(
      collect_browser_data(url, observation_seconds),
      timeout=150
    )
    cf_mitigated = data.pop("cf_mitigated")
    result.update(data)
    http_status = result["http_status"]
    title = result["title"]
    body_text = result["body_text"]
    challenge_titles = [
      "just a moment...",
      "잠시만 기다리십시오…",
      "잠시만 기다리십시오..."
    ]
    has_challenge_title = title.strip().lower() in challenge_titles
    has_cloudflare_text = "cloudflare" in body_text.lower()

    if cf_mitigated == "challenge" or (has_challenge_title and has_cloudflare_text):
      result["status"] = "challenge"
      result["reason"] = "인증 화면이 지속되어 실제 콘텐츠를 확인하지 못했습니다."
    elif len(result["navigation_history"]) > 10:
      result["status"] = "limit_exceeded"
      result["reason"] = "메인 페이지 응답 기록이 10회를 초과했습니다."
    elif http_status is None:
      result["status"] = "incomplete"
      result["reason"] = "메인 페이지의 HTTP 응답을 확인하지 못했습니다."
    elif http_status < 200 or http_status >= 300:
      result["status"] = "http_error"
      result["reason"] = f"HTTP {http_status} 응답을 받아 정상 콘텐츠 수집을 확인하지 못했습니다."
    elif not body_text.strip():
      result["status"] = "incomplete"
      result["reason"] = "페이지 본문을 확보하지 못했습니다."
    else:
      result["status"] = "success"
      result["reason"] = "조사 전용 Chrome으로 페이지 정보를 수집했습니다."

    result["needs_human_review"] = result["status"] != "success"
    return result
  except TimeoutError:
    result["reason"] = "Chrome 조사 제한 시간을 초과했습니다."
    return result
  except Exception as error:
    result["reason"] = f"Chrome 조사 중 오류({type(error).__name__})가 발생했습니다."
    return result


if __name__ == "__main__":
  mcp.run(transport="stdio")

"""Dooray 출/퇴근(working-times) API 클라이언트.

기존 `working_times.py`의 동작을 변경하지 않고, HTTP API 서버에서도 재사용할 수 있도록 로직만 분리한다.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright

from src.config import settings
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class DoorayEndpoints:
  login_url: str
  origin: str
  working_times_api_url: str


def build_endpoints() -> DoorayEndpoints:
  login_url = "https://dooray.com/orgs"
  origin = f"https://{settings.DOORAY_SUBDOMAIN}.dooray.com"
  working_times_api_url = f"{origin}/wapi/work-schedule/v1/working-times"
  return DoorayEndpoints(login_url=login_url, origin=origin, working_times_api_url=working_times_api_url)


async def login_to_dooray(page: Page, context: BrowserContext, endpoints: DoorayEndpoints) -> tuple[bool, list[dict]]:
  """Dooray 로그인 및 쿠키 획득."""
  try:
    await page.goto(endpoints.login_url)
    logger.info("Dooray 로그인 페이지 로드 완료")

    await page.wait_for_timeout(2000)

    await page.focus("input[id=subdomain]")
    await page.type("input[id=subdomain]", settings.DOORAY_SUBDOMAIN, delay=100)
    await page.click("button[type=button]")
    await asyncio.sleep(2)
    await page.wait_for_timeout(2000)

    username = settings.DOORAY_LOGIN_USERNAME
    password = settings.DOORAY_LOGIN_PASSWORD

    if not username or not password:
      logger.error("DOORAY_LOGIN_USERNAME 또는 DOORAY_LOGIN_PASSWORD가 설정되지 않았습니다.")
      return False, []

    await page.focus("input[type=text]")
    await page.type("input[type=text]", username, delay=100)
    await page.focus("input[type=password]")
    await page.type("input[type=password]", password, delay=100)
    await page.click("button[type=submit]")

    try:
      await page.wait_for_load_state("load", timeout=15000)
    except Exception:
      await page.wait_for_timeout(3000)

    await page.wait_for_timeout(2000)

    try:
      await page.goto(endpoints.origin, wait_until="load", timeout=30000)
      await page.wait_for_timeout(5000)

      try:
        await page.wait_for_selector("body", timeout=10000)
      except Exception:
        pass
    except Exception as e:
      logger.warning(f"Dooray 메인 페이지 이동 중 오류 (무시하고 진행): {e}")
      await page.wait_for_timeout(5000)

    cookies = await context.cookies()
    if cookies:
      logger.info(f"로그인 성공 (쿠키 {len(cookies)}개 획득)")
      return True, cookies

    logger.warning("쿠키를 획득하지 못했습니다.")
    return False, []
  except Exception as e:
    logger.error(f"로그인 실패: {e}")
    return False, []


def cookies_to_httpx_dict(cookies: list[dict]) -> dict:
  """Playwright 쿠키를 httpx용 쿠키 딕셔너리로 변환."""
  cookie_dict: dict[str, str] = {}
  for cookie in cookies:
    cookie_dict[cookie["name"]] = cookie["value"]
  return cookie_dict


async def request_attendance(base_date: str, attendance_type: str) -> dict:
  """출/퇴근 요청 API 호출.

  Args:
    base_date: 기준 날짜 (YYYY-MM-DD 형식)
    attendance_type: "ENTER" 또는 "LEAVE"
  """
  endpoints = build_endpoints()

  async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    context = await browser.new_context(
      user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
      ),
      bypass_csp=True,
      viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()

    login_success, cookies = await login_to_dooray(page, context, endpoints)
    if not login_success:
      await browser.close()
      return {"error": "로그인 실패"}

    cookie_dict = cookies_to_httpx_dict(cookies)
    await browser.close()

  request_payload = {"baseDate": base_date, "attendanceType": attendance_type}
  type_name = "출근" if attendance_type == "ENTER" else "퇴근"
  logger.info(f"{type_name} 요청 API 호출: {endpoints.working_times_api_url}")
  logger.info(f"요청 본문: {json.dumps(request_payload, ensure_ascii=False)}")

  try:
    async with httpx.AsyncClient(cookies=cookie_dict, timeout=30.0) as client:
      response = await client.post(
        endpoints.working_times_api_url,
        json=request_payload,
        headers={
          "Content-Type": "application/json",
          "Referer": f"{endpoints.origin}/",
          "Origin": endpoints.origin,
        },
      )

      logger.info(f"응답 상태 코드: {response.status_code}")

      try:
        result = response.json()
        logger.info(f"응답 본문: {json.dumps(result, ensure_ascii=False, indent=2)}")
      except json.JSONDecodeError:
        result = {
          "error": "JSON 파싱 실패",
          "status_code": response.status_code,
          "response_text": response.text[:500],
        }
        logger.error(f"응답 본문 (JSON 파싱 실패): {response.text[:500]}")

      if response.status_code != 200:
        result["status_code"] = response.status_code

      return result
  except httpx.TimeoutException:
    logger.error("API 요청 타임아웃")
    return {"error": "타임아웃"}
  except httpx.RequestError as e:
    logger.error(f"API 요청 실패: {e}")
    return {"error": str(e)}
  except Exception as e:
    logger.error(f"API 호출 중 예외 발생: {e}")
    return {"error": str(e)}


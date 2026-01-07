"""Dooray 출/퇴근(working-times) API 클라이언트.

쿠키 캐싱 + 로그인 속도 최적화.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from playwright.async_api import async_playwright

from src.config import settings
from src.utils.logger import get_logger


logger = get_logger(__name__)


# 쿠키 캐시 (TTL: 30분)
_COOKIE_CACHE_TTL = 30 * 60
_cached_cookies: Optional[dict] = None
_cookie_cached_at: float = 0
_cookie_lock = asyncio.Lock()


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


def _is_cookie_valid() -> bool:
  if not _cached_cookies:
    return False
  return (time.time() - _cookie_cached_at) < _COOKIE_CACHE_TTL


def _invalidate_cookie_cache() -> None:
  global _cached_cookies, _cookie_cached_at
  _cached_cookies = None
  _cookie_cached_at = 0
  logger.info("쿠키 캐시 무효화됨")


async def _login_and_get_cookies(endpoints: DoorayEndpoints) -> dict:
  """Playwright로 로그인하고 쿠키 획득. (속도 최적화)"""
  start_time = time.time()

  async with async_playwright() as p:
    browser = await p.chromium.launch(
      headless=True,
      args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
      ]
    )
    try:
      context = await browser.new_context(
        user_agent=(
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        bypass_csp=True,
        viewport={"width": 1280, "height": 800},
      )
      page = await context.new_page()

      # 로그인 페이지 이동
      await page.goto(endpoints.login_url, wait_until="domcontentloaded")
      logger.info(f"로그인 페이지 로드 완료 ({time.time() - start_time:.1f}s)")

      # 서브도메인 입력 필드 대기 및 입력
      subdomain_input = page.locator("input[id=subdomain]")
      await subdomain_input.wait_for(state="visible", timeout=5000)
      
      # type()으로 입력해야 JavaScript 이벤트가 트리거되어 버튼이 활성화됨
      await subdomain_input.click()
      await subdomain_input.fill("")  # 기존 값 클리어
      await page.keyboard.type(settings.DOORAY_SUBDOMAIN, delay=30)
      
      # Next 버튼이 활성화될 때까지 대기 후 클릭
      next_button = page.locator("button[type=button]:not([disabled])")
      await next_button.wait_for(state="visible", timeout=5000)
      await next_button.click()

      # 로그인 폼 대기
      username_input = page.locator("input[type=text]")
      await username_input.wait_for(state="visible", timeout=10000)

      username = settings.DOORAY_LOGIN_USERNAME
      password = settings.DOORAY_LOGIN_PASSWORD

      if not username or not password:
        raise ValueError("DOORAY_LOGIN_USERNAME 또는 DOORAY_LOGIN_PASSWORD가 설정되지 않았습니다.")

      # 로그인 정보 입력 (fill은 즉시 입력)
      await username_input.fill(username)
      await page.locator("input[type=password]").fill(password)
      await page.click("button[type=submit]")

      logger.info(f"로그인 폼 제출 ({time.time() - start_time:.1f}s)")

      # 로그인 완료 대기 (URL 변경 또는 특정 요소 확인)
      try:
        await page.wait_for_url(f"**/{settings.DOORAY_SUBDOMAIN}**", timeout=15000)
      except Exception:
        # URL 변경이 안 되면 잠시 대기
        await page.wait_for_timeout(2000)

      # 쿠키 확보를 위해 메인 페이지 방문
      try:
        await page.goto(endpoints.origin, wait_until="domcontentloaded", timeout=10000)
      except Exception as e:
        logger.warning(f"메인 페이지 이동 중 오류 (무시): {e}")

      cookies = await context.cookies()
      if not cookies:
        raise ValueError("쿠키를 획득하지 못했습니다.")

      elapsed = time.time() - start_time
      logger.info(f"로그인 성공 (쿠키 {len(cookies)}개, {elapsed:.1f}s 소요)")
      return {c["name"]: c["value"] for c in cookies}

    finally:
      await browser.close()


async def _get_cookies(endpoints: DoorayEndpoints, force_refresh: bool = False) -> dict:
  """쿠키 획득 (캐시 사용)."""
  global _cached_cookies, _cookie_cached_at

  async with _cookie_lock:
    if not force_refresh and _is_cookie_valid():
      logger.debug("캐시된 쿠키 사용")
      return _cached_cookies

    logger.info("새로운 쿠키 획득 중...")
    _cached_cookies = await _login_and_get_cookies(endpoints)
    _cookie_cached_at = time.time()
    return _cached_cookies


async def _call_attendance_api(
  endpoints: DoorayEndpoints,
  cookie_dict: dict,
  base_date: str,
  attendance_type: str
) -> tuple[dict, bool]:
  """출/퇴근 API 호출."""
  request_payload = {"baseDate": base_date, "attendanceType": attendance_type}
  type_name = "출근" if attendance_type == "ENTER" else "퇴근"

  logger.info(f"{type_name} API 호출: {base_date}")

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

    logger.info(f"응답: {response.status_code}")

    if response.status_code in (401, 403):
      return {"error": "인증 실패"}, False

    try:
      result = response.json()
    except json.JSONDecodeError:
      result = {
        "error": "JSON 파싱 실패",
        "status_code": response.status_code,
        "response_text": response.text[:500],
      }

    if response.status_code != 200:
      result["status_code"] = response.status_code

    return result, True


async def request_attendance(base_date: str, attendance_type: str) -> dict:
  """출/퇴근 요청 API 호출."""
  endpoints = build_endpoints()

  try:
    cookie_dict = await _get_cookies(endpoints, force_refresh=False)
    result, success = await _call_attendance_api(endpoints, cookie_dict, base_date, attendance_type)

    if not success:
      logger.warning("인증 실패, 쿠키 갱신 후 재시도")
      _invalidate_cookie_cache()
      cookie_dict = await _get_cookies(endpoints, force_refresh=True)
      result, _ = await _call_attendance_api(endpoints, cookie_dict, base_date, attendance_type)

    return result

  except httpx.TimeoutException:
    logger.error("API 요청 타임아웃")
    return {"error": "타임아웃"}
  except httpx.RequestError as e:
    logger.error(f"API 요청 실패: {e}")
    return {"error": str(e)}
  except Exception as e:
    logger.error(f"API 호출 중 예외 발생: {e}", exc_info=True)
    return {"error": str(e)}

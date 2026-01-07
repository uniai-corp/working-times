"""Dooray 출/퇴근 API 서버.

- Dooray 슬래시 커맨드 형식 지원 (JSON 및 form-urlencoded)
- 비동기 응답: 즉시 "처리 중" 반환 후, responseUrl로 결과 전송
- 날짜를 주지 않으면 Asia/Seoul 기준 "오늘"로 처리
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel

from src.config import settings
from src.dooray_client import request_attendance
from src.utils.logger import setup_logger, get_logger


setup_logger("working_times_api", log_file="logs/working_times_api.log")
logger = get_logger(__name__)

app = FastAPI(title="Dooray Working Times API", version="1.0.0")

_TZ = ZoneInfo("Asia/Seoul")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


# Dooray 슬래시 커맨드 요청 모델
class DoorayCommandRequest(BaseModel):
  tenantId: Optional[str] = None
  tenantDomain: Optional[str] = None
  channelId: Optional[str] = None
  channelName: Optional[str] = None
  userId: Optional[str] = None
  userName: Optional[str] = None
  userEmail: Optional[str] = None
  command: Optional[str] = None
  text: Optional[str] = None
  responseUrl: Optional[str] = None
  appToken: Optional[str] = None
  cmdToken: Optional[str] = None
  triggerId: Optional[str] = None


def _today_yyyy_mm_dd() -> str:
  return datetime.now(_TZ).date().isoformat()


def _extract_date_from_text(text: str | None) -> str:
  """text에서 YYYY-MM-DD 형식 날짜 추출, 없으면 오늘 날짜 반환."""
  if text:
    match = _DATE_PATTERN.search(text.strip())
    if match:
      return match.group()
  return _today_yyyy_mm_dd()


def _ensure_settings() -> str | None:
  """설정 검증. 실패 시 에러 메시지 반환."""
  try:
    settings.validate()
    return None
  except Exception as e:
    return str(e)


def _dooray_response(message: str, response_type: str = "ephemeral") -> dict:
  """Dooray 슬래시 커맨드 응답 형식."""
  return {
    "responseType": response_type,
    "text": message
  }


async def _send_to_response_url(
  response_url: str,
  channel_id: str | None,
  message: str,
  response_type: str = "inChannel"
) -> None:
  """responseUrl로 결과 메시지 전송.
  
  Dooray responseUrl (Incoming Webhook) 형식:
  - channelId: 필수
  - responseType: "ephemeral" (본인만) 또는 "inChannel" (전체)
  - text: 메시지
  """
  if not response_url:
    logger.warning("responseUrl이 없어서 결과를 전송할 수 없습니다.")
    return

  if not channel_id:
    logger.warning("channelId가 없어서 결과를 전송할 수 없습니다.")
    return

  # Dooray Incoming Webhook 형식 (channelId 필수)
  payload = {
    "channelId": channel_id,
    "responseType": response_type,
    "text": message
  }

  try:
    async with httpx.AsyncClient(timeout=10.0) as client:
      response = await client.post(
        response_url,
        json=payload,
        headers={"Content-Type": "application/json"}
      )
      logger.info(f"responseUrl 전송: status={response.status_code}, body={response.text[:200]}")
  except Exception as e:
    logger.error(f"responseUrl 전송 실패: {e}")


async def _process_attendance_async(
  attendance_type: str,
  base_date: str,
  user_email: str | None,
  response_url: str | None,
  channel_id: str | None
) -> None:
  """백그라운드에서 출/퇴근 처리 후 결과를 responseUrl로 전송."""
  type_name = "출근" if attendance_type == "ENTER" else "퇴근"
  user_display = user_email.split("@")[0] if user_email else "사용자"

  logger.info(f"[백그라운드] {type_name} 처리 시작: user={user_display}, base_date={base_date}")

  try:
    result = await request_attendance(base_date, attendance_type)

    header = result.get("header", {})
    if header.get("isSuccessful"):
      message = f"{user_display}님, {base_date} {type_name} 처리가 완료되었습니다."
    else:
      error_msg = header.get("resultMessage", "알 수 없는 오류")
      message = f"{user_display}님, {type_name} 처리 실패: {error_msg}"

  except Exception as e:
    logger.error(f"{type_name} 처리 중 오류: {e}", exc_info=True)
    message = f"{type_name} 처리 중 오류가 발생했습니다: {str(e)}"

  # responseUrl로 결과 전송 (channelId 필수)
  await _send_to_response_url(response_url, channel_id, message, "inChannel")


async def _parse_dooray_request(request: Request) -> dict:
  """Dooray 요청 파싱 (JSON 또는 form-urlencoded 모두 지원)."""
  content_type = request.headers.get("content-type", "")

  # JSON 형식
  if "application/json" in content_type:
    try:
      body = await request.json()
      logger.info(f"JSON 요청 수신: {body}")
      return body
    except Exception as e:
      logger.warning(f"JSON 파싱 실패: {e}")
      return {}

  # form-urlencoded 형식
  if "application/x-www-form-urlencoded" in content_type:
    try:
      form = await request.form()
      body = dict(form)
      logger.info(f"Form 요청 수신: {body}")
      return body
    except Exception as e:
      logger.warning(f"Form 파싱 실패: {e}")
      return {}

  # Content-Type이 없거나 다른 경우
  try:
    raw_body = await request.body()
    if not raw_body:
      return {}

    # JSON 시도
    try:
      body = json.loads(raw_body.decode("utf-8"))
      logger.info(f"Raw JSON 요청 수신: {body}")
      return body
    except json.JSONDecodeError:
      pass

    # form-urlencoded 시도
    try:
      from urllib.parse import parse_qs
      parsed = parse_qs(raw_body.decode("utf-8"))
      body = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
      logger.info(f"Raw Form 요청 수신: {body}")
      return body
    except Exception:
      pass

    return {}
  except Exception:
    return {}


# Health check
@app.get("/health")
async def health() -> dict:
  return {"ok": True}


# Dooray 슬래시 커맨드 통합 엔드포인트
@app.post("/dooray")
async def dooray_command(request: Request, background_tasks: BackgroundTasks) -> dict:
  """Dooray 슬래시 커맨드 통합 처리.

  즉시 "처리 중" 메시지를 반환하고, 백그라운드에서 처리 후 responseUrl로 결과 전송.
  """
  # 설정 검증
  error = _ensure_settings()
  if error:
    return _dooray_response(f"설정 오류: {error}")

  body = await _parse_dooray_request(request)

  if not body:
    return _dooray_response("요청 본문이 비어있습니다.")

  try:
    data = DoorayCommandRequest(**body)
  except Exception as e:
    return _dooray_response(f"요청 형식 오류: {e}")

  command = (data.command or "").strip()
  base_date = _extract_date_from_text(data.text)
  user_email = data.userEmail
  response_url = data.responseUrl
  channel_id = data.channelId

  logger.info(f"Dooray 커맨드: command={command}, user={user_email}, date={base_date}, channelId={channel_id}")

  if command in ("/출근", "/enter"):
    # 백그라운드에서 처리
    background_tasks.add_task(
      _process_attendance_async, "ENTER", base_date, user_email, response_url, channel_id
    )
    return _dooray_response("출근 처리 중...")

  elif command in ("/퇴근", "/leave"):
    # 백그라운드에서 처리
    background_tasks.add_task(
      _process_attendance_async, "LEAVE", base_date, user_email, response_url, channel_id
    )
    return _dooray_response("퇴근 처리 중...")

  else:
    return _dooray_response(f"알 수 없는 명령어: {command}\n사용 가능: /출근, /퇴근")


# 개별 엔드포인트
@app.post("/enter")
async def enter(request: Request, background_tasks: BackgroundTasks) -> dict:
  """출근(ENTER)"""
  error = _ensure_settings()
  if error:
    return _dooray_response(f"설정 오류: {error}")

  body = await _parse_dooray_request(request)

  if body:
    try:
      data = DoorayCommandRequest(**body)
      base_date = _extract_date_from_text(data.text)
      user_email = data.userEmail
      response_url = data.responseUrl
      channel_id = data.channelId
    except Exception:
      base_date = _today_yyyy_mm_dd()
      user_email = None
      response_url = None
      channel_id = None
  else:
    base_date = _today_yyyy_mm_dd()
    user_email = None
    response_url = None
    channel_id = None

  background_tasks.add_task(
    _process_attendance_async, "ENTER", base_date, user_email, response_url, channel_id
  )
  return _dooray_response("출근 처리 중...")


@app.post("/leave")
async def leave(request: Request, background_tasks: BackgroundTasks) -> dict:
  """퇴근(LEAVE)"""
  error = _ensure_settings()
  if error:
    return _dooray_response(f"설정 오류: {error}")

  body = await _parse_dooray_request(request)

  if body:
    try:
      data = DoorayCommandRequest(**body)
      base_date = _extract_date_from_text(data.text)
      user_email = data.userEmail
      response_url = data.responseUrl
      channel_id = data.channelId
    except Exception:
      base_date = _today_yyyy_mm_dd()
      user_email = None
      response_url = None
      channel_id = None
  else:
    base_date = _today_yyyy_mm_dd()
    user_email = None
    response_url = None
    channel_id = None

  background_tasks.add_task(
    _process_attendance_async, "LEAVE", base_date, user_email, response_url, channel_id
  )
  return _dooray_response("퇴근 처리 중...")

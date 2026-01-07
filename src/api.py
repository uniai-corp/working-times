"""Dooray 출/퇴근 API 서버.

- Dooray 슬래시 커맨드 형식 지원 (JSON 및 form-urlencoded)
- 비동기 응답: 즉시 "처리 중" 반환 후, responseUrl로 결과 전송
- 날짜를 주지 않으면 Asia/Seoul 기준 "오늘"로 처리
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import FastAPI, Request
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


# 동기 처리 헬퍼
async def _process_attendance_sync(
  attendance_type: str,
  base_date: str,
  user_email: str | None
) -> str:
  """동기적으로 출/퇴근 처리 후 결과 메시지 반환."""
  type_name = "출근" if attendance_type == "ENTER" else "퇴근"
  user_display = user_email.split("@")[0] if user_email else "사용자"

  try:
    result = await request_attendance(base_date, attendance_type)

    header = result.get("header", {})
    if header.get("isSuccessful"):
      return f"✅ {user_display}님, {base_date} {type_name} 완료!"
    else:
      error_msg = header.get("resultMessage", "알 수 없는 오류")
      return f"❌ {type_name} 실패: {error_msg}"

  except Exception as e:
    logger.error(f"{type_name} 처리 중 오류: {e}", exc_info=True)
    return f"❌ {type_name} 처리 중 오류: {str(e)}"


# Dooray 슬래시 커맨드 통합 엔드포인트
@app.post("/dooray")
async def dooray_command(request: Request) -> dict:
  """Dooray 슬래시 커맨드 통합 처리 (동기 방식).

  처리 완료 후 바로 결과를 반환합니다.
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

  logger.info(f"Dooray 커맨드: command={command}, user={user_email}, date={base_date}")

  if command in ("/출근", "/enter"):
    # 동기 처리 후 바로 결과 반환
    result_msg = await _process_attendance_sync("ENTER", base_date, user_email)
    return _dooray_response(result_msg, "inChannel")

  elif command in ("/퇴근", "/leave"):
    # 동기 처리 후 바로 결과 반환
    result_msg = await _process_attendance_sync("LEAVE", base_date, user_email)
    return _dooray_response(result_msg, "inChannel")

  else:
    return _dooray_response(f"알 수 없는 명령어: {command}\n사용 가능: /출근, /퇴근")


# 개별 엔드포인트
@app.post("/enter")
async def enter(request: Request) -> dict:
  """출근(ENTER) - 동기 처리"""
  error = _ensure_settings()
  if error:
    return _dooray_response(f"설정 오류: {error}")

  body = await _parse_dooray_request(request)

  if body:
    try:
      data = DoorayCommandRequest(**body)
      base_date = _extract_date_from_text(data.text)
      user_email = data.userEmail
    except Exception:
      base_date = _today_yyyy_mm_dd()
      user_email = None
  else:
    base_date = _today_yyyy_mm_dd()
    user_email = None

  result_msg = await _process_attendance_sync("ENTER", base_date, user_email)
  return _dooray_response(result_msg, "inChannel")


@app.post("/leave")
async def leave(request: Request) -> dict:
  """퇴근(LEAVE) - 동기 처리"""
  error = _ensure_settings()
  if error:
    return _dooray_response(f"설정 오류: {error}")

  body = await _parse_dooray_request(request)

  if body:
    try:
      data = DoorayCommandRequest(**body)
      base_date = _extract_date_from_text(data.text)
      user_email = data.userEmail
    except Exception:
      base_date = _today_yyyy_mm_dd()
      user_email = None
  else:
    base_date = _today_yyyy_mm_dd()
    user_email = None

  result_msg = await _process_attendance_sync("LEAVE", base_date, user_email)
  return _dooray_response(result_msg, "inChannel")

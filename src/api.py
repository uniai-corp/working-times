"""Dooray 출/퇴근 API 서버.

- Dooray 슬래시 커맨드 형식 지원
- 날짜를 주지 않으면 Asia/Seoul 기준 "오늘"로 처리
"""

from __future__ import annotations

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


def _ensure_settings() -> dict | None:
  """설정 검증. 실패 시 Dooray 응답 형식으로 에러 반환."""
  try:
    settings.validate()
    return None
  except Exception as e:
    return {
      "responseType": "ephemeral",
      "text": f"설정 오류: {e}"
    }


def _dooray_response(success: bool, message: str, result: dict | None = None) -> dict:
  """Dooray 슬래시 커맨드 응답 형식."""
  text = message
  if result:
    header = result.get("header", {})
    if header.get("isSuccessful"):
      text = message
    else:
      text = f"{message}\n결과: {header.get('resultMessage', '알 수 없는 오류')}"
  
  return {
    "responseType": "ephemeral",  # 채널에 표시 (ephemeral: 본인만 보임)
    "text": text
  }


async def _process_attendance(attendance_type: str, base_date: str, user_name: str | None) -> dict:
  """출/퇴근 처리 공통 로직."""
  error = _ensure_settings()
  if error:
    return error
  
  type_name = "출근" if attendance_type == "ENTER" else "퇴근"
  user_display = user_name or "사용자"
  
  logger.info(f"{type_name} 요청: user={user_display}, base_date={base_date}")
  
  try:
    result = await request_attendance(base_date, attendance_type)
    
    header = result.get("header", {})
    if header.get("isSuccessful"):
      return _dooray_response(
        True,
        f"{user_display}님, {base_date} {type_name} 처리가 완료되었습니다.",
        result
      )
    else:
      return _dooray_response(
        False,
        f"{user_display}님, {type_name} 처리 실패: {header.get('resultMessage', '알 수 없는 오류')}",
        result
      )
  except Exception as e:
    logger.error(f"{type_name} 처리 중 오류: {e}", exc_info=True)
    return _dooray_response(False, f"{type_name} 처리 중 오류가 발생했습니다: {str(e)}")


# Health check
@app.get("/health")
async def health() -> dict:
  return {"ok": True}


# Dooray 슬래시 커맨드 통합 엔드포인트
@app.post("/dooray")
async def dooray_command(request: Request) -> dict:
  """Dooray 슬래시 커맨드 통합 처리.
  
  /출근 또는 /퇴근 커맨드를 하나의 URL로 처리합니다.
  RequestUrl에 이 엔드포인트를 등록하세요.
  """
  try:
    body = await request.json()
    data = DoorayCommandRequest(**body)
  except Exception as e:
    logger.warning(f"요청 파싱 실패: {e}")
    return {"responseType": "ephemeral", "text": f"요청 형식 오류: {e}"}
  
  command = (data.command or "").strip()
  base_date = _extract_date_from_text(data.text)
  user_name = data.userName
  
  logger.info(f"Dooray 커맨드 수신: command={command}, user={user_name}, text={data.text}")
  
  if command in ("/출근", "/enter"):
    return await _process_attendance("ENTER", base_date, user_name)
  elif command in ("/퇴근", "/leave"):
    return await _process_attendance("LEAVE", base_date, user_name)
  else:
    return {
      "responseType": "ephemeral",
      "text": f"알 수 없는 명령어입니다: {command}\n사용 가능: /출근, /퇴근"
    }


# 개별 엔드포인트 (Dooray 형식 지원)
@app.post("/enter")
async def enter(request: Request) -> dict:
  """출근(ENTER) - Dooray 슬래시 커맨드 또는 직접 호출."""
  try:
    body = await request.json()
    data = DoorayCommandRequest(**body)
    base_date = _extract_date_from_text(data.text)
    user_name = data.userName
  except Exception:
    # Dooray 형식이 아닌 직접 호출
    base_date = _today_yyyy_mm_dd()
    user_name = None
  
  return await _process_attendance("ENTER", base_date, user_name)


@app.post("/leave")
async def leave(request: Request) -> dict:
  """퇴근(LEAVE) - Dooray 슬래시 커맨드 또는 직접 호출."""
  try:
    body = await request.json()
    data = DoorayCommandRequest(**body)
    base_date = _extract_date_from_text(data.text)
    user_name = data.userName
  except Exception:
    # Dooray 형식이 아닌 직접 호출
    base_date = _today_yyyy_mm_dd()
    user_name = None
  
  return await _process_attendance("LEAVE", base_date, user_name)

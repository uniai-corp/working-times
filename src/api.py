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
from fastapi.responses import HTMLResponse
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


# ========================================
# QR 코드 출퇴근 엔드포인트
# ========================================


def _html_response(title: str, message: str, success: bool = True) -> HTMLResponse:
  """QR 스캔 결과를 보여주는 HTML 페이지."""
  color = "#10b981" if success else "#ef4444"
  icon = "✓" if success else "✗"
  
  html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      color: white;
    }}
    .container {{
      text-align: center;
      padding: 2rem;
    }}
    .icon {{
      width: 80px;
      height: 80px;
      border-radius: 50%;
      background: {color};
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 1.5rem;
      font-size: 2.5rem;
    }}
    h1 {{
      font-size: 1.5rem;
      margin-bottom: 0.5rem;
    }}
    .message {{
      font-size: 1.1rem;
      color: #94a3b8;
      line-height: 1.6;
    }}
    .time {{
      margin-top: 1.5rem;
      font-size: 0.9rem;
      color: #64748b;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p class="message">{message}</p>
    <p class="time">{datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")}</p>
  </div>
</body>
</html>
"""
  return HTMLResponse(content=html)


@app.get("/qr/enter")
async def qr_enter():
  """QR 코드로 출근 처리 (GET 요청)."""
  error = _ensure_settings()
  if error:
    return _html_response("설정 오류", error, success=False)

  base_date = _today_yyyy_mm_dd()
  result_msg = await _process_attendance_sync("ENTER", base_date, None)
  
  success = "완료" in result_msg
  return _html_response("출근 처리", result_msg, success=success)


@app.get("/qr/leave")
async def qr_leave():
  """QR 코드로 퇴근 처리 (GET 요청)."""
  error = _ensure_settings()
  if error:
    return _html_response("설정 오류", error, success=False)

  base_date = _today_yyyy_mm_dd()
  result_msg = await _process_attendance_sync("LEAVE", base_date, None)
  
  success = "완료" in result_msg
  return _html_response("퇴근 처리", result_msg, success=success)


@app.get("/qr")
async def qr_page(request: Request):
  """QR 코드 페이지 (출근/퇴근 QR 표시)."""
  # 요청의 host 정보로 base URL 생성
  host = request.headers.get("host", "localhost:8000")
  scheme = request.headers.get("x-forwarded-proto", "http")
  base_url = f"{scheme}://{host}"
  
  enter_url = f"{base_url}/qr/enter"
  leave_url = f"{base_url}/qr/leave"
  
  # QR 코드는 Google Charts API 또는 직접 생성
  qr_enter = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={enter_url}"
  qr_leave = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={leave_url}"
  
  html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>출퇴근 QR 코드</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      min-height: 100vh;
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      color: white;
      padding: 2rem;
    }}
    h1 {{
      text-align: center;
      margin-bottom: 2rem;
      font-size: 1.8rem;
    }}
    .qr-container {{
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 2rem;
    }}
    .qr-card {{
      background: rgba(255,255,255,0.05);
      border-radius: 16px;
      padding: 2rem;
      text-align: center;
      border: 1px solid rgba(255,255,255,0.1);
    }}
    .qr-card img {{
      border-radius: 8px;
      margin-bottom: 1rem;
    }}
    .qr-card h2 {{
      font-size: 1.3rem;
      margin-bottom: 0.5rem;
    }}
    .qr-card.enter h2 {{ color: #10b981; }}
    .qr-card.leave h2 {{ color: #f59e0b; }}
    .qr-card p {{
      font-size: 0.85rem;
      color: #94a3b8;
      word-break: break-all;
    }}
    .info {{
      text-align: center;
      margin-top: 2rem;
      color: #64748b;
      font-size: 0.9rem;
    }}
  </style>
</head>
<body>
  <h1>출퇴근 QR 코드</h1>
  <div class="qr-container">
    <div class="qr-card enter">
      <img src="{qr_enter}" alt="출근 QR">
      <h2>출근</h2>
      <p>{enter_url}</p>
    </div>
    <div class="qr-card leave">
      <img src="{qr_leave}" alt="퇴근 QR">
      <h2>퇴근</h2>
      <p>{leave_url}</p>
    </div>
  </div>
  <p class="info">스마트폰으로 QR 코드를 스캔하세요</p>
</body>
</html>
"""
  return HTMLResponse(content=html)

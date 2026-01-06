"""Dooray 출/퇴근 API 서버.

- 기능은 기존 `request_attendance()`를 그대로 사용한다.
- 날짜를 주지 않으면 Asia/Seoul 기준 "오늘"로 처리한다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException

from src.config import settings
from src.dooray_client import request_attendance
from src.utils.logger import setup_logger, get_logger


setup_logger("working_times_api", log_file="logs/working_times_api.log")
logger = get_logger(__name__)

app = FastAPI(title="Dooray Working Times API", version="1.0.0")

_TZ = ZoneInfo("Asia/Seoul")


def _today_yyyy_mm_dd() -> str:
  return datetime.now(_TZ).date().isoformat()


def _ensure_settings() -> None:
  try:
    settings.validate()
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health() -> dict:
  return {"ok": True}


@app.post("/enter")
async def enter(base_date: str | None = None) -> dict:
  """오늘 기준 출근(ENTER)."""
  _ensure_settings()
  base_date = base_date or _today_yyyy_mm_dd()
  logger.info(f"ENTER 요청: base_date={base_date}")
  return await request_attendance(base_date, "ENTER")


@app.post("/leave")
async def leave(base_date: str | None = None) -> dict:
  """오늘 기준 퇴근(LEAVE)."""
  _ensure_settings()
  base_date = base_date or _today_yyyy_mm_dd()
  logger.info(f"LEAVE 요청: base_date={base_date}")
  return await request_attendance(base_date, "LEAVE")


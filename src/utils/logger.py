"""로깅 유틸 (working_times.py 호환).

기존 코드가 기대하는 함수 시그니처를 제공한다:
- setup_logger(app_name: str, log_file: str | None = None)
- get_logger(name: str)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional


_CONFIGURED = False


def setup_logger(app_name: str, log_file: Optional[str] = None, level: int = logging.INFO) -> None:
  global _CONFIGURED
  if _CONFIGURED:
    return

  handlers: list[logging.Handler] = [logging.StreamHandler()]

  if log_file:
    log_path = Path(log_file)
    if log_path.parent and str(log_path.parent) not in (".", ""):
      os.makedirs(log_path.parent, exist_ok=True)
    handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

  logging.basicConfig(
    level=level,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    handlers=handlers,
  )

  logging.getLogger("httpx").setLevel(logging.WARNING)
  _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
  return logging.getLogger(name)


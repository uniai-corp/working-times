"""설정 관리 (Dooray 출퇴근 스크립트용 최소 설정).

현재 프로젝트에서는 `working_times.py`에서 필요한 설정만 환경변수로 받는다.
- 사용하지 않는 환경변수는 모두 제거했다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
  """프로젝트 루트의 `.env`를 로드한다(없으면 무시)."""
  # `src/config.py` 기준: 프로젝트 루트는 parent
  env_path = Path(__file__).resolve().parent.parent / ".env"
  load_dotenv(dotenv_path=env_path)


@dataclass(frozen=True)
class Settings:
  """애플리케이션 설정(최소)."""

  DOORAY_LOGIN_USERNAME: str = ""
  DOORAY_LOGIN_PASSWORD: str = ""
  DOORAY_SUBDOMAIN: str = "uniai"  # 기존 코드 하드코딩과 동일한 기본값

  @classmethod
  def from_env(cls) -> "Settings":
    _load_env()
    return cls(
      DOORAY_LOGIN_USERNAME=os.getenv("DOORAY_LOGIN_USERNAME", "").strip(),
      DOORAY_LOGIN_PASSWORD=os.getenv("DOORAY_LOGIN_PASSWORD", "").strip(),
      DOORAY_SUBDOMAIN=os.getenv("DOORAY_SUBDOMAIN", "uniai").strip() or "uniai",
    )

  def validate(self) -> None:
    missing: list[str] = []
    if not self.DOORAY_LOGIN_USERNAME:
      missing.append("DOORAY_LOGIN_USERNAME")
    if not self.DOORAY_LOGIN_PASSWORD:
      missing.append("DOORAY_LOGIN_PASSWORD")
    if not self.DOORAY_SUBDOMAIN:
      missing.append("DOORAY_SUBDOMAIN")

    if missing:
      raise ValueError(f"Missing required settings: {', '.join(missing)}")


settings = Settings.from_env()


#!/usr/bin/env python3
"""Dooray 근무시간 API 테스트 스크립트"""
import asyncio
import json
from src.dooray_client import request_attendance
from src.utils.logger import setup_logger, get_logger
from src.config import settings

# 로거 설정
setup_logger("working_times_test", log_file="logs/working_times_test.log")
logger = get_logger(__name__)

async def request_leave(base_date: str) -> dict:
    """퇴근 요청 API 호출 (호환성을 위한 래퍼 함수)

    Args:
      base_date: 기준 날짜 (YYYY-MM-DD 형식)

    Returns:
      API 응답 딕셔너리
    """
    return await request_attendance(base_date, "LEAVE")


async def request_arrive(base_date: str) -> dict:
    """출근 요청 API 호출

    Args:
      base_date: 기준 날짜 (YYYY-MM-DD 형식)

    Returns:
      API 응답 딕셔너리
    """
    return await request_attendance(base_date, "ENTER")


def test_attendance_request(base_date: str, attendance_type: str, type_name: str):
    """출/퇴근 요청 테스트

    Args:
      base_date: 기준 날짜
      attendance_type: 출근 타입 ("ENTER" 또는 "LEAVE")
      type_name: 타입 이름 ("출근" 또는 "퇴근")
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Dooray 근무시간 API {type_name} 요청 테스트")
    logger.info("=" * 60)
    logger.info(f"테스트 날짜: {base_date}")
    logger.info("")

    # API 요청
    result = asyncio.run(request_attendance(base_date, attendance_type))

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"{type_name} 요청 테스트 결과")
    logger.info("=" * 60)

    if "error" in result:
        logger.error(f"테스트 실패: {result['error']}")
        return

    # 응답 검증
    header = result.get("header", {})
    is_successful = header.get("isSuccessful", False)
    result_code = header.get("resultCode", -1)
    result_message = header.get("resultMessage", "")

    if is_successful and result_code == 0:
        logger.info(f"성공: {type_name} 요청이 정상적으로 처리되었습니다.")
        logger.info(f"결과 코드: {result_code}")
        logger.info(f"결과 메시지: {result_message if result_message else '(없음)'}")
    else:
        logger.warning(f"실패 또는 예상과 다른 응답")
        logger.warning(f"성공 여부: {is_successful}")
        logger.warning(f"결과 코드: {result_code}")
        logger.warning(f"결과 메시지: {result_message}")

    logger.info("")
    logger.info(f"전체 응답:")
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))


def test_working_times():
    """출/퇴근 요청 테스트"""
    try:
        logger.info("=" * 60)
        logger.info("Dooray 근무시간 API 출/퇴근 요청 테스트 시작")
        logger.info("=" * 60)

        # 설정 검증
        if not settings.DOORAY_LOGIN_USERNAME or not settings.DOORAY_LOGIN_PASSWORD:
            logger.error("DOORAY_LOGIN_USERNAME 또는 DOORAY_LOGIN_PASSWORD가 설정되지 않았습니다.")
            logger.error(".env 파일에 설정을 추가하거나 환경 변수를 설정하세요.")
            return

        # 테스트할 날짜 (사용자가 제공한 예시 날짜)
        base_date = "2026-01-05"

        # 출근 테스트
        test_attendance_request(base_date, "ENTER", "출근")

        # 퇴근 테스트
        test_attendance_request(base_date, "LEAVE", "퇴근")

    except Exception as e:
        logger.error(f"테스트 실패: {e}", exc_info=True)


def test_working_times_leave():
    """퇴근 요청 테스트 (호환성을 위한 함수)"""
    try:
        logger.info("=" * 60)
        logger.info("Dooray 근무시간 API 퇴근 요청 테스트 시작")
        logger.info("=" * 60)

        # 설정 검증
        if not settings.DOORAY_LOGIN_USERNAME or not settings.DOORAY_LOGIN_PASSWORD:
            logger.error("DOORAY_LOGIN_USERNAME 또는 DOORAY_LOGIN_PASSWORD가 설정되지 않았습니다.")
            logger.error(".env 파일에 설정을 추가하거나 환경 변수를 설정하세요.")
            return

        # 테스트할 날짜
        base_date = "2026-01-05"
        test_attendance_request(base_date, "LEAVE", "퇴근")

    except Exception as e:
        logger.error(f"테스트 실패: {e}", exc_info=True)


if __name__ == "__main__":
    test_working_times()
d
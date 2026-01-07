# working-times

Dooray 출퇴근 API 서버 - 슬래시 커맨드 연동 지원

## 환경변수 설정

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 설정하세요.
(`env.example` 참고)

| 키 | 필수 | 설명 |
|----|------|------|
| `DOORAY_LOGIN_USERNAME` | O | Dooray 로그인 아이디 |
| `DOORAY_LOGIN_PASSWORD` | O | Dooray 로그인 비밀번호 |
| `DOORAY_SUBDOMAIN` | - | 조직 서브도메인 (기본값: `uniai`) |

## 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt
playwright install chromium

# API 서버 실행
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

## Docker 실행

```bash
docker compose up --build
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 |
| POST | `/enter` | 출근 처리 |
| POST | `/leave` | 퇴근 처리 |
| POST | `/dooray` | Dooray 슬래시 커맨드 통합 (추천) |

## Dooray 슬래시 커맨드 설정

### 1) 공개 URL 준비

Dooray 서버에서 호출하려면 **인터넷에서 접근 가능한 URL**이 필요합니다.

**ngrok 사용 예시:**
```bash
ngrok http 8000
# 출력된 URL 사용: https://xxxx.ngrok-free.app
```

### 2) Dooray 메신저에서 슬래시 커맨드 등록

#### 방법 A: 통합 엔드포인트 사용 (추천)

하나의 URL로 `/출근`, `/퇴근` 모두 처리:

| 필드 | `/출근` 커맨드 | `/퇴근` 커맨드 |
|------|----------------|----------------|
| **Command** | `/출근` | `/퇴근` |
| **RequestUrl** | `https://xxx.ngrok-free.app/dooray` | `https://xxx.ngrok-free.app/dooray` |
| **Short Description** | `오늘 날짜로 출근 처리` | `오늘 날짜로 퇴근 처리` |
| **Parameter 힌트** | `YYYY-MM-DD (선택)` | `YYYY-MM-DD (선택)` |

#### 방법 B: 개별 엔드포인트 사용

| 필드 | `/출근` 커맨드 | `/퇴근` 커맨드 |
|------|----------------|----------------|
| **Command** | `/출근` | `/퇴근` |
| **RequestUrl** | `https://xxx.ngrok-free.app/enter` | `https://xxx.ngrok-free.app/leave` |
| **Short Description** | `오늘 날짜로 출근 처리` | `오늘 날짜로 퇴근 처리` |

### 3) 사용 예시

Dooray 메신저에서:
```
/출근
/퇴근
/출근 2026-01-10   (날짜 지정)
```

### 응답 형식

성공 시:
```
홍길동님, 2026-01-07 출근 처리가 완료되었습니다.
```

실패 시:
```
홍길동님, 출근 처리 실패: 근무기준에 맞지 않는 시간입니다.
```

## 테스트 스크립트 실행

```bash
python working_times.py
```

## 프로젝트 구조

```
working-times/
├── src/
│   ├── api.py           # FastAPI 서버 (슬래시 커맨드 지원)
│   ├── config.py        # 환경변수 설정
│   ├── dooray_client.py # Dooray API 호출 (Playwright)
│   └── utils/
│       └── logger.py    # 로깅 설정
├── working_times.py     # 테스트 스크립트
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── env.example
```

# working-times
출퇴근 API

## 환경변수 설정

이 프로젝트는 프로젝트 루트의 `.env` 파일을 읽습니다. (파일이 없으면 OS 환경변수만 사용)

- `env.example`을 복사해서 `.env`를 만들고 값만 채우세요.

필수 키:
- `DOORAY_LOGIN_USERNAME`
- `DOORAY_LOGIN_PASSWORD`
- `DOORAY_SUBDOMAIN` (기본값: `uniai`)

## 실행

```bash
python working_times.py
```

## API 서버 실행 (오늘 날짜 기준 출/퇴근)

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

엔드포인트:
- `POST /enter` : 출근(ENTER)
- `POST /leave` : 퇴근(LEAVE)
- `POST /enter?base_date=YYYY-MM-DD` 처럼 날짜를 지정할 수도 있습니다.

## Docker로 실행

프로젝트 루트에 `.env`를 준비한 뒤 실행합니다(예: `env.example` 참고).

```bash
docker compose up --build
```

호출 예:
- `POST http://localhost:8000/enter`
- `POST http://localhost:8000/leave`

만약 `8000` 포트가 이미 사용 중이면, 호스트 포트를 바꿔서 실행할 수 있습니다:

```bash
HOST_PORT=8001 docker compose up --build
```

이 경우 호출 예:
- `POST http://localhost:8001/enter`
- `POST http://localhost:8001/leave`

외부(다른 PC)에서 호출하려면, 호출 측에서 `http://<이-머신-IP>:8000/...`로 접근 가능해야 하고,
공유기/방화벽 정책에 따라 포트(8000) 허용이 필요할 수 있습니다.

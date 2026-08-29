# DALM Backend

Flutter 클라이언트와 연동되는 FastAPI 백엔드입니다.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
export DALM_JWT_SECRET='replace-with-at-least-32-random-characters'
uvicorn app.main:app --reload
```

프론트의 `API_BASE_URL`은 로컬 서버의 `/v1`을 포함해 설정합니다.

```dotenv
API_BASE_URL=http://localhost:8000/v1
```

## 인증 연동 계약

`POST /v1/auth/refresh`는 인증 헤더 없이 Refresh Token을 요청 본문으로 받습니다.

```json
{"refresh_token": "..."}
```

성공 시 Flutter의 `ApiResponseDto<TokenPairDto>`가 읽을 수 있는 형식으로 새 토큰 쌍을
반환합니다. Refresh Token은 한 번 사용하면 폐기되므로 클라이언트는 두 토큰을 함께
교체해야 합니다.

```json
{
  "data": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "Bearer",
    "expires_in": 1800
  },
  "error": null
}
```

실패 시 HTTP 401과 공통 오류 형식을 반환합니다. 프론트는 재발급 요청 자체에 대해
다시 재발급을 시도하지 않고 저장된 토큰을 삭제해야 합니다.

현재 Refresh Token 저장소는 단일 프로세스용 인메모리 구현입니다. 다중 인스턴스 배포
전에는 동일한 인터페이스를 PostgreSQL 또는 Redis 기반 원자적 회전 구현으로 교체해야 합니다.


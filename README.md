# DALM Backend

서로 다른 사람의 사진에서 우연히 닮은 순간을 발견하고, 한 장의 엽서를 주고받는
AI 사진 매칭 앱 **DALM**의 FastAPI 백엔드입니다.

Flutter 클라이언트에 REST API를 제공하고 인증, 사용자, 사진, AI 매칭, 엽서,
알림과 안전 기능의 비즈니스 규칙을 담당합니다.

## 개발 환경

- Python 3.11 이상
- FastAPI
- Uvicorn
- Pydantic
- PyJWT
- SQLAlchemy 2.x + asyncpg + Alembic
- PostgreSQL 16
- Redis 7
- Docker Compose
- API 형식: REST + JSON, Base path `/v1`
- 인증: JWT Bearer Access Token + 회전형 Refresh Token
- 테스트: Pytest + FastAPI TestClient
- 코드 검사: Ruff

의존성 버전과 개발 도구는 [`pyproject.toml`](pyproject.toml)에서 관리합니다.

## 현재 구현 범위

- `GET /health`: 서버 프로세스 상태 확인
- `GET /ready`: PostgreSQL·Redis 연결 준비 상태 확인
- `POST /v1/auth/refresh`: Access/Refresh Token 재발급
- `POST /v1/auth/logout`: Bearer Access Token 검증 및 로그아웃 요청
- 공통 성공 응답: `data`, `error`
- 공통 오류 응답: `error.code`, `error.message`, `error.request_id`
- Refresh Token 회전 및 동일 토큰 재사용 방지

전체 목표 API와 데이터 계약은
[`docs/openapi/dalm-openapi.yaml`](docs/openapi/dalm-openapi.yaml)을 기준으로 합니다.

> 현재 Refresh Token 저장소는 단일 프로세스용 인메모리 구현입니다. 다중 인스턴스
> 배포 전 PostgreSQL 또는 Redis 기반 원자적 저장소로 교체해야 합니다.

## 프로젝트 구조

```text
DALM/
├── app/
│   ├── main.py              # FastAPI 앱과 라우트
│   ├── config.py            # 환경변수 및 실행 설정
│   ├── database.py          # SQLAlchemy 비동기 DB 연결
│   ├── cache.py             # Redis 비동기 연결
│   ├── dependencies.py      # 인증 등 FastAPI 의존성
│   ├── errors.py            # 공통 API 오류 응답
│   ├── schemas.py           # 요청·응답 Pydantic 모델
│   ├── tokens.py            # JWT 발급·검증·회전
│   └── token_store.py       # Refresh Token 저장소
├── alembic/                 # DB 마이그레이션
├── tests/                   # 단위·통합 테스트
├── docs/
│   ├── openapi/             # OpenAPI 및 Swagger UI
│   ├── notion-db-spec/      # DB·기능 명세
│   └── notion-dalm-spec-v2/ # 서비스 통합 명세
├── .github/                 # Pull Request 템플릿과 CI
├── compose.yaml             # API·PostgreSQL·Redis 개발 환경
├── Dockerfile              # FastAPI 컨테이너 이미지
├── CONTRIBUTING.md          # 상세 브랜치 및 협업 규칙
└── pyproject.toml           # 패키지·도구 설정
```

## 로컬 실행

### 1. 저장소 준비

```bash
git clone https://github.com/Team-DALM/DALM-Backend.git
cd DALM-Backend
git switch main
```

### 2. 가상환경과 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Windows PowerShell에서는 다음 명령으로 가상환경을 활성화합니다.

```powershell
.venv\Scripts\Activate.ps1
```

### 3. 환경변수 설정

```bash
cp .env.example .env
export DALM_JWT_SECRET='replace-with-at-least-32-random-characters'
```

| 환경변수 | 기본값 | 설명 |
|---|---:|---|
| `DALM_JWT_SECRET` | 없음 | JWT 서명 키, 최소 32자 필수 |
| `DALM_DATABASE_URL` | 로컬 PostgreSQL | SQLAlchemy 비동기 연결 URL |
| `DALM_REDIS_URL` | `redis://localhost:6380/0` | Redis 연결 URL |
| `DALM_ACCESS_TOKEN_TTL_SECONDS` | `1800` | Access Token 유효 시간(초) |
| `DALM_REFRESH_TOKEN_TTL_SECONDS` | `2592000` | Refresh Token 유효 시간(초) |

운영 환경에서는 예시 값을 사용하지 말고 Secret Manager 등 안전한 저장소에서 무작위
서명 키를 주입합니다. `.env` 파일은 Git에 커밋하지 않습니다.

### 4. API 서버 실행

```bash
uvicorn app.main:app --reload
```

- API 서버: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- 상태 확인: `http://localhost:8000/health`

## Docker Compose 실행

`.env.example`을 복사하고 JWT Secret을 변경한 뒤 전체 개발 환경을 실행합니다.

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api alembic upgrade head
```

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

- FastAPI: `localhost:8000`
- PostgreSQL: `localhost:5433`
- Redis: `localhost:6380`

호스트 포트는 `.env`의 `POSTGRES_PORT`와 `REDIS_PORT`로 변경할 수 있습니다.

로그와 종료 명령은 다음과 같습니다.

```bash
docker compose logs -f api
docker compose down
```

데이터 볼륨까지 삭제하려면 `docker compose down -v`를 사용합니다. 이 명령은 로컬
PostgreSQL과 Redis 데이터를 삭제하므로 필요한 데이터가 없는지 먼저 확인합니다.

## 데이터베이스 마이그레이션

```bash
alembic upgrade head
alembic revision --autogenerate -m "add users table"
alembic downgrade -1
```

마이그레이션 파일은 `alembic/versions/`에 커밋하며, 모델 변경 PR에 함께 포함합니다.

## 프론트엔드 연동

Flutter의 `.env`에 `/v1`을 포함한 Base URL을 설정합니다.

```dotenv
API_BASE_URL=http://localhost:8000/v1
```

Android Emulator에서 호스트의 로컬 서버에 접근할 때는 환경에 따라
`http://10.0.2.2:8000/v1`을 사용합니다. 실제 기기에서는 개발 PC의 LAN 주소와
방화벽 설정을 확인해야 합니다.

### 공통 응답

성공 응답은 다음 형식을 사용합니다.

```json
{
  "data": {},
  "error": null
}
```

오류 응답은 Flutter의 `ApiErrorDto`가 읽을 수 있는 형식을 사용합니다.

```json
{
  "data": null,
  "error": {
    "code": "AUTHENTICATION_FAILED",
    "message": "인증 토큰이 유효하지 않거나 만료되었습니다.",
    "request_id": "request-uuid"
  }
}
```

### 토큰 재발급

`POST /v1/auth/refresh`는 Access Token 인증 없이 호출합니다.

```json
{
  "refresh_token": "..."
}
```

성공하면 두 토큰을 모두 새 값으로 교체합니다.

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

- 보호 API에는 `Authorization: Bearer <access_token>` 헤더를 전송합니다.
- 로그인과 재발급 요청에는 기존 Access Token을 첨부하지 않습니다.
- 재발급 요청 자체가 401이면 무한 재시도하지 않고 저장된 두 토큰을 삭제합니다.
- 동시에 여러 요청이 401이어도 프론트는 재발급 요청을 한 번만 실행해야 합니다.

## 브랜치 및 PR 전략

DALM Backend는 `main`을 중심으로 한 Pull Request 흐름을 사용합니다. 이슈를 먼저
만든 다음 최신 `main`에서 이슈 번호를 포함한 작업 브랜치를 생성합니다.

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/12-kakao-login
```

- `main`에 직접 푸시하지 않습니다.
- 작업자는 `main` 대상 PR을 **Open** 상태로 생성합니다.
- PR 생성자는 임의로 병합하지 않고 사용자의 담당자 assign을 기다립니다.
- 담당자가 assign되면 검증 상태를 확인한 뒤 `main`에 **Squash and merge**합니다.
- PR 본문에 `Closes #<이슈번호>`를 작성하고 병합 후 작업 브랜치를 삭제합니다.

자세한 작업·검증·병합 절차는 [`CONTRIBUTING.md`](CONTRIBUTING.md)를 참고하세요.

## 커밋 규칙

| 타입 | 용도 |
|---|---|
| `feat` | 새로운 기능 |
| `fix` | 버그 수정 |
| `refactor` | 동작 변경 없는 구조 개선 |
| `docs` | 문서 변경 |
| `test` | 테스트 추가 또는 수정 |
| `chore` | 빌드, 설정, 의존성 변경 |

```text
feat: 카카오 로그인 API 구현
fix: Refresh Token 동시 재발급 방지
docs: 인증 API 연동 방법 추가
```

## 기본 검증

**모든 커밋 전에 `ruff check app tests alembic`를 최소 한 번 실행해야 합니다.**
PR 생성 전에는 테스트와 Ruff 검사를 모두 통과시킵니다.

```bash
ruff check app tests alembic
pytest -q
```

현재 인증 테스트는 다음 동작을 검증합니다.

- 정상 Refresh Token으로 새 토큰 쌍 발급
- 사용된 Refresh Token 재사용 차단
- Access Token을 이용한 재발급 차단
- 보호 API의 Bearer 인증
- 동시 재발급 시 한 요청만 성공
- DB·Redis readiness 성공 및 장애 시 503 응답

## 문서

- [OpenAPI 명세](docs/openapi/dalm-openapi.yaml)
- [Swagger 실행 안내](docs/openapi/README.md)
- [서비스 구조 및 전체 워크플로우](docs/notion-dalm-spec-v2/01-서비스-구조-및-전체-워크플로우.md)
- [DB 스키마 및 ERD](docs/notion-dalm-spec-v2/02-DB-스키마-및-ERD.md)
- [API 및 파트 간 인터페이스](docs/notion-dalm-spec-v2/05-API-및-파트간-인터페이스.md)
- [정책·예외·테스트 체크리스트](docs/notion-dalm-spec-v2/06-정책-예외-테스트-체크리스트.md)


# EC2 PostgreSQL 전체 이관

기존 운영 DB의 PostgreSQL 18과 pgvector를 지원하는 별도 Compose 프로젝트입니다.
API 배포와 독립적으로 실행하며 DB 포트를 호스트나 인터넷에 공개하지 않습니다.
기존 앱 네트워크에서만 `postgres:5432`로 연결합니다.

## 준비

- EC2 디스크와 메모리, 원본의 서버 버전·확장 기능·전체 테이블을 확인합니다.
- 이 디렉터리를 체크아웃 밖의 root 전용 운영 디렉터리로 복사합니다.
- `secrets/`를 mode 700으로 만들고 무작위 관리자 비밀번호를
  `secrets/postgres_password`에 mode 600으로 저장합니다. 파일은 커밋하지 않습니다.
- `docker compose up -d --wait`로 시작합니다. PostgreSQL 18의 데이터 볼륨은
  `/var/lib/postgresql`에 마운트합니다. `down -v`는 사용하지 않습니다.
- 앱 전용 `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE` 역할을 별도로 생성합니다.
  앱에 관리자 자격 증명을 제공하지 않습니다.

## 복사와 검증

1. 원본의 직접 연결 URL을 사용합니다. Neon의 `-pooler` 연결은 사용하지 않습니다.
2. PostgreSQL 18의 `pg_dump --format=custom --no-owner --no-acl`로 전체 DB를
   mode 600 파일에 백업합니다. 비밀번호는 프로세스 인자가 아닌 환경으로 전달합니다.
3. 앱 역할이 소유한 새 DB에 `pg_restore --no-owner --no-acl --exit-on-error`로
   복원합니다. `vector` 확장은 관리자가 미리 생성하고 복원 목록의 해당 확장 생성·주석
   항목만 제외합니다. 그 외 테이블·데이터·시퀀스·인덱스·제약은 모두 복원합니다.
4. 테이블별 정확한 건수와 전체 행 내용 해시, 시퀀스 상태, Alembic revision,
   pgvector 및 사진 storage_key를 원본과 대조합니다. 개인정보 행은 로그에 출력하지 않습니다.
5. 복원 DB에서 Alembic head와 앱 읽기·쓰기·트랜잭션 rollback을 검증합니다.

## 최종 전환

`migrate_postgres.py`는 root로 실행하는 2단계 도구입니다. 기본 실행은 `prepare`로,
비공개 DB를 시작하고 시험 복원·전체 데이터 비교까지만 수행합니다.
`MIGRATION_PHASE=cutover python3 /PATH/migrate_postgres.py`는 위 검증을 마친 뒤
명시적으로 전체 이관을 요청받은 경우에만 실행합니다. 운영 파일은
`/var/lib/dalm/db-migration`에 mode 600으로 보관하고 체크아웃에 저장하지 않습니다.
원본 DB의 read-only 설정은 모든 기존 앱에 영향을 줍니다. 실패 시 보호된 진단 파일과
원본 설정을 확인해 복구하며, 원본 쓰기 재개와 AWS 쓰기가 동시에 발생하지 않게 합니다.

- 자동 배포를 잠시 중지하고 원본에 쓰는 모든 앱·작업자의 쓰기를 중단합니다.
- 원본 DB의 기존 read-only 설정을 기록한 뒤 새 연결의 기본 트랜잭션을 read-only로
  바꾸고 남아 있는 쓰기 연결을 종료합니다. 이후 원본은 참조용으로 보존합니다.
- 최종 백업으로 **새로운** 대상 DB에 복원하고 같은 검증을 반복합니다.
- 보호된 `deploy/aws/.env`의 `DALM_DATABASE_URL`을 앱 역할의 내부 주소로 변경합니다.
  예: `postgresql+asyncpg://dalm:PASSWORD@postgres:5432/NEW_DATABASE?ssl=disable`.
  PostgreSQL은 포트를 공개하지 않고 같은 호스트의 Docker 네트워크에서만 접근합니다.
- 앱을 재생성해 `/ready`, 인증되지 않은 API의 401 응답, 기존 데이터 읽기를 확인합니다.
- 자동 배포를 다시 시작하고 외부 백업 및 복원 점검을 운영 일정에 포함합니다.

실패 시 원본 DB 설정과 앱 환경 파일을 복구합니다. 새 DB에 사용자 쓰기가 발생한 뒤에는
원본으로 바로 되돌리지 말고 변경 데이터를 먼저 보존·동기화합니다. 원본 DB와 백업은
검증 없이 삭제하지 않습니다. Redis와 사진 저장소는 이 DB 이관과 별개입니다.

참고: [PostgreSQL pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html),
[pgvector Docker](https://github.com/pgvector/pgvector#docker).

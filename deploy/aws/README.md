# 학교 AWS 이관 실행서

학교 계정의 정책에 따라 HTTP로 공개하는 EC2 배포 구성입니다. 기존 리소스 삭제는
자동 실행하지 않습니다. 현재 확인된 가이드는 아래와 같습니다.

- 서울 `ap-northeast-2`, EC2 `t3.nano`~`t3.small`만 허용.
- EC2에는 `SafeInstanceProfile-gachon-20` 연결. 액세스 키 발급 금지.
- S3 버킷 이름은 `gachon-20`으로 시작.
- EIP는 생성한 인스턴스 ID를 조교에게 전달하면 직접 부착.
- 조교 메일에 HTTPS/Route53 불허. HTTP 80 공개 시 토큰과 API 데이터는 전송 중
  암호화되지 않습니다. EIP는 주소 고정용이며 HTTP 접속의 필수 조건은 아닙니다.

출처: [학교 가이드](https://rowan-cupboard-1fe.notion.site/AWS-Management-Console-Credentials-Detailed-gachon-3f92156ceb5f8020a3a8c26a8da440c2).
가이드의 최초 비밀번호 변경과 MFA는 사용자가 직접 완료합니다.

## 1. 먼저 확보할 정보

- 학교 콘솔 로그인 및 MFA, 사용 가능한 VPC/subnet/security group.
- 기존 DB의 직접 연결 URL, GCS 버킷과 읽기 권한, Redis 운영 방식과 연결 정보.
- 기존 JWT secret, internal API key, Apple client IDs. 값은 Git/PR/로그에 남기지 않습니다.
- S3 생성/객체 접근 권한. 역할 이름만으로 실제 권한을 보장할 수 없습니다.
- 현재 퍼블릭 IP와 클라이언트 배포 담당자. EIP는 조교가 부착합니다.

## 2. EC2 준비

학교 콘솔에서 Ubuntu 24.04 x86_64, t3.small, 암호화 EBS로 생성합니다.
디스크 크기는 실제 데이터와 백업 용량 확인 후 결정합니다. 학교가 허용한 기본 VPC를
사용하고 인스턴스 프로필을 연결합니다. IMDSv2 required 및 **hop limit 2**로 설정해
Docker 컨테이너에서도 인스턴스 역할을 사용할 수 있도록 합니다.

보안 그룹은 관리자의 IP에서만 SSH 22를 허용합니다. SSM을 쓰려면 역할의 SSM 권한과
Agent 연결부터 확인합니다. DB/Redis/8000 포트를 인터넷에 개방하지 않습니다.
API는 기본적으로 localhost에만 바인딩됩니다. 테스트는 SSH 터널로 진행합니다.

```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@INSTANCE_IP
curl --fail http://127.0.0.1:8000/ready
```

EC2에서 [Docker 공식 Ubuntu 설치 절차](https://docs.docker.com/engine/install/ubuntu/)로
Engine과 Compose plugin, git, curl을 설치합니다. 재부팅 시 Docker가 자동 시작되도록
설정하고 `docker info`, `docker compose version`을 확인합니다. 운영자에게 Docker 실행
권한이 필요합니다. 개인 GitHub 토큰을 서버 디스크에 저장하지 말고 검증한 커밋의 소스를
전송하거나 읽기 전용 저장소 접근을 사용합니다.

## 3. 사진 저장소

`gachon-20-dalm-<고유 suffix>` 비공개 S3 버킷을 서울에 생성합니다. Block Public Access
전체 활성화, 기본 암호화, 버전 관리를 사용합니다. 인스턴스 역할에 해당 버킷의
`photos/*`에 대한 `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`가 필요합니다.
학교 권한으로 불가능하면 조교에게 해당 범위만 요청합니다. IAM 사용자를 새로 만들거나
액세스 키를 발급하지 않습니다.

`DALM_S3_BUCKET` 설정 시 S3를 우선 사용하며 미설정이면 기존 GCS 동작을 유지합니다.
새 환경에서 GCS는 Cloud Run 서비스 계정이 자동 상속되지 않습니다. S3 전환 전 모든
기존 GCS 객체를 **동일한 key**로 복사하고 건수/크기 및 샘플 해시를 검증합니다.
원본은 삭제하지 않습니다. SDK의 조건부 업로드로 같은 key 덮어쓰기를 막고 조회는
짧은 수명의 presigned GET URL만 제공합니다.

## 4. DB와 Redis 보존

첫 EC2 검증은 기존 PostgreSQL을 유지할 수 있습니다. `DALM_DATABASE_URL`을 기존 운영
URL로 설정하되 실제 운영 DB에 migration을 실행하기 전 백업과 변경 내용을 확인합니다.
DB를 RDS PostgreSQL로 옮길 경우 학교가 허용하는 엔진/버전에서 `vector` extension
사용 가능 여부를 먼저 확인합니다. RDS 네트워크 접근은 EC2만 허용합니다. 가이드에서
public access를 요구해도 5432를 전체 인터넷에 개방하지 않습니다.

검증용 새 DB에서 PostgreSQL 도구의 `pg_dump --format=custom --no-owner --no-acl` 및
`pg_restore --no-owner --no-acl --exit-on-error`로 복원 시험 후 테이블별 건수, Alembic
revision, vector extension, 사진 storage_key를 대조합니다. 복원된 DB에
`alembic upgrade head`를 실행합니다. URL은 SQLAlchemy의 `+asyncpg` URL이 아닌
PostgreSQL 도구용 URL로 변환하고 비밀번호는 안전한 PGPASSFILE로 전달합니다.

실제 전환은 쓰기를 중지하고 최종 DB dump/restore와 GCS 증분 복사를 완료한 후 합니다.
공존 중 양쪽 서버가 서로 다른 DB에 쓰지 않게 합니다. Redis refresh-token 데이터를
옮기지 않으면 기존 사용자는 재로그인이 필요합니다. 이를 유지하려면 기존 Redis를
계속 쓰도록 `.env`의 `DALM_REDIS_URL`에 기존 URL을 설정하거나 쓰기 중지 상태에서 호환 RDB/AOF
백업/복원 후 회전/재사용 차단을 검증합니다. Redis 키를 문서나 PR에 출력하지 않습니다.

## 5. 릴리스 실행

```bash
cp deploy/aws/.env.example deploy/aws/.env
chmod 600 deploy/aws/.env
# 기존 운영 secret, 검증된 DB URL, 실제 S3 bucket, Apple ID로 파일 편집
bash deploy/aws/deploy.sh
```

배포 스크립트는 현재 커밋 SHA로 이미지를 빌드하고 Redis 준비 → migration 성공 → API
준비를 순서대로 확인합니다. 기존 앱의 mock inline validation 동작을 유지하며 별도
AI worker를 자동 실행하지 않습니다. 실제 임베딩 worker/만료 스케줄은 기존 실행 현황을
확인한 후 별도로 옮기며 중복 실행을 피합니다.

상태와 로그:

```bash
cd deploy/aws
docker compose ps
docker compose logs --tail=100 api
```

EBS 단일 서버 장애에 대비해 Redis와 DB의 외부 백업/복원 점검을 운영 일정에 포함합니다.
`docker compose down -v`는 운영 데이터 볼륨을 삭제하므로 사용하지 않습니다.

## 6. 전환 조건과 되돌리기

다음 항목을 확인한 뒤 Flutter API_BASE_URL을 HTTP 진입점으로 전환합니다.

- `/health`, `/ready` 성공, Kakao/Apple 로그인과 refresh/logout 성공.
- 새 사진 업로드/조회/삭제 및 기존 사진 조회 성공, 공개 S3 접근 거부.
- DB/Redis 비공개 접근, 재부팅 후 자동 복구, 백업 복원 확인.
- HTTP 80 외부 접속과 앱의 해당 호스트 HTTP 허용 설정 확인. EIP 부착 후에는 고정 주소로 갱신.
- 운영 쓰기를 중지한 뒤 최종 동기화, 구 서버의 쓰기/worker 중지 확인.

코드 롤백은 이전 SHA checkout 후 재배포하되 migration의 이전 코드 호환성을 먼저 확인합니다.
DB를 새로 옮긴 후 쓰기가 발생했다면 단순히 Cloud Run으로 주소만 되돌리면 데이터가
유실됩니다. 다시 쓰기를 중지하고 새 DB의 변경 데이터를 원본에 동기화한 뒤 되돌립니다.
기존 DB/버킷/Cloud Run은 복구 기간과 데이터 정합성을 확인한 뒤 별도 승인으로 정리합니다.

GitHub Actions는 CI만 수행합니다. 기존 GCP 배포 job과 배포 인증은 사용하지 않습니다.
AWS 자동 배포 설치 절차는 아래와 같습니다.

AWS 근거: [조건부 객체 쓰기](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html),
[임시 조회 URL](https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html),
[SSM 인스턴스 권한](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-instance-profile.html).


## 7. HTTP 공개와 자동 배포

SSM에서 아래 명령으로 Nginx gateway를 실행합니다. API 8000은 계속 localhost 전용입니다.
Nginx는 사진 업로드를 위해 12MiB 요청을 허용하며 `/internal/` 경로는 외부에서 404입니다.

```bash
cd /opt/dalm/backend/deploy/aws
sudo docker compose up -d --wait nginx
curl --fail http://127.0.0.1/ready
```

학교 가이드대로 보안 그룹의 자동 `username` 태그를 확인한 뒤 TCP 80을 허용합니다.
DB/Redis/8000/SSH는 추가 개방하지 않습니다. 외부에서 `/health`, `/ready`, `/docs`와
비인증 보호 API의 401을 확인합니다. 클라이언트에는 `http://현재IP/v1/`을 전달합니다.

```bash
sudo bash /opt/dalm/backend/deploy/aws/install-ops.sh
```

5분마다 public GitHub의 main을 확인하고 **해당 SHA의 push CI 전체 성공**을 확인한 뒤
배포합니다. AWS 액세스 키나 GitHub 토큰을 서버에 저장하지 않습니다. 로컬 수정이 있거나
main에 AWS 배포 코드가 아직 병합되지 않았으면 건너뜁니다. 배포는 파일 잠금으로 직렬화하며
성공한 이미지 SHA를 `.env`에 기록해 재부팅 후에도 동일한 버전을 사용합니다.

```bash
systemctl list-timers dalm-deploy.timer
journalctl -u dalm-deploy.service --no-pager -n 30
```

## 8. 선택적 백업·복원 검증

DB 전체 복사에 대한 승인을 받은 경우에만 실행합니다. 기본 설치에서는 백업 timer를
활성화하지 않습니다. 운영 DB를 변경하거나 Redis 세션을 초기화하지 않습니다.

```bash
sudo python3 /opt/dalm/backend/deploy/aws/backup.py --upload
```

덤프는 mode 600으로 저장하고 네트워크가 차단된 임시 pgvector PostgreSQL 18에 복원하여
Alembic revision과 vector extension을 확인합니다. 복원이 성공한 덤프만 인스턴스 역할로
비공개 S3의 `backups/postgres/`에 저장하고 다시 읽어 SHA256을 대조합니다.
S3에 별도 백업 버킷을 쓰려면 `.env`의 `DALM_BACKUP_S3_BUCKET`을 설정합니다.

서버의 PostgreSQL major 버전이 변경되면 pg_dump/복원 이미지의 버전도 맞춰야 합니다. 장기 운영의
백업 주기와 보존 정책은 데이터 승인 범위를 확정한 뒤 설정합니다. 구 서버/버킷/운영 DB를
삭제하는 작업은 이 스크립트에 포함되지 않습니다.

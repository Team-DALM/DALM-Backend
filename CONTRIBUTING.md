# DALM Backend 기여 가이드

## 작업 흐름

DALM Backend는 `main`을 중심으로 한 Pull Request 흐름을 사용합니다.

1. 작업 내용을 백엔드 GitHub 이슈로 생성합니다.
2. 최신 `main`에서 작업 브랜치를 분기합니다.
3. 구현·문서·테스트를 완성합니다.
4. **커밋 전 Ruff를 최소 한 번 실행합니다.**
5. 커밋과 푸시 후 `main` 대상 PR을 `Open` 상태로 생성합니다.
6. PR 작업자는 병합하지 않고 사용자의 담당자 assign을 기다립니다.
7. 담당자가 assign되면 검증 결과를 확인하고 `main`에 Squash Merge합니다.
8. 병합된 작업 브랜치를 삭제합니다.

## 브랜치 이름

```text
feature/12-kakao-login
fix/18-refresh-token-race
refactor/24-token-store
docs/31-api-guide
chore/35-ci
```

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/<issue-number>-<description>
```

## 커밋 전 필수 검증

모든 커밋 전에 아래 Ruff 명령을 최소 한 번 실행합니다.

```bash
ruff check app tests alembic
```

Ruff가 실패하면 문제를 수정하고 다시 실행해 통과한 후 커밋합니다.
코드를 변경했다면 PR 생성 전에 테스트도 실행합니다.

```bash
pytest -q
```

## PR 생성과 담당자 지정

- Base 브랜치는 항상 `main`으로 설정합니다.
- PR 본문에 변경 내용, 검증 결과, `Closes #<번호>`를 작성합니다.
- PR은 `Open` 상태로 유지하고 생성자가 임의로 merge하지 않습니다.
- 사용자가 GitHub에서 담당자를 assign하는 것을 병합 승인 신호로 사용합니다.
- assign 후 테스트와 Ruff 결과를 확인하고 **Squash and merge**합니다.
- 병합 후 원격 작업 브랜치를 삭제합니다.

## 커밋과 PR 제목

- `feat`: 기능 추가
- `fix`: 버그 수정
- `refactor`: 동작 변경 없는 구조 개선
- `test`: 테스트
- `docs`: 문서
- `chore`: 설정과 유지보수

PR은 한 가지 목적만 포함합니다.


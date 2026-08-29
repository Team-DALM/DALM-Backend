# DALM Backend 기여 가이드

## 브랜치 전략

DALM Backend는 Git Flow를 사용합니다.

| 브랜치 | 역할 | 분기 기준 | 병합 대상 |
|---|---|---|---|
| `main` | 운영 배포 가능한 코드 | - | - |
| `develop` | 다음 릴리스의 통합 개발 코드 | `main` | `release/*` |
| `feature/*` | 기능 및 일반 작업 | `develop` | `develop` |
| `release/*` | 릴리스 검증과 버전 준비 | `develop` | `main`, 이후 `develop` 동기화 |
| `hotfix/*` | 운영 긴급 수정 | `main` | `main`, 이후 `develop` 동기화 |

`feature/*`, `release/*`, `hotfix/*`는 작업이 끝나면 삭제합니다. 장기간 유지하는
브랜치는 `main`과 `develop`뿐입니다.

## 브랜치 이름

이슈 번호와 작업 내용을 포함합니다.

```text
feature/12-kakao-login
fix/18-refresh-token-race
release/1.0.0
hotfix/1.0.1-auth-failure
```

일반 버그 수정은 `feature/*`와 동일하게 `develop`에서 `fix/*`로 분기하고
`develop`으로 병합합니다. 운영 긴급 수정에만 `hotfix/*`를 사용합니다.

## 기능 개발

```bash
git switch develop
git pull --ff-only origin develop
git switch -c feature/<issue-number>-<description>
```

작업이 끝나면 원격에 푸시하고 `develop`을 대상으로 Pull Request를 만듭니다.

```bash
git push -u origin feature/<issue-number>-<description>
```

- 이슈를 먼저 생성하고 PR 본문에 `Closes #<번호>`를 작성합니다.
- CI가 통과하고 최소 1명이 승인한 뒤 병합합니다.
- 병합 방식은 **Squash and merge**만 사용합니다.
- `main`과 `develop`에 직접 푸시하지 않습니다.

## 릴리스

1. `develop`에서 `release/<version>`을 분기합니다.
2. 릴리스 브랜치에서는 버전, 문서, 배포 차단 버그만 수정합니다.
3. 검증 후 `main` 대상 PR을 Squash 병합합니다.
4. `main` 병합 커밋에 `v<version>` 태그를 생성합니다.
5. 릴리스 중 발생한 수정이 있다면 `develop`에도 다시 병합합니다.

```bash
git switch develop
git switch -c release/1.0.0
git push -u origin release/1.0.0

git switch main
git pull --ff-only origin main
git tag -a v1.0.0 -m "DALM Backend v1.0.0"
git push origin v1.0.0
```

## 긴급 수정

1. `main`에서 `hotfix/<version>-<description>`을 분기합니다.
2. 수정 및 검증 후 `main` 대상 PR을 생성합니다.
3. 배포 태그를 생성합니다.
4. 같은 수정이 누락되지 않도록 `develop` 대상 PR도 생성합니다.

## 커밋과 PR

커밋과 PR 제목은 다음 접두사를 사용합니다.

- `feat`: 기능 추가
- `fix`: 버그 수정
- `refactor`: 동작 변경 없는 구조 개선
- `test`: 테스트
- `docs`: 문서
- `chore`: 설정과 유지보수

PR은 한 가지 목적만 포함하고, 변경 이유·검증 방법·관련 이슈를 반드시 기록합니다.


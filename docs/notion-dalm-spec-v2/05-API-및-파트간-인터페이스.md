# 05. API 및 파트 간 인터페이스

## 1. API 공통 규칙

- Base path: `/v1`
- 인증: `Authorization: Bearer {access_token}`
- 시간: ISO 8601 UTC
- ID: UUID 문자열
- 목록: Cursor Pagination
- 내부 오류·스택 트레이스는 노출하지 않음

### 성공

```json
{
  "data": {},
  "error": null
}
```

### 실패

```json
{
  "data": null,
  "error": {
    "code": "PHOTO_NOT_FOUND",
    "message": "사진을 찾을 수 없습니다.",
    "request_id": "request-uuid"
  }
}
```

---

## 2. 주요 Endpoint

### 인증·사용자

| Method | Path | 기능 |
|---|---|---|
| POST | `/auth/kakao` | 카카오 로그인 |
| POST | `/auth/refresh` | 토큰 재발급 |
| POST | `/auth/logout` | 로그아웃 |
| POST | `/users/onboarding` | 약관·프로필 생성 |
| GET | `/users/me` | 내 프로필 |
| PATCH | `/users/me` | 프로필 수정 |
| DELETE | `/users/me` | 회원 탈퇴 |

### 사진·매칭

| Method | Path | 기능 |
|---|---|---|
| GET | `/photos/today` | 오늘 활성 사진·등록 가능 여부 |
| POST | `/photos` | 사진 등록 및 검사 시작 |
| GET | `/photos/{photo_id}` | 사진 상태·상세 |
| DELETE | `/photos/{photo_id}` | 탐색 중·만료 사진 삭제 |
| GET | `/moments?status=` | 상태별 순간 목록 |
| GET | `/matches/{match_id}` | 매칭 결과 |
| PATCH | `/matches/{match_id}/visibility` | 내 목록 숨김·복원 |

### 엽서·알림·안전

| Method | Path | 기능 |
|---|---|---|
| POST | `/matches/{match_id}/postcards` | 엽서 발송 |
| GET | `/postcards/received` | 받은 엽서 |
| GET | `/postcards/sent` | 보낸 엽서 |
| PATCH | `/postcards/{id}/read` | 읽음 처리 |
| DELETE | `/postcards/{id}` | 내 엽서함에서 삭제 |
| GET | `/notifications` | 알림 목록 |
| PATCH | `/notifications/{id}/read` | 알림 읽음 |
| PATCH | `/notifications/read-all` | 전체 읽음 |
| POST | `/device-tokens` | FCM 토큰 등록 |
| GET/PATCH | `/notification-settings` | 알림 설정 |
| POST | `/blocks/{user_id}` | 사용자 차단 |
| DELETE | `/blocks/{user_id}` | 차단 해제 |
| GET | `/blocks` | 차단 목록 |
| POST | `/reports` | 신고 |

---

## 3. 사진 등록 응답

```http
POST /v1/photos
Content-Type: multipart/form-data
```

```json
{
  "data": {
    "photo_id": "photo-uuid",
    "status": "VALIDATING",
    "registered_at": "2026-08-15T03:10:00Z"
  },
  "error": null
}
```

---

## 4. 오늘 사진 조회 응답

```json
{
  "data": {
    "can_register": false,
    "photo": {
      "id": "photo-uuid",
      "image_url": "signed-url",
      "ai_title": "비가 그친 골목의 빛",
      "status": "SEARCHING",
      "registered_at": "2026-08-15T03:10:00Z",
      "search_expires_at": "2026-08-22T03:10:00Z",
      "remaining_days": 7
    }
  },
  "error": null
}
```

`remaining_days`는 표시 편의를 위해 제공할 수 있지만, Flutter는 이를 영구 상태로 저장하지 않는다.

---

## 5. AI 적합성 검사 계약

### Backend → AI

```json
{
  "job_id": "validation-job-uuid",
  "photo_id": "photo-uuid",
  "storage_key": "users/user-id/photos/photo-id.jpg",
  "checks": [
    "QUALITY",
    "SCREENSHOT",
    "TEXT_DOMINANT",
    "QR_BARCODE",
    "SENSITIVE_INFORMATION",
    "SAFETY",
    "ADVERTISEMENT"
  ]
}
```

### AI → Backend: 통과

```json
{
  "job_id": "validation-job-uuid",
  "status": "PASSED",
  "scores": {
    "quality": 0.91,
    "safety": 0.99
  },
  "model_name": "dalm-validator",
  "model_version": "1.0.0",
  "processing_time_ms": 820
}
```

### AI → Backend: 거절

```json
{
  "job_id": "validation-job-uuid",
  "status": "REJECTED",
  "rejection_code": "TOO_BLURRY",
  "model_name": "dalm-validator",
  "model_version": "1.0.0"
}
```

---

## 6. 특징 추출 계약

```json
{
  "photo_id": "photo-uuid",
  "ai_title": "비가 그친 골목의 빛",
  "vectors": {
    "scene": [0.12, -0.08],
    "object_action": [0.31, 0.22],
    "composition": [-0.10, 0.54],
    "color": [0.75, 0.11],
    "mood": [0.43, 0.38]
  },
  "labels": {
    "scene": ["alley", "evening"],
    "objects": ["umbrella", "road"],
    "mood": ["calm"]
  },
  "model_name": "dalm-encoder",
  "model_version": "1.0.0"
}
```

실제 벡터 차원은 AI 파트와 확정한다. 문서 예시는 축약된 값이다.

---

## 7. 후보 재정렬 계약

### 요청

```json
{
  "source_photo_id": "photo-a",
  "candidate_photo_ids": ["photo-b", "photo-c"]
}
```

### 응답

```json
{
  "source_photo_id": "photo-a",
  "candidates": [
    {
      "photo_id": "photo-b",
      "final_score": 0.84,
      "scores": {
        "scene": 0.88,
        "object_action": 0.76,
        "composition": 0.83,
        "color": 0.91,
        "mood": 0.79
      },
      "explanation_factors": ["scene", "color", "composition"],
      "explanation": "두 사진 모두 비가 그친 저녁 골목을 담고 있어요."
    }
  ],
  "model_name": "dalm-reranker",
  "model_version": "1.0.0"
}
```

---

## 8. Flutter 공개 상태 모델

| 서버 상태 | Flutter 동작 |
|---|---|
| `VALIDATING` | 적합성 검사 로딩 화면 |
| `REJECTED` | 사유와 다시 선택·촬영 버튼 |
| `SEARCHING` | 진행선과 남은 기간 |
| `MATCHED` | 매칭 결과 진입 버튼 |
| `EXPIRED` | 지나간 순간 안내 |
| `DELETED` | 목록에서 제거 또는 삭제 안내 |

---

## 9. 오류 코드

| 코드 | HTTP | 재시도 | 의미 |
|---|---:|---:|---|
| `TODAY_PHOTO_ALREADY_EXISTS` | 409 | N | 오늘 활성 사진 존재 |
| `PHOTO_NOT_FOUND` | 404 | N | 사진 없음 |
| `PHOTO_NOT_OWNED` | 403 | N | 사진 소유권 없음 |
| `INVALID_ASPECT_RATIO` | 422 | N | 4:5 비율 아님 |
| `IMAGE_TOO_SMALL` | 422 | N | 최소 해상도 미달 |
| `IMAGE_TOO_LARGE` | 413 | N | 용량 초과 |
| `UNSUPPORTED_IMAGE_FORMAT` | 415 | N | 지원하지 않는 MIME |
| `VALIDATION_TEMPORARILY_FAILED` | 503 | Y | 적합성 검사 장애 |
| `PHOTO_ALREADY_MATCHED` | 409 | N | 이미 매칭된 사진 |
| `SEARCH_PERIOD_EXPIRED` | 409 | N | 탐색 기간 종료 |
| `POSTCARD_ALREADY_SENT` | 409 | N | 이미 엽서 발송 |
| `POSTCARD_ORDER_NOT_ALLOWED` | 409 | N | 현재 발송 순서가 아님 |
| `USER_BLOCKED` | 403 | N | 차단 관계 |

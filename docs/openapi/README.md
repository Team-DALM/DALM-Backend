# DALM Swagger

## 파일

- `dalm-openapi.yaml`: OpenAPI 3.1 API 명세
- `swagger-ui.html`: 로컬 Swagger UI

## Swagger UI 실행

브라우저의 로컬 파일 보안 정책 때문에 HTML 파일을 직접 열지 말고 이 디렉터리에서 정적 서버를 실행한다.

```bash
python3 -m http.server 8080
```

그다음 아래 주소로 접속한다.

```text
http://localhost:8080/swagger-ui.html
```

### macOS에서 `PermissionError: Operation not permitted`가 발생하는 경우

Python이 Documents 폴더의 현재 경로를 읽지 못하는 macOS 권한 문제일 수 있다. `sudo`를 사용하지 말고 파일을 임시 폴더로 복사해 실행한다.

```bash
mkdir -p /tmp/dalm-swagger
cp docs/openapi/dalm-openapi.yaml /tmp/dalm-swagger/
cp docs/openapi/swagger-ui.html /tmp/dalm-swagger/
cd /tmp/dalm-swagger
python3 -m http.server 8080
```

이미 8080 포트를 사용 중이라면 `8081`로 변경한다.

```bash
python3 -m http.server 8081
```

이 경우 접속 주소도 `http://localhost:8081/swagger-ui.html`로 변경한다.

## Swagger Editor 사용

`dalm-openapi.yaml`의 전체 내용을 Swagger Editor에 붙여넣어 확인할 수 있다.

## FastAPI 적용

FastAPI는 코드에서 OpenAPI 문서를 자동 생성한다. 실제 구현 시 이 명세의 다음 항목을 기준으로 라우터와 Pydantic 모델을 작성한다.

- Path와 HTTP Method
- Request/Response Schema
- HTTP Status Code
- Error Code
- JWT 인증 여부

구현이 시작되면 CI에서 FastAPI가 생성한 `/openapi.json`과 이 기준 명세의 차이를 검사하는 방식을 권장한다.

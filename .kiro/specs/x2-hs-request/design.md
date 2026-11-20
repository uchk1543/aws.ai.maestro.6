# Design Document

## Overview

```
GET /api/jobs/{id}/hs-request → 작업·서류 기록을 읽어 → tools/hs_request.py → PDF 바이트 → 응답
```

검수 완료서(X1 #258, `tools/certificate.py`)와 같은 구조다. 새 의존성·새 리소스가 없다.

| 대안 | 고르지 않은 이유 |
|---|---|
| `notice_document`(2번 소유)에 HS 칸을 더함 | 마크다운·HTML 통지 문서와 PDF 요청서는 받는 사람과 내용이 다르다. 2번 파일을 건드리지 않는다 |
| 모델이 제품 정보를 추론해 채움 | 서류에 없는 재질·용도를 지어낼 위험. 규칙: 도구 결과에 없는 내용은 쓰지 않는다. 요청 목록으로 대신한다 |
| 승인 때 PDF를 만들어 S3에 저장 | 정책 변경과 presigned URL이 필요하다. 문서가 작아 요청할 때 만들어도 1초 안이다 |

## Architecture

### `tools/hs_request.py` (새 파일, PM)
- `pending_hs(job)`: 상태가 '사람 확인 필요'인 품목.
- `check_requestable(job)`: 미확정이 없으면 `NothingToRequest`(API가 409로 바꿈).
- `make_hs_request(job, docs, *, importer=None, now=None) -> bytes`:
  1. 화물 정보 표 (서류에서 첫 값: B/L 번호, 송장 번호, 수입자, 수출자, 원산지, 거래 조건)
  2. 품목마다 서류별 값 표(같은 행 번호를 가진 서류의 줄), 후보 표, 사유 목록. 블록은 쪽이 갈라지지 않게 `KeepTogether`
  3. 제품 정보 요청 목록 (고정 문장)
- `reasons(h, rows)`: 저장된 값만으로 판단. 서류 HS 숫자만 비교한다 (`9401.61` → `940161`).
- 글꼴·글자 정리는 `tools/declaration.py`의 `_register_fonts`, `_show`(이스케이프·길이 제한)를 가져다 쓴다.
- 같은 입력은 같은 PDF다: `invariant=1`, `now`를 인자로 받아 시험이 고정한다. 체크 표시는 나눔고딕에 ☐ 글자가 없어 `[  ]`로 쓴다.

### API (`api/handler.py`, 4번)
`job_hs_request(job_id)`: 404 → 409(`NothingToRequest`) → PDF(`_pdf_response`, 검수 완료서와 공용) / 500. 서류 기록이 없으면 `docs=[]`로 만든다.

### 화면 (`web/`, 3번)
`HsPicker`의 미확정 품목이 있을 때 `hs-actions` 맨 위에 링크 `hsRequestUrl(jobId)`와 "관세사에게 전달할 문서입니다 (품목 N개)". 승인 대기가 아니어도 보인다.

## 시험 (`tests/unit/test_hs_request.py`, AWS·Bedrock 호출 없음)
식별 번호·값·후보·요청 목록이 글자로 읽힘, 확정 품목은 빠짐, 같은 입력 같은 바이트, 사유 5종과 일반 문장, 서류 행이 없는 품목, 미확정 없음은 `NothingToRequest`, 품목 40개가 쪽을 넘어도 전부 포함, 서류 글자의 `<b>`·`<img>`가 해석되지 않음, API 200·404·409·500·서류 기록 없음.
`web`: 링크 보임·숨김.

## 배포
`deploy.sh`(API Lambda)와 `deploy-web.sh`. `create.sh`·infra 변경 없음. 배포 뒤 HS 미확정 작업에서 PDF를 받아 열어 보고 CloudFront를 거친 응답이 깨지지 않는지 확인한다.

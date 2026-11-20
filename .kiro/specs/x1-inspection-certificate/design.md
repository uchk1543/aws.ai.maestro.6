# Design Document

## Overview

승인으로 등록된 작업의 저장된 결과를 코드가 PDF로 옮긴다. 새 리소스는 없다. 흐름은 한 줄이다.

```
승인 (POST /approve) → wms.approver·approved_at 저장
내려받기 (GET /jobs/{id}/certificate) → 작업·서류 기록을 읽어 → tools/certificate.py → PDF 바이트 → 응답
```

대안과 고른 이유:

| 대안 | 고르지 않은 이유 |
|---|---|
| LaTeX, 헤드리스 브라우저 | 패키지가 수백 MB~GB라 Lambda 제한(압축 해제 250MB)과 맞지 않는다. 컨테이너 이미지·ECR이 필요해 PM 작업이 늘어난다 |
| 승인 때 PDF를 만들어 S3에 저장 | 버킷 쓰기 정책 변경(infra)과 presigned URL이 필요하다. 문서가 작아 GET 때 만들어도 1초 안이다 |
| 모델로 문장 작성 | 팀 규칙: 문서 칸 채우기는 코드가 한다. 근거 없는 문장이 들어갈 위험 |
| `reportlab` + 저장소의 나눔고딕 | 선택. 이미 의존성이고 신고서 PDF(`render_declaration_pdf`, #251)가 같은 방식으로 쓴다. 새 의존성·`uv.lock` 변경 없음 |

## Architecture

### 데이터 (`tools/models.py` 하나에만 추가, 공용 파일)

`WmsState`에 두 칸을 더한다. 둘 다 기본 null이라 옛 작업 줄도 읽힌다.

```python
class WmsState(_Strict):
    status: WmsStatus
    by: WmsBy | None = None
    wms_id: str | None = None
    approver: str | None = Field(default=None, description="검수자 이름(사람 승인일 때). 자동 등록·승인 대기는 null")
    approved_at: str | None = Field(default=None, description="승인 시각, 한국 시간 ISO 8601(+09:00). 사람 승인일 때만")
```

- `docs/schema.md`(약속 2 wms), `docs/examples/job_waiting_approval.json`(예시는 승인 대기라 null)도 같은 PR에서 고친다.
- `tests/unit/test_contracts.py`에 새 함수 약속을 더한다 (`make_certificate`).

### 승인 때 저장 (`api/handler.py` approve, 4번)

- 기존 `approve`가 WMS 등록에 성공하면 `WmsState(status="등록됨", by="human", wms_id=..., approver=<검증된 이름>, approved_at=<KST 지금>)`로 저장한다.
- 시각은 코드가 `ZoneInfo("Asia/Seoul")`로 계산한다 (Lambda 시계는 UTC). 이미 있는 한국 시간 도우미가 있으면 그것을 쓴다.
- 이미 등록된 작업을 다시 승인해도 처음 값을 바꾸지 않는다 (D3 멱등).
- 이름은 이미 `_validate_approver`가 공백 정리·길이(50자)를 검사한다. PDF에 넣기 전에 제어 문자를 한 번 더 뺀다.

### PDF 만들기 (`tools/certificate.py`, 위치는 열린 결정 2)

```python
def make_certificate(job: Job, docs: list[ExtractedDocument]) -> bytes:
    """검수 완료서 PDF를 만든다.
    언제: GET /jobs/{id}/certificate 가 사람 승인으로 등록된 작업을 받았을 때.
    받는 것: job(결과의 issues·hs·wms), docs(읽은 서류).
    반환: PDF 바이트. 모델·AWS를 부르지 않는다. 승인자·시각이 없으면 ValueError.
    """
```

- 입력 검사: `job.result.wms`가 `등록됨`, `by == "human"`, `approver`·`approved_at`이 있어야 한다. 아니면 `ValueError`(핸들러가 409로 바꾼다).
- 구성: reportlab platypus(`SimpleDocTemplate`, `Paragraph`, `Table`)로 위에서 아래로 칸을 쓴다. `render_declaration_pdf`와 같은 모양이다.
- 글꼴: `tools/declaration.py`의 `_register_fonts()`와 글꼴 이름 상수를 가져다 쓴다 (2번 소유 파일은 고치지 않는다). 글꼴은 `tools/fonts/`에 이미 있다.
- 긴 글자는 `Paragraph`가 줄바꿈하고, 항목이 많으면 `Table(repeatRows=1)`이 쪽을 넘긴다. 서류에서 온 글자는 XML 이스케이프해 데이터로만 넣는다.
- 같은 입력은 같은 PDF가 되게 한다: 만든 시각을 쓰지 않고 `invariant=1`로 생성 시각·ID 메타데이터를 고정한다.
- 호출할 때마다 `[tool] make_certificate job=... docs=...`를 print로 남긴다 (팀 규칙).

### 내려받기 (`api/handler.py`, 4번)

- 경로 `GET /jobs/{job_id}/certificate` (`/api` 접두사는 기존 `_route_path`가 처리).
- 작업 없음 404 → 아직 사람 승인 등록이 아님 409 (JSON `{"error": "..."}`) → PDF.
- 서류는 승인 때와 같은 방식으로 저장된 서류 기록(`docs`)을 읽는다.
- 응답은 이진이다. API Gateway HTTP API는 `isBase64Encoded: true`로 본문을 base64 글자로 받는다.
  ```python
  {"statusCode": 200, "isBase64Encoded": True,
   "headers": {"Content-Type": "application/pdf",
               "Content-Disposition": f'attachment; filename="certificate-{job_id}.pdf"'},
   "body": base64.b64encode(pdf).decode()}
  ```
- 기존 `_response`는 JSON만 만든다. 이진 응답은 작은 도우미 `_pdf_response`를 따로 둔다.
- CloudFront의 `/api/*` 동작이 이진을 압축·변환하지 않는지 배포 뒤 한 번 확인한다 (시험 순서의 마지막 확인).

### 화면 (`web/`, 3번)

- `WmsPanel`: `wms.status === "등록됨" && wms.by === "human"`이면 `<a href="/api/jobs/{id}/certificate" download>검수 완료서 받기</a>`.
- 승인 입력칸 라벨은 기존 시험이 찾는 "승인자"를 그대로 두고, 그 아래 안내 한 줄 ("입력한 이름이 검수 완료서에 검수자로 찍힙니다.").
- 링크 곁에 "검수자 김담당 · 2026-11-21 09:30"을 보인다. 링크 주소는 `certificateUrl(jobId)`(`web/src/api.ts`).
- `types.ts`의 `WmsState`에 `approver`, `approved_at`을 더하고, 가짜 응답(`mock.ts`)도 맞춘다.

## 오류와 경계

| 경우 | 동작 |
|---|---|
| 작업 없음 | 404 |
| 승인 대기, 자동 등록, 실패 | 409 "사람이 승인해 등록한 작업만 발급합니다" |
| 옛 작업(승인했지만 approver 칸 없음) | 409. 이름이 없는 문서는 만들지 않는다. 지금까지의 시험 작업은 모두 해당될 수 있다 |
| PDF 만들기 실패 | 500 + 짧은 이유, 등록 상태는 그대로 |
| 이름에 제어 문자·긴 글자 | 제어 문자 제거, 50자 제한은 승인 때 이미 적용 |
| 서류에 지시문 글자 | 데이터로만 출력, 따르지 않음 |

## 시험 (`tests/unit`, AWS·Bedrock 호출 없음)

- `test_certificate.py`: 사람 승인 작업을 PDF로 만들고 `pypdf`로 글자를 읽어 검수자 이름, B/L, 승인 시각, HS, WMS 번호가 있는지 확인한다. 한글이 글자로 읽히는지, 같은 입력이 같은 바이트인지, 자동 등록·승인 대기는 `ValueError`인지, 항목이 많아 쪽이 넘어가도 모두 들어가는지 본다.
- `test_handler.py`: 승인 후 `wms.approver·approved_at`이 저장되고 한국 시간(+09:00)인지, 재승인이 값을 바꾸지 않는지, `GET /certificate`가 200·`application/pdf`·`isBase64Encoded`인지, 409·404 경우를 본다.
- `test_screen_contract.py`(FB14, #246)에 사람 승인까지 이어 `wms.approver`가 채워지는지 한 경우를 더한다.
- `web`: 등록됨+human에서만 링크가 보이는지, 이름 안내 문구가 있는지.
- 배포 뒤 확인: 실제 승인 대기 작업을 승인하고 PDF를 내려받아 열어 본다 (한글, 이름, 쪽 구성). CloudFront를 거친 응답이 깨지지 않는지 본다.

## 의존성과 배포

- 새 의존성 없음. `pyproject.toml`·`uv.lock`을 바꾸지 않는다. 글꼴은 `tools/fonts/`에 있고 `config.sh`가 `tools/` 전체를 zip에 넣는다.
- 배포는 `deploy.sh`(API Lambda)와 `deploy-web.sh`. 처리 Lambda 코드도 같은 zip이라 함께 갱신된다. infra·정책 변경 없음, `create.sh` 불필요.

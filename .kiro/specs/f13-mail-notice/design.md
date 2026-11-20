# Design Document

## Overview

```
처리 Lambda (api/worker.py lambda_handler)
  run_job → _draft → _register → _record_shipment → _mark_waiting
  → notify.send_notice(job, docs, importer)                      ← 새로
       ├ 보낼 것 고르기: 불일치 / HS 미확정 (없으면 None)
       ├ 첨부: tools.validate.notice_document → HTML
       │      tools.hs_request.make_hs_request → PDF
       ├ 메일 만들기: email.message.EmailMessage (제목은 B/L·송장 번호를 정리해서만, 서류 글자는 본문에만)
       └ SES v2 send_email (Raw) ──────────────▶ 담당자 메일함 (NOTIFY_TO)
  → 단계 기록 send_notice 한 줄 → 마지막 저장 (_save)
```

## Approaches

첨부 (사용자가 A를 골랐다)

| 대안 | 내용 | 판단 |
|---|---|---|
| **A (고름)** | 불일치 → 불일치 통지 문서 HTML, HS 미확정 → HS 확인 요청서 PDF, 한 통에 함께 | 이미 있는 문서를 그대로 쓰고 2번·PM 파일을 고치지 않는다 |
| B | HS 확인 요청서만 붙이고 불일치는 본문에 몇 줄 | 불일치 근거가 본문에만 남는다 |
| C | 불일치 통지 문서를 PDF로 새로 만듦 | 새 문서 작업이 늘고 2번 영역 문서와 겹친다 |

보내는 자리

| 대안 | 판단 |
|---|---|
| **처리 Lambda 마지막 저장 직전 (고름)** | 결과가 정해진 바로 뒤라 조건 판단이 정확하고, 단계 기록을 같은 저장에 넣는다. 새 리소스가 SES 하나뿐이다 |
| DynamoDB Streams·EventBridge → 메일 Lambda | Lambda·트리거·권한이 늘어 남은 일정에 무리다 |
| API `GET` 때 보냄 | 사람이 화면을 열어야 보내져서 알림 의미가 없다 |

SES 호출 방식

| 대안 | 판단 |
|---|---|
| **sesv2 `send_email` + `Content.Raw` (고름)** | 첨부를 넣을 수 있고 boto3에 이미 있다. 실행 역할 권한으로 부른다 |
| SES SMTP | SMTP 비밀번호를 어딘가 저장해야 해서 "키를 코드·설정에 적지 않는다" 규칙과 맞지 않는다 |

## Architecture

### `api/notify.py` (새 파일, 4번)

- `NOTIFY_TOOL = "send_notice"`
- `notice_targets(job: Job) -> tuple[list[Issue], list[HSResult]]`
  `waiting_approval`이고 결과가 있을 때 (불일치 문제 목록, `hs_request.pending_hs(job)`). 그 밖은 `([], [])`.
- `build_attachments(job, docs, importer, *, now=None) -> list[tuple[str, str, bytes]]`
  (파일 이름, MIME 형식, 바이트). 불일치가 있으면 `notice_document(job.job_id, docs, job.result.issues).html`을
  `handler._notice_name(notice.subject, job.job_id, "html")` 이름, `text/html; charset=utf-8`로.
  HS 미확정이 있으면 `make_hs_request(job, docs, importer=importer, now=now)`를 `hs-request-<작업 ID>.pdf`, `application/pdf`로.
- `build_message(job, docs, importer, *, sender, to, now=None) -> EmailMessage`
  제목은 `[서류 검증 요청] B/L <번호> / 송장 <번호> - 불일치 N건, HS 확인 M건`이고 번호는 `_subject_no`(첫 낱말, 영문·숫자·/._-, 40자)로 정리한다. 본문은 관리자에게 거래처·관세사 검증 요청을 부탁하는 문장이다 (2026-11-21 사용자 요청). 본문은 일반 텍스트이고, 서류 글자는 `_one_line(text, limit=80)`로 정리해서 넣는다
  (제어 문자·줄바꿈 → 공백, 공백 하나로, 80자 상한). 첨부는 `add_attachment`.
- `class MailSender(Protocol)`: `send(self, sender: str, to: str, raw: bytes) -> str` (SES MessageId). `tools/wms.py`의 어댑터와 같은 방식이다.
- `ses_sender() -> MailSender`: `boto3.client("sesv2", region_name=AWS_REGION 또는 ap-northeast-2, config=Config(connect_timeout=5, read_timeout=5, retries={"total_max_attempts": 2, "mode": "standard"}))`.
  `send`는 `send_email(FromEmailAddress=sender, Destination={"ToAddresses": [to]}, Content={"Raw": {"Data": raw}})`.
- `send_notice(job, docs, importer, *, mail=None, env=None, now=None) -> Step | None`
  - 보낼 것이 없으면 `None`. `NOTIFY_FROM`·`NOTIFY_TO`가 없으면 로그만 남기고 `None`.
  - 첨부 만들기 실패 → `Step(ok=False, "확인 요청 메일 못 보냄: 첨부를 만들지 못함 (<오류 종류>)")`, 메일은 보내지 않는다.
  - SES 실패 → `Step(ok=False, "확인 요청 메일 못 보냄: <오류 종류>")`.
  - 성공 → `Step(ok=True, "담당자에게 확인 요청 메일 보냄 (불일치 N건 · HS 미확정 M개, 첨부 K개)")`.
  - 예외를 올리지 않는다. `print(f"[tool] send_notice job=… 불일치=N HS미확정=M")`. 주소는 찍지 않는다.

### `api/worker.py` (4번)

`_mark_waiting(result)` 바로 뒤, `columns`를 만들기 전에 넣는다.

```python
if result.status == "waiting_approval" and read:
    if (step := notify.send_notice(result, read, importer_of(read))) is not None:
        result.steps.append(step)
```

모듈 docstring의 환경 변수 목록에 `NOTIFY_FROM`, `NOTIFY_TO`(선택)를 더한다.

- **시간**: 마지막 60초 예산 안에서 돈다. PDF 만들기는 1초 안이고, SES는 최악이면 (5초+5초) × 2회 남짓이다 (total_max_attempts 2).
- **한 번만 보내기**: worker는 `queued`만 처리한다. 보낸 뒤 저장이 실패해 Lambda가 이벤트를 다시 보내면 상태가 `running`이라
  `failed`로 끝내고 메일은 다시 가지 않는다. 그래서 메일은 많아야 한 번 간다. 보내기 실패는 다시 보내지 않는다 (화면에서 문서를 받을 수 있다).
- **WMS 오류로 승인 대기가 된 작업**: `_register`가 `done`을 `waiting_approval`로 바꾼 경우는 불일치·HS 미확정이 없으므로 보내지 않는다.

### `infra/` (4번이 PR, PM이 실행)

- `infra/policy-notify.json` (새): `ses:SendEmail`, `ses:SendRawEmail`,
  Resource `arn:aws:ses:ap-northeast-2:__ACCOUNT_ID__:identity/*`, Condition `StringEquals ses:FromAddress = __NOTIFY_FROM__`.
- `infra/create.sh`
  1. 값 정하기: `${NOTIFY_FROM+x}`로 넘겼는지 본다. 안 넘겼으면 worker 함수가 있을 때 지금 환경 변수에서 읽는다. 빈 값을 넘겼으면 끈다.
  2. SES ID: 값이 있으면 `aws sesv2 get-email-identity`로 찾고 없으면 `create-email-identity`. `VerifiedForSendingStatus`가 false면 인증 안내를 출력한다.
  3. 정책: 값이 있으면 `team06-worker-role`에 `team06-notify`를 `render policy-notify.json "NOTIFY_FROM=…"`로 붙인다. 끄면 `delete-role-policy`(없으면 무시).
  4. `WORKER_ENV`에 값이 있을 때만 `NOTIFY_FROM=…,NOTIFY_TO=…`를 더한다. `sync_env`는 지금 그대로 쓴다.
- `infra/README.md`: 리소스 목록(SES 이메일 ID 2개, 정책 `policy-notify.json`), worker 환경 변수, 실행 예와 끄는 법,
  샌드박스 한도(하루 200통, 초당 1통), 첫 발송 때 스팸함 확인.

### 보안과 주의

- 서류 글자는 본문에만 넣고, 제목에는 B/L·송장 번호의 첫 낱말에서 영문·숫자·/._- 만 남겨 넣는다. 서류에 `\r\nBcc: …` 같은 글자가 있어도 헤더가 늘지 않는다.
- 첨부 HTML은 `notice_document`가 이미 이스케이프한다. PDF는 `make_hs_request`가 데이터로만 넣는다.
- 메일 주소는 환경 변수로만 받는다. 단계 기록·로그·테스트에 실제 주소가 없다.
- 받는 주소의 도메인 SPF에 SES가 없으면(DMARC 없음), 같은 주소로 보내고 받을 때 스팸함에 갈 수 있다. 첫 발송 때 확인하고,
  스팸함이면 보내는 주소를 바꿀지 PM과 정한다.
- 평가·10회 반복 측정을 배포된 처리 Lambda로 돌리면 세트마다 메일이 간다. 그때는 `NOTIFY_FROM= NOTIFY_TO= bash infra/create.sh`로 끈다.

## 시험 (AWS 호출 없음, 가짜 `MailSender`)

`tests/unit/test_notify.py` (새, 4번)
- 보낼 것 고르기: 불일치만, HS 미확정만, 둘 다, 확인 필요·참고만(None), `done`(None)
- 첨부: 이름·MIME 형식·내용 (HTML에 규칙 ID, PDF는 `%PDF`로 시작), 둘 다면 메일 한 통에 첨부 두 개
- 제목: B/L·송장 번호와 건수, 0인 쪽 빠짐, 번호 없으면 작업 ID. 서류 글자에 `\r\nBcc:`가 있어도 헤더 수가 같고 본문은 한 줄
- 설정 없음: `NOTIFY_TO` 없으면 None이고 보내지 않음
- 실패: 첨부 실패·SES 실패 → `ok=False`와 오류 종류, 예외 없음. 단계 요약에 `@`가 없음
- `ses_sender`: 서울 리전, 타임아웃 5초, `total_max_attempts` 2

`tests/unit/test_worker.py` (4번)
- 불일치로 승인 대기 → 메일 한 통, 마지막 저장의 단계 기록 끝에 `send_notice` ok
- SES 실패 → 작업은 `waiting_approval`로 저장, `send_notice` ok=False
- `done`(자동 등록) → 메일 없음
- `running` 재시도 이벤트 → 메일 없음

## 배포 (PM)

1. PR이 합쳐진 뒤 `MODEL_ID=… NOTIFY_FROM=<보내는 주소> NOTIFY_TO=<담당자 주소> bash infra/create.sh`
2. 두 주소의 메일함에서 SES 인증 링크를 누른다 (`aws sesv2 get-email-identity`로 `VerifiedForSendingStatus: true` 확인)
3. `bash infra/deploy.sh`
4. 불일치 세트와 HS 미확정 세트를 하나씩 올려 메일이 오는지, 첨부가 열리는지(HTML 한글, PDF), 스팸함에 가지 않는지 본다

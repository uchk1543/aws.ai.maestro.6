# Requirements Document

## Introduction

처리가 끝난 작업에 불일치나 HS 미확정이 남으면, 지금은 담당자가 화면을 열어 문서를 직접 내려받아야 알 수 있다.
문서는 이미 코드가 만든다: 불일치 통지 문서(C7 #158, `tools/validate.py`의 `notice_document`, HTML)와
HS 확인 요청서(X2 #260, `tools/hs_request.py`의 `make_hs_request`, PDF). X2 스펙은 "메일 발송"을 범위 밖으로 남겼다.
이번 일은 처리 Lambda가 작업을 끝낼 때 그 문서를 첨부해 **담당자에게 확인 요청 메일**을 SES로 보내는 것이다. 이슈: #263

받는 사람은 내부 담당자다. 두 문서 모두 "사람이 검토한 뒤 전달"이라고 찍혀 있으므로, 담당자가 검토한 뒤 관세사·거래처에 넘긴다.
관세사·거래처에게 바로 보내지 않는다.

정한 방향:
- 첨부 (방향 A): 불일치가 있으면 불일치 통지 문서 HTML, HS 미확정이 있으면 HS 확인 요청서 PDF. 둘 다 있으면 메일 한 통에 둘 다.
- 메일은 코드가 보낸다. 에이전트 도구에 넣지 않는다 (agent-design.md 8번: 외부에 쓰는 일은 AI가 하지 않는다). 모델 호출이 없다.
- 새 의존성이 없다. 표준 라이브러리 `email`과 이미 쓰는 `boto3`(sesv2)만 쓴다.
- 보내는 주소와 받는 주소는 저장소(코드·설정·테스트)에 적지 않고, 처리 Lambda 환경 변수 `NOTIFY_FROM`, `NOTIFY_TO`로 받는다.
- SES는 서울 리전(ap-northeast-2)이고 이메일 주소 인증만 쓴다 (사용자 지정 도메인 없음, team.md). 샌드박스라 두 주소 모두 인증해야 한다.
- 2번 소유 `tools/validate.py`와 PM 소유 `tools/hs_request.py`는 고치지 않고 부르기만 한다.

담당: 4번 서버 (`api/`). `infra/`는 4번이 PR로 고치고 실행은 PM이 한다.

## Glossary

- **확인 요청 메일**: 이번에 보내는 메일. 담당자가 검토할 문서를 첨부한다.
- **불일치**: `job.result.issues` 중 `grade`가 `불일치`인 것.
- **HS 미확정**: `job.result.hs` 중 `status`가 `사람 확인 필요`인 품목 (`tools/hs_request.pending_hs`).
- **담당자**: 작업 결과를 검토하는 내부 사람. 주소는 `NOTIFY_TO`.

## Requirements

### Requirement 1: 언제 보내나

#### Acceptance Criteria

1. WHEN 처리 Lambda가 작업을 `waiting_approval`로 끝내고 읽은 서류가 있으며 불일치가 1건 이상이거나 HS 미확정이 1개 이상이면 THE 처리 Lambda SHALL 마지막 저장 직전에 확인 요청 메일을 한 통 보낸다.
2. IF 확인 필요·참고만 남았거나 작업이 `done`(WMS 등록됨)·`failed`면 THEN 보내지 않는다.
3. THE 메일 SHALL 작업 하나에 많아야 한 번 간다. HS 선택(`POST /jobs/{id}/hs`), 승인, 조회 때는 보내지 않는다.
4. IF `NOTIFY_FROM`이나 `NOTIFY_TO`가 없으면 THEN 보내지 않고 로그만 남긴다 (로컬 실행·평가 실행).

### Requirement 2: 첨부와 내용

#### Acceptance Criteria

1. WHEN 불일치가 있으면 THE 메일 SHALL 불일치 통지 문서 HTML을 첨부한다. 파일 이름은 내려받기 API와 같은 `notice-<B/L 번호 또는 작업 ID>.html`이다.
2. WHEN HS 미확정이 있으면 THE 메일 SHALL HS 확인 요청서 PDF를 첨부한다. 파일 이름은 `hs-request-<작업 ID>.pdf`이다.
3. THE 제목 SHALL 실무 메일처럼 건과 할 일을 쓴다: `[서류 검증 요청] B/L <번호> / 송장 <번호> - 불일치 N건, HS 확인 M건`. 0인 쪽과 못 읽은 번호는 빼고, 번호가 둘 다 없으면 `작업 <작업 ID>`다.
   제목의 번호는 서류 글자의 첫 낱말에서 영문·숫자·`/._-`만 남기고 40자에서 자른다. 그 밖의 서류 글자는 제목과 헤더에 넣지 않는다. (2026-11-21 사용자 요청으로 바꿈)
4. THE 본문 SHALL 관리자(ERP 담당)에게 거래처·관세사 검증 요청을 부탁하는 한국어 일반 텍스트다: 인사, "아래 건의 수입 서류를 대조한 결과 확인이 필요한 사항이 있어, 관련 거래처·관세사에게 검증을 요청드리고자 합니다.",
   건 정보(작업 번호, B/L 번호, 송장 번호, 수입자, 수출자), 불일치가 있으면 "거래처 확인 요청"(규칙 ID와 근거 문장, 정정 서류 요청), HS 미확정이 있으면 "관세사 확인 요청"(행·품명·서류 HS·후보, 제품 정보 안내),
   처리 상태, 자동 발송 표시. 요청마다 해당 첨부 파일 이름을 적는다. 없는 값은 '없음'이다.
5. THE 서류에서 온 글자 SHALL 본문에는 데이터로만 넣는다. 줄바꿈과 제어 문자를 공백으로 바꿔 한 줄로 만들고 80자(근거 문장은 200자)에서 자른다.
6. THE 메일 SHALL 도구 결과(작업 결과와 읽은 서류)에 없는 내용을 쓰지 않는다.

### Requirement 3: 메일이 실패해도 작업은 끝난다

#### Acceptance Criteria

1. WHEN 메일을 보내면 THE 처리 Lambda SHALL 단계 기록에 `send_notice` 한 줄을 `ok=true`로 남긴다. 예: "관리자에게 검증 요청 메일 보냄 (불일치 2건, HS 확인 1건, 첨부 2개)".
2. IF 첨부를 만들지 못하거나 SES 호출이 실패하면 THEN 단계 기록에 `ok=false`와 오류 종류를 남기고, 작업 상태와 결과는 그대로 저장한다. 예외를 올리지 않는다.
3. THE SES 호출 SHALL 연결·읽기 타임아웃 5초, 재시도 1회다 (team.md 외부 API).
4. THE 단계 기록과 로그 SHALL 메일 주소를 쓰지 않는다 (단계 기록은 화면에 보인다).

### Requirement 4: 리소스와 권한 (infra/, PM이 실행)

#### Acceptance Criteria

1. THE `infra/create.sh` SHALL `NOTIFY_FROM`·`NOTIFY_TO`의 SES 이메일 ID를 만들고(있으면 건너뜀) 인증 상태를 출력한다. 인증 전이면 "메일함의 인증 링크를 눌러야 보낼 수 있습니다"를 출력한다.
2. THE 처리 Lambda 역할 SHALL `ses:SendEmail`·`ses:SendRawEmail`만 받는다. 서울 리전 이메일 ID로 한정하고, 보내는 주소는 `ses:FromAddress = NOTIFY_FROM` 조건으로 묶는다. API Lambda에는 붙이지 않는다.
3. THE 환경 변수 SHALL 이렇게 정한다: 값을 넘기면 그 값, 넘기지 않으면 지금 함수의 값을 그대로 두고, 빈 값을 넘기면 메일을 끈다(변수와 정책을 지운다).
4. THE 메일 주소 SHALL 저장소에 적지 않는다. 테스트 주소는 `example.com`이다.

## 범위 밖

관세사·거래처에게 직접 보내기, 담당자 여러 명·작업별 담당자, 다시 보내기 버튼, 메일 상태 전용 화면(단계 기록으로 대신),
반송·수신 거부 처리(SNS), SES 프로덕션 접근 신청, 사용자 지정 도메인과 DKIM, HTML 본문, 불일치 통지 문서 PDF.

# Requirements Document

## Introduction

사람이 검수(승인)해 WMS에 등록한 작업에 대해, 검수자 이름이 찍힌 **검수 완료서(PDF)** 를 만들어 내려받게 한다.
데모용이라 가장 가볍게 만든다. 이미 있는 `reportlab`과 `tools/fonts/`의 나눔고딕(신고서 PDF `render_declaration_pdf`가 쓰는 것)을 그대로 쓰므로 새 의존성이 없다. 새 AWS 리소스·전자서명·시점 증명·PDF/A는 이번 범위에 넣지 않는다.
이슈: #258

정한 방향:
- 문서 내용은 전부 코드가 이미 저장된 결과에서 옮긴다. 모델을 부르지 않는다 (AI는 서류 분류·읽기·HS 후보 고르기·질문 변환만 한다).
- 검수자 = 승인(`POST /api/jobs/{id}/approve`)의 `approver`. 로그인이 없어서 사용자가 입력한 글자다. 문서에 "시스템 기록용, 전자서명 아님"을 적는다.
- 파일은 저장하지 않는다. `GET`할 때 저장된 작업에서 매번 만든다 (같은 작업은 같은 내용). 그래서 S3·정책·infra 변경이 없다.
- 사람 승인으로 등록된 작업만 발급한다. 처리 직후 자동 등록(by=auto)은 사람 검수가 없어 발급하지 않는다.

담당: 약속(모델·schema) PM, 승인 때 이름·시각 저장과 `GET` 경로 4번 서버, PDF 만들기 담당 지정 필요, 내려받기 버튼 3번 화면.
관련: FB22 #178 (같은 방식으로 GET에서 채움), FB14 #171 (약속 시험), WMS 승인 D3.

## Glossary

- **검수 완료서**: 한 작업의 검수 결과를 한 장(내용이 길면 둘 이상)으로 적은 PDF.
- **검수자**: 승인 때 입력한 이름 (`approver`, 공백 정리 후 1~50자).
- **승인 시각**: 승인이 WMS 등록에 성공한 시각. 한국 시간(Asia/Seoul)으로 코드가 계산해 저장한다.

## Requirements

### Requirement 1: 검수자와 승인 시각 저장

#### Acceptance Criteria

1. WHEN 사람 승인이 WMS 등록에 성공하면 THE approve SHALL `wms.approver`(검수자 이름)와 `wms.approved_at`(한국 시간 ISO 8601, 예 `2026-11-21T09:30:12+09:00`)을 작업에 저장한다.
2. THE 저장값 SHALL 단계 기록 글자를 읽어 만들지 않는다 (문장이 바뀌어도 깨지지 않게 칸으로 둔다).
3. IF 자동 등록(by=auto)이면 THEN THE 저장값 SHALL `approver`와 `approved_at`을 null로 둔다.
4. THE 옛 작업(두 칸이 없는 줄) SHALL 그대로 읽힌다.

### Requirement 2: 검수 완료서 내용

#### Acceptance Criteria

1. THE 문서 SHALL 다음 칸을 담는다. 값이 없으면 "없음"으로 적는다.
   - 머리: 문서 제목 "검수 완료서", 작업 번호, B/L 번호, 수입자
   - 검수: 검수자 이름, 승인 시각(KST), 승인 방식 "사람 승인"
   - 서류: 읽은 서류 종류와 파일 이름
   - 대조 결과: 불일치·확인 필요 건수, 항목마다 규칙 번호·근거(서류, 칸)
   - HS: 품목별 최종 HS와 확정 방식 (자동 확정, 이력, 사람이 고름)
   - 등록: WMS 번호, 등록 시각
   - 꼬리: "시스템 기록용이며 전자서명이 아닙니다", 작업 번호
2. THE 문서 SHALL 도구 결과에 없는 내용을 쓰지 않는다. 모델이 쓴 문장을 넣지 않는다.
3. THE 서류에서 읽은 글자(품명, 번호 등) SHALL 데이터로만 넣는다. 그 안의 지시문은 따르지 않는다.
4. THE 문서 SHALL 한국어로 쓰고, 한글이 깨지지 않게 글꼴을 포함한다.
5. THE 문서의 날짜·시각 SHALL 한국 시간이고, 만든 시각이 아니라 저장된 승인 시각을 쓴다 (같은 작업은 같은 내용).

### Requirement 3: 내려받기 API

#### Acceptance Criteria

1. THE API SHALL `GET /api/jobs/{job_id}/certificate`로 PDF를 돌려준다 (`Content-Type: application/pdf`, 파일 이름 `certificate-{job_id}.pdf`로 내려받기).
2. IF 작업이 없으면 THEN 404, 아직 사람 승인으로 등록되지 않았으면(승인 대기, 자동 등록 포함) THEN 409와 이유("사람이 승인해 등록한 작업만 발급합니다")를 JSON으로 돌려준다.
3. THE 만들기 SHALL 모델·AWS(S3, Bedrock)를 부르지 않고 저장된 작업과 서류 기록만 쓴다.
4. IF PDF를 만들다 실패하면 THEN 500과 짧은 이유를 돌려주고, WMS 등록 상태는 바꾸지 않는다.
5. THE 응답 SHALL 6MB 이하다 (Lambda 응답 제한. 문서는 수십 KB).

### Requirement 4: 화면 버튼

#### Acceptance Criteria

1. WHEN 작업이 사람 승인으로 등록됨이면 THE 화면 SHALL WMS 패널에 "검수 완료서 받기" 링크를 보인다.
2. WHILE 승인 대기·자동 등록·실패이면 THE 화면 SHALL 링크를 숨긴다.
3. THE 승인 입력칸 SHALL 이름이 검수 완료서에 찍힌다고 알린다. 라벨은 기존 시험이 쓰는 "승인자"를 그대로 두고, 곁에 안내 한 줄("입력한 이름이 검수 완료서에 검수자로 찍힙니다.")을 둔다.
4. WHEN 검수 완료서 링크를 보일 때 THE 화면 SHALL 검수자 이름과 승인 시각(분까지)도 함께 보인다.

### Requirement 5: 가볍게 유지

#### Acceptance Criteria

1. THE 추가 의존성 SHALL 없다. `pyproject.toml`과 `uv.lock`을 바꾸지 않는다 (`reportlab`과 나눔고딕은 이미 있다).
2. THE Lambda 패키지 SHALL 커지지 않는다 (`tools/` 전체가 이미 zip에 들어간다).
3. THE 만들기 SHALL 한 문서에 1초 안에 끝난다.
4. THE 이번 범위 SHALL 새 AWS 리소스·정책 변경·전자서명·타임스탬프·PDF/A를 포함하지 않는다 (발표에서 다음 단계로 설명).

## 범위 밖 (다음 단계로 설명)

- 전자서명(KMS), 공인 시각 증명, PDF/A, S3 보존(Object Lock)·접근 기록, 양식 버전 관리, 로그인으로 신원 보증.

## 열린 결정

1. 자동 등록 건에도 문서를 내줄지. 기본은 "내주지 않음"(요구가 검수자 이름이 찍힌 문서라서). 데모의 정상 세트는 자동 등록이라 이 경로에서는 버튼이 안 보인다. 승인 대기 세트(불일치가 없고 확인 필요·HS 선택만 있는 것)로 시연한다.
2. 코드 위치. 새 파일 `tools/certificate.py`로 정했다 (2번 소유인 `tools/declaration.py`를 건드리지 않고 글꼴 등록 도우미만 가져다 쓴다). 팀 규칙의 `tools/` 파일 목록에 없으므로 단톡에 알린다.

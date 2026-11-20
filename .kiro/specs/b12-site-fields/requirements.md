# Requirements Document

## Introduction

지금 판독(약속 1)은 사무실·관세사가 보는 칸 위주라서, 항만 현장(터미널 게이트·보세창고·CFS)이 화물을 알아볼 때 쓰는 칸을
서류에 찍혀 있는데도 읽지 않는다. 판독은 VLM(Bedrock)이 하고, 모델은 출력 스키마(`RawDocument`·`RawBillOfLading`)에 있는 칸만 옮긴다.
이 칸들이 스키마에 없어서 안 읽었다. 이번 일은 VLM 판독에 칸을 더하는 것이고, Textract로 판독을 옮기는 것이 아니다
(Textract는 지금처럼 다시 확인의 두 번째 근거와 화면의 칸 위치에만 쓴다).

단톡 공지(2026-11-20)에서 팀이 승인한 방향:
- 현장용 칸을 늘린다 (B/L 봉인 번호·규격·컨테이너별 포장 수·중량·화인, 포장명세서 품목별 포장 수·화인).
- 금액·단가·결제 조건은 현장에서 안 보지만 불일치가 나면 관리자에게 알려야 하므로 읽기·대조·통지 문서에서 빼지 않는다.
- 칸마다 누구에게 보여 줄지(현장 / 관리자)만 구분한다. 관리자는 모든 칸을 본다.

샘플 서류로 확인한 것 (samples/dev, pypdf 글자층):
- B/L: `MARKS & NUMBERS` 칸과 `CONTAINER DETAILS: CONTAINER NO. / SEAL NO. / SIZE-TYPE / PACKAGES / GROSS WEIGHT / MEASUREMENT` 줄이 모든 세트에 찍혀 있다.
- 포장명세서 스타일 1(D001): 화인(`C/NO. 1-53` 포함)은 있고 품목별 포장 수 열은 없다.
- 포장명세서 스타일 2(D008): 품목별 `No. of Pkgs` 열은 있고 화인 칸은 없다.
- 품목별 박스 번호 범위(C/No.)는 어느 양식에도 따로 없다. 서류 전체 범위는 화인 안에 있다. 그래서 `carton_range` 칸은 만들지 않는다.

담당: 칸·판독은 1번 판독(공용 파일 포함), 대조 규칙은 2번 검증, 서류 보기 응답은 4번 서버.
관련: #110 (B2 P1 칸 추가), #163 (FB06 대조 규칙), #188 (F10 서류 보기 marks), #216 (B4-L0).

## Glossary

- **현장 칸**: 항만 현장이 실물과 맞춰 보는 칸. `SITE_FIELDS`(tools/models.py)에 서류 종류별로 적는다.
- **관리자**: 사무실 담당자. 모든 칸과 모든 문제를 본다. 불일치 통지 문서(C7)도 관리자에게 간다.
- **화인(marks)**: 상자와 서류에 찍는 Shipping Marks (`MARKS & NUMBERS`). 여러 줄을 공백 하나로 이어 한 칸으로 둔다.
- **컨테이너 줄(containers)**: B/L `CONTAINER DETAILS`의 한 줄. 컨테이너 번호·봉인 번호·규격·포장 수·총중량·용적.

## Requirements

### Requirement 1: 현장 칸 읽기

#### Acceptance Criteria

1. THE read_document SHALL 선하증권에서 `marks`와 `containers[]`(`container_no`, `seal_no`, `size_type`, `packages`, `gross_kg`, `cbm`)를 raw로 옮긴다.
2. THE read_document SHALL 포장명세서에서 `marks`와 품목별 `items[].packages`를 raw로 옮긴다.
3. IF 그 양식에 칸이 없으면 THEN THE read_document SHALL raw를 null, unreadable을 '칸 없음'으로 둔다 (스타일 1 포장 수, 스타일 2 화인).
4. THE 코드 SHALL value·unit을 raw에서 푼다: `packages`는 개수와 포장 단위, `gross_kg`는 kg, `cbm`은 숫자, `marks`는 대문자·공백 하나로 맞춘 글자.
5. THE 기존 칸 SHALL 이름·뜻이 그대로다. `container_no`(번호를 공백으로 이은 한 칸)도 남긴다 (X-CNTR-01, fields.csv).
6. THE Raw 모델 스키마 SHALL Bedrock 구조화 출력의 선택 속성 12개 한도를 넘지 않는다 (새 칸은 필수 + null 허용).

### Requirement 2: 관리자용 칸 유지

#### Acceptance Criteria

1. THE read_document SHALL 금액·단가·결제 조건(`total_amount`, `unit_price`, `amount`, `payment_term`, `incoterms`)을 지금처럼 읽는다.
2. THE cross_check·notice_document SHALL 이 칸들의 문제를 지금처럼 내고 통지 문서에 담는다. 현장 칸 구분으로 빠지는 문제는 없다.

### Requirement 3: 현장 칸 대조

#### Acceptance Criteria

1. THE cross_check SHALL 선하증권 화인과 포장명세서 화인을 정규화(대문자, 글자·숫자 말고 모두 뺌)해서 비교하고, 다르면 '확인 필요'를 낸다 (X-MARK-01).
2. THE cross_check SHALL 선하증권 컨테이너 줄 포장 수의 합과 `total_packages`가 다르면 '불일치'를 낸다 (X-PKG-02).
3. THE cross_check SHALL 포장명세서 품목별 포장 수의 합과 `total_packages`가 다르면 '불일치'를 낸다 (X-PKG-03).
4. IF 비교할 칸이 그 양식에 없으면(칸 없음, 빈 목록) THEN THE cross_check SHALL 그 규칙을 건너뛴다.
5. IF 일부만 읽혔거나 흐림·가려짐이면 THEN THE cross_check SHALL '확인 필요'를 낸다 (빈 값을 일치로 세지 않음).
6. THE 새 규칙 SHALL 개발용 정상 세트에서 오탐 0건이고, 기존 규칙의 탐지 수를 바꾸지 않는다.

### Requirement 4: 서류 보기의 현장 표시

#### Acceptance Criteria

1. THE `GET /api/jobs/{id}/files` SHALL `fields[]`에 컨테이너 줄 칸(`containers[0].seal_no` 등)과 한국어 이름을 담는다.
2. THE `fields[]`의 각 칸 SHALL `site`(현장 칸이면 true)를 가진다. 화면이 이것으로 현장 보기를 거른다 (화면은 이번 범위 밖).

### Requirement 5: 정답지와 측정

#### Acceptance Criteria

1. THE build_samples SHALL 개발용 `eval/fields.csv`에 새 칸의 정답(`marks`, `containers[i].*`, `items[i].packages`)을 쓴다. 발표용은 잠금을 깨지 않는다.
2. THE 판독 측정 SHALL 새 칸의 칸별 정답 수를 내고, 기존 P0 칸 정답 수가 줄지 않았음을 보인다.

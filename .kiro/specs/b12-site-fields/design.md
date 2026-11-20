# Design Document

## Overview

칸을 늘리는 일(공용 모델 + 판독)과, 늘린 칸을 쓰는 일(대조 규칙, 서류 보기)을 나눈다. 이슈도 셋으로 나눈다.

| 이슈 | 작업 ID(제안) | 담당 | 브랜치 | 먼저 |
|---|---|---|---|---|
| 현장 칸 추가 (공용 파일) #228 | B12 | 1번 판독 | `chore/228-site-fields` | - |
| 현장 칸 대조 규칙 #229 | B13 | 2번 검증 | `feat/b13-site-rules` | B12 |
| 서류 보기에 현장 칸 표시 #230 | F12 | 4번 서버 | `feat/f12-site-view` | B12 |

작업 ID는 tasks.csv에 없는 다음 번호로 제안한 것이다. PM이 정한다.

진행: #228은 PR #237로 main에 합쳐졌다 (`0dfec90`). 리뷰 보완은 `fix/228-site-fields-review`. #229·#230은 아직.

## Architecture

```
서류 → read_document (모델: raw만, 새 칸 marks·containers[]·items[].packages)
     → to_extracted (코드: value·unit 풀기)                       ← B12 #228
     → cross_check (X-MARK-01·X-PKG-02·X-PKG-03, 코드)            ← B13 #229
     → reread_field (containers[i].칸 경로로 다시 확인)            ← B12 #228
     → GET /api/jobs/{id}/files (fields[].site = SITE_FIELDS)     ← F12 #230
```

모델은 적힌 글자를 옮기기만 하고, 합계·비교·현장 칸 구분은 코드가 한다 (agent-design.md 1·2번). 금액·단가·결제 조건은 이 흐름에서 빠지지 않는다.

## Data Models

### 칸 (tools/models.py, 약속 1)

```python
class ExtractedContainer(_Strict):
    line: int                      # CONTAINER DETAILS 줄 순서, 1부터
    container_no: Cell | None = None
    seal_no: Cell | None = None    # 'SEAL NO.'. 컨테이너 번호와 다르다
    size_type: Cell | None = None  # 적힌 그대로. 예: "20'GP (22G1)"
    packages: Cell | None = None   # value 개수, unit 포장 단위. 예: '53 CTNS'
    gross_kg: Cell | None = None
    cbm: Cell | None = None

ExtractedDocument.marks: Cell | None = None                     # B/L·포장명세서(상업송장도 있으면)
ExtractedDocument.containers: list[ExtractedContainer] = []     # B/L만
ExtractedItem.packages: Cell | None = None                      # 포장명세서 품목별 No. of Pkgs
```

모델이 채우는 모양
- `RawContainer`: `line` + 여섯 칸 모두 필수 + null 허용 (`RawOriginItem`과 같은 방식).
- `RawBillOfLading`: `marks`, `containers: list[RawContainer]`를 더한다. 파이썬 기본값(None·빈 목록)을 두고 JSON 스키마에서만 필수로 표시한다
  (기존 B/L 가짜 응답이 깨지지 않게, `RawDocument`와 같은 방식).
- `RawDocument`: `marks`를 `RAW_REQUIRED_NEW`에, `RawItem`: `packages`를 필수 목록에 더한다.
- 선택 속성은 늘지 않는다. `tests/unit/test_extract.py`의 `_optional_count(...) <= 12`가 지킨다.

결정과 이유
- **`container_no`는 남긴다.** X-CNTR-01·fields.csv·신고서가 이 칸을 쓴다. `containers[].container_no`와 겹치지만 기존 약속을 깨지 않는 쪽을 골랐다.
- **화인은 한 칸.** 줄 구성은 서류마다 다르게 꺾인다(포장명세서 D001은 `EXAMPLE \nDISTRIBUTION KOREA \nINC.`, B/L은 `EXAMPLE DISTRIBUTION KOREA\nINC.`). 줄 목록으로 두면 비교가 어려워 공백 하나로 잇는다. `container_no`와 같은 방식이다.
- **`carton_range`는 만들지 않는다.** 줄별 C/No. 범위가 찍힌 양식이 데이터셋에 없다. 실제 서류에서 보이면 나중에 더한다.
- **이름 `packages`**: 공지의 `ctns`는 예시였다. `total_packages`와 맞추려고 `packages`로 한다 (단위가 CTN이 아닐 수도 있음).

현장 칸 (`SITE_FIELDS: dict[str, frozenset[str]]`, tools/models.py). 품목·컨테이너 칸은 번호 없이 `items.qty`, `containers.seal_no`로 적는다.

| 서류 | 현장 칸 |
|---|---|
| bill_of_lading | `doc_no` `consignee_name` `vessel_voyage` `port_discharge` `container_no` `total_packages` `total_gross_kg` `total_cbm` `marks` `containers.*` 여섯 칸 |
| packing_list | `marks` `total_packages` `total_gross_kg` `items.item_code` `items.name` `items.qty` `items.packages` `items.gross_kg` |
| commercial_invoice | `items.name` `origin` |
| certificate_of_origin | 없음 |

관리자는 모든 칸을 본다. 그래서 '관리자 칸' 목록은 두지 않는다. 금액·단가·결제 조건은 현장 칸이 아닐 뿐이고 읽기·대조·통지에서 빠지지 않는다.

## Components and Interfaces

### 판독 (tools/extract.py)

- `_cell`에 `"marks"` 종류를 더한다: `value = " ".join(raw.upper().split())`.
- `_DOC_KINDS["marks"] = "marks"`, `_ITEM_KINDS["packages"] = "qty"`,
  `_CONTAINER_KINDS = {"container_no": "text", "seal_no": "text", "size_type": "text", "packages": "qty", "gross_kg": "kg", "cbm": "number"}`.
- `to_extracted`: `containers`를 `items`처럼 줄마다 `ExtractedContainer`로 바꾼다.
- `_DOC_RULES` 문장 추가
  - bill_of_lading: "marks는 MARKS & NUMBERS 칸의 줄을 공백 하나로 이어 옮긴다. containers는 CONTAINER DETAILS(또는 Container No./Seal No.) 줄마다 하나다. 컨테이너 번호와 봉인 번호를 섞지 않는다."
  - packing_list: "marks는 Marks and Numbers 칸. 품목 행의 packages는 그 행의 포장 개수(No. of Pkgs, CTNS) 열이다. 열이 없으면 칸 없음."
- 판독 캐시 키에 스키마 해시가 들어가므로(`_schema_hash`) 옛 캐시는 저절로 안 쓰인다.

다시 확인 (tools/reread.py): `field_raw`의 경로에 `containers[i].<칸>`, `containers[*].<칸>`을 더한다. 대조 규칙이 짚는 칸을 다시 확인할 수 있어야 한다.
`same_value`는 `packages`·`cbm`(새 칸과 `total_packages`·`total_cbm`)을 숫자와 단위로 비교한다. 단위는 `CTNS`·`CARTONS` = `CTN`으로 맞춘다 (리뷰 보완).

### 대조 규칙 (tools/validate.py, tools/rules/rules.csv)

세 규칙 모두 `_SINGLE_DOC_RULES`처럼 함수로 둔다 (X-MARK-01은 두 서류를 보지만 정규화가 달라 `_check_rule`에 넣지 않는다).

| rule_id | 대상 | 판정 | 짚는 칸 (IssueCell) |
|---|---|---|---|
| X-MARK-01 | B/L `marks` ↔ 포장명세서 `marks` | 정규화(대문자, `[^A-Z0-9]` 제거) 뒤 다르면 확인 필요 | 두 서류의 `marks` |
| X-PKG-02 | B/L 한 장 안 | `sum(containers[].packages.value) != total_packages.value` 이면 불일치 | `containers[*].packages`, `total_packages` |
| X-PKG-03 | 포장명세서 한 장 안 | `sum(items[].packages.value) != total_packages.value` 이면 불일치 | `items[*].packages`, `total_packages` |

- 건너뜀: 화인이 한쪽이라도 '칸 없음'(`_is_absent`), 컨테이너 줄이 없음, 품목 포장 수가 모두 '칸 없음', `total_packages`가 '칸 없음'.
- 확인 필요: 흐림·가려짐, 일부 줄만 읽힘, 숫자로 못 풂.
- 화인이 다르다고 불일치로 확정하지 않는 이유: 화인은 서류마다 줄을 더하거나 빼도 틀린 것이 아닐 수 있다. 계산으로 확정되는 것만 불일치로 둔다 (agent-design.md 3번).
- 출처 열은 2번 검증(관세 규칙 담당)이 조사해 넣는다. 허용 오차는 0 (개수).
- 데이터셋에는 이 규칙들로 잡을 심은 오류가 없다 (E14는 생성기가 컨테이너 줄을 함께 맞춘다, build_samples.py:313). 그래서 이번 측정은 오탐 0과 기존 탐지 수 유지만 본다.

### 서류 보기 (api/handler.py, 약속 2)

- `ReadField.site: bool = False` (공용 모델, B12 PR에서 더한다. 기본값이 있어 응답 모양은 깨지지 않는다).
- `read_fields`: 컨테이너 줄을 `containers[{i}].{칸}`, 이름은 `"{line}번 컨테이너 {한국어}"`로 펼친다. `site`는 `SITE_FIELDS[doc_type]`에 경로의 `[숫자]`를 뺀 이름이 있으면 true.
- `_LABELS` 추가: `marks` 화인, `packages` 포장 수, `seal_no` 봉인 번호, `size_type` 규격, `cbm` 용적(CBM).
- 화면(3번)이 `site`로 거르는 것은 이번 범위 밖이다.

## Correctness Properties

- Raw 모델 스키마의 선택 속성은 전체 12개 이하다 (`_optional_count(...) <= 12`).
- 새 칸이 없는 옛 응답·옛 가짜 응답도 검증되고, 새 칸은 None·빈 목록이다.
- 기존 칸의 이름·뜻·값은 바뀌지 않는다 (`container_no` 포함). 기존 채점(`eval.score --p1`) 결과가 전후로 같다.
- 모델 출력에는 raw만 있고 value·unit은 코드가 채운다.
- 현장 칸이 아닌 칸도 읽기·대조·통지에서 빠지지 않는다 (`SITE_FIELDS`는 표시용).

## Error Handling

- 그 양식에 칸이 없으면 raw null, unreadable '칸 없음'. 대조 규칙은 건너뛴다 (스타일 1 포장 수, 스타일 2 화인, 컨테이너 줄 없음).
- 흐림·가려짐·일부 줄만 읽힘·숫자로 못 풂은 일치로 세지 않고 '확인 필요'.
- `field_raw`는 모르는 경로에 `ValueError`, 범위 밖 줄 번호에는 None.

## Testing Strategy

### 정답지와 측정 (samples/, eval/fields.csv)

- `build_samples.py`가 개발용 `eval/fields.csv`에 쓴다: B/L `marks`, `containers[i].container_no|seal_no|size_type|packages`, 포장명세서 스타일 1 `marks`, 스타일 2 `items[i].packages`. 값은 서류에 찍은 글자와 같게.
- `check_samples.py --docs`의 `found()`가 새 칸도 일반 규칙(글자·숫자 맞춤)으로 찾으므로 고치지 않는다. `measure_read_all.py`의 칸 경로·맞춤 기준에 `containers[i].*`와 `marks`(대문자·공백 맞춤)를 더한다.
- 측정: 개발용 12세트(`--only D001 … D011 D013`, B4-L0 튜닝 세트와 같음)를 `NO_CACHE=1`로 읽어, 새 칸 정답 수와 기존 P0 칸 정답 수를 B2 #93 결과와 비교한다.
- 발표용(eval/test/)은 잠금(samples/test_lock.json) 때문에 이번에 다시 쓰지 않는다. 마지막 측정 전에 PM과 정한다.

#### 측정 결과 (2026-11-20, 개발용 12세트 45장, `NO_CACHE=1`, MODEL_ID `global.anthropic.claude-sonnet-5-5`)
| 서류 | 전체 칸 | 새 칸 |
|---|---|---|
| 상업송장 | 72/72 | - |
| 포장명세서 | 71/71 | `marks` 4/4, `items[*].packages` 7/7 |
| 선하증권 | 232/232 | `marks` 12/12, `containers[*]` 네 칸 각 16/16 |
| 원산지증명서 | 99/100 | - |

- P0 칸(송장·포장명세서 invoice_no·total_qty·total_gross_kg)은 72/72로 그대로다.
- 틀린 1칸은 기존 칸이다: D001 스캔본 원산지증명서 `co_no`에서 0을 하나 더 읽음(`K26TAO0001737` → `K26TAO00001737`). 새 칸과 관계없다.
- 한 장 중간 17.4초, 최대 22.8초. 12세트 안의 스캔·PNG 서류도 새 칸이 모두 정답과 맞았다. 정답지 자체는 텍스트 PDF 347칸을 글자층에서 확인했다.
- 포장명세서 새 칸 정답이 적은 것은 심은 오류·변형이 있는 세트를 정답지에서 뺐기 때문이다 (tasks.md 작업 4 Ruling).

## 범위 밖 (나중)

- 화면의 현장 보기 (3번), 작업 카드.
- 서류에 없는 현장 정보: 수리 여부, D/O, 화물관리번호, 장치 위치, 검사 지정, 차량. UNI-PASS·선사·터미널 연동이 필요하다 (P2).
- 가상 WMS 입고 예정에 화인·컨테이너·봉인 번호 넣기 (`push_to_wms`, 4번).
- 위험물(UN 번호·등급)·냉동 설정 온도 칸. 데이터셋 서류에 없다.

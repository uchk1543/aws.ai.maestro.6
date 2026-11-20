# 데이터셋 (samples/)

주최 측이 서류를 주지 않아서 직접 만든 **합성 데이터셋**이다. 거래처·품목 카탈로그와 규칙으로 화물 한 건(세트)을 만들고,
공개된 실제 서류 양식을 본떠 서류와 정답지를 만든다. 회사명·주소·번호는 모두 가상이고 모든 서류에 SAMPLE이 찍혀 있다.

- 125세트: 개발용 `D001`~`D075`(저장소에 있음), 발표용 `T001`~`T050`(저장소에 없음, 해시로 잠금)
- 세트 하나 = 상업송장 + 포장명세서 + 선하증권(B/L) + 원산지증명서(약 80%). 모두 479장 (개발용 288장)
- 형식이 섞여 있다: PDF(글자층 있음), PNG, 스캔본(기울기·흐림·잡티가 있는 글자층 없는 그림 PDF)

## 이 데이터셋으로 재는 것 (먼저 읽기)

과제 기능 다섯 개를 모두 잰다. 오류 찾기는 그중 하나다. 숫자는 개발용 기준.

| 기능 | 정답 파일 | 규모 (개발용) | 이렇게 잰다 |
|---|---|---|---|
| ① 읽기(핵심 항목 추출) | `eval/fields.csv` | 서류 288장, 정답 칸 2,528개 | 서류마다 찍힌 값과 읽은 값이 같은지. 형식(PDF·PNG·스캔본)별로 따로 |
| ② 분류 | `eval/sets.csv` 의 `docs` | 서류 288장 | 파일 이름(`doc_a`~`doc_d`)으로는 종류를 알 수 없다. 고른 종류가 맞는지 |
| ② 서류 대조 | `eval/answers.csv` | 심은 오류 53건(P0 37), 정상 30세트 | 탐지는 오류 세트에서, 오탐은 정상 세트에서 |
| ③ HS 추천 | `eval/sets.csv` 의 `hs_answer`·`trap_hs` | 품목 줄 132개 | 정답 HS를 골랐는지, 헷갈리는 HS를 골랐는지 |
| ③ 신고서 초안 | `eval/declarations.csv` | 2,295칸 (비워야 할 칸 49) | 칸 값이 맞는지, 문제가 남은 칸을 비웠는지 |
| ④ WMS 자동 등록 | `eval/answers.csv` 의 정상 세트 | 30세트 | 사람 손 없이 등록까지 끝난 수 |
| ⑤ 현황 조회 | `eval/queries.csv` + `samples/data/shipments.json` | 질문 20개, 화물 기록 76건 | 질문을 조건으로 바꿨는지, 센 건수가 맞는지 |

**서류 대부분은 깨끗하다.** 오류가 찍힌 서류는 288장 중 52장(18%)이고, 전체 칸의 2.1%다. 나머지는 읽기·분류 문제다.

**세트의 60%에 오류를 심은 건 탐지율을 재기 위한 설계이고, 실제 빈도가 아니다.** 실무에서는 오류가 훨씬 드물다.
그래서 숫자는 나눠서 낸다.
- 탐지율: 오류 세트에서 ("심은 오류 37건 중 몇 건")
- 오탐, 자동 처리율, 처리 시간: 정상 세트에서
- P0 채점은 `answers.csv` 의 `phase=P0` 줄만 정답으로 보고, P0 줄이 없는 세트는 P0 기준 정상 세트로 센다
- 데모는 현실에 가까운 묶음(정상 세트 여럿 + 오류 세트 하나둘)으로 "대부분 자동으로 끝나고 하나만 사람에게"를 보여 준다

## 처음 보는 사람을 위한 5분 안내

1. 세트 하나를 연다: `samples/dev/D003/` 에 `doc_a`~`doc_d` 네 장이 있다.
2. 무슨 서류인지: `eval/sets.csv` 의 D003 줄 `docs` 칸. `doc_a=commercial_invoice;...;fmt_a=pdf;...`
3. 무엇을 심었는지: `eval/answers.csv` 의 D003 줄. "상업송장 총중량 12683.1 → 21683.1, digit_swap". 포장명세서·B/L은 원래 값이다
4. 서류에 찍힌 값: `eval/fields.csv` 의 D003 줄들
5. 신고서에 들어가야 할 값: `eval/declarations.csv` 의 D003 줄들. 총중량은 문제가 남아 `expect_blank=1`

심는 오류 21종과 헷갈리지만 정상인 차이, 그 근거(UCP 600, ISBP, 관세법령, FTA 고시, 협정문)는 [RULES.md](RULES.md) 에 있다.

```
samples/
├─ generate_dataset.py   ① 세트 만들기 (값과 심을 오류를 정함)
├─ build_samples.py      ② 서류 그리기 + 정답지 (answers·fields·sets)
├─ render_docs.py        ②에서 씀: B/L·원산지증명서 그리기, 스캔본 효과
├─ make_extra.py         ③ 신고서 정답, 가상 화물 기록, 현황 조회 질문
├─ check_samples.py      ④ 검사 (정답 값이 서류에 찍혔는지 OCR로 확인), 발표용 잠금
├─ RULES.md              규칙 · 심는 오류 · 근거
├─ templates/templates.xlsx  상업송장·포장명세서 양식 (레퍼런스를 본뜬 엑셀)
├─ gen/                  카탈로그 (사람이 고치는 곳): parties.csv 거래처, items.csv 품목
├─ data/                 생성기 결과 (sets.csv 세트, shipments.json 화물 기록)
├─ dev/D001~D075/        개발용 서류
└─ test_lock.json        발표용 파일 198개의 해시 (잠금)
```

## 만드는 법 (저장소 맨 위에서)

LibreOffice·poppler·tesseract가 필요하다(맥: `brew install --cask libreoffice && brew install poppler tesseract`).
파이썬 패키지는 팀 의존성을 건드리지 않게 `uv run --with` 로 붙인다.

```bash
DS="uv run --with openpyxl --with reportlab --with pillow --with numpy python"
```

| 순서 | 하는 일 | 명령 |
|---|---|---|
| 1 | 세트 만들기 (개발용은 매번 새로, 발표용은 없을 때만) | `$DS samples/generate_dataset.py` |
| 2 | 개발용 서류와 정답지 (약 1분) | `$DS samples/build_samples.py` |
| 3 | 신고서 정답, 화물 기록, 현황 질문 (몇 초, 서류는 다시 그리지 않음) | `$DS samples/make_extra.py` |
| 4 | 확인 (입력 검사, 정답 값이 찍혔는지, 품명이 보이는지, 약 5분) | `$DS samples/check_samples.py --docs` |

- 발표용은 잠겨 있다(`test_lock.json`, 태그 `test-lock-v2`). 다시 만들면 잠금이 깨지니 만들지 않는다.
  발표용 전용 품목·거래처(`gen/*_test.csv`)는 git에 없어서 다른 사람 PC에서는 만들 수도 없다.
- 일부 세트만 서류를 다시 만들 때: `$DS samples/build_samples.py --only D001 D002` (정답지는 항상 전체)
- 같은 시드(`--seed 6`)면 같은 데이터가 나온다.

## 정답 파일

| 파일 | 칸 | 내용 |
|---|---|---|
| `eval/answers.csv` | `set_id, split, doc, field, planted_value, original_value, error_type, expected_rule_id, line, phase, variant` | 심은 오류 한 줄씩. 정상 세트는 `error_type=none`. 형식은 `docs/schema.md` 약속 3 |
| `eval/fields.csv` | `set_id, doc, field, answer` | 서류마다 찍힌 핵심 칸 값 (심은 오류 포함). 날짜는 YYYY-MM-DD |
| `eval/sets.csv` | `set_id, split, consignee, docs, line, item, hs_answer, trap_hs` | 서류 자리·형식, 품목 줄마다 정답 HS 10자리와 헷갈리는 HS |
| `eval/declarations.csv` | `set_id, split, line, field, label, answer, source, expect_blank` | 신고서 간이 칸의 진짜 값. `line` 이 비면 신고서 한 장에 하나인 칸. `expect_blank=1` 은 심은 오류 때문에 비워야 하는 칸 |
| `eval/queries.csv` | `query_id, question, expected_conditions, expected_count` | 현황 질문 20개. 조건은 JSON (`status`, `period`, `date_from`, `date_to`, 기준일 `today`, `period_resolved`, 지연 `rule`) |
| `samples/data/shipments.json` | `docs/examples/shipment.json` 과 같음 | 가상 화물 기록 76건. `data/seed/shipments.json` 으로 옮겨 쓰면 된다 (A5) |

**제안값이라 담당이 확정하면 고칠 것** (`make_extra.py` 맨 위 값만 바꾸고 3번을 다시 돌린다)
- 신고서 칸 목록(`DECL_FIELDS`): 검증 담당 C4(#22). 비울 칸 규칙: 수량 오류 → 그 줄 수량(상업송장이면 금액·결제금액도),
  총중량·포장 수·결제금액 오류 → 그 칸, 운임 조건 충돌 → 인도조건, HS 오류 → 그 줄 세번부호,
  원산지 기준 오류 → 그 줄 협정·원산지결정기준, 원산지증명서 발급 기한·출항일 오류 → 모든 줄 협정·원산지결정기준.
  송장 번호·컨테이너 번호 오류는 신고서 칸이 아니라 비울 칸이 없다.
- 통관 상태 값과 '통관 지연' 기준(`STATUSES`, `DELAY_DAYS`): 검증 담당 E1(#29). 지금은 상태 `입항 · 수입신고 · 심사 중 · 검사 중 · 수리 · 반출`,
  지연은 "입항 후 3일이 지나도 수리·반출이 아님", 기간 조건은 입항일(`arrived_at`) 기준, 기준일은 2026-11-21(발표일).
  다른 날 시드를 넣으면 날짜를 그날로 옮기고 정답도 그날 날짜로 다시 계산한다 (`samples/seed_dates.py`, #170).
  '오늘까지'처럼 끝일이 오늘인 질문은 조건에 `date_to_today: true`를 붙인다.

## 무엇을 고치나

`data/*.csv` 와 `eval/*.csv` 는 스크립트가 덮어쓰니 직접 고치지 않는다.

| 바꾸고 싶은 것 | 고칠 곳 |
|---|---|
| 거래처, 송장·주문 번호 형식 | `gen/parties.csv` |
| 품목, 정답 HS, 헷갈리는 HS(`trap_hs`), 한-중 FTA용 HS2012(`hs6_2012`), 단가, 포장, B/L 품명·비고 | `gen/items.csv` (HS는 HS 표에 있는 10자리여야 생성된다) |
| 세트 비율, 날짜, 인코텀즈, 결제 조건, 서류 형식 비율, 운송사, 원산지 기준 | `generate_dataset.py` 맨 위 규칙 |
| 심는 오류와 비율, 헷갈리는 차이 | `generate_dataset.py` 의 `CATEGORIES`·`KINDS`·`BL_OPTIONS`·`CO_OPTIONS`·`VARIANTS` |
| 신고서 칸, 통관 상태 값, 지연 기준, 현황 질문 | `make_extra.py` 맨 위 |
| `rule_id` | `build_samples.py` 의 `RULES` |
| 상업송장·포장명세서 생김새 | `templates/templates.xlsx` |
| B/L·원산지증명서 생김새, 스캔본 효과 | `render_docs.py` |

## 하지 않은 것

- 휴대폰 촬영본(A3): 출력·촬영 여건이 없어 하지 않는다. 글자층 없는 스캔본 163장(개발용 99장)으로 OCR 상황을 대신 잰다.
- 아직 넣지 않은 오류 종류는 [RULES.md](RULES.md) 맨 아래.

# 데이터 약속
필드 이름은 예시다. 데이터셋 서류를 보고 판독 담당과 검증 담당이 함께 확정하고, 바꾸면 단톡에 알린다.
코드의 기준은 `tools/models.py`, 예시는 `docs/examples/`다. 셋이 어긋나면 CI(`tests/unit/test_examples.py`)가 실패한다.
## 약속 1. 서류 추출 결과 (read_document 반환)
- 모든 칸은 `{"raw": 문자열|null, "value": 풀어 쓴 값|null}` 형태다.
- `raw`: 모델이 서류에 적힌 그대로 옮긴 문자열. `value`·`unit`: 코드가 raw를 풀어 채운 값.
- 못 읽은 칸: `raw`와 `value`를 null로 두고 `unreadable`에 이유(흐림 · 가려짐 · 칸 없음)를 적는다.
- 모델이 스스로 매긴 확신 점수는 두지 않는다.
- `doc_type`: `bill_of_lading` | `commercial_invoice` | `packing_list` | `certificate_of_origin` | `unknown`
- `doc_no`: 서류끼리 맞춰 보는 번호. 상업송장은 송장 번호, **포장명세서는 거기 적힌 송장 번호**(Packing List No.가 아니다), B/L은 B/L No.
  X-INV-01은 상업송장 `doc_no`와 포장명세서 `doc_no`를 비교한다. 포장명세서 번호 자체는 지금 담지 않는다 (#89).
- `total_qty`: 합계로 찍힌 **품목 수량**의 합계. 포장 개수의 합계(CTNS 등)가 아니다. 합계가 찍혀 있지 않으면 비우고, 대조 코드가 줄 값을 더한다.
- 예시: `docs/examples/extract_packing_list.json`
## 약속 2. 작업 API (화면 ↔ Lambda)
주소: 화면과 같은 CloudFront 주소의 `/api/…`. CloudFront가 `/api/*`를 API Gateway(HTTP API)로 보낸다. 같은 주소라 CORS 설정이 필요 없다.
Lambda가 받는 이벤트는 HTTP API 2.0 형식이고 `rawPath`에 `/api`가 붙어 온다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /api/uploads` | `{"files":[{"name","content_type"}]}` | `{"uploads":[{"key","url"}]}` (url로 S3에 직접 PUT, 몇 분 뒤 만료) |
| `POST /api/jobs` | `{"files":[{"key","doc_type":null}]}` | `{"job_id"}` 바로 응답 (doc_type이 null이면 에이전트가 분류. 분류(B1)가 들어가기 전 뼈대에서는 400이므로 doc_type을 넣어 보낸다) |
| `GET /api/jobs/{id}` | - | 작업 상태 (`docs/examples/job_waiting_approval.json`) |
| `POST /api/jobs/{id}/hs` | `{"choices":[{"line","hs"}]}` | `{"declaration_draft":{...}}` |
| `POST /api/jobs/{id}/approve` | `{"approver"}` | `{"wms":{"status","wms_id"}}`, 불일치가 남았으면 409 |
| `POST /api/chat` | `{"session_id","message"}` | `docs/examples/chat_response.json` |
값 목록
- `status`: `queued` | `running` | `waiting_approval` | `done` | `failed`
- `grade`: `불일치` | `확인 필요` | `참고`
- `checked_by`: `pdf_text` | `textract` | `model_reread` | `none`
- `hs[].status`: `자동 확정` | `사람 확인 필요` | `사람 확정`, `hs[].by`: `history` | `auto_match` | `human` | null
- `wms.status`: `승인 대기` | `등록됨`, `wms.by`: `auto` | `human` | null
- `suspect`: 서류가 셋 이상일 때 다수결로 고른 서류 종류, 둘뿐이면 null
처리 방식: API Gateway는 요청 하나를 30초 안에 끝내야 해서, `POST /api/jobs`는 작업을 `queued`로 저장하고 `job_id`를 바로 돌려준다.
처리 Lambda가 비동기로 `run_job`을 돌려 `running` → `waiting_approval`·`done`·`failed`로 바꾼다. 화면은 `GET /api/jobs/{id}`를 2초마다 부른다.
## 화물 기록 (team06-shipments 한 줄)
- 예시: `docs/examples/shipment.json`
- `customs_status` 값 목록과 "통관 지연" 기준(입항 뒤 며칠)은 검증 담당이 정해 여기에 적는다.
## 신고서 초안 칸 (declaration_draft)
- 간이 양식이다. 코드가 템플릿에 값을 채우고 모델은 쓰지 않는다 (agent-design.md 7번). 초안에는 "사람 검토 전 초안"을 적고 신고 전송은 하지 않는다.
- `fields[]`: `{"name": 신고서 칸 이름, "value": 채운 값, "source": 출처}`. `source`는 `서류.칸`이고, 품목 칸은 `items[0]`처럼 줄 번호 − 1을 쓴다 (1번 줄 = `items[0]`).
- `blank_fields[]`: 비워 둔 칸의 경로. 서류 전체 칸은 `total_gross_kg`, 품목 칸은 `items[0].qty`처럼 쓴다 (줄 번호 − 1).
- 칸 목록은 `eval/declarations.csv`(정답지)의 `field`·`label`·`source`와 같다. 바꾸면 정답지도 함께 바꾼다.
- "읽기 칸"은 지금 `tools/models.py`의 `ExtractedDocument`에 이 출처가 있는지다. 없음인 칸은 읽기 칸(B2, 1번 담당)이 늘어야 채울 수 있고, 그 전에는 비워 두고 blank_fields에 적는다.

서류 전체 칸 (줄 번호 없음)
| field | 신고서 칸 | 출처 | 읽기 칸 |
|---|---|---|---|
| `bl_no` | B/L 번호 | `bill_of_lading.bl_no` (= `doc_no`) | 있음 |
| `vessel` | 선기명 | `bill_of_lading.vessel_voyage` | 없음 |
| `importer` | 수입자 | `commercial_invoice.consignee_name` | 없음 |
| `supplier` | 해외공급자 | `commercial_invoice.exporter_name` | 없음 |
| `export_country` | 적출국 | `bill_of_lading.port_loading` | 없음 |
| `total_gross_kg` | 총중량(kg) | `packing_list.total_gross_kg` | 있음 |
| `total_packages` | 총포장갯수 | `packing_list.total_packages` | 없음 |
| `package_kind` | 포장종류 | `packing_list` (포장 단위에서 코드가 정함) | 없음 |
| `incoterms` | 인도조건 | `commercial_invoice.incoterms` | 없음 |
| `currency` | 통화 | `commercial_invoice` (금액 칸의 통화) | 없음 |
| `total_amount` | 결제금액 | `commercial_invoice.total_amount` | 없음 |
| `payment` | 결제방법 | `commercial_invoice.payment_term` | 없음 |
| `co_present` | 원산지증명서 유무 | `certificate_of_origin` (서류가 올라왔는지, Y/N) | 있음 |

품목 칸 (줄마다 하나씩)
| field | 신고서 칸 | 출처 | 읽기 칸 |
|---|---|---|---|
| `description` | 품명 | `commercial_invoice.items[0].name` | 있음 |
| `hs_code` | 세번부호 | `hs[0].hs_code` (recommend_hs 결과. 확정 전이면 비움) | 있음 |
| `qty` | 수량 | `commercial_invoice.items[0].qty` | 있음 |
| `unit` | 단위 | `commercial_invoice.items[0].qty` (칸의 `unit`) | 있음 |
| `net_kg` | 순중량(kg) | `packing_list.items[0].net_kg` | 있음 |
| `unit_price` | 단가 | `commercial_invoice.items[0].unit_price` | 없음 |
| `amount` | 금액 | `commercial_invoice.items[0].amount` | 없음 |
| `origin` | 원산지 | `commercial_invoice.origin` | 없음 |
| `fta` | 협정 | `certificate_of_origin` (서류 양식에서 코드가 정함) | 없음 |
| `origin_criterion` | 원산지결정기준 | `certificate_of_origin.items[0].origin_criterion` | 없음 |

비우는 규칙 (코드가 정한다)
- 불일치·확인 필요 `issues`의 `cells`가 칸의 출처와 같은 서류·칸을 짚으면 그 칸을 비운다. 참고는 비우지 않는다.
- `hs_code`는 그 줄의 HS가 `사람 확인 필요`면 비운다 (`자동 확정`·`사람 확정`이면 채운다).
- 읽기 칸이 없거나 못 읽은 칸(raw가 null)도 추측하지 않고 비운다.
- 비운 칸은 `fields`에 넣지 않고 `blank_fields`에만 적는다. 틀린 값과 비운 칸은 평가에서 따로 센다.

## 약속 3. 정답지 (eval/answers.csv)
```csv
set_id,split,doc,field,planted_value,original_value,error_type,expected_rule_id,line,phase,variant
S01,dev,packing_list,total_gross_kg,6520,6250,digit_swap,X-WT-01,1,P0,
S02,dev,,,,,none,,,,
S03,dev,packing_list,invoice_no,SHE-2026 0214,SHE-2026-0214,none,,,,invoice_no_format
S04,test,certificate_of_origin,items[0].hs_code,6105.10,6109.10,trap_code,X-HS-01,1,P1,
```
- 심은 오류 하나가 한 줄(오류가 둘이면 두 줄), 정상 세트는 error_type=none 한 줄.
- split: dev(개발용) / test(발표용, 마지막에 한 번만). 발표용 정답지는 git에 올리지 않는다(eval/test/).
- doc: commercial_invoice, packing_list, bill_of_lading, certificate_of_origin.
- P0 대조 규칙은 서류 전체 값만 비교하므로 field는 서류 전체 값 이름이다: total_qty, total_gross_kg, invoice_no(약속 1의 doc_no).
  합계가 찍히지 않은 서류는 줄 값을 코드가 더한다. 약속 2의 cells가 items[0].gross_kg처럼 행 단위로 짚어도 채점은 같은 서류의 전체 값으로 묶어 센다.
- line: 값이 바뀐 품목 줄 번호(1부터). 서류 전체 값이 바뀌었으면 빈칸.
- phase: P0 = 상업송장·포장명세서의 invoice_no·total_qty·total_gross_kg, 나머지(합계, 송장 HS, B/L, 원산지증명서)는 P1.
  P0 채점은 phase=P0 줄만 정답으로 보고, P0 줄이 없는 세트는 P0 기준 정상 세트로 센다.
- variant: 정상 세트에 심은 헷갈리지만 정상인 차이(S03). 불일치로 잡으면 오탐, '참고'로 알리는 것은 괜찮다.
- 행 단위 칸(S04의 items[0].hs_code처럼)은 행 맞추기와 HS 대조를 하는 P1부터 쓴다.
- error_type은 심은 방식(samples/RULES.md의 E·V 목록), expected_rule_id는 규칙표 v1의 ID다(지금은 임시).
- 서류마다 찍힌 핵심 칸 값은 eval/fields.csv(set_id,doc,field,answer), 서류 자리·형식과 품목별 HS 정답·헷갈리는 HS는
  eval/sets.csv(set_id,split,consignee,docs,line,item,hs_answer,trap_hs), 현황 조회 질문은
  eval/queries.csv(query_id,question,expected_conditions,expected_count).
- 신고서 초안 칸별 정답은 eval/declarations.csv(set_id,split,line,field,label,answer,source,expect_blank).
  line은 품목 줄(1부터, 서류 전체 칸이면 빈칸), source는 값을 가져올 서류 칸(예 bill_of_lading.bl_no),
  expect_blank=1이면 문제가 남아 비워 두어야 맞는 칸이다. 비워 둔 칸은 틀림과 따로 센다 (agent-design.md 11번).

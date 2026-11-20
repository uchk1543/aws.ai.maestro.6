# 데이터 약속
필드 이름은 예시다. 데이터셋 서류를 보고 판독 담당과 검증 담당이 함께 확정하고, 바꾸면 단톡에 알린다.
코드의 기준은 `tools/models.py`, 예시는 `docs/examples/`다. 셋이 어긋나면 CI(`tests/unit/test_examples.py`)가 실패한다.
## 약속 1. 서류 추출 결과 (read_document 반환)
- 모든 칸은 `{"raw": 문자열|null, "value": 풀어 쓴 값|null}` 형태다.
- `raw`: 모델이 서류에 적힌 그대로 옮긴 문자열. `value`·`unit`: 코드가 raw를 풀어 채운 값.
- 못 읽은 칸: `raw`와 `value`를 null로 두고 `unreadable`에 이유(흐림 · 가려짐 · 칸 없음)를 적는다.
- 모델이 스스로 매긴 확신 점수는 두지 않는다.
- `doc_type`: `bill_of_lading` | `commercial_invoice` | `packing_list` | `certificate_of_origin` | `unknown`
- `doc_no`: 서류끼리 맞춰 보는 번호. 상업송장은 송장 번호, **포장명세서는 거기 적힌 송장 번호**(Packing List No.가 아니다), B/L은 B/L No., **원산지증명서는 10번 칸의 송장 번호**(증명서 번호는 `co_no`)
  X-INV-01은 상업송장 `doc_no`와 포장명세서 `doc_no`를 비교한다. 포장명세서 번호 자체는 지금 담지 않는다 (#89).
- `total_qty`: 합계로 찍힌 **품목 수량**의 합계. 포장 개수의 합계(CTNS 등)가 아니다. 합계가 찍혀 있지 않으면 비우고, 대조 코드가 줄 값을 더한다.
- `consignee_name`: 수하인(Consignee, 수입자) 칸의 회사 이름 한 줄. 주소·전화는 뺀다. 상업송장 값이 HS 확정 이력과 WMS 등록의 수입자다 (#110). 칸이 없으면 null.
  모델 스키마(`RawDocument`)에서는 필수 + null 허용이다 (Bedrock 구조화 출력의 선택 속성 12개 한도).
- 읽는 종류: 상업송장·포장명세서·선하증권·원산지증명서 (B2 P1 #11). 그 밖의 종류가 생기면 분류만 하고 '참고'(DOC-LATER)로 알린다.
- 서류 종류별 칸 (#110). 모두 `Cell | null`이고 그 서류에 없는 칸은 null이다. 칸 이름은 `eval/fields.csv`, 아래 신고서 표의 출처와 같다.

  | 서류 | 칸 |
  |---|---|
  | 상업송장 | `doc_no` `exporter_name` `consignee_name` `incoterms` `payment_term` `origin` `total_qty` `total_gross_kg` `total_amount`, 품목 `item_code` `name` `hs_code` `qty` `unit_price` `amount` `gross_kg` `net_kg` |
  | 포장명세서 | `doc_no` `exporter_name` `consignee_name` `total_qty` `total_gross_kg` `total_packages`, 품목 `item_code` `name` `qty` `gross_kg` `net_kg` |
  | 선하증권 | `doc_no`(B/L No.) `shipper_name` `consignee_name` `notify_name` `vessel_voyage` `port_loading` `port_discharge` `onboard_date` `container_no` `freight_term` `total_packages` `total_gross_kg` `total_cbm`. 품목 행은 없다 |
  | 원산지증명서 | `doc_no`(송장 번호) `co_no` `exporter_name` `consignee_name` `departure_date` `invoice_date` `issue_date` `issued_retroactively`, 품목 `name` `hs_code` `qty` `origin_criterion` |
- 이름 칸(`*_name`)은 첫 이름 줄만 담고 주소는 뺀다. 선하증권의 'TO ORDER OF SHIPPER', 'SAME AS CONSIGNEE'는 적힌 그대로다.
- 날짜 칸의 `value`는 `YYYY-MM-DD`이고, 숫자만 쓴 날짜(`10/11/2026`)는 일/월/연으로 푼다. 금액(`total_amount`·`unit_price`·`amount`)은 `value` 숫자, `unit` 통화.
- `total_packages`는 포장 개수의 합계(`unit` CTN 등)로 `total_qty`(품목 수량)와 다르다. `container_no`는 여러 개면 공백 하나로 잇는다.
- 모델이 채우는 모양: 상업송장·포장명세서는 `RawDocument`(새 칸은 필수 + null 허용), 선하증권·원산지증명서는 종류별 `RawBillOfLading`·`RawOrigin`(칸 모두 필수 + null 허용). 코드가 위 칸으로 바꾼다.
- 예시: `docs/examples/extract_packing_list.json`
## 약속 2. 작업 API (화면 ↔ Lambda)
주소: 화면과 같은 CloudFront 주소의 `/api/…`. CloudFront가 `/api/*`를 API Gateway(HTTP API)로 보낸다. 같은 주소라 CORS 설정이 필요 없다.
Lambda가 받는 이벤트는 HTTP API 2.0 형식이고 `rawPath`에 `/api`가 붙어 온다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /api/uploads` | `{"files":[{"name","content_type"}]}` | `{"uploads":[{"key","url"}]}` (url로 S3에 직접 PUT, 몇 분 뒤 만료) |
| `POST /api/jobs` | `{"files":[{"key","doc_type":null}]}` | `{"job_id"}` 바로 응답 (doc_type이 null이면 에이전트가 분류한다. 정해 보낼 때는 `unknown`을 뺀 4종만 받고, 그 밖의 값은 400) |
| `GET /api/jobs/{id}` | - | 작업 상태 (`docs/examples/job_waiting_approval.json`) |
| `POST /api/jobs/{id}/hs` | `{"choices":[{"line","hs"}]}` | `{"declaration_draft":{...}}` |
| `POST /api/jobs/{id}/approve` | `{"approver"}` | `{"wms":{"status","wms_id"}}`, 불일치가 남았으면 409 |
| `POST /api/chat` | `{"session_id","message"}` | `docs/examples/chat_response.json` |
| `GET /api/chat/{session_id}` | - | `docs/examples/chat_history.json` (대화 기록 최근 50줄, 오래된 순. #157) |
| `GET /api/documents?doc_type=<종류>&cursor=<다음 쪽>` | - | `docs/examples/documents.json` (문서 분류 내역, #143) |
| `GET /api/jobs/{id}/files` | - | `docs/examples/job_files.json` (서류 보기: 원본 주소 + 읽은 칸, #156) |

대화 기록 (`POST /api/chat`·`GET /api/chat/{session_id}`, E6 #157. 모양은 `tools/models.py`의 `ChatHistoryLine`·`ChatHistoryResponse`)
- `session_id`: 영문 대소문자·숫자·`-`로 1~64자 (`^[A-Za-z0-9-]{1,64}$`). 화면의 `crypto.randomUUID()`와 `s-<밀리초>-<16진수>`가 이 형식이다
  - `POST /api/chat`: 칸이 없거나 null이면 답은 하고 기록은 남기지 않는다. 그 밖의 값이 형식에 맞지 않으면(빈 문자열 포함) 400 "session_id는 영문·숫자·-로 64자까지입니다"
  - `GET /api/chat/{session_id}`: 형식에 맞지 않으면 같은 400
- 요청 하나가 질문 한 줄(`role` `user`)과 답 한 줄(`role` `assistant`)을 남긴다. 기록 저장이 실패해도 답은 그대로 200이다
- `messages[]` 칸: `session_id`, `ts`, `role`, `text`, `filters`, `count`, `rule`, `blocked`, `block_reason`
  - 질문 줄: `text`는 앞뒤 공백을 뺀 질문. 나머지 다섯 칸은 모두 null
  - 조회한 답 줄 (`ChatResponse.blocked`가 null): `blocked` false, `filters`는 쓴 조회 조건, `count`는 코드가 센 건수(`rows` 수), `rule`은 통관 지연 조회일 때만 규칙 문장(그 밖은 null), `block_reason` null
  - 가드레일(E7 #152)이 막은 답 줄 (`ChatResponse.blocked`가 있음): `blocked` true, `block_reason`은 `ChatResponse.blocked` 값(예: `무관한 질문`, `프롬프트 공격`), `filters`·`count`·`rule` null
- `ts`: `<요청 받은 시각, 한국 시간 YYYYMMDDHHMMSSmmm 17자리>#<요청마다 새로 만든 16진수 8자리>#<0 질문 | 1 답>`. 예: `20261121090000123#a1b2c3d4#0`. 앞 17자리는 `infra/README.md` team06-chat의 `ts` 형식 그대로이고, 뒤 꼬리는 같은 밀리초의 두 줄이 겹치지 않게 더한 것이다. 글자 순서가 저장 순서이고, 같은 요청의 질문 줄 바로 뒤에 답 줄이 온다. 화면에 보일 시각은 앞 17자리에서 구한다
- `GET`은 그 세션에서 `ts`가 가장 큰 50줄을 읽어 만료된 줄을 빼고 오래된 순으로 준다 (줄 기준이라 맨 앞 줄이 짝 없는 답 줄일 수 있다). 기록이 없으면 `{"messages": []}`, 읽기 실패는 502 "대화 기록을 불러오지 못했습니다"
- 저장: team06-chat (파티션 키 `session_id`, 정렬 키 `ts`, 둘 다 문자열. `infra/README.md` "테이블"). 한 줄의 칸은 `session_id`, `ts`, `role`, `text`, `expires_at`(UTC 유닉스 초 = 요청 시각 + 604800, TTL 7일)이고, 답 줄은 `blocked`와 값이 있는 `filters`(map)·`count`·`rule`·`block_reason`을 더한다. null은 칸을 쓰지 않는다. `block_reason`은 E6이 더한 칸이다. `expires_at`은 `GET` 응답에 없다

서류 보기 (`GET /api/jobs/{id}/files`, F7 #156. 모양은 `tools/models.py`의 `JobFilesResponse`)
- 서류마다 `url`(원본, 미리 서명된 GET 300초, inline), `content_type`. 화면은 PDF는 iframe, 이미지는 img로 띄운다
- `pages`: 이미지 서류만 원본 한 장과 크기(px). PDF는 쪽 그림을 만들지 않아 빈 목록
- `marks`: 칸 위치(bbox). OCR 좌표가 없어 지금은 늘 빈 목록 (Textract B4 뒤)
- `fields[]`: 읽은 칸 `{field, label, raw, value, unit, unreadable}`. `field`는 `IssueCell.field`와 같은 이름이라 `issues[].cells`의 `doc`+`field`로 불일치 칸을 바로 짚는다. 읽지 않은 서류는 빈 목록
- 분류 전(queued·running)인 서류는 빼고, 종류·근거는 문서 분류 내역과 같은 규칙

문서 분류 내역 (`GET /api/documents`, G10 #143. 모양은 `tools/models.py`의 `DocumentsResponse`)
- `doc_type`: 약속 1의 4종 또는 `unknown`(분류 못 함·분류 실패). 그 밖은 400. `cursor`는 앞 쪽의 `next_cursor`
- `counts`: 전체 작업 기준 종류별 서류 수 (다섯 종류 모두). 화면은 다시 세지 않는다
- `items[]`: `job_id`, `key`, `file_name`, `doc_type`, `classified_by`(`model`·`user`), `reason`(분류 근거), `doc_no`·`consignee`(읽은 raw, 읽지 않았으면 null), `job_status`, `created_at`(한국 시간 `YYYY-MM-DD HH:MM`)
- 최근 작업 먼저, 한 쪽 50건. 아직 분류 전(queued·running)인 서류는 빼고, 끝난 작업에서 분류 기록이 없으면 `unknown`
- 분류 근거는 작업 단계 기록의 `classify_document` 문장에서 읽는다. `POST /api/jobs`가 작업 줄에 `files`(요청한 키·종류)와 `created_at`을 함께 저장한다
값 목록
- `status`: `queued` | `running` | `waiting_approval` | `done` | `failed`
- `grade`: `불일치` | `확인 필요` | `참고`
- `checked_by`: `pdf_text` | `textract` | `model_reread` | `none`
- `hs[].status`: `자동 확정` | `사람 확인 필요` | `사람 확정`, `hs[].by`: `history` | `auto_match` | `human` | null
- `hs[].item_name`: 그 행의 품명(서류에 적힌 글자, 못 읽었으면 null). `hs[].doc_hs_code`: 서류에 적힌 HS를 적힌 그대로(예: `8507.60`, 없으면 null). 화면이 "1행 · 품명 (서류 HS)"로 보여 준다 (FB07 #164)
- `wms.status`: `승인 대기` | `등록됨`, `wms.by`: `auto` | `human` | null
- `suspect`: 서류가 셋 이상일 때 다수결로 고른 서류 종류, 둘뿐이면 null
처리 방식: API Gateway는 요청 하나를 30초 안에 끝내야 해서, `POST /api/jobs`는 작업을 `queued`로 저장하고 `job_id`를 바로 돌려준다.
처리 Lambda가 비동기로 `run_job`을 돌려 `running` → `waiting_approval`·`done`·`failed`로 바꾼다. 화면은 `GET /api/jobs/{id}`를 2초마다 부른다.
## 화물 기록 (team06-shipments 한 줄)
- 예시: `docs/examples/shipment.json`
- `customs_status` 값은 아래 6개만 쓴다 (진행 순서). 검사 중은 심사 중 뒤에 거치는 선택 단계다.
  `입항` → `수입신고` → `심사 중` → `검사 중` → `수리` → `반출`
- 통관이 끝난 상태: `수리`, `반출`.
- 처리한 작업의 줄 (E3, `tools/report.py`의 `record_shipment`·`mark_registered`, 부르는 쪽은 처리 Lambda·승인):
  - 작업이 `waiting_approval`·`done`으로 끝나고 선하증권 B/L 번호와 수하인이 있으면 한 줄 쓴다. B/L이 없으면 쓰지 않는다.
  - 서류에는 입항일 칸이 없어서 `arrived_at`은 **처리한 날**(한국 시간), `customs_status`는 `입항`, `job_id`는 그 작업이다 (데모용 결정).
    `consignee`는 상업송장 → 선하증권 → 포장명세서의 `consignee_name`, `item`은 첫 품목 품명(여럿이면 "… 외 N개 품목").
  - 가상 WMS에 등록되면(자동 D2 · 사람 승인 D3) 그 작업이 쓴 줄을 `수입신고`로 고친다. 이미 그 뒤 상태면 그대로 둔다.
  - 미리 넣은 가상 기록(`job_id` 없음)과 B/L이 같으면 덮어쓰지 않는다 (조건부 쓰기). 같은 B/L을 다시 처리하면 입항일·상태는 두고 `job_id`·수하인·품명만 바꾼다.
- "통관 지연"은 상태 값이 아니다. `customs_status`에 넣지 않고, 아래 규칙으로 코드가 계산한다.
  - 통관 지연 = (오늘 − `arrived_at`) ≥ **3일** 이고 `customs_status`가 `수리`·`반출`이 아님.
  - 입항일 당일이 0일이다. 입항일이 11/17이면 11/20부터 지연이다.
  - 오늘은 한국 시간(Asia/Seoul) 날짜다. 지연 일수 `DELAY_DAYS = 3`은 코드 한 곳에 상수로 둔다.
  - 3일은 데모용으로 정한 값이다. 법령이나 관세청 기준이 아니다. 바꿀 때는 이 문서와 `DELAY_DAYS`, 현황 질문 정답(`eval/queries.csv`)을 함께 고친다.
  - 답에는 쓴 규칙을 함께 보여 준다 (`ChatResponse.rule`, 예: "입항 후 3일 지나도 수리·반출 아님").
- 기간 조건(`today` · `this_week` · `last_week` · `range`)은 `arrived_at`(입항일) 기준이다. 주는 월요일부터 일요일까지이고, 날짜 계산은 코드가 한국 시간으로 한다.
- 현황 조회 조건(`ChatFilters`, `POST /api/chat` 응답의 `filters`)은 상태 하나·기간만 담는다 (#165).
  - `unsupported`: 모델이 이 칸으로 나타내지 못한 조건 목록 (예: 수하인, B/L 번호, 상태 둘 이상). 비어 있지 않으면 조회하지 않고 "… 조건은 아직 조회할 수 없습니다"로 답한다 (`rows` 빈 목록).
  - 조건이 하나도 없으면(상태·기간·`unsupported` 모두 비었음) 조회하지 않고 되묻는다. 전체 목록을 답하지 않는다.
- 가드레일 (E7 #152, `ChatResponse.blocked`): 막으면 조회하지 않고 "통관·화물 현황 질문만 답합니다. 예: …"로 답하고 `blocked`에 이유를 넣는다. 막지 않았으면 `null`.
  - 질문을 모델에 넣기 전에 Bedrock Guardrail(`GUARDRAIL_ID`·`GUARDRAIL_VERSION`, ApplyGuardrail 입력 검사)로 본다. 이유는 필터 이름(예: `프롬프트 공격`, `모욕`).
    환경 변수가 없거나 호출이 실패하면 막지 않는다 (로그만).
  - 모델이 낸 조건이 모두 비었고 질문에 화물·통관 낱말(또는 B/L 번호 모양)이 없으면 `무관한 질문`으로 막는다. 가드레일은 무관한 질문을 막지 않는다 (#151).
## 신고서 초안 칸 (declaration_draft)
- 간이 양식이다. 코드가 템플릿에 값을 채우고 모델은 쓰지 않는다 (agent-design.md 7번). 초안에는 "사람 검토 전 초안"을 적고 신고 전송은 하지 않는다.
- `fields[]`: `{"name": 신고서 칸 이름, "value": 채운 값, "source": 출처}`. `source`는 `서류.칸`이고, 품목 칸은 `items[0]`처럼 줄 번호 − 1을 쓴다 (1번 줄 = `items[0]`).
- `blank_fields[]`: 비워 둔 칸. 아래 표의 `field`(칸 키)로 적는다. 서류 전체 칸은 `total_gross_kg`, 품목 칸은 `items[0].qty`처럼 쓴다 (줄 번호 − 1). 수량과 단위처럼 출처가 같은 칸도 키로 구분한다.
- 칸 목록은 `eval/declarations.csv`(정답지)의 `field`·`label`·`source`와 같다. 바꾸면 정답지도 함께 바꾼다.
- "읽기 칸"은 지금 `tools/models.py`의 `ExtractedDocument`에 이 출처가 있는지다. 없음인 칸은 읽기 칸(B2, 1번 담당)이 늘어야 채울 수 있고, 그 전에는 비워 두고 blank_fields에 적는다.

서류 전체 칸 (줄 번호 없음)
| field | 신고서 칸 | 출처 | 읽기 칸 |
|---|---|---|---|
| `bl_no` | B/L 번호 | `bill_of_lading.bl_no` (= `doc_no`) | 있음 |
| `vessel` | 선기명 | `bill_of_lading.vessel_voyage` | 있음 |
| `importer` | 수입자 | `commercial_invoice.consignee_name` | 있음 |
| `supplier` | 해외공급자 | `commercial_invoice.exporter_name` | 있음 |
| `export_country` | 적출국 | `bill_of_lading.port_loading` | 있음 |
| `total_gross_kg` | 총중량(kg) | `packing_list.total_gross_kg` | 있음 |
| `total_packages` | 총포장갯수 | `packing_list.total_packages` | 있음 |
| `package_kind` | 포장종류 | `packing_list` (포장 단위에서 코드가 정함) | 없음 |
| `incoterms` | 인도조건 | `commercial_invoice.incoterms` | 있음 |
| `currency` | 통화 | `commercial_invoice` (금액 칸의 통화) | 없음 |
| `total_amount` | 결제금액 | `commercial_invoice.total_amount` | 있음 |
| `payment` | 결제방법 | `commercial_invoice.payment_term` | 있음 |
| `co_present` | 원산지증명서 유무 | `certificate_of_origin` (서류가 올라왔는지, Y/N) | 있음 |

품목 칸 (줄마다 하나씩)
| field | 신고서 칸 | 출처 | 읽기 칸 |
|---|---|---|---|
| `description` | 품명 | `commercial_invoice.items[0].name` | 있음 |
| `hs_code` | 세번부호 | `hs[0].hs_code` (recommend_hs 결과. 확정 전이면 비움) | 있음 |
| `qty` | 수량 | `commercial_invoice.items[0].qty` | 있음 |
| `unit` | 단위 | `commercial_invoice.items[0].qty` (칸의 `unit`) | 있음 |
| `net_kg` | 순중량(kg) | `packing_list.items[0].net_kg` | 있음 |
| `unit_price` | 단가 | `commercial_invoice.items[0].unit_price` | 있음 |
| `amount` | 금액 | `commercial_invoice.items[0].amount` | 있음 |
| `origin` | 원산지 | `commercial_invoice.origin` | 있음 |
| `fta` | 협정 | `certificate_of_origin` (서류 양식에서 코드가 정함) | 없음 |
| `origin_criterion` | 원산지결정기준 | `certificate_of_origin.items[0].origin_criterion` | 있음 |

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

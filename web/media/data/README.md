# 6팀 합성 데이터

부산항 수입 통관 시나리오용 테스트 데이터다. 회사, 주소, 선사, 선박, 은행, 발급 기관은 모두 가상이다. 모든 서류에 `SAMPLE` 워터마크와 "NOT A VALID TRADE DOCUMENT" 문구가 들어가 있다. 항구 코드(UN/LOCODE)와 HS 6단위 코드는 실제 체계를 따른다.

## 들어 있는 것

| 경로 | 내용 |
| --- | --- |
| `output/sets/SET-001 ~ SET-015/` | 서류 4종 PDF + `ground_truth.json`. 정상 10세트, 오류 5세트 |
| `output/sets/SET-011 ~ SET-015/corrected/` | 오류를 고친 정정본 서류 4종. 데모의 "정정 요청 → 수정본 재업로드 → 통과" 장면용 |
| `output/sets/SET-001, 004, 011, 012/scans/` | 기울기·노이즈·흐림을 넣은 스캔본 JPG (사진 입력 테스트용) |
| `output/manifest.csv` | 세트별 요약: 품목, B/L 번호, 넣은 오류, 기대 판정 |
| `master/item_master.csv` | 가상 ERP 품목 마스터 13건. 샘플 품목 일부는 일부러 빠져 있다 (신규 품목 시연용) |
| `master/hs_answer_key.csv` | 샘플 품목 15종의 HS 6단위 정답, 근거, 모호한 품목의 되묻기 질문 |
| `logistics/shipments_seed.json` | 가상 물류 시스템 화물 30건 (지연 6건). 15건은 샘플 세트와 B/L 번호가 같다 |
| `generator/` | 위 데이터를 만드는 스크립트 |

## 세트 구성

| 세트 | 품목 | 조건 | 넣은 오류 / 특징 |
| --- | --- | --- | --- |
| SET-001 | 리튬이온 배터리, LED 전구 | CIF | 정상 |
| SET-002 | 노트북, 스마트폰 | CIF | 정상 |
| SET-003 | 면 티셔츠 | FOB | 정상 (운임·보험료가 Invoice에 적혀 있음) |
| SET-004 | 냉동 새우 | CIF | 정상, 냉동 컨테이너(40RH) |
| SET-005 | 볼트, 너트, **MACHINE PARTS** | CIF | 정상. 모호한 품목 → HS 되묻기 시연 |
| SET-006 | PP 수납 상자, 스테인리스 싱크대 | FOB | 정상. 싱크대는 품목 마스터에 없음 |
| SET-007 | 목제 옷장 | CIF | 정상. 지시식 B/L (Consignee = TO ORDER OF 은행) → 참고 알림 |
| SET-008 | 커피 생두 | CIF | 정상. 품목 마스터에 없음 |
| SET-009 | 스마트폰, **ELECTRONIC COMPONENTS** | CIF | 정상. 모호한 품목 |
| SET-010 | 승용차 타이어 | FOB | 정상. 품목 마스터에 없음 |
| SET-011 | 리튬이온 배터리 | CIF | **데모 세트 (입항 3일 전).** PL 총중량 자릿수 뒤바뀜 + B/L 컨테이너 체크디지트 오류 |
| SET-012 | 볼트, 너트 | CIF | B/L 포장 수 1 적음 (화인에는 실제 포장 수가 적혀 있음) |
| SET-013 | 노트북 | CIF | Invoice 합계가 품목 합계보다 1,000 많음 |
| SET-014 | 면 티셔츠 | CIF | PL의 Invoice 번호 오타 + C/O 원산지 불일치 |
| SET-015 | PP 수납 상자 | FOB | 운임·보험료 정보 없음 → 누락 경고 |

서류마다 양식이 2종(A/B) 있다. 라벨(`Gross Weight` / `G.W.`), 단위(`KG` / `KGS`), 날짜 형식(`2026-11-05` / `05 NOV 2026` / `Nov. 05, 2026` / `05/11/2026`), 항목 순서가 다르다. 어떤 세트에 어떤 양식을 썼는지는 `ground_truth.json`의 `template_variants`에 있다.

## ground_truth.json 구조

```text
set_id, scenario            "SET-011", "normal" | "error"
template_variants           서류별 양식 A/B
files, scans                서류 파일 이름
shipment_truth              화물의 실제 값 (오류가 들어가기 전)
printed_fields              서류별로 실제 인쇄된 값 (오류 포함) ← 추출 정확도는 이것과 비교
  bill_of_lading            bl_no, shipper_name, consignee_name, vessel, voyage, port_of_loading,
                            container_numbers, total_packages, gross_weight_kg, measurement_cbm, ...
  commercial_invoice        invoice_no, invoice_date, incoterms, line_items[], total_amount,
                            freight_amount, insurance_amount, country_of_origin, ...
  packing_list              invoice_no_ref, line_items[], total_packages, total_gross_weight_kg, ...
  certificate_of_origin     certificate_no, country_of_origin, invoice_no_ref, items[](hs_code), ...
injected_errors             넣은 오류: 서류, 필드, 원래 값, 인쇄된 값, 규칙, 기대 판정
expected_findings           검증 결과로 나와야 하는 것 (error / missing_warning / info)
```

- 날짜는 ISO(`YYYY-MM-DD`), 숫자는 숫자 타입으로 정규화되어 있다. 서류에 인쇄된 형식은 양식마다 다르다.
- `printed_fields`의 키 이름을 BDA 블루프린트 필드 이름으로 그대로 쓰면 평가 스크립트를 따로 맞출 필요가 없다.

## 실행 방법

```bash
pip install -r data/generator/requirements.txt
cd data/generator
python generate_documents.py --base-date 2026-11-19     # 서류 15세트 (같은 seed면 같은 결과)
python generate_master_data.py                         # 품목 마스터, HS 정답표
python generate_logistics_seed.py --base-date 2026-11-21  # 가상 화물 30건
python check_generated_data.py                         # 의도대로 생성됐는지 확인
```

- **발표 당일에는 `generate_logistics_seed.py`를 그날 날짜로 다시 실행**한 뒤 DynamoDB에 다시 넣는다. 그래야 "이번 주 통관 지연 건"에 결과가 나온다.

## 가상 화물 데이터 (shipments_seed.json)

| 필드 | 뜻 |
| --- | --- |
| `customs_status` | 입항 예정 / 수입신고 / 심사 중 / 검사 지정 / 보완 요구 / 신고 수리 / 반출 완료 |
| `docs_status` | 검증 필요 (입항 전) / 보완 요청 중 / 검증 완료 / 서류 미등록 |
| `eta`, `ata`, `discharge_date` | 입항 예정일, 실제 입항일, 하선일 |
| `free_time_days`, `free_time_end` | 프리타임 일수(가상 값 5일)와 만료일. 이 날이 지나면 보관료·체화료가 붙는다고 가정 |
| `gate_out_date` | 반출일 (반출 완료 화물만) |
| `is_delayed`, `delay_reason`, `delay_days` | 지연 여부, 사유, 예상 수리일 대비 지연 일수 |

- 데모 세트(SET-011)는 `입항 예정`, 입항 3일 전, `검증 필요 (입항 전)` 상태다. `--demo-set`으로 바꿀 수 있다.
- 나머지 오류 세트(SET-012~015)는 이번 주 입항 후 서류 문제로 멈춘 지연 화물이다.
- 시연할 질의 예: "이번 주 통관 지연 건 알려줘", "프리타임이 이틀 안에 끝나는데 아직 수리 안 된 화물은?"
- DynamoDB 적재: 테이블(파티션 키 `shipment_id`, 문자열)을 만든 뒤 `python load_to_dynamodb.py --table <테이블> --region <리전>`. 자격 증명은 터미널의 AWS 프로필을 쓴다. **이 스크립트는 아직 실제 AWS에서 실행해 보지 않았다.**
- `check_generated_data.py`는 기획서 4장의 교차 검증 규칙을 인쇄값에 돌린다. F2 검증 도구의 기준 구현으로 참고할 수 있다.

## 아직 안 된 것

- [ ] `registered_hsk10`, `expected_hsk10` (HSK 10단위): 공공데이터포털 HSK 데이터로 확인해서 채운다
- [ ] 실제 휴대폰 사진: `scans/`는 사진 흉내를 낸 이미지라 실제 촬영본이 따로 필요하다
- [ ] 여러 페이지짜리 서류, 한글 서류
- [ ] 수입신고 항목 매핑표 (기획서 8장 ⑦)

## 단순화한 부분

- 이 데이터는 수입 화물만 다룬다. 환적 화물(부산항 물동량의 약 57%)은 국내 수입신고 대상이 아니라 넣지 않았다.
- FOB 정상 세트는 Invoice 비고란에 운임·보험료를 적었다. 실제로는 포워더의 운임 청구서 같은 별도 서류로 받는 경우가 많다.
- 원산지증명서 발급 기관은 `○○ EXPORT CERTIFICATION OFFICE (FICTIONAL)`이라는 가상 기관이다.
- 모호한 품목(MACHINE PARTS, ELECTRONIC COMPONENTS)의 원산지증명서에는 수출자가 적은 HS(8487.90, 8542.39)가 있지만, 정답표에서는 "분류 불가 → 되묻기"가 정답이다.

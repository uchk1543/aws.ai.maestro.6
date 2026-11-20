# B4-L0 설계: Textract 우선, Bedrock은 예외만

## 1. 측정: Bedrock 없이 Textract만으로 (2026-11-20)
개발용 세트만 썼다 (발표용은 열지 않음). 규칙을 만든 세트와 검증 세트를 나눴다.
- 튜닝: D001~D011·D013 (12세트 45장). 검증: D053·D065~D075 (12세트 47장, 규칙을 만들 때 보지 않음).
- 형식: pdf·png·스캔본, 스타일 1·2, 원산지증명서 KCFTA·AK·VK.
- 채점: `samples/measure_read_all.same`과 같은 기준, 정답은 `eval/fields.csv`.

| 방식 | 분류 | 전체 칸 | P0 칸 (송장·포장명세서 invoice_no·total_qty·total_gross_kg) |
|---|---|---|---|
| A. DetectDocumentText + 코드 규칙 (튜닝 세트) | 45/45 | 383/388 | 72/72 |
| A. DetectDocumentText + 코드 규칙 (**검증 세트**) | 47/47 | 408/412 | 71/72 |
| B. AnalyzeDocument Queries, 템플릿 규칙 없음 (검증 세트) | - | 354/401 | 63/72 |
| 참고: Bedrock 판독 (B2 #93, B1 #86) | 288/288 | - | 450/450 |

방식 A 검증 세트에서 틀린 4칸
- 회사 이름 쉼표·공백을 OCR이 다르게 읽음 3칸 (`CO.,LTD` → `CO. LTD`). 규칙으로 못 고친다.
- 스캔본 포장명세서 총수량 1칸 (`3,050 M2`의 단위 `M2`를 수량으로 못 봄). 규칙 버그, 검증 뒤 고침.
  고친 뒤 검증 세트 409/412, P0 72/72 (검증 세트를 보고 고친 숫자라 참고로만 쓴다).

실험 스크립트(로컬 OCR 캐시 포함)는 저장소에 넣지 않았다. 다시 돌리려면 4번 담당에게 받는다.
튜닝 세트에는 스캔본 원산지증명서 O/0 혼동(`K26TAO…` → `K26TA0…`) 1칸이 있었다.

방식 B는 합계가 안 찍힌 총수량을 더하지 못하고, 송장 수입자에 수출자를 답하는 등 P0에서 약했다. 값도 10배라 쓰지 않는다.

주의: 데이터셋은 생성기가 만든 양식이라 서류마다 스타일이 2개뿐이다. 방식 A가 잘 맞는 것은 양식이 적어서다.
실제 서류는 양식이 훨씬 많으니, 규칙으로 읽는 것은 "확신할 때만 쓰고 아니면 Bedrock"이어야 한다.

## 2. 비용 (서울 리전, 쪽당)
| 항목 | 값 | 출처 |
|---|---|---|
| Textract DetectDocumentText | $0.0015 | AWS Pricing API (APN2-SyncTextPagesProcessed). F10부터 서류마다 이미 낸다 |
| Textract Queries | $0.015 | 같음 |
| Bedrock 판독 1장 (Sonnet 5.5) | 약 $0.03 | 어림값: 입력 약 5천 토큰(프롬프트·스키마·쪽 그림) × $2/MTok + 출력 약 2천 토큰(JSON·생각) × $10/MTok. 1st-party 가격 기준이고 Bedrock 가격은 다를 수 있다 |
| Bedrock 분류 1장 | 약 $0.01 | 같은 방식의 어림값 |

어림값은 CloudWatch 로그의 실제 `usage`로 바꿔야 한다 (tasks.md 나중 3).
서류 4장 작업이면 Bedrock 분류·판독이 약 $0.16, Textract가 $0.006이다.

## 3. 파이프라인
```
l0  Textract DetectDocumentText (서류마다, S3 cache/ocr/ 에 원본, 같은 파일은 재사용, 초당 1건으로 간격)
l1  분류: Textract 제목 줄 → 확신 없으면 Bedrock          (CLASSIFY_BY_OCR=1, 이번에 만듦)
    읽기: Bedrock (판독 캐시 켬)                           (Textract 규칙 읽기는 나중, 아래 4)
l2  cross_check → 불일치 칸만 reread_field (pdf_text → textract → model)
l3  finish_report → 초안·WMS·화물 기록
```

## 4. 나중: 읽기를 Textract 규칙으로 (팀 결정 필요)
- agent-design.md는 "읽기는 AI"다. 읽기를 코드로 옮기려면 steering을 바꿔야 하고, `tools/extract.py`·`agent/`는 1번 담당이다.
- 품목 행(품명·HS·수량·단가·금액·순중량)을 아직 규칙으로 뽑지 않았다. HS 추천·신고서 초안에 필요하다.
- 확신 기준(모두 채워야 규칙 결과를 쓴다): 필수 칸이 다 있고 형식이 맞음, 줄 합 = 합계, 서류끼리 같은 값.
  하나라도 어긋나면 그 서류만 Bedrock으로 읽는다.
- 규칙으로 읽은 칸의 불일치는 Textract가 두 번째 근거가 될 수 없다(같은 출처). 그 칸은 Bedrock이 다시 확인한다
  (agent-design.md 4번 "두 번째 근거는 다른 방법으로").
- 예상: 선하증권(품목 행 없음)부터 옮기면 위험이 가장 작다.

## 5. 팀 규칙과 맞추기
- 분류를 코드가 하는 것은 기본으로 끈다(`CLASSIFY_BY_OCR=0`). 켤지는 팀이 정한다. 켜도 확신이 없으면 Bedrock이 분류한다.
- 문서 분류 내역(`GET /api/documents`)의 `classified_by`는 단계 기록을 보고 `model`로 나온다. 근거 문장에 "Textract 글자, 모델 호출 없음"을 적어 구분한다.
- 판독 캐시를 켜면 같은 서류는 Bedrock을 안 부른다. 라이브 데모와 10회 반복은 `NO_CACHE=1`로 배포한다(agent-design.md 2번).

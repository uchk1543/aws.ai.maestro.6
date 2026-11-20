# 00-skeleton 설계

## 흐름
```
curl POST /jobs {"files":[{"key","doc_type"}]}
  └ api/handler.py (Function URL, 이벤트 형식 2.0)
      └ agent/document_agent.run_job()
          ├ S3에서 파일 받기 (DOCS_BUCKET)
          ├ tools/extract.read_document() × N  (ThreadPoolExecutor, 서류마다 따로)
          │    └ Strands Agent + structured_output_model=RawDocument → raw만
          │    └ 코드가 value·unit 채움 → ExtractedDocument
          ├ tools/validate.cross_check()  (X-WT-01 총중량)
          └ Job(steps, result.issues) → DynamoDB team06-jobs (data 칸에 JSON 문자열)
curl GET /jobs/{id} → 저장된 Job 그대로
```

> 2026-11-20 배포 구조를 CloudFront → API Gateway(HTTP API) → API Lambda → 처리 Lambda(비동기)로 바꾸기로 했다 (#67, `infra/README.md` 목표 구조).
> 아래는 뼈대(Function URL, 동기 처리) 기준 기록이다.

## 결정
- 오늘 밤 POST /jobs 안에서 끝까지 처리한다 (동기). 응답은 처음부터 `{"job_id"}` → GET 조회 형식이다.
- 뼈대에서는 doc_type을 요청에 반드시 넣는다. null이면 400. 분류는 Spec 1에서 만든다.
- 순서는 코드(run_job)가 지킨다. 도구를 고르는 에이전트 루프는 Spec 1에서 만든다.
- 총중량은 서류 하단 합계 칸(total_gross_kg)을 쓰고, 없으면 행별 총중량을 코드가 더한다.
  행 하나라도 못 읽었으면 '확인 필요'.
- 허용 오차 0.1kg. 차이가 0이면 문제 없음, 0.1kg 이하면 참고, 넘으면 불일치.
- 서류가 셋 이상이고 한 서류만 다르면 그 서류를 suspect로 짚는다.
- 읽기 실패(형식 검증 두 번 실패, 모델 호출 실패)는 READ-FAIL '확인 필요'로 남기고 그 서류는 대조에서 뺀다.
- DynamoDB에는 Job JSON을 문자열 한 칸으로 저장한다 (float → Decimal 변환 문제를 피함).
- Bedrock 호출: max_tokens는 MAX_TOKENS 환경 변수(기본 8000), 읽기 타임아웃 120초, 재시도 1회.
  temperature 등 샘플링 값은 넣지 않는다. 응답은 블록 종류("text")로 읽는다.
- 형식 받는 방법: READ_MODE 환경 변수. `structured`(기본, Strands structured_output) | `json`(JSON 텍스트).
  S1 결과를 보고 정한다.

## S1 결과 (scripts/ping_bedrock.py 실행 후 채운다)
| 항목 | 결과 |
|---|---|
| MODEL_ID | `global.anthropic.claude-sonnet-5-5` (ap-northeast-2, 2026-11-19 확인) |
| 인사 응답·토큰 | '안녕하세요, 만나서 반갑습니다!' / 입력 26, 출력 21, 합계 47 / 0.8초 |
| structured_output 동작 | 동작함 (`Classification` → doc_type=packing_list, 근거 포함) |
| 도구 호출 | 됨 (`today` 도구, auto) |
| 서류 한 장 읽는 시간 | 미확인: samples/에 서류 없음. 받으면 `ping_bedrock <파일> <doc_type>` |
| 정한 READ_MODE | `structured` (기본값). 실제 서류에서 실패하면 `json` |

로컬 실행에는 `botocore[crt]`가 필요하다 (aws login 자격 증명). dev 의존성에 넣었다.

## S4 상태
- 2026-11-19: PM의 IAM 사용자에 `iam:CreateRole` 권한이 없어 `create.sh` 첫 단계에서 멈춤. 만든 리소스 없음.
- 2026-11-20: 대회 측이 그룹 `pnu6`(5명, AdministratorAccess)으로 권한을 열었다. 새 구조(#67)로 F1에서 배포한다.

## S5 결과
| 항목 | 결과 |
|---|---|
| POST /jobs 응답 시간 (서류 두 장) | (미확인) |

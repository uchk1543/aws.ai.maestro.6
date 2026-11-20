# infra: 리소스와 배포 (담당: PM, 배포 단독. 4번 서버는 PR로 고칠 수 있다)

리소스는 이 폴더의 스크립트로만 만든다. 콘솔이나 MCP로 즉석에서 만들거나 바꾸지 않는다.
리전은 ap-northeast-2, 이름은 모두 `team06-`으로 시작한다 (CloudFront는 전역 서비스라 예외).
대회 계정은 그룹 `pnu6`으로 5명 모두 관리자 권한이 있다. 그래도 리소스 생성·배포 실행은 PM만 한다 (team.md).

## 구조 (#67)
```
브라우저 → CloudFront `team06-web` ─┬ /*     → S3 `team06-web-<계정ID>` (화면 빌드 파일, OAC로 CloudFront만 읽음)
                                   └ /api/* → API Gateway HTTP API `team06-api` (초당 10건, 순간 20건 제한)
                                                → Lambda `team06-api` (api.handler.lambda_handler, 30초)
                                                    → 비동기 호출 → Lambda `team06-worker` (api.worker.lambda_handler, 300초)
서류 원본: S3 `team06-docs-<계정ID>/uploads/` (화면이 미리 서명된 URL로 직접 PUT, 화면 주소에서만 CORS 허용)
상태·결과: DynamoDB `team06-jobs`
```
PM과 4번 사이 이름 약속(진입점, 이벤트, 환경 변수)은 이슈 #34·#36 댓글에 있다. 바꾸려면 그 이슈에서 먼저 맞춘다.

## 리소스 목록
| 종류 | 이름 | 설정 |
|---|---|---|
| IAM 역할 | `team06-api-role` | 인라인 정책: logs, data, bedrock, invoke-worker |
| IAM 역할 | `team06-worker-role` | 인라인 정책: logs, data, bedrock, textract, cache |
| 정책 | `policy-bedrock.json` | global 추론 프로필 `global.anthropic.*`과 foundation-model(서울 + 리전 없는 global ARN) |
| 정책 | `policy-logs.json` | 두 Lambda의 로그 그룹에 쓰기 |
| 정책 | `policy-data.json` | `team06-jobs` Get/Put/UpdateItem, 서류 버킷 `uploads/*` Get/PutObject (미리 서명된 URL 포함), `team06-wms` Scan (같은 B/L 중복 등록 검사, #176) |
| 정책 | `policy-cache.json` | worker만: 서류 버킷 `cache/read/*`(판독 캐시)·`cache/ocr/*`(OCR 원본·캐시) Get/PutObject, 서류 버킷 ListBucket(없는 캐시 키가 403 대신 404로 와서 경고 로그가 안 쌓인다) (B4-L0) |
| 정책 | `policy-jobs-list.json` | API Lambda만: `team06-jobs` Scan (문서 분류 내역 `GET /api/documents`, #143) |
| 정책 | `policy-chat.json` | API Lambda만: `team06-chat` Get/Put/Query, 가드레일 `team06-chat-guard` ApplyGuardrail (APAC 프로필 도착 리전 6곳 포함, #151) |
| 가드레일 | `team06-chat-guard` (`guardrail-chat.json`) | 현황 조회 입력 검사: 프롬프트 공격 HIGH, 유해 표현. Standard 등급(한국어), `apac.guardrail.v1:0`. 거부 주제는 정상 질문을 막아(21개 중 3개) 뺐다. 바꿀 때 `update-guardrail.sh` → `create.sh`. 환경 변수 `GUARDRAIL_ID`·`GUARDRAIL_VERSION`(API Lambda) |
| 정책 | `policy-invoke-worker.json` | API Lambda가 `team06-worker`만 호출 |
| DynamoDB | `team06-jobs`, `team06-hs-history`, `team06-wms`, `team06-shipments`, `team06-chat` | 온디맨드. 키와 칸은 아래 "테이블" |
| 정책 | `policy-textract.json` | worker만: `textract:AnalyzeDocument`, `DetectDocumentText` (서울), OCR 캐시 권한은 `policy-cache.json` |
| S3 | `team06-docs-<계정ID>` | 공개 차단. `uploads/` 서류, `deploy/` 배포 zip. CORS: 화면 주소에서 PUT만 |
| S3 | `team06-web-<계정ID>` | 공개 차단. 버킷 정책 `policy-web-bucket.json`: CloudFront 배포 하나만 읽기 |
| 로그 그룹 | `/aws/lambda/team06-api`, `/aws/lambda/team06-worker` | 보존 7일 |
| Lambda | `team06-api` | Python 3.13, x86_64, 512MB, 30초, 동시 실행 상한 5. 환경 변수: 공통 + `WORKER_FUNCTION` |
| Lambda | `team06-worker` | Python 3.13, x86_64, 1024MB, 300초, 동시 실행 상한 5. 환경 변수: 공통 |
| 공통 환경 변수 | | `MODEL_ID`, `JOBS_TABLE`, `HS_HISTORY_TABLE`, `WMS_TABLE`, `SHIPMENTS_TABLE`, `DOCS_BUCKET` (`create.sh`가 이미 있는 함수도 이 값으로 맞춘다) |
| API Gateway | `team06-api` (HTTP API) | 경로 `ANY /api`, `ANY /api/{proxy+}` → team06-api (페이로드 2.0, 30초). `$default` 스테이지 자동 배포 |
| CloudFront | 설명 `team06-web` | 설정 `cloudfront.json`. 기본 → 화면 버킷(캐시), `/api/*` → API Gateway(캐시 안 함, Host 헤더 안 넘김). 기본 주소 사용 |
| OAC | `team06-web-oac` | CloudFront가 화면 버킷을 서명해서 읽음 |

## 테이블 (키와 칸 약속)
코드 쪽(4번의 DynamoDB판, 2번의 HS 이력)은 이 모양을 따른다. 바꾸려면 infra/ PR로 먼저 맞춘다.

| 테이블 | 키 (문자열) | 칸 | 쓰는 곳 |
|---|---|---|---|
| `team06-jobs` | `job_id` | `data`(Job JSON 문자열), `updated_at`(초), `docs`(읽은 서류 `ExtractedDocument` 목록 JSON 문자열), `importer`(수입자 = 상업송장 `consignee_name` raw, 못 읽었으면 칸 없음), `files`(요청한 `[{"key","doc_type"}]` JSON 문자열), `created_at`(초) | api/, 처리 Lambda. `docs`·`importer`는 처리 Lambda가 마지막 저장 때 쓰고 HS 선택·승인이 읽는다 (#122). `files`·`created_at`은 `POST /api/jobs`가 쓰고 문서 분류 내역이 읽는다 (#143) |
| `team06-hs-history` | `importer`(파티션) + `item_key`(정렬, `tools.hs.item_key`) — 4번 C3 설계(#76) | `hs`(10자리), `job_id`, `updated_at` | `HSHistory` 구현 (C2), 사람 확정 (C3) |
| `team06-wms` | `idempotency_key` = `"<B/L 번호>#<작업 ID>"` | `wms_id`, `record`(WmsRecord JSON 문자열), `registered_at` | `WmsAdapter` 구현 (D1). 같은 키는 조건부 쓰기(`attribute_not_exists`)로 한 번만. 등록 전에 Scan(`begins_with "<B/L 번호>#"`)으로 같은 B/L의 다른 작업을 찾아 있으면 등록하지 않는다 (#176) |
| `team06-shipments` | `bl_no` | Shipment 칸 그대로 (날짜는 `YYYY-MM-DD` 문자열, `job_id` 없으면 칸 없음) | `ShipmentStore` 구현 (E3·E4). 시드는 `infra/seed_shipments.py` (E2). Lambda 권한에 Scan 포함 |
| `team06-chat` | `session_id`(파티션) + `ts`(정렬, 한국 시간 `YYYYMMDDHHMMSSmmm`) | `role`(user·assistant), `text`, 답이면 `filters`·`count`·`rule`·`blocked`, `expires_at`(초, TTL 7일) | 채팅 기록 (E6 #157). 환경 변수 `CHAT_TABLE` |

### 데모·평가 전 초기화 (PM만, #170)
평가·10회 반복·데모 직전에는 확정 이력이 비어 있어야 한다 (agent-design.md 11번). 기본은 미리보기이고, `--apply`면 `reset`을 입력해야 지운다.
지우기 전에 지울 줄을 `build/reset-<시각>.json`에 남긴다.
```bash
uv run python infra/reset_demo.py --job <job_id>              # 시험 작업 하나가 남긴 줄 (HS 이력·WMS·화물 기록·작업)
uv run python infra/reset_demo.py --all                       # 처리 기록 전체 미리보기
uv run python infra/reset_demo.py --all --apply               # 비우고 시드 화물 기록 다시 넣기
uv run python infra/reset_demo.py --all --apply --s3          # 서류 버킷 uploads/·cache/read/·cache/ocr/까지
```
시드 화물 기록(job_id 칸 없음)은 지우지 않는다. 처리한 작업이 쓴 줄만 지운다.

같은 B/L은 WMS에 한 번만 들어간다 (#176). 같은 샘플 세트를 다시 올려 승인하면 409, 자동 등록은 승인 대기로 막힌다.
리허설·영상 녹화·시연 직전마다 `--all --apply`를 돌린다 (시험으로 남은 WMS 줄도 같은 세트를 막는다).

### 테이블 키 바꾸기
`create.sh`는 이미 있는 테이블의 키가 다르면 멈춘다. 키는 만든 뒤 바꿀 수 없어서 지우고 다시 만들어야 한다.
PM이 승인한 뒤 `recreate-table.sh`로만 지운다 (지운 데이터는 되돌릴 수 없다). 손으로 `delete-table`을 쓰지 않는다.
```bash
# 1. create.sh의 ensure_table 줄을 새 키로 고치는 PR을 먼저 합친다
# 2. 최신 main에서
MODEL_ID=global.anthropic.claude-sonnet-5-5 bash infra/recreate-table.sh <테이블 이름>
```
스크립트가 지키는 것: `team06-` 테이블만, 키가 이미 맞으면 아무것도 안 함, 항목이 하나라도 있으면 멈춤, 지우기 전에 테이블 이름을 한 번 더 입력받음.
지운 뒤 `create.sh`를 불러 새 키로 만들고 두 Lambda 환경 변수도 맞춘다.

## 실행 순서 (PM)
```bash
aws login && aws sts get-caller-identity       # 계정 <계정ID>, 사용자 확인
git switch main && git pull && uv sync && uv run pytest -q

# 처음 한 번: 리소스 만들기 (있으면 건너뜀, 지우지 않음). CloudFront가 퍼지는 데 5~10분
MODEL_ID=global.anthropic.claude-sonnet-5-5 bash infra/create.sh
curl -s https://<CloudFront 주소>/api/            # 4번 F3 전: 핸들러 404 JSON / F3 뒤: {"ok": true}

# 가상 화물 기록 넣기 (E2). 시드 파일이 바뀌면 다시 (같은 bl_no는 덮어씀)
uv run python infra/seed_shipments.py           # 검사만
uv run python infra/seed_shipments.py --apply

# 배포 시각(15·18·23·03·07시, 데모 직전)마다: 두 Lambda 코드 갱신
bash infra/deploy.sh

# 화면 빌드가 생기면 (F5)
WEB_DIST=web/dist bash infra/deploy-web.sh
```

모델 ID를 바꿀 때 (설정만 바뀜): 두 함수 모두 `aws lambda update-function-configuration --environment ...`로 바꾼다. 다른 환경 변수도 함께 넣어야 한다(덮어쓰기).

## 끝까지 한 번 (F3 뒤)
화면과 같은 순서(업로드 URL → S3 PUT → 작업, doc_type null → 조회)를 공개 주소로 돌린다. AWS 자격 증명이 필요 없다.
```bash
uv run python -m scripts.e2e_upload https://<CloudFront 주소> samples/dev/D003/doc_a.pdf samples/dev/D003/doc_b.pdf samples/dev/D003/doc_c.pdf samples/dev/D003/doc_d.pdf
```
S3에 직접 올려 보는 옛 방법:
```bash
BUCKET=team06-docs-<계정ID>
aws s3 cp <상업송장>.pdf s3://$BUCKET/uploads/s1/invoice.pdf
aws s3 cp <포장명세서>.pdf s3://$BUCKET/uploads/s1/packing_list.pdf
URL=https://<CloudFront 주소>
curl -s -X POST "$URL/api/jobs" -H 'content-type: application/json' \
  -d '{"files":[{"key":"uploads/s1/invoice.pdf","doc_type":"commercial_invoice"},{"key":"uploads/s1/packing_list.pdf","doc_type":"packing_list"}]}'
curl -s "$URL/api/jobs/<job_id>"                # queued → running → waiting_approval·done
```

## 로컬 확인 (AWS 없이)
- `uv run pytest -q`: 핸들러·읽기·대조를 가짜 DynamoDB·S3·모델로 확인한다.
- 모델 호출: `MODEL_ID=... uv run python -m scripts.ping_bedrock [서류 경로 doc_type]` (로컬 aws login 필요)

## 남은 일
- [x] F1 `create.sh` 실행, CloudFront → API Gateway → Lambda 연결 확인
- [x] F3(4번) 합친 뒤 `deploy.sh`, `/api/` → `{"ok": true}`, 끝까지 한 번 (2026-11-20, `scripts/e2e_upload.py`, D003 4장 14.7초)
- [x] F4 Textract 권한(worker), team06-hs-history·team06-wms 테이블과 권한, 환경 변수 (HS 이력 키는 C3 설계로 맞춤)
- [x] E2 team06-shipments 테이블과 시드 넣기 (`infra/seed_shipments.py`)
- [x] F5 화면 빌드 올리기 (`deploy-web.sh`)
- [ ] F6 배포 시각마다 배포, `team06-` 아닌 리소스·서울 밖 리소스(CloudFront 제외) 점검

## 알려진 문제와 주의
- **패키징 플랫폼**: `x86_64-manylinux_2_28`을 쓴다. pillow 13(strands-agents-tools 의존성)에 manylinux2014 휠이 없다. 2_28은 Lambda Python 3.13(Amazon Linux 2023, glibc 2.34)에서 돈다.
- **zip 크기**: 약 51MB(압축 전 약 153MB). 직접 업로드 한도 50MB를 넘어 S3(`deploy/`)를 거쳐 올린다. 두 Lambda가 같은 zip을 쓴다.
- **API 시간 제한**: API Gateway는 요청 하나를 30초 안에 끝내야 한다. 서류 처리는 반드시 처리 Lambda로 넘긴다 (F3).
- **화면 라우팅**: CloudFront의 오류 응답 바꾸기(404 → index.html)를 쓰지 않는다. 배포 전체에 걸려 `/api`의 404 JSON까지 바뀐다. 화면은 해시 라우팅(`#/jobs/…`)을 쓴다.
- **공개 주소**: 인증 없이 누구나 부를 수 있다. API 요청 제한(초당 10건), Lambda 동시 실행 상한 5, 요청 검사(`uploads/` 키만, 서류 10개까지, 4.5MB까지)로 비용과 피해를 줄인다.
- **Bedrock 정책 범위**: `global.anthropic.*` 추론 프로필만 허용한다. 다른 프로필을 쓰면 `policy-bedrock.json`을 고친 뒤 `create.sh`를 다시 실행한다(인라인 정책만 덮어씀).
- **같은 계정의 다른 팀 리소스**: `team06-`으로 시작하지 않는 리소스는 조회도 하지 말고 절대 바꾸지 않는다.

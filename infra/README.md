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
| IAM 역할 | `team06-worker-role` | 인라인 정책: logs, data, bedrock |
| 정책 | `policy-bedrock.json` | global 추론 프로필 `global.anthropic.*`과 foundation-model(서울 + 리전 없는 global ARN) |
| 정책 | `policy-logs.json` | 두 Lambda의 로그 그룹에 쓰기 |
| 정책 | `policy-data.json` | `team06-jobs` Get/Put/UpdateItem, 서류 버킷 `uploads/*` Get/PutObject (미리 서명된 URL 포함) |
| 정책 | `policy-invoke-worker.json` | API Lambda가 `team06-worker`만 호출 |
| DynamoDB | `team06-jobs`, `team06-hs-history`, `team06-wms`, `team06-shipments` | 온디맨드. 키와 칸은 아래 "테이블" |
| 정책 | `policy-textract.json` | worker만: `textract:AnalyzeDocument`, `DetectDocumentText` (서울) |
| S3 | `team06-docs-<계정ID>` | 공개 차단. `uploads/` 서류, `deploy/` 배포 zip. CORS: 화면 주소에서 PUT만 |
| S3 | `team06-web-<계정ID>` | 공개 차단. 버킷 정책 `policy-web-bucket.json`: CloudFront 배포 하나만 읽기 |
| 로그 그룹 | `/aws/lambda/team06-api`, `/aws/lambda/team06-worker` | 보존 7일 |
| Lambda | `team06-api` | Python 3.13, x86_64, 512MB, 30초, 동시 실행 상한 5. 환경 변수: 공통 + `WORKER_FUNCTION` |
| Lambda | `team06-worker` | Python 3.13, x86_64, 1024MB, 300초, 동시 실행 상한 5. 환경 변수: 공통 |
| 공통 환경 변수 | | `MODEL_ID`, `JOBS_TABLE`, `HS_TABLE`, `WMS_TABLE`, `SHIPMENTS_TABLE`, `DOCS_BUCKET` (`create.sh`가 이미 있는 함수도 이 값으로 맞춘다) |
| API Gateway | `team06-api` (HTTP API) | 경로 `ANY /api`, `ANY /api/{proxy+}` → team06-api (페이로드 2.0, 30초). `$default` 스테이지 자동 배포 |
| CloudFront | 설명 `team06-web` | 설정 `cloudfront.json`. 기본 → 화면 버킷(캐시), `/api/*` → API Gateway(캐시 안 함, Host 헤더 안 넘김). 기본 주소 사용 |
| OAC | `team06-web-oac` | CloudFront가 화면 버킷을 서명해서 읽음 |

## 테이블 (키와 칸 약속)
코드 쪽(4번의 DynamoDB판, 2번의 HS 이력)은 이 모양을 따른다. 바꾸려면 infra/ PR로 먼저 맞춘다.

| 테이블 | 키 (문자열) | 칸 | 쓰는 곳 |
|---|---|---|---|
| `team06-jobs` | `job_id` | `data`(Job JSON 문자열), `updated_at`(초) | api/, 처리 Lambda |
| `team06-hs-history` | `pk` = `"<수입자>#<품목 키>"` (품목 키는 `tools.hs.item_key`) | `hs`(10자리), `job_id`, `updated_at` | `HSHistory` 구현 (C2), 사람 확정 (C3) |
| `team06-wms` | `idempotency_key` = `"<B/L 번호>#<작업 ID>"` | `wms_id`, `record`(WmsRecord JSON 문자열), `registered_at` | `WmsAdapter` 구현 (D1). 같은 키는 조건부 쓰기(`attribute_not_exists`)로 한 번만 |
| `team06-shipments` | `bl_no` | Shipment 칸 그대로 (날짜는 `YYYY-MM-DD` 문자열, `job_id` 없으면 칸 없음) | `ShipmentStore` 구현 (E3·E4). 시드는 `infra/seed_shipments.py` (E2). Lambda 권한에 Scan 포함 |

## 실행 순서 (PM)
```bash
aws login && aws sts get-caller-identity       # 계정 465105354705, 사용자 확인
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
```bash
BUCKET=team06-docs-465105354705
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
- [ ] F1 `create.sh` 실행, CloudFront → API Gateway → Lambda 연결 확인
- [ ] F3(4번) 합친 뒤 `deploy.sh`, `/api/` → `{"ok": true}`, 끝까지 한 번
- [x] F4 Textract 권한(worker), team06-hs-history·team06-wms 테이블과 권한, 환경 변수
- [x] E2 team06-shipments 테이블과 시드 넣기 (`infra/seed_shipments.py`)
- [ ] F5 화면 빌드 올리기 (`deploy-web.sh`)
- [ ] F6 배포 시각마다 배포, `team06-` 아닌 리소스·서울 밖 리소스(CloudFront 제외) 점검

## 알려진 문제와 주의
- **패키징 플랫폼**: `x86_64-manylinux_2_28`을 쓴다. pillow 13(strands-agents-tools 의존성)에 manylinux2014 휠이 없다. 2_28은 Lambda Python 3.13(Amazon Linux 2023, glibc 2.34)에서 돈다.
- **zip 크기**: 약 51MB(압축 전 약 153MB). 직접 업로드 한도 50MB를 넘어 S3(`deploy/`)를 거쳐 올린다. 두 Lambda가 같은 zip을 쓴다.
- **API 시간 제한**: API Gateway는 요청 하나를 30초 안에 끝내야 한다. 서류 처리는 반드시 처리 Lambda로 넘긴다 (F3).
- **화면 라우팅**: CloudFront의 오류 응답 바꾸기(404 → index.html)를 쓰지 않는다. 배포 전체에 걸려 `/api`의 404 JSON까지 바뀐다. 화면은 해시 라우팅(`#/jobs/…`)을 쓴다.
- **공개 주소**: 인증 없이 누구나 부를 수 있다. API 요청 제한(초당 10건), Lambda 동시 실행 상한 5, 요청 검사(`uploads/` 키만, 서류 10개까지, 4.5MB까지)로 비용과 피해를 줄인다.
- **Bedrock 정책 범위**: `global.anthropic.*` 추론 프로필만 허용한다. 다른 프로필을 쓰면 `policy-bedrock.json`을 고친 뒤 `create.sh`를 다시 실행한다(인라인 정책만 덮어씀).
- **같은 계정의 다른 팀 리소스**: `team06-`으로 시작하지 않는 리소스는 조회도 하지 말고 절대 바꾸지 않는다.

# infra: 뼈대 리소스와 배포 (담당: PM, 배포 단독. 4번 서버는 PR로 고칠 수 있다)

리소스는 이 폴더의 스크립트로만 만든다. 콘솔이나 MCP로 즉석에서 만들거나 바꾸지 않는다.
리전은 ap-northeast-2, 이름은 모두 `team06-`으로 시작한다.

## 리소스 목록
| 종류 | 이름 | 설정 |
|---|---|---|
| IAM 역할 | `team06-agent-role` | Lambda 신뢰 정책(`trust-lambda.json`), 인라인 정책 3개 |
| 인라인 정책 | `team06-bedrock` | `policy-bedrock.json`: global 추론 프로필 `global.anthropic.*`과 foundation-model(서울 + 리전 없는 global ARN), InvokeModel·InvokeModelWithResponseStream |
| 인라인 정책 | `team06-logs` | `policy-logs.json`: `/aws/lambda/team06-agent` 로그 스트림 쓰기 |
| 인라인 정책 | `team06-data` | `policy-data.json`: `team06-jobs` Get/Put/UpdateItem, 버킷 `uploads/*` Get/PutObject |
| DynamoDB | `team06-jobs` | 키 `job_id`(S), 온디맨드. 칸: `data`(Job JSON 문자열), `updated_at` |
| S3 | `team06-docs-<계정ID>` | 공개 차단. `uploads/`: 서류, `deploy/`: 배포 zip |
| 로그 그룹 | `/aws/lambda/team06-agent` | 보존 7일 |
| Lambda | `team06-agent` | Python 3.13, x86_64, 1024MB, 제한 시간 300초, 핸들러 `api.handler.lambda_handler` |
| Lambda 환경 변수 | | `MODEL_ID`, `JOBS_TABLE=team06-jobs`, `DOCS_BUCKET=team06-docs-<계정ID>` |
| 동시 실행 상한 | | 5 (공개 URL 비용 상한) |
| Function URL | | 인증 NONE, CORS `*` GET/POST, 리소스 정책 2개(InvokeFunctionUrl, InvokeFunction + InvokedViaFunctionUrl) |

## 배포하는 사람의 권한
`create.sh`·`deploy.sh`를 실행하는 IAM 사용자에게 `policy-deployer.json` 권한이 있어야 한다 (team06-* 리소스만, 서울만).
붙일 때 `__ACCOUNT_ID__`를 계정 번호로 바꾼다.
2026-11-19 PM의 IAM 사용자는 `iam:CreateRole`이 없어 S4 첫 단계에서 멈췄다 (만든 리소스 없음). 계정 관리자가 이 정책을 붙여야 진행된다.

## 실행 순서
```bash
aws login                                   # 브라우저 로그인 (ExpiredToken이면 다시)
aws configure set region ap-northeast-2
uv sync && uv run pytest -q                 # 먼저 테스트 통과 확인

# 처음 한 번: 리소스 만들기 (있으면 건너뜀, 지우지 않음)
MODEL_ID=<global.anthropic... 추론 프로필 ID> bash infra/create.sh
curl <출력된 URL>                            # {"ok": true}

# 코드만 다시 배포 (main 최신으로 받은 뒤)
bash infra/deploy.sh
```

모델 ID를 바꿀 때 (설정만 바뀜, 코드는 그대로):
```bash
aws lambda update-function-configuration --function-name team06-agent \
  --environment "Variables={MODEL_ID=<새 ID>,JOBS_TABLE=team06-jobs,DOCS_BUCKET=team06-docs-<계정ID>}"
```

## 끝까지 한 번 (S5 확인)
```bash
BUCKET=team06-docs-$(aws sts get-caller-identity --query Account --output text)
aws s3 cp samples/<송장>.pdf s3://$BUCKET/uploads/s1/invoice.pdf
aws s3 cp samples/<포장명세서>.pdf s3://$BUCKET/uploads/s1/packing_list.pdf
URL=<Function URL>
time curl -s -X POST "${URL}jobs" -H 'content-type: application/json' \
  -d '{"files":[{"key":"uploads/s1/invoice.pdf","doc_type":"commercial_invoice"},{"key":"uploads/s1/packing_list.pdf","doc_type":"packing_list"}]}'
curl -s "${URL}jobs/<job_id>"                 # result.issues 확인
```
응답 시간은 `.kiro/specs/00-skeleton/design.md`의 S5 결과에 적는다.

## 로컬 확인 (AWS 없이)
- `uv run pytest -q`: 핸들러·읽기·대조를 가짜 DynamoDB·S3·모델로 확인한다.
- 모델 첫 호출: `MODEL_ID=... uv run python -m scripts.ping_bedrock [서류 경로 doc_type]` (로컬 aws login 필요)

## 남은 일
- [ ] S1 실행과 결과 기록 (`design.md` S1 표), READ_MODE 결정
- [ ] S4 `create.sh` 실행, curl `{"ok": true}` 확인
- [ ] S5 실제 서류 두 장으로 끝까지 한 번, 응답 시간 기록
- [ ] POST /uploads(미리 서명된 URL), 비동기 처리, Textract 권한, team06-shipments·hs-history 테이블 (Spec 2·3)
- [ ] 8장 점검: `team06-` 아닌 리소스나 서울 밖 리소스가 없는지

## 알려진 문제와 주의
- **패키징 플랫폼**: `x86_64-manylinux_2_28`을 쓴다. pillow 13(strands-agents-tools 의존성)에 manylinux2014 휠이 없기 때문이다. 2_28은 2014 휠도 받고, Lambda Python 3.13(Amazon Linux 2023, glibc 2.34)에서 돈다.
- **zip 크기**: 약 51MB, 압축 전 약 153MB. 직접 업로드 한도 50MB를 넘어서 S3(`deploy/`)를 거쳐 올린다. 압축 전 한도는 250MB다. 큰 의존성은 sympy, botocore, cryptography, pillow 순이고 대부분 strands-agents-tools에서 온다. Lambda에서 strands-agents-tools를 쓰지 않으면 빼서 줄일 수 있다.
- **동시 실행 상한**: 계정의 동시 실행 한도가 낮으면(예: 10) `put-function-concurrency`가 실패한다. 그때는 Service Quotas에서 Lambda 동시 실행 한도 상향을 요청한다. 상한 없이 공개 URL을 두지 않는다.
- **Bedrock 정책 범위**: `global.anthropic.*` 추론 프로필만 허용한다. 다른 프로필(예: `apac.`)을 쓰면 `policy-bedrock.json`을 고친 뒤 `create.sh`를 다시 실행한다(인라인 정책만 덮어씀).
- **모델 접근**: 계정에서 해당 Anthropic 모델 사용이 허용되어 있어야 한다. AccessDenied가 나면 Bedrock 콘솔의 모델 접근 상태를 먼저 본다.
- **동기 처리**: POST /jobs 안에서 끝까지 처리한다. Function URL은 최대 15분, 함수 제한 시간은 300초다. 서류가 많으면 비동기로 바꾼다(2일차).
- **공개 URL**: 인증 없이 누구나 부를 수 있다. 동시 실행 상한 5와 요청 검사(`uploads/` 키만, 서류 10개까지, 4.5MB까지)로 피해를 줄인다.

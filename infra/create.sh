#!/usr/bin/env bash
# 새 구조(#67) 리소스를 처음 한 번 만든다. 이미 있으면 건너뛴다 (지우거나 바꾸지 않는다). 실행: PM만.
#   MODEL_ID=<global 추론 프로필 ID> bash infra/create.sh
# 만드는 것
#   IAM 역할 team06-api-role, team06-worker-role (인라인 정책만, 필요한 권한만. worker에만 Textract)
#   DynamoDB team06-jobs, team06-hs-history, team06-wms, team06-shipments
#   S3 team06-docs-<계정>(서류·배포 zip), team06-web-<계정>(화면, CloudFront만 읽음)
#   로그 그룹 2개(보존 7일), Lambda team06-api(30초) · team06-worker(300초), 각각 동시 실행 상한 5
#   API Gateway HTTP API team06-api (/api, /api/{proxy+}, 요청 제한), CloudFront team06-web (/* → S3, /api/* → API)
source "$(dirname "$0")/config.sh"

: "${MODEL_ID:?MODEL_ID 환경 변수가 필요합니다}"
case "${MODEL_ID}" in global.anthropic.*) ;; *)
  echo "MODEL_ID는 global.anthropic. 로 시작해야 합니다 (policy-bedrock.json 범위)"; exit 1;;
esac
echo "[create] 계정 ${ACCOUNT_ID}, 리전 ${AWS_REGION}"
mkdir -p "${BUILD}"

# ---------------------------------------------------------------------------
# 1. IAM 역할 두 개
# ---------------------------------------------------------------------------
ensure_role() {
  local role="$1"; shift
  if aws iam get-role --role-name "${role}" >/dev/null 2>&1; then
    echo "[create] 역할 ${role} 있음"
  else
    aws iam create-role --role-name "${role}" \
      --assume-role-policy-document "file://${ROOT}/infra/trust-lambda.json" >/dev/null
    echo "[create] 역할 ${role} 만듦"
  fi
  local name
  for name in "$@"; do
    aws iam put-role-policy --role-name "${role}" --policy-name "team06-${name}" \
      --policy-document "file://$(render "policy-${name}.json")"
  done
}
ensure_role "${ROLE_API}" logs data bedrock invoke-worker jobs-list  # jobs-list: 문서 분류 내역 GET /documents (#143)
ensure_role "${ROLE_WORKER}" logs data bedrock textract

# ---------------------------------------------------------------------------
# 2. DynamoDB 테이블 (모두 온디맨드, 문자열 키. 정렬 키는 있을 때만)
# ---------------------------------------------------------------------------
# 이미 있는 테이블의 키가 다르면 지우지 않고 멈춘다 (지우는 것은 PM이 따로 승인하고 한다)
ensure_table() {
  local table="$1" hash="$2" range="${3:-}" want have
  want="${hash}${range:+,${range}}"
  if have=$(aws dynamodb describe-table --table-name "${table}" \
      --query "join(',', Table.KeySchema[].AttributeName)" --output text 2>/dev/null); then
    if [ "${have}" != "${want}" ]; then
      echo "[create] 테이블 ${table}의 키가 다릅니다 (지금 ${have}, 맞는 것 ${want}). 지우고 다시 만들어야 합니다 → infra/README.md '테이블 키 바꾸기'"
      exit 1
    fi
    echo "[create] 테이블 ${table} 있음 (키 ${have})"
    return
  fi
  local attrs="AttributeName=${hash},AttributeType=S" keys="AttributeName=${hash},KeyType=HASH"
  if [ -n "${range}" ]; then
    attrs="${attrs} AttributeName=${range},AttributeType=S"
    keys="${keys} AttributeName=${range},KeyType=RANGE"
  fi
  # shellcheck disable=SC2086
  aws dynamodb create-table --table-name "${table}" --attribute-definitions ${attrs} \
    --key-schema ${keys} --billing-mode PAY_PER_REQUEST >/dev/null
  aws dynamodb wait table-exists --table-name "${table}"
  echo "[create] 테이블 ${table} 만듦 (키 ${want})"
}
ensure_table "${TABLE}" job_id
ensure_table "${HS_HISTORY_TABLE}" importer item_key
ensure_table "${WMS_TABLE}" idempotency_key
ensure_table "${SHIPMENTS_TABLE}" bl_no

# ---------------------------------------------------------------------------
# 3. S3 버킷 두 개 (둘 다 공개 차단)
# ---------------------------------------------------------------------------
ensure_bucket() {
  if aws s3api head-bucket --bucket "$1" >/dev/null 2>&1; then
    echo "[create] 버킷 $1 있음"
  else
    aws s3api create-bucket --bucket "$1" --create-bucket-configuration LocationConstraint=ap-northeast-2 >/dev/null
    echo "[create] 버킷 $1 만듦"
  fi
  aws s3api put-public-access-block --bucket "$1" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
}
ensure_bucket "${BUCKET}"
ensure_bucket "${WEB_BUCKET}"

# ---------------------------------------------------------------------------
# 4. 로그 그룹 (보존 7일)
# ---------------------------------------------------------------------------
for fn in "${FN_API}" "${FN_WORKER}"; do
  aws logs create-log-group --log-group-name "/aws/lambda/${fn}" 2>/dev/null || true
  aws logs put-retention-policy --log-group-name "/aws/lambda/${fn}" --retention-in-days 7
done

# ---------------------------------------------------------------------------
# 5. Lambda 두 개 (같은 zip, 진입점만 다름)
# ---------------------------------------------------------------------------
package_and_upload
ensure_function() {
  local fn="$1" handler="$2" role="$3" timeout="$4" memory="$5" env="$6"
  if aws lambda get-function --function-name "${fn}" >/dev/null 2>&1; then
    echo "[create] 함수 ${fn} 있음. 코드 갱신은 deploy.sh"
  else
    local role_arn attempt
    role_arn=$(aws iam get-role --role-name "${role}" --query Role.Arn --output text)
    # 새 역할은 몇 초 뒤에 쓸 수 있어 몇 번 다시 시도한다
    for attempt in 1 2 3 4 5 6; do
      if aws lambda create-function --function-name "${fn}" \
        --runtime python3.13 --architectures x86_64 --memory-size "${memory}" --timeout "${timeout}" \
        --handler "${handler}" --role "${role_arn}" \
        --code "S3Bucket=${BUCKET},S3Key=${CODE_KEY}" \
        --environment "Variables={${env}}" >/dev/null 2>"${BUILD}/create-function.err"; then
        echo "[create] 함수 ${fn} 만듦"; break
      fi
      if grep -q "cannot be assumed" "${BUILD}/create-function.err" && [ "${attempt}" -lt 6 ]; then
        echo "[create] 역할 전파 대기 (${attempt}/6)"; sleep 10
      else
        cat "${BUILD}/create-function.err"; exit 1
      fi
    done
    aws lambda wait function-active-v2 --function-name "${fn}"
  fi
  aws lambda put-function-concurrency --function-name "${fn}" --reserved-concurrent-executions 5 >/dev/null
}
COMMON_ENV="MODEL_ID=${MODEL_ID},JOBS_TABLE=${TABLE},HS_HISTORY_TABLE=${HS_HISTORY_TABLE},WMS_TABLE=${WMS_TABLE},SHIPMENTS_TABLE=${SHIPMENTS_TABLE},DOCS_BUCKET=${BUCKET}"
WORKER_ENV="${COMMON_ENV}"
API_ENV="${COMMON_ENV},WORKER_FUNCTION=${FN_WORKER}"
ensure_function "${FN_WORKER}" "${HANDLER_WORKER}" "${ROLE_WORKER}" 300 1024 "${WORKER_ENV}"
ensure_function "${FN_API}" "${HANDLER_API}" "${ROLE_API}" 30 512 "${API_ENV}"

# 환경 변수는 이미 있는 함수도 이 스크립트 값으로 맞춘다 (테이블이 늘면 여기만 고친다).
# 바뀌는 것: 두 함수의 환경 변수만. 코드·메모리·제한 시간은 그대로.
sync_env() {
  local fn="$1" env="$2" current
  current=$(aws lambda get-function-configuration --function-name "${fn}" --query "Environment.Variables" --output json)
  if python3 -c 'import json,sys; want=dict(p.split("=",1) for p in sys.argv[1].split(",")); sys.exit(0 if want == (json.loads(sys.argv[2]) or {}) else 1)' "${env}" "${current}"; then
    echo "[create] ${fn} 환경 변수 그대로"
  else
    aws lambda update-function-configuration --function-name "${fn}" --environment "Variables={${env}}" >/dev/null
    aws lambda wait function-updated-v2 --function-name "${fn}"
    echo "[create] ${fn} 환경 변수 맞춤"
  fi
}
sync_env "${FN_WORKER}" "${WORKER_ENV}"
sync_env "${FN_API}" "${API_ENV}"

# ---------------------------------------------------------------------------
# 6. API Gateway HTTP API (/api, /api/{proxy+} → team06-api)
# ---------------------------------------------------------------------------
API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text)
if [ "${API_ID}" != "None" ] && [ -n "${API_ID}" ]; then
  echo "[create] API ${API_NAME} 있음 (${API_ID})"
else
  API_ID=$(aws apigatewayv2 create-api --name "${API_NAME}" --protocol-type HTTP --query ApiId --output text)
  INTEGRATION_ID=$(aws apigatewayv2 create-integration --api-id "${API_ID}" --integration-type AWS_PROXY \
    --integration-uri "$(fn_arn "${FN_API}")" --payload-format-version 2.0 --timeout-in-millis 30000 \
    --query IntegrationId --output text)
  for route in "ANY /api" "ANY /api/{proxy+}"; do
    aws apigatewayv2 create-route --api-id "${API_ID}" --route-key "${route}" \
      --target "integrations/${INTEGRATION_ID}" >/dev/null
  done
  # 요청 제한: 초당 10건, 순간 20건 (공개 주소 비용 상한)
  aws apigatewayv2 create-stage --api-id "${API_ID}" --stage-name '$default' --auto-deploy \
    --default-route-settings '{"ThrottlingBurstLimit":20,"ThrottlingRateLimit":10}' >/dev/null
  aws lambda add-permission --function-name "${FN_API}" --statement-id team06-apigw \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*" >/dev/null
  echo "[create] API ${API_NAME} 만듦 (${API_ID})"
fi
API_DOMAIN="${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"

# ---------------------------------------------------------------------------
# 7. CloudFront (/* → 화면 버킷, /api/* → API Gateway)
# ---------------------------------------------------------------------------
OAC_ID=$(aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='${OAC_NAME}'].Id | [0]" --output text)
if [ "${OAC_ID}" = "None" ] || [ -z "${OAC_ID}" ]; then
  OAC_ID=$(aws cloudfront create-origin-access-control --origin-access-control-config \
    "Name=${OAC_NAME},SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" \
    --query OriginAccessControl.Id --output text)
  echo "[create] OAC ${OAC_NAME} 만듦"
fi

DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='${DIST_COMMENT}'].Id | [0]" --output text)
if [ "${DIST_ID}" != "None" ] && [ -n "${DIST_ID}" ]; then
  echo "[create] CloudFront ${DIST_COMMENT} 있음 (${DIST_ID})"
else
  CONFIG=$(render cloudfront.json "CALLER_REF=team06-web-$(date +%s)" "OAC_ID=${OAC_ID}" "API_DOMAIN=${API_DOMAIN}" \
    "CACHE_OPTIMIZED=${CACHE_OPTIMIZED}" "CACHE_DISABLED=${CACHE_DISABLED}" "ORIGIN_ALL_EXCEPT_HOST=${ORIGIN_ALL_EXCEPT_HOST}")
  DIST_ID=$(aws cloudfront create-distribution --distribution-config "file://${CONFIG}" --query Distribution.Id --output text)
  echo "[create] CloudFront ${DIST_COMMENT} 만듦 (${DIST_ID}). 퍼지는 데 몇 분 걸린다"
fi
DIST_ARN="arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${DIST_ID}"
WEB_DOMAIN=$(aws cloudfront get-distribution --id "${DIST_ID}" --query Distribution.DomainName --output text)

# 화면 버킷은 이 CloudFront만 읽는다. 서류 버킷은 화면 주소에서 미리 서명된 URL로 PUT만 받는다
aws s3api put-bucket-policy --bucket "${WEB_BUCKET}" \
  --policy "file://$(render policy-web-bucket.json "DIST_ARN=${DIST_ARN}")"
aws s3api put-bucket-cors --bucket "${BUCKET}" \
  --cors-configuration "file://$(render s3-cors-docs.json "WEB_DOMAIN=${WEB_DOMAIN}")"

# 화면이 아직 없으면 자리표시 페이지 하나 (3번이 빌드하면 deploy-web.sh가 덮어쓴다)
if ! aws s3api head-object --bucket "${WEB_BUCKET}" --key index.html >/dev/null 2>&1; then
  printf '<!doctype html><meta charset="utf-8"><title>6팀</title><p>6팀 물류 문서 Agent: 화면 준비 중</p>\n' > "${BUILD}/index.html"
  aws s3 cp --only-show-errors --content-type "text/html; charset=utf-8" "${BUILD}/index.html" "s3://${WEB_BUCKET}/index.html"
fi

echo "[create] CloudFront가 퍼지기를 기다린다 (보통 5~10분)"
aws cloudfront wait distribution-deployed --id "${DIST_ID}"
echo "[create] 끝"
echo "  화면: https://${WEB_DOMAIN}/"
echo "  API : https://${WEB_DOMAIN}/api/   (4번 F3 전에는 핸들러의 404 JSON이 정상)"

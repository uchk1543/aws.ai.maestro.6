#!/usr/bin/env bash
# 공통 설정. create.sh, deploy.sh, deploy-web.sh가 source 한다. 서울 리전, team06- 이름만 쓴다.
# 구조 (#67): CloudFront ─┬ /*     → S3 화면 버킷
#                         └ /api/* → API Gateway HTTP API → Lambda team06-api ─비동기→ Lambda team06-worker
set -euo pipefail

export AWS_REGION=ap-northeast-2
export AWS_DEFAULT_REGION=ap-northeast-2

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Lambda 두 개 (진입점 약속: 이슈 #34·#36 댓글)
FN_API=team06-api                       # 짧은 요청 (업로드 URL, 작업 생성·조회, HS 선택, 승인, 채팅)
FN_WORKER=team06-worker                 # 서류 처리 (run_job)
HANDLER_API=api.handler.lambda_handler
HANDLER_WORKER=api.worker.lambda_handler
ROLE_API=team06-api-role
ROLE_WORKER=team06-worker-role

# 데이터
TABLE=team06-jobs
BUCKET="team06-docs-${ACCOUNT_ID}"      # 서류 원본(uploads/)과 배포 zip(deploy/)
WEB_BUCKET="team06-web-${ACCOUNT_ID}"   # 화면 빌드 파일 (CloudFront만 읽음)

# 입구
API_NAME=team06-api                     # API Gateway HTTP API
DIST_COMMENT=team06-web                 # CloudFront 배포를 찾는 표시
OAC_NAME=team06-web-oac

CODE_KEY="deploy/team06-lambda.zip"     # 두 Lambda가 같은 zip을 쓴다

# CloudFront 관리형 정책 (이름으로 찾은 ID, 2026-11-20 확인)
CACHE_OPTIMIZED=658327ea-f89d-4fab-a63d-7e88639e58f6      # Managed-CachingOptimized (화면)
CACHE_DISABLED=4135ea2d-6df8-44a3-9df3-4b5a84be39ad       # Managed-CachingDisabled (API)
ORIGIN_ALL_EXCEPT_HOST=b689b0a8-53d0-40ab-baf2-68738e2966ac  # Managed-AllViewerExceptHostHeader (API로 Host를 넘기지 않음)

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BUILD="${ROOT}/build"

# infra/ 의 JSON 틀에서 __이름__ 자리를 채워 build/ 에 쓰고 경로를 돌려준다
# 쓰는 자리: __ACCOUNT_ID__ __BUCKET__ __WEB_BUCKET__ 와 호출할 때 넘기는 KEY=VALUE
render() {
  local file="$1"; shift
  mkdir -p "${BUILD}/rendered"
  local out="${BUILD}/rendered/${file}"
  sed -e "s|__ACCOUNT_ID__|${ACCOUNT_ID}|g" -e "s|__BUCKET__|${BUCKET}|g" -e "s|__WEB_BUCKET__|${WEB_BUCKET}|g" \
    "${ROOT}/infra/${file}" > "${out}"
  local pair
  for pair in "$@"; do
    sed -i.bak "s|__${pair%%=*}__|${pair#*=}|g" "${out}" && rm -f "${out}.bak"
  done
  echo "${out}"
}

# 코드와 의존성을 Lambda(x86_64, Python 3.13)용 zip으로 묶어 S3에 올린다
package_and_upload() {
  # manylinux_2_28은 2014 휠도 받는다. pillow 13 이후 2014 휠이 없어 2_28로 둔다 (Lambda AL2023 glibc 2.34)
  # zip이 50MB를 넘어 직접 업로드 대신 S3를 거친다
  echo "[deploy] 패키징 (manylinux_2_28 x86_64, Python 3.13)"
  rm -rf "${BUILD}/pkg" "${BUILD}/team06-lambda.zip"
  mkdir -p "${BUILD}/pkg"
  (cd "${ROOT}" && uv export --frozen --no-dev --no-hashes --no-emit-project -o "${BUILD}/requirements.txt" >/dev/null)
  uv pip install --quiet --target "${BUILD}/pkg" \
    --python-platform x86_64-manylinux_2_28 --python-version 3.13 --only-binary=:all: \
    -r "${BUILD}/requirements.txt"
  cp -R "${ROOT}/agent" "${ROOT}/tools" "${ROOT}/api" "${BUILD}/pkg/"
  find "${BUILD}/pkg" -name "__pycache__" -type d -prune -exec rm -rf {} +
  (cd "${BUILD}/pkg" && zip -qr "../team06-lambda.zip" .)
  echo "[deploy] zip 크기: $(du -h "${BUILD}/team06-lambda.zip" | cut -f1)"
  aws s3 cp --only-show-errors "${BUILD}/team06-lambda.zip" "s3://${BUCKET}/${CODE_KEY}"
}

# Lambda 함수 ARN
fn_arn() { echo "arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:$1"; }

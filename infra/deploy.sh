#!/usr/bin/env bash
# 두 Lambda의 코드만 다시 배포한다 (리소스 설정은 바꾸지 않는다). 실행: PM만, 최신 main에서.
#   git switch main && git pull && bash infra/deploy.sh
source "$(dirname "$0")/config.sh"

package_and_upload
for fn in "${FN_API}" "${FN_WORKER}"; do
  aws lambda update-function-code --function-name "${fn}" --s3-bucket "${BUCKET}" --s3-key "${CODE_KEY}" >/dev/null
  aws lambda wait function-updated-v2 --function-name "${fn}"
  echo "[deploy] ${fn} 갱신"
done
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='${DIST_COMMENT}'].Id | [0]" --output text)
DOMAIN=$(aws cloudfront get-distribution --id "${DIST_ID}" --query Distribution.DomainName --output text)
echo "[deploy] 끝. 확인: curl https://${DOMAIN}/api/"

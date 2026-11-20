#!/usr/bin/env bash
# 화면 빌드 파일을 S3에 올리고 CloudFront 캐시를 비운다 (F5). 실행: PM만, 최신 main에서.
#   WEB_DIST=web/dist bash infra/deploy-web.sh      # 기본값 web/dist (3번이 G1에서 정한 빌드 폴더로 바꾼다)
source "$(dirname "$0")/config.sh"

WEB_DIST="${WEB_DIST:-${ROOT}/web/dist}"
[ -f "${WEB_DIST}/index.html" ] || { echo "${WEB_DIST}/index.html 이 없습니다. 3번 화면을 먼저 빌드하세요"; exit 1; }

DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='${DIST_COMMENT}'].Id | [0]" --output text)
[ "${DIST_ID}" != "None" ] || { echo "CloudFront ${DIST_COMMENT} 가 없습니다. create.sh 먼저"; exit 1; }

aws s3 sync --only-show-errors --delete "${WEB_DIST}" "s3://${WEB_BUCKET}/"
aws cloudfront create-invalidation --distribution-id "${DIST_ID}" --paths "/*" >/dev/null
DOMAIN=$(aws cloudfront get-distribution --id "${DIST_ID}" --query Distribution.DomainName --output text)
echo "[deploy-web] 끝. https://${DOMAIN}/ (캐시가 비워지는 데 1~2분)"

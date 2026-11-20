#!/usr/bin/env bash
# 두 Lambda의 코드만 다시 배포한다 (리소스 설정은 바꾸지 않는다). 실행: PM만, 최신 main에서.
#   git switch main && git pull && bash infra/deploy.sh
#   bash infra/deploy.sh --check      # 배포 전 검사만 한다 (AWS를 부르지 않는다)
#
# 배포 전에 검사한다 (#174). 하나라도 어긋나면 AWS를 부르기 전에 멈춘다.
#   - 작업 폴더가 깨끗해야 한다: 커밋하지 않은 수정·새 파일(.gitignore 대상 제외)이 있으면 그대로 묶여 올라가서
#   - HEAD가 origin/main과 같은 커밋이어야 한다: main에 합쳐지지 않은 코드가 배포되지 않게
#     (branch 이름은 보지 않는다. origin/main을 받아 둔 워크트리에서 배포해도 된다)
# 배포한 커밋(짧은 SHA)은 API Lambda 환경 변수 GIT_SHA로 넣는다. GET /api/ 의 version이 이 값이다.
# GIT_SHA는 이 스크립트만 쓴다. infra/create.sh의 sync_env가 비교에서 빼고 지우지 않는다.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"

# ---------------------------------------------------------------------------
# 0. 배포 전 검사 (AWS를 부르지 않는다)
# ---------------------------------------------------------------------------
git -C "${REPO}" fetch --quiet origin main || { echo "[deploy] origin/main을 받지 못했습니다. 네트워크를 확인하세요"; exit 1; }
DIRTY="$(git -C "${REPO}" status --porcelain)"
if [ -n "${DIRTY}" ]; then
  echo "[deploy] 작업 폴더에 커밋하지 않은 변경이 있어 배포하지 않습니다:"
  echo "${DIRTY}" | head -10
  echo "[deploy] 커밋·되돌리기·치우기 중 하나를 한 뒤 다시 하거나, origin/main을 받은 깨끗한 워크트리에서 배포하세요"
  echo "[deploy]   git worktree add --detach tmp/deploy-main origin/main && bash tmp/deploy-main/infra/deploy.sh"
  exit 1
fi
HEAD_SHA="$(git -C "${REPO}" rev-parse HEAD)"
MAIN_SHA="$(git -C "${REPO}" rev-parse origin/main)"
if [ "${HEAD_SHA}" != "${MAIN_SHA}" ]; then
  echo "[deploy] 이 폴더의 커밋(${HEAD_SHA:0:7})이 origin/main(${MAIN_SHA:0:7})과 달라 배포하지 않습니다"
  echo "[deploy] main에 합쳐진 코드만 배포합니다. git switch main && git pull 뒤에 다시 하세요"
  exit 1
fi
GIT_SHA="$(git -C "${REPO}" rev-parse --short HEAD)"
echo "[deploy] 검사 통과: origin/main ${GIT_SHA}, 작업 폴더 깨끗함"
if [ "${1:-}" = "--check" ]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# 1. 배포
# ---------------------------------------------------------------------------
source "${HERE}/config.sh"
package_and_upload
for fn in "${FN_API}" "${FN_WORKER}"; do
  aws lambda update-function-code --function-name "${fn}" --s3-bucket "${BUCKET}" --s3-key "${CODE_KEY}" >/dev/null
  aws lambda wait function-updated-v2 --function-name "${fn}"
  echo "[deploy] ${fn} 갱신"
done

# API Lambda 환경 변수에 GIT_SHA만 더한다. update-function-configuration --environment 는 변수를 통째로 바꾸므로
# 지금 변수를 읽어서 GIT_SHA만 넣어 다시 보낸다 (JOBS_TABLE 등이 사라지지 않게). 코드 갱신이 끝난 뒤에 한다.
CURRENT_ENV="$(aws lambda get-function-configuration --function-name "${FN_API}" --query "Environment.Variables" --output json)"
NEW_ENV="$(python3 -c 'import json,sys; v = json.loads(sys.argv[1]) or {}; v["GIT_SHA"] = sys.argv[2]; print(json.dumps({"Variables": v}))' "${CURRENT_ENV}" "${GIT_SHA}")"
aws lambda update-function-configuration --function-name "${FN_API}" --environment "${NEW_ENV}" >/dev/null
aws lambda wait function-updated-v2 --function-name "${FN_API}"
echo "[deploy] ${FN_API} 환경 변수 GIT_SHA=${GIT_SHA}"

DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='${DIST_COMMENT}'].Id | [0]" --output text)
DOMAIN=$(aws cloudfront get-distribution --id "${DIST_ID}" --query Distribution.DomainName --output text)
echo "[deploy] 끝. 확인: curl https://${DOMAIN}/api/   (version이 ${GIT_SHA}여야 한다)"

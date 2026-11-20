#!/usr/bin/env bash
# 키 모양이 바뀐 빈 DynamoDB 테이블을 지우고 create.sh로 다시 만든다. 실행: PM만, 최신 main에서.
#   MODEL_ID=<global 추론 프로필 ID> bash infra/recreate-table.sh <테이블 이름>
# 지키는 것
#   - team06- 으로 시작하는 테이블만 다룬다
#   - 키가 이미 create.sh와 같으면 아무것도 하지 않는다
#   - 항목이 하나라도 있으면 지우지 않고 멈춘다 (지운 데이터는 되돌릴 수 없다. 먼저 내보내기)
#   - 지우기 전에 테이블 이름을 한 번 더 입력받는다 (CONFIRM=<테이블 이름> 으로 미리 줄 수도 있다)
source "$(dirname "$0")/config.sh"

TABLE_NAME="${1:?지울 테이블 이름이 필요합니다. 예: bash infra/recreate-table.sh team06-hs-history}"
: "${MODEL_ID:?MODEL_ID 환경 변수가 필요합니다 (create.sh가 함수 환경 변수를 맞출 때 씀)}"

case "${TABLE_NAME}" in team06-*) ;; *)
  echo "[recreate] team06- 으로 시작하는 테이블만 다룹니다: ${TABLE_NAME}"; exit 1;;
esac

# create.sh가 만들 키 (create.sh의 ensure_table 줄에서 읽는다)
WANT=""
while read -r _ var hash range; do
  name=$(eval echo "${var}")
  if [ "${name}" = "${TABLE_NAME}" ]; then WANT="${hash}${range:+,${range}}"; fi
done < <(grep -E "^ensure_table " "${ROOT}/infra/create.sh")
[ -n "${WANT}" ] || { echo "[recreate] create.sh에 ${TABLE_NAME}이 없습니다"; exit 1; }

if ! HAVE=$(aws dynamodb describe-table --table-name "${TABLE_NAME}" \
    --query "join(',', Table.KeySchema[].AttributeName)" --output text 2>/dev/null); then
  echo "[recreate] ${TABLE_NAME}이 없습니다. create.sh만 돌리면 됩니다"; exit 1
fi
if [ "${HAVE}" = "${WANT}" ]; then
  echo "[recreate] ${TABLE_NAME} 키가 이미 맞습니다 (${HAVE}). 할 일 없음"; exit 0
fi

COUNT=$(aws dynamodb scan --table-name "${TABLE_NAME}" --select COUNT --query Count --output text)
if [ "${COUNT}" != "0" ]; then
  echo "[recreate] ${TABLE_NAME}에 항목이 ${COUNT}개 있어 지우지 않습니다. 먼저 내보내고 옮기는 방법을 정하세요"; exit 1
fi

echo "[recreate] ${TABLE_NAME}: 키 ${HAVE} → ${WANT}, 항목 0개. 지우고 다시 만듭니다 (되돌릴 수 없음)"
if [ "${CONFIRM:-}" != "${TABLE_NAME}" ]; then
  read -r -p "[recreate] 계속하려면 테이블 이름을 그대로 입력: " typed
  [ "${typed}" = "${TABLE_NAME}" ] || { echo "[recreate] 이름이 달라 그만둡니다"; exit 1; }
fi

aws dynamodb delete-table --table-name "${TABLE_NAME}" >/dev/null
aws dynamodb wait table-not-exists --table-name "${TABLE_NAME}"
echo "[recreate] ${TABLE_NAME} 지움. create.sh로 다시 만든다"
bash "${ROOT}/infra/create.sh"

#!/usr/bin/env bash
# 가드레일 team06-chat-guard 설정을 infra/guardrail-chat.json으로 바꾸고 새 버전을 만든다 (F8 #151). 실행: PM만.
#   bash infra/update-guardrail.sh
# 그다음 MODEL_ID=... bash infra/create.sh 로 API Lambda의 GUARDRAIL_VERSION을 새 버전으로 맞춘다.
# 버전은 바뀌지 않는 사진이라 이전 버전으로 되돌리려면 GUARDRAIL_VERSION만 바꾸면 된다.
source "$(dirname "$0")/config.sh"
GUARDRAIL_ID=$(aws bedrock list-guardrails --query "guardrails[?name=='${GUARDRAIL_NAME}'].id | [0]" --output text)
if [ -z "${GUARDRAIL_ID}" ] || [ "${GUARDRAIL_ID}" = "None" ]; then
  echo "[guardrail] ${GUARDRAIL_NAME}이 없습니다. create.sh로 먼저 만든다"; exit 1
fi
# update-guardrail은 crossRegionConfig를 받지만 이름 칸은 같아야 한다. JSON에 없는 정책은 지워진다.
aws bedrock update-guardrail --guardrail-identifier "${GUARDRAIL_ID}" \
  --cli-input-json "file://${ROOT}/infra/guardrail-chat.json" >/dev/null
VERSION=$(aws bedrock create-guardrail-version --guardrail-identifier "${GUARDRAIL_ID}" \
  --description "infra/guardrail-chat.json $(git -C "${ROOT}" rev-parse --short HEAD)" --query version --output text)
echo "[guardrail] ${GUARDRAIL_NAME} (${GUARDRAIL_ID}) 버전 ${VERSION} 만듦. create.sh로 API Lambda 환경 변수를 맞춘다"

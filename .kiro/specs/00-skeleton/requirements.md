# 00-skeleton 요구사항 (PM, 오늘 밤 뼈대)

## 목적
서류 업로드 → 읽기 → 대조 → 결과 조회가 AWS 위에서 한 번 끝까지 도는 가장 얇은 한 줄을 만든다.
내일 팀원이 이 견본을 따라 기능을 채운다. 범위는 agent-design.md P0보다 좁다.

## 범위 안
- R1 모델 호출: MODEL_ID 환경 변수로 Strands Agent를 한 번 부르고 응답과 토큰 사용량을 출력한다.
  structured_output 동작, 도구 호출, 서류 한 장 읽는 시간을 확인해 design.md에 적는다.
- R2 읽기: 상업송장·포장명세서 파일 하나를 모델에 document/image 블록으로 넣어 약속 1의 raw만 받는다.
  value·unit은 코드가 푼다. 서류는 한 장씩 따로, 동시에 읽는다.
- R3 대조: 서류 전체 총중량 하나(X-WT-01)만 비교한다. 등급 셋(불일치·확인 필요·참고)과 근거 문장틀을 쓴다.
  못 읽은 값은 일치로 세지 않는다.
- R4 배포: Lambda team06-agent(Python 3.13, x86_64, 1024MB), Function URL, 동시 실행 상한 5,
  DynamoDB team06-jobs, S3 버킷. 모두 infra/ 스크립트로 만든다. `curl` → `{"ok": true}`.
- R5 끝까지 한 번: POST /jobs(S3 키)에서 R2→R3을 처리해 team06-jobs에 저장하고 job_id를 반환한다.
  GET /jobs/{id}는 약속 2 형식(steps 포함)으로 돌려준다.
- R6 인계: infra/README.md만 보고 PM이 다시 배포할 수 있다.

## 범위 밖 (tasks.md '나중')
분류(classify_document), B/L·원산지증명서, OCR, 다시 확인, HS, 신고서, WMS, 현황 조회, 판독 캐시, POST /uploads.

## 끝난 기준
- `uv run pytest -q` 통과 (AWS·Bedrock 호출 없음)
- Function URL에서 `{"ok": true}` (R4), 서류 두 장 → issues 확인 (R5)

# Implementation Plan

- [x] 1. `tools/hs_request.py`: `make_hs_request`, `check_requestable`, 사유 판단 (PM)
  - 확인: `tests/unit/test_hs_request.py`, PDF를 PNG로 그려 눈으로 확인
  - _Requirements: 1.1~1.8_
- [x] 2. `GET /jobs/{id}/hs-request` (`api/handler.py`, 4번) + `docs/schema.md` 경로 + `test_contracts.py` 함수 약속 (공용)
  - _Requirements: 2.1~2.4_
- [x] 3. 화면 링크 (`HsPicker.tsx`, `api.ts`, `styles.css`, 3번)
  - 확인: `npm test`, `npm run build`
  - _Requirements: 3.1, 3.2_
- [ ] 4. 배포와 실제 확인 (PM): `deploy.sh`, `deploy-web.sh`. HS 미확정 작업에서 PDF를 받아 열기, CloudFront 응답 확인
  - 선행: X1 #258(PR #259)이 먼저 합쳐져야 한다 (`_pdf_response`를 같이 쓴다)

## 범위 밖
메일·팩스 발송, 사전심사 신청서, 화물관리번호, 통지 문서와 합치기, 세관 이상보고서.

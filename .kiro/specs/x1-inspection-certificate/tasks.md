# Implementation Plan

Kiro 작업 하나는 30분, 파일 서너 개 이하이고 끝나면 테스트하고 커밋한다. GitHub 이슈 하나 = 브랜치 하나 = PR 하나.
데모 동결(토 09시) 전에 끝낸다. 작업 1이 끝나야 2·3·4를 시작할 수 있다. 3·4·5는 서로 독립이다.

- [x] 1. 약속: 검수자·승인 시각 칸 (PM, 공용 파일)
  - `tools/models.py`의 `WmsState`에 `approver`, `approved_at` 더하기 (기본 null)
  - `docs/schema.md` 약속 2 wms와 `docs/examples/job_waiting_approval.json` 맞추기
  - `tests/unit/test_contracts.py`에 `make_certificate` 함수 약속 더하기
  - 확인: `uv run pytest`가 통과하고, 옛 작업 줄(칸 없음)이 그대로 읽히는 시험이 있다
  - 끝나면 단톡에 공지 (공용 파일)
  - _Requirements: 1.2, 1.4_

- [x] 2. 승인 때 이름·시각 저장 (4번 서버)
  - `api/handler.py` approve가 사람 승인 등록 성공 때 `wms.approver`, `wms.approved_at`(KST) 저장
  - 재승인은 처음 값 유지, 자동 등록은 null
  - 확인: `test_handler.py`에 저장·한국 시간(+09:00)·재승인·자동 등록 시험
  - _Requirements: 1.1, 1.3_

- [x] 3. PDF 만들기 함수 (담당 지정 필요)
  - `tools/certificate.py`의 `make_certificate(job, docs) -> bytes` (reportlab과 `tools/fonts/` 나눔고딕, 새 의존성 없음)
  - 확인: `tests/unit/test_certificate.py` — `pypdf`로 읽어 이름·B/L·HS·WMS 번호·한글 확인, 같은 입력 같은 바이트, 사람 승인 아니면 `ValueError`, 항목이 많아 쪽이 넘어가도 전부 포함
  - _Requirements: 2.1~2.5, 5.1~5.3_

- [x] 4. 내려받기 API (4번 서버, 작업 2·3 뒤)
  - `GET /jobs/{id}/certificate`, 이진 응답 도우미 `_pdf_response`, 404·409·500
  - 확인: `test_handler.py` — 200·`application/pdf`·`isBase64Encoded`, 승인 대기·자동 등록 409, 작업 없음 404
  - `test_screen_contract.py`에 사람 승인까지 이어 `wms.approver` 채워지는지 한 경우 더하기
  - _Requirements: 3.1~3.5_

- [x] 5. 화면 버튼과 안내 (3번 화면, 작업 1 뒤)
  - `WmsPanel`: 등록됨+human에서 "검수 완료서 받기" 링크, 승인 입력칸 "검수자 이름" 라벨·안내
  - `types.ts`, `mock.ts`에 두 칸
  - 확인: `npm test`(링크 보임·숨김, 문구), `npm run build`, 390·1440 화면
  - _Requirements: 4.1~4.3_

- [ ] 6. 배포와 실제 확인 (PM)
  - `bash infra/deploy.sh`(API Lambda만), 화면은 `deploy-web.sh`
  - 승인 대기 세트를 올려 이름을 넣고 승인 → 검수 완료서를 내려받아 열기 (한글, 이름, 쪽 구성)
  - CloudFront를 거친 응답이 깨지지 않는지, 파일 이름이 `certificate-{job_id}.pdf`인지 확인
  - 자동 등록 세트에서는 버튼이 안 보이고 `GET`이 409인지 확인
  - _Requirements: 3.1, 3.2, 4.1, 4.2_

## 이번 범위 밖

전자서명(KMS), 공인 시각 증명, PDF/A, S3 보존·접근 기록, 양식 버전 관리, 로그인 신원 보증. 발표에서 "다음 단계"로 설명한다.

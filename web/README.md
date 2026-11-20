# web/ 화면 (담당: 화면)

## 정해진 것 (#67)
- **호스팅**: CloudFront + S3. 빌드한 정적 파일(HTML·JS·CSS)을 PM이 S3에 올린다. 결과물은 정적 빌드 파일이어야 한다(서버가 필요한 프레임워크 기능은 쓰지 않는다).
- **API 주소**: 화면과 같은 CloudFront 주소의 `/api/…`. 같은 주소라 CORS 설정이 필요 없다. 코드에서는 상대 경로(`/api/jobs`)로 부른다.
- **비동기**: `POST /api/jobs`는 `job_id`를 바로 돌려준다. 결과는 `GET /api/jobs/{id}`를 2초마다 불러 받는다.

## 먼저 정할 것 (G1)
- [ ] 기술: (예: React + Vite, 순수 HTML/JS). 정적 빌드가 되는 것
- [ ] 개발 중 가짜 응답 모드: `docs/examples/`를 돌려주는 방법 (예: 환경 변수 하나로 켜고 끔)
- [ ] 로컬 개발 서버에서 `/api`를 어디로 보낼지 (배포 전에는 가짜 응답, 배포 뒤에는 CloudFront 주소로 프록시)

정하면 이 칸을 채우고, 실행·빌드 방법을 아래에 적는다.

## 화면과 쓰는 API (docs/schema.md 약속 2)
| 작업 | 화면 | 부르는 것 | 가짜 응답 |
|---|---|---|---|
| G2 | 업로드 (서류 종류 고치기 포함) | `POST /api/uploads` → url로 S3에 PUT → `POST /api/jobs` | 없음 (job_id만 흉내) |
| G3 | 진행 | `GET /api/jobs/{id}` 2초마다, `steps` | `docs/examples/job_waiting_approval.json` |
| G4 | 결과: 오류 목록 | `result.issues` (등급, 근거, 서류·칸·raw, checked_by) | 같은 파일 |
| G5 | 결과: HS 선택 | `result.hs`, `POST /api/jobs/{id}/hs` | 같은 파일 |
| G6 | 결과: 신고서 초안 | `result.declaration_draft`, "사람 검토 전 초안" 표시 | 같은 파일 |
| G7 | 결과: WMS 상태·승인 | `result.wms`, `POST /api/jobs/{id}/approve` (409면 안내) | 같은 파일 |
| G8 | 현황 채팅 | `POST /api/chat` | `docs/examples/chat_response.json` |

## 규칙
- 서버가 아직 없는 경로는 501을 돌려준다. 그동안은 가짜 응답으로 화면을 만든다.
- 응답 칸 이름은 docs/examples/와 똑같이 쓴다. 바뀌면 공용 파일 변경으로 단톡에 알림이 온다.
- 서류 원본이나 키를 화면 코드에 넣지 않는다.

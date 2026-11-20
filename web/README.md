# web/ 화면 (담당: 화면)

## 정해진 것 (#67)
- **호스팅**: CloudFront + S3. 빌드한 정적 파일(HTML·JS·CSS)을 PM이 S3에 올린다. 결과물은 정적 빌드 파일이어야 한다(서버가 필요한 프레임워크 기능은 쓰지 않는다).
- **API 주소**: 화면과 같은 CloudFront 주소의 `/api/…`. 같은 주소라 CORS 설정이 필요 없다. 코드에서는 상대 경로(`/api/jobs`)로 부른다.
- **비동기**: `POST /api/jobs`는 `job_id`를 바로 돌려준다. 결과는 `GET /api/jobs/{id}`를 2초마다 불러 받는다.

## 먼저 정할 것 (G1)
- [x] 기술: React + Vite + TypeScript. `npm run build`가 정적 파일(`dist/`)만 만든다
  - 서버 상태와 2초 폴링: TanStack Query (`refetchInterval`)
  - 라우팅: 해시 방식 (`#/jobs/job-7c1e`). 새로고침해도 S3에 없는 경로를 요청하지 않는다
  - 스타일: 일반 CSS 또는 CSS Modules (UI 라이브러리는 쓰지 않는다)
  - 테스트: Vitest + Testing Library. AWS와 서버를 부르지 않고 `docs/examples/`의 가짜 응답을 쓴다
  - 패키지 관리: npm (Node 20 이상)
- [x] 개발 중 가짜 응답 모드: Vite 모드 `mock`(`npm run dev`)에서는 `/api` 호출을 `docs/examples/*.json`으로 대신 답한다. 예시 파일을 직접 읽으므로 예시가 바뀌면 가짜 응답도 같이 바뀐다. 빌드(`npm run build`)에는 가짜 응답이 들어가지 않는다. API 호출은 `src/api.ts` 한 곳에 모으고, 코드에서는 항상 상대 경로(`/api/...`)로 부른다
- [x] 로컬 개발 서버에서 `/api`를 어디로 보낼지: `npm run dev:api`는 Vite 개발 서버 프록시로 `/api`를 환경 변수 `VITE_API_PROXY`(배포된 CloudFront 주소)에 보낸다. 배포 전에는 `npm run dev`(가짜 응답)만 쓴다
  - S3 업로드 CORS는 CloudFront 주소에서 오는 PUT만 허용한다(`infra/s3-cors-docs.json`). 그래서 `localhost`에서는 S3에 파일을 올릴 수 없고, 실제 업로드는 배포된 주소에서 확인한다

## 구조 (G1, G9에서 배치 변경)
메뉴는 파일 업로드 · 문서 분류 내역 · 대시보드 · AI chat 네 개다. 사용자와 관리자를 나누지 않는다. 주소는 해시 방식이다.

| 주소 | 메뉴 | 화면 | 작업 |
|---|---|---|---|
| `#/upload` (첫 화면) | 파일 업로드 | 파일 고르기(끌어다 놓기도 됨) → 선택된 파일 목록(오른쪽 위 X로 빼기) → 업로드. 서류 종류는 고르지 않고 모두 자동 분류 | G2, G9 |
| `#/jobs/{job_id}` | (업로드가 끝나면 열림) | 진행 단계, 결과(오류 목록 · HS 선택 · 신고서 초안 · WMS 상태·승인). 오류는 왼쪽 서류 그림 \| 오른쪽 오류, 누르면 그 칸에 박스(G11) | G3~G7, G11 |
| `#/documents` | 문서 분류 내역 | 종류(상업송장 · 포장명세서 · 선하증권 · 원산지증명서 · 분류 못 함)를 고르면 그 종류의 서류 표(모바일·태블릿은 카드). 건수·근거는 서버 값 그대로 | G10 |
| `#/dashboard` | 대시보드 | 지금 할 일 · 통관 흐름 · 서류 처리. 누르면 문서 분류 내역(`#/documents?grade=불일치` 등)이나 AI chat 질문(`#/chat?q=…`)으로 간다. 오른쪽 위 애니메이션 ON/OFF (ON: 부산항 영상 `public/dashboard/`) | G15 |
| `#/chat` | AI chat | 예시 질문(누르면 바로 질문), 대화, 입력창. 답마다 조건과 표(모바일은 카드) | G8, G9 |

```
web/
  index.html
  package.json, tsconfig.json
  vite.config.ts        개발 서버 프록시, docs/examples 읽기 허용, 테스트 설정
  src/
    main.tsx            시작점 (TanStack Query 준비)
    App.tsx             메뉴와 해시 주소
    api.ts              /api 호출을 모은 곳. 가짜 응답 모드면 mock.ts가 답한다
    mock.ts             docs/examples/*.json으로 답하는 가짜 서버
    types.ts            약속 2의 모양 (tools/models.py와 칸 이름이 같다)
    pages/              UploadPage, JobPage, ChatPage
    components/         결과 화면의 부분 (오류 목록, HS 선택, 신고서 표, WMS), Icon(인라인 SVG 아이콘),
                        DocViewer·DocReview·DocDetail(서류 그림 위 박스, G11)
    fixtures/           서버 약속이 합쳐지기 전 임시 가짜 데이터
    styles.css          스타일 한 파일 (화면 크기별 배치 포함)
    *.test.ts(x)        테스트는 고친 파일 옆에 둔다
```

## 화면 모양 (G9)
- 크기: 모바일 767px 이하(주 사용), 태블릿 768~1199px, PC 1200px 이상. `styles.css` 의 `@media` 로만 바꾼다.
- 메뉴: 모바일은 아래 탭(아이콘 + 글자, 고른 쪽은 굵게 + 점), 태블릿·PC 는 위 왼쪽 칩(앱 이름 + 메뉴 네 개).
- 화면: 가운데 질문 한 줄, 큰 회색 칸, 아래 검은 버튼 하나(단계형). 흑백으로 쓰고 빨강은 불일치·실패·오류에만 쓴다. 상태는 색만으로 구분하지 않는다(글자 + 채움 방식).
- 업로드 버튼과 채팅 입력칸은 모바일에서 아래 탭 위에 고정, 태블릿은 화면 아래 가운데 고정, PC 는 내용 안에 둔다.
- 표(채팅 결과)는 모바일에서 줄마다 카드로 바꾼다. `<table>` 은 그대로 두고 `td` 의 `data-label` 을 칸 이름으로 보여 준다.
- 누르는 곳 44px 이상, 입력칸 글자 16px(iOS 확대 방지), 아래 고정 칸은 `safe-area-inset-bottom` 만큼 띄운다.
- 글꼴: Pretendard(OFL, npm `pretendard` 1.3.9). 빌드에 글꼴 파일이 함께 들어가고 외부 주소를 부르지 않는다.
- 작업 화면(`#/jobs/{id}`)은 G3~G7 구조 그대로이고 색만 맞췄다.

## 실행·빌드 방법
프로젝트 파일(`package.json` 등)은 G2에서 만든다. 만든 뒤 아래 명령을 쓴다.
```
cd web
npm install
npm run dev            # 개발 서버, 가짜 응답 모드 (http://localhost:5173)
npm test               # 단위 테스트
npm run build          # dist/ 생성. PM이 infra/deploy-web.sh로 이 폴더를 S3에 올린다

# 배포된 API에 붙이기 (PowerShell)
$env:VITE_API_PROXY="https://<CloudFront 주소>"; npm run dev:api
# 배포된 API에 붙이기 (bash)
VITE_API_PROXY=https://<CloudFront 주소> npm run dev:api
```

## 화면과 쓰는 API (docs/schema.md 약속 2)
| 작업 | 화면 | 부르는 것 | 가짜 응답 |
|---|---|---|---|
| G2 | 업로드 (서류 종류는 모두 `doc_type: null`, 에이전트가 분류) | `POST /api/uploads` → url로 S3에 PUT → `POST /api/jobs` | 없음 (job_id만 흉내) |
| G3 | 진행 | `GET /api/jobs/{id}` 2초마다, `steps` | `docs/examples/job_waiting_approval.json` |
| G4 | 결과: 오류 목록 | `result.issues` (등급, 근거, 서류·칸·raw, checked_by) | 같은 파일 |
| G5 | 결과: HS 선택 | `result.hs`, `POST /api/jobs/{id}/hs` | 같은 파일 |
| G6 | 결과: 신고서 초안 | `result.declaration_draft`, "사람 검토 전 초안" 표시 | 같은 파일 |
| G7 | 결과: WMS 상태·승인 | `result.wms`, `POST /api/jobs/{id}/approve` (409면 안내) | 같은 파일 |
| G10 | 문서 분류 내역 | `GET /api/documents?doc_type=&cursor=` (서버 약속 제안 중) | `src/fixtures/documents.draft.json` (임시. 약속이 합쳐지면 `docs/examples/documents.json`) |
| G11 | 서류 보기 (오류 칸·분류 근거를 서류 위에 박스로) | `GET /api/jobs/{id}/files` (서버 약속 제안 중. 쪽 그림 주소와 표시 위치 bbox) | `src/mockDocs.ts` 가 가짜 서류 SVG 와 위치를 만든다 (임시) |
| G15 | 대시보드 | `GET /api/stats` (F11 #195), 문서 분류 내역 거르기 `job_status`·`grade`·`rule_id`·`hs` | `src/fixtures/stats.draft.json` (임시. F11이 합쳐지면 `docs/examples/stats.json`) |
| G8 | 현황 채팅 | `POST /api/chat` | `docs/examples/chat_response.json` |

## 규칙
- 서버가 아직 없는 경로는 501을 돌려준다. 그동안은 가짜 응답으로 화면을 만든다.
- 응답 칸 이름은 docs/examples/와 똑같이 쓴다. 바뀌면 공용 파일 변경으로 단톡에 알림이 온다.
- 서류 원본이나 키를 화면 코드에 넣지 않는다.

## 대시보드 영상 (G15)
`public/dashboard/`의 영상은 부산항 Blender 장면(발표 영상과 같은 렌더, 1920×1080 PNG 900장)에서 만들었다.
- `port-intro.mp4`: 오프닝(1~240 프레임, 바다에서 터미널로 내려옴) 8초, 한 번 재생
- `port-loop.mp4`: 마무리 항공샷(691~900 프레임)을 앞으로·뒤로 이어 붙인 14초, 되풀이 (끊김 없게)
- `port-poster.jpg`: 첫 프레임. 영상을 못 틀 때와 불러오는 동안 보인다
- 모두 1280×720 H.264(CRF 27~28), 소리 없음. 합쳐서 약 4.5MB. 다시 만들 때는 ffmpeg로 같은 설정을 쓴다

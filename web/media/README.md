# web/media: 발표 영상 · Blender 자산 (인수인계)

화면 담당(3번)이 만든 영상과 3D 자산을 다른 작업자가 이어서 고칠 수 있게 한곳에 모았다 (G20 #287).
웹 앱(`web/src`) 빌드에는 들어가지 않는다. 앱이 쓰는 결과물은 `web/public/dashboard/`의 대시보드 영상뿐이다.

## 무엇이 어디 있나

| 경로 | 내용 | 결과물 |
|---|---|---|
| `video/blender/dash_port/` | **대시보드 부산항 애니메이션.** 흰 클레이 항구 장면을 코드 한 파일(`build_scene.py`)로 만든다. 예전 `web/scene/` | `web/public/dashboard/port-*.mp4·jpg` |
| `video/blender/real_port/` | 같은 장면에 Poly Haven 실사 질감·HDRI를 입힌 발표용 판 (`build_real.py`가 `../dash_port/build_scene.py`를 불러 쓴다) | `video/public/real/*.mp4` |
| `video/blender/busan_port.blend` | 첫 발표 영상의 부산항 장면 (카메라 4대, 900프레임). Tripo 작업자·트럭 모델이 들어 있다 | `video/public/blender/*.mp4` |
| `video/blender/assets/` | `truck_lite.blend`·`worker_lite.blend`(Tripo 모델을 줄인 것), `incoming/*.glb`(Tripo 원본), `polyhaven/`(CC0 질감·HDRI), `tablet_screen.png` | - |
| `video/blender/*.py, *.mjs` | `prep_asset.py`(GLB 줄이기), `make_tablet_screen.py`(태블릿 화면 그림), `encode_shots.mjs`(프레임 → 장면 mp4) | - |
| `video/blender/ASSET_REQUESTS.md` | 3D 모델을 더 만들 때 쓰는 Tripo 요청서·프롬프트 | - |
| `video/` (그 밖) | Remotion(React로 영상 만들기) 프로젝트. 2D 화면·자막을 Blender 장면 위에 얹는다. 자세한 장면표는 [video/README.md](video/README.md) | `video/out/*.mp4` |
| `video/record/record.py` | 시연 영상 화면 녹화 (Playwright로 앱을 움직이고 프레임을 모은다, #272) | `video/public/demo/take/` |
| `data/` | **영상 전용** 합성 서류 15세트(SET-001~015)와 가상 화물 30건. `video/prepare_assets.py`가 여기서 서류 그림·검증 값을 뽑는다. 평가용 데이터셋(저장소 `samples/`, `eval/`)과는 다른, 먼저 만든 것이다. [data/README.md](data/README.md) | `video/src/data.json`, `video/public/docs/` |

## 큰 파일 받기 (처음 한 번)

`.blend`, Tripo 원본 `.glb`, 질감, 장면 mp4, 최종 렌더는 저장소에 넣지 않았다 (합계 약 560MB. git 기록과 LFS 한도를 아끼려고).
GitHub Release **`media-assets-2026-11-21`** 에 zip 4개로 올려 두었고, 스크립트가 받아서 제자리(`web/media/...`)에 푼다. 받은 파일은 `.gitignore`가 막아서 커밋되지 않는다.

```powershell
gh auth login                                  # 처음 한 번
powershell -File web/media/fetch_assets.ps1                      # 기본: blender-scenes, video-media
powershell -File web/media/fetch_assets.ps1 tripo-originals final-renders
```
```bash
bash web/media/fetch_assets.sh                 # Git Bash · macOS · Linux
```

| zip | 크기 | 들어 있는 것 | 언제 필요한가 |
|---|---|---|---|
| `blender-scenes.zip` | 111MB | `busan_port.blend`, `real_port/real_port.blend`, `assets/*_lite.blend`, `assets/polyhaven/` | Blender 장면을 열거나 고칠 때 |
| `video-media.zip` | 131MB | `video/public/blender/*.mp4`, `video/public/real/*.mp4`, `video/public/demo/take/screen.mp4`, `video/public/fonts/NotoSansKR-VF.ttf` | Remotion으로 영상을 미리 보거나 다시 렌더할 때 |
| `tripo-originals.zip` | 130MB | `assets/incoming/worker.glb`, `truck.glb` (각 150만 삼각형, 4K 텍스처) | 경량 모델을 다시 만들 때만 |
| `final-renders.zip` | 191MB | `video/out/team6_*.mp4` (발표에 쓴 완성 영상 6개) | 완성 영상만 보거나 발표에 쓸 때 |

sha256 (받은 파일 확인용, `Get-FileHash` / `sha256sum`)
```
bc1f01f866c0bc6e0ab3d2be586a60a880115c9f5d66e8ccd086608b2d283702  blender-scenes.zip
b6eaac1e4f63c6d05f55c74dd53faf036fff6fc41aa2aa98e4c582e276fd2651  video-media.zip
d99d85c3f4ddeb5bd721e611dc2cc3f806c8c46096496d54ade096725706c2f6  tripo-originals.zip
4fd735d0f423ad2a4c4def0096923b72f1eed27ff6a3d5fb4e63052262ee96c1  final-renders.zip
```

`dash_port.blend`는 zip에 없다. `build_scene.py`가 몇 초 만에 다시 만든다.

## 준비물

| 도구 | 버전 | 쓰는 곳 |
|---|---|---|
| Blender | 4.0 (EEVEE). 기본 경로 `C:\Program Files\Blender Foundation\Blender 4.0\blender.exe` (`real_port/render_shots.sh`에 적혀 있으니 다르면 고친다) | 장면 만들기·렌더 |
| Node.js | 20 이상 | Remotion (`video/`) |
| uv + Python 3.13 | - | `prepare_assets.py`(pymupdf), `encode.py`(pillow), `record.py`(playwright) |
| ffmpeg | Remotion이 함께 깔아 준다 (`npx remotion ffmpeg`). `dash_port/encode.py`는 환경 변수 `FFMPEG`로 경로를 준다 | mp4 묶기 |

## 자주 할 일

### 1. 대시보드 애니메이션 고치기 (앱에 바로 보이는 것)
```bash
cd web/media/video/blender/dash_port
blender -b -P build_scene.py -- still      # dash_port.blend 저장 + 확인용 스틸 몇 장(stills/)
blender -b dash_port.blend -o //frames/f#### -s 1 -e 888 -a     # 888장, 내장 그래픽으로 3~4시간
FFMPEG=<ffmpeg 경로> uv run --no-project --with pillow python encode.py ../../../../public/dashboard
```
- 영상 길이·장면 시간을 바꾸면 `web/src/pages/DashboardPage.tsx`의 `STAGE_TIMES`(통관 단계가 바뀌는 초)도 함께 고친다.
- 결과물 규격과 구간: [web/README.md "대시보드 영상 (G15)"](../README.md).

### 2. 발표 영상 글자·화면 고치기 (Remotion)
```bash
powershell -File web/media/fetch_assets.ps1 video-media
cd web/media/video
npm install
npm run studio                                      # 브라우저 미리보기 (http://localhost:3000)
npx remotion render src/index.ts Workflow out/team6_workflow_blender.mp4 --codec=h264 --crf=18
```
- 컴포지션: `Workflow`(Blender 판, 발표 권장) · `WorkflowWeb`(실사 질감 판) · `Opening` · `Opening3D` · `Demo`(시연 녹화 편집) · `WebSample`
- 장면 순서·길이 `src/Workflow.tsx`의 `PLAN`, 2D 장면 `src/scenes.tsx`, 색·글꼴 `src/theme.ts`

### 3. Blender 장면 고치기
- 실사 판: `cd web/media/video/blender/real_port && bash render_shots.sh` (장면 만들기 + 네 구간 렌더)
- 첫 판: `busan_port.blend`를 열어 고친 뒤 [video/README.md "Blender 장면"](video/README.md)의 렌더 → `node blender/encode_shots.mjs`
- 사람·트럭 모델 바꾸기: Tripo에서 GLB를 받아 `assets/incoming/`에 두고 `prep_asset.py`로 줄인다 (명령은 video/README.md "Tripo 모델")

### 4. 영상 속 서류·숫자 바꾸기
`data/generator/`의 스크립트로 데이터를 다시 만들고 → `python web/media/video/prepare_assets.py` → 렌더. 발표 날짜에 맞추려면 `generate_logistics_seed.py --base-date <날짜>`.

## 라이선스·출처
- Poly Haven 질감·HDRI: CC0 (`assets/polyhaven/` 폴더 이름이 Poly Haven 자산 이름)
- 작업자·트럭 머리: Tripo AI로 생성한 모델
- 글꼴: Noto Sans KR, Pretendard (둘 다 OFL)
- 서류·회사·번호는 모두 가상 값이고 서류마다 SAMPLE 표시가 있다

## 넣지 않은 것
렌더 프레임(PNG 수천 장), 렌더 로그, `.blend1` 백업, 확인용 스틸, 녹화 시험본(`record/dry`)은 다시 만들 수 있어서 올리지 않았다.

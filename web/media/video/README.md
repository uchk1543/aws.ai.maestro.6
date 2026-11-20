# 6팀 워크플로 영상 (발표용)

부산항 현장 촬영부터 분류, 추출, 교차 검증, 정정 요청, HS·신고서 초안, 시스템 연동, 반출, 자연어 조회까지 과제 기능 5개가 이어지는 흐름을 보여주는 영상이다. 3D 부산항 장면은 [Blender](https://www.blender.org/)로 렌더링하고, 글자와 화면 UI는 [Remotion](https://www.remotion.dev/)(React로 영상을 만드는 도구)으로 그 위에 얹었다.

| 파일 | 길이 | 내용 |
| --- | --- | --- |
| `out/team6_workflow_blender.mp4` | 1분 54초 | **발표용 권장.** Blender 실사풍 부산항 장면 4개(오프닝, 현장 촬영, 반출, 마무리) + 2D 화면 |
| `out/team6_workflow_3d.mp4` | 1분 54초 | three.js로 그린 이전 3D 버전 |
| `out/team6_workflow_2d.mp4` | 1분 36초 | 2D 모션 그래픽만 있는 첫 버전 |

모두 1920×1080, 30fps, 무음이다. 내레이션이나 배경음악은 발표 때 따로 얹는다.

## 화면 속 값은 어디서 오나

- 서류 이미지와 하이라이트 위치: `data/output/sets/SET-011` 의 실제 PDF를 렌더링하고, 값의 위치를 PDF에서 찾아 쓴다.
- 검증 결과(불일치 3건, 정정본 0건): `data/generator/check_generated_data.py` 의 규칙을 실제로 돌린 결과다.
- 지연 화물 6건, 프리타임 임박 4건: `data/logistics/shipments_seed.json` 그대로다.
- Agent 답변, 정정 요청 메일, 신고서 초안 화면은 **기획한 동작을 그린 것**이다. 실제 앱 화면은 아니다. 앱이 완성되면 실제 화면 녹화로 바꾸거나, 이 영상을 발표 도입부로 쓴다.
- 3D 부산항은 터미널·크레인·선박·장치장·배후 물류단지·산을 단순화해 재현한 것이다. 실제 지형이나 배치와는 다르다.

## 장면 구성

| 시간 | 장면 | 형식 | 과제 기능 |
| --- | --- | --- | --- |
| 0:00 | 오프닝: 바다 쪽에서 부산신항 터미널로 내려옴, 물동량 | Blender | - |
| 0:08 | 문제: 서류 4종을 손으로 대조 | 2D | - |
| 0:15 | STEP 1 안벽 크레인 아래 작업자 → 어깨 너머로 태블릿 촬영 → S3 업로드 | Blender | ① OCR |
| 0:23 | STEP 1 전송 화면 (사진 2장 + PDF 2개) | 2D | ① OCR |
| 0:32 | STEP 2 문서 분류 | 2D | ② 분류 |
| 0:39 | STEP 3 항목 추출 + 원본 위치 | 2D | ① 추출 |
| 0:49 | STEP 4 교차 검증 (9개 규칙, 3건 불일치) | 2D | ② 교차 검증 |
| 1:00 | STEP 5 Agent 설명, 정정 요청, 재검증 통과 | 2D | - |
| 1:11 | STEP 6 HS 코드 추천, 수입신고서 초안 | 2D | ③ HS·통관 서류 |
| 1:21 | STEP 7 가상 물류 시스템 등록, 진행 흐름 | 2D | ④ 시스템 연동 |
| 1:31 | STEP 7 입항 당일 트럭이 반출 게이트에서 차단기가 열리고 통과 | Blender | ④ 시스템 연동 |
| 1:38 | STEP 7 자연어 현황 조회 (입항 후) | 2D | ⑤ 자연어 조회 |
| 1:47 | 마무리: 터미널 항공샷 위로 핵심 메시지, 아키텍처 | Blender + 2D | - |

## 다시 만들기

```bash
cd web/media/video   # 큰 파일은 먼저 ../fetch_assets 로 받는다 (../README.md)
npm install
python prepare_assets.py      # 데이터가 바뀌었으면 먼저 실행
npm run studio                # 브라우저에서 미리보기·수정
npx remotion render src/index.ts Workflow out/team6_workflow_blender.mp4 --codec=h264 --crf=18
node check_frames.mjs 120 800 # 특정 프레임만 PNG로 확인 (out/frames)
```

- 장면 길이와 순서: `src/Workflow.tsx` 의 `PLAN`
- 2D 장면: `src/scenes.tsx` · Blender 장면 위 글자: `src/blender.tsx` · 이전 three.js 장면: `src/three/`
- 색과 글꼴: `src/theme.ts` (글꼴은 `public/fonts/NotoSansKR-VF.ttf`, OFL 라이선스)
- 발표 날짜에 맞추려면 `data/generator/generate_logistics_seed.py --base-date <날짜>` → `prepare_assets.py` → 렌더링

## Blender 장면 (`blender/`)

`blender/busan_port.blend` 한 파일에 장면 4개가 카메라 4대로 들어 있다 (900프레임, 30fps). 타임라인 마커가 카메라를 바꾼다.

| 프레임 | 카메라 | 장면 |
| --- | --- | --- |
| 1-240 | `CAM-opening` | 바다 위 항공샷에서 터미널로 하강 |
| 241-480 | `CAM-field` | 크레인 다리 사이 안벽 → 작업자에게 다가감 → 어깨 너머 태블릿 (피사계 심도) |
| 481-690 | `CAM-gate` | 트럭 정차 → 차단기 열림 → 출발 |
| 691-900 | `CAM-outro` | 터미널 전체 항공샷 |

- 엔진: EEVEE (32샘플, AgX), 하늘과 조명은 Poly Haven HDRI, 바닥·아스팔트·골판·녹·도장 금속은 Poly Haven PBR 텍스처 (모두 CC0, `blender/assets/polyhaven/`)
- 태블릿 화면 이미지: `uv run --with pillow python blender/make_tablet_screen.py` → `blender/assets/tablet_screen.png`
- 이 PC(내장 GPU)에서 한 프레임에 약 8초, 900프레임에 약 2시간 걸린다.

```bash
# 1) 프레임 렌더링 (PNG 900장 → blender/renders/seq/)
"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe" -b blender/busan_port.blend -o blender/renders/seq/f_#### -F PNG -s 1 -e 900 -a
# 2) Remotion이 쓰는 영상 한 개로 묶기
npx remotion ffmpeg -y -framerate 30 -i blender/renders/seq/f_%04d.png -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p -movflags +faststart public/blender/busan_port.mp4
```

### Tripo 모델 (작업자, 트럭 머리)

작업자와 트럭 머리는 Tripo AI로 만든 모델이다 (`blender/assets/incoming/worker.glb`, `truck.glb`, 각 150만 삼각형·4K 텍스처). 그대로는 무거워서 먼저 줄여 쓴다.

```bash
# 15만 삼각형, 2K 텍스처로 줄여 .blend로 저장 (각 1분 이내)
"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe" -b --factory-startup --python blender/prep_asset.py -- blender/assets/incoming/worker.glb blender/assets/worker_lite.blend worker 150000 2048
"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe" -b --factory-startup --python blender/prep_asset.py -- blender/assets/incoming/truck.glb blender/assets/truck_lite.blend truck 160000 2048
```

- 작업자(`GEO-worker_tripo`): 키 1.75m로 맞추고, 직접 만든 뼈대(`ARM-worker`)로 태블릿을 양손으로 든 자세를 잡았다. 자동 가중치는 이 메시에서 실패해서 뼈까지의 거리로 가중치를 계산했다. 손 위치는 `TGT-wrist.L/R`, 팔꿈치 방향은 IK의 pole 각도로 조절한다. 예전 도형 작업자는 숨겨 두었다.
- 트럭 머리(`GEO-truck_tripo`): 6.3배(길이 약 6.9m)로 키워 `EMP-truck` 아래 붙였다. 예전 트랙터는 숨겨 두었다.

다른 모델을 더 바꾸고 싶으면 `blender/ASSET_REQUESTS.md` 의 목록과 프롬프트를 쓴다.

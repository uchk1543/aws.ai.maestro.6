# 3D 에셋 요청서 (Tripo AI 등으로 생성)

이전 3D 영상이 "AI 티"가 났던 이유는 세 가지다.

1. 사람·트럭이 원기둥·상자 몇 개로 된 단순 도형이었다.
2. 모든 표면이 단색이고 질감(녹, 먼지, 도장, 줄무늬)이 없었다.
3. 하늘·조명이 실사 기반이 아니었다.

그래서 **복잡한 형태(사람, 트럭)는 AI 3D 생성**으로, **실사 질감과 하늘은 실사 사진 기반 무료 에셋(Poly Haven, CC0)**으로, **크고 반복적인 구조물(크레인, 컨테이너, 선박, 안벽)은 Blender에서 직접** 만든다.

## 1. 만들어 주실 3D 모델 (우선순위 순)

저장 위치: `video/blender/assets/incoming/` · 형식: **GLB (텍스처 포함)** · 텍스처: **PBR, 2K**

**2026-11-20 기준 우선순위** (Blender 영상이 나온 뒤 다시 정함)

| 순위 | 파일 이름 | 무엇 | 쓰는 장면 | 폴리곤 목표 | 효과 |
| --- | --- | --- | --- | --- | --- |
| 1 | `worker_rigged.glb` (없으면 `worker_apose.glb`) | 항만 작업자 | 현장 촬영 (뒷모습이 화면 절반을 차지) | 3만 삼각형 이하 | **가장 큼.** 지금 작업자는 단순 도형이라 가장 어색함 |
| 2 | `truck_tractor.glb` | 컨테이너 트럭 머리(트랙터) | 반출 | 5만 이하 | 중간. 게이트를 빠져나갈 때 보임 |
| 3 | `chassis_40ft.glb` | 40ft 컨테이너 섀시(트레일러) | 반출 | 2만 이하 | 작음. 지금 것도 바퀴·프레임은 있음 |
| - | `tablet_rugged.glb` | 산업용 태블릿 | 현장 촬영 | 5천 이하 | 필요 없음 (화면 이미지를 직접 만들어 씀) |
| - | `clipboard_docs.glb` | 서류 클립보드 | - | - | 필요 없음 (장면 구성이 바뀜) |
| - | `reach_stacker.glb` | 리치스태커 | 오프닝 배경 | 4만 이하 | 선택. 항공샷에서 거의 안 보임 |

작업자는 **뒷모습**이 크게 나오므로 조끼 등판의 반사띠와 안전모 뒤쪽이 잘 만들어진 결과를 고른다.

작업자는 Tripo에서 **자동 리깅(Auto Rig)** 이 되면 리깅된 버전도 같이 받는다 (`worker_rigged.glb`). 태블릿을 드는 자세는 Blender에서 잡는다.

### Tripo 공통 설정

- 이미지로 생성(Image to 3D)을 기본으로 하고, 결과가 이상하면 아래의 텍스트 프롬프트로 다시 생성한다.
- 텍스처: 켜기 (PBR / HD Texture가 있으면 사용)
- 내보내기: GLB, 텍스처 포함
- 같은 모델을 2~3번 생성해서 손·얼굴·바퀴가 가장 덜 뭉개진 것을 고른다.

## 2. 이미지 생성 프롬프트 (Tripo에 넣을 입력 이미지용)

이미지→3D 변환이 잘 되는 입력 이미지의 조건은 이렇다: 물체 하나만, 화면 가운데, 전체가 다 보이게, 단색 밝은 회색 배경, 그림자 없음, 글자·로고 없음.
아래 프롬프트는 영어로 쓰는 것이 결과가 좋다. 정사각형(1:1)으로 생성한다.

**모든 프롬프트 공통 끝부분 (그대로 붙이기)**

```text
single object only, centered, entire object fully visible, plain light gray seamless background, soft even studio lighting, no cast shadows, no text, no logos, no watermark, realistic proportions, physically based materials, high detail, product render, 1:1
```

**네거티브 프롬프트 (지원하는 도구만)**

```text
multiple objects, cropped, cut off, text, letters, logo, brand, watermark, cartoon, toy, low detail, blurry, dramatic shadows, busy background, extra limbs, deformed hands
```

### ① 항만 작업자 — `worker_apose.glb`

```text
Full-body 3D character reference of an adult Korean container port worker standing in a neutral A-pose, arms slightly away from the body, empty hands with work gloves. White safety hard hat, high-visibility fluorescent orange safety vest with two silver reflective stripes over a dark navy long-sleeve work jacket, dark navy cargo work pants, black steel-toe safety boots. Calm neutral face, short black hair. Front three-quarter view, whole body from head to boots visible.
```

Tripo 텍스트 프롬프트(대안): `adult port terminal worker, white hard hat, orange hi-vis vest with reflective stripes, navy work uniform, safety boots, gloves, A-pose, realistic`

### ② 산업용 태블릿 — `tablet_rugged.glb`

```text
A rugged industrial tablet computer, 10 inch, black rubberized protective bumper case with reinforced corners, a hand strap on the back, screen turned off showing a dark glossy glass surface. Three-quarter view showing the screen side and one edge.
```

### ③ 컨테이너 트럭 머리 — `truck_tractor.glb`

```text
A heavy-duty cab-over semi truck tractor unit as used at South Korean container ports, white cab with flat front, large windshield, side mirrors, chrome bumper details, three axles with dual rear wheels, fifth-wheel coupling plate on the back, no trailer attached, clean but slightly weathered. Side three-quarter view from the front left.
```

Tripo 텍스트 프롬프트(대안): `white cab-over semi truck tractor, three axles, fifth wheel, no trailer, realistic`

### ④ 40ft 컨테이너 섀시 — `chassis_40ft.glb`

```text
An empty 40-foot intermodal container chassis trailer, skeletal dark gray steel frame with twist-lock pins at the corners, landing gear legs at the front, two rear axles with eight black tires, red rear lights, no container loaded. Side three-quarter view.
```

### ⑤ 서류 클립보드 — `clipboard_docs.glb`

```text
A brown hardboard clipboard with a silver metal clip holding a short stack of white printed A4 shipping documents with blank tables and lines, slightly curled paper edges. Three-quarter view from above.
```

### ⑥ (선택) 리치스태커 — `reach_stacker.glb`

```text
A container reach stacker port vehicle, yellow body with a long telescopic boom and a container spreader attachment at the end, large black tires, operator cab at the rear, industrial and slightly weathered. Side three-quarter view.
```

## 3. AI로 만들지 않는 것

**실사 무료 에셋 (Poly Haven, CC0, 다운로드 시 확인받기)**

- 노을 하늘 HDRI 1종 (조명과 하늘 반사를 실사로)
- 콘크리트 바닥, 아스팔트, 도장 금속, 녹슨 금속 텍스처 각 1종

**Blender에서 직접 만드는 것**

- 안벽 크레인(STS), 야드 크레인: 가는 철골 구조라 AI 생성이 뭉개진다
- 컨테이너: 정확한 규격(20ft/40ft), 골판 모양, 문 쪽 레버, 색 변화를 절차적으로 만든다. 로고는 넣지 않는다
- 컨테이너선, 안벽, 게이트, 바다, 배경 산과 도시 불빛

## 4. 받은 뒤 하는 일

1. `incoming/` 의 GLB를 Blender로 불러와 크기를 실제 치수(사람 1.75m, 트럭 길이 약 7m, 섀시 12.2m)에 맞춘다.
2. 작업자에게 태블릿을 쥐어 주고 촬영 자세를 잡는다.
3. 장면별로 Cycles(실사) 또는 EEVEE로 렌더링하고, Remotion에서 기존 텍스트·UI를 위에 얹는다.

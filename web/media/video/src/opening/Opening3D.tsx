// 발표 영상 오프닝 v2: Three.js 3D 부두 (코드만, Blender 없음). 1920×1080, 30fps
// 연출: 지는 해를 등진 역광 · 긴 그림자 · 노을 안개 · 낮은 카메라에서 크레인처럼 솟고 도는 무빙
//   0   알약 창: 땅에 붙은 카메라, 트레일러 옆모습이 해를 등진 실루엣
//   90  창이 화면 가득 열리며 카메라가 물러나고 솟는다
//   230 훑는 벽이 지나간 자리부터 같은 부두가 선(가장자리)과 점으로 바뀐다 (AI 시야). 차량마다 3D 상자
//   380 카메라가 하늘로 올라가 내려다보면 컨테이너가 타일 판이 된다 → 흰 바탕 제목
import React, {useLayoutEffect, useMemo, useRef} from 'react';
import * as THREE from 'three';
import {useThree} from '@react-three/fiber';
import {ThreeCanvas} from '@remotion/three';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {TitleAct, Words} from './Opening';
import {loadPretendard, WMONO} from '../web/theme';

loadPretendard();

const SCENE_END = 452; // 3D 가 끝나는 프레임 (여기서 타일 판 → 제목)
export const OPENING3D_FRAMES = SCENE_END + 125;

const ACCENT = '#ff5a3c';
const WIRE = '#a9c4dc';
const W = 1920;
const H = 1080;
const FOV_ASPECT = W / H;

const out = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
const k = (f: number, a: number, b: number, easing = out) =>
	interpolate(f, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing});
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
type V3 = [number, number, number];
const mix3 = (a: V3, b: V3, t: number): V3 => [mix(a[0], b[0], t), mix(a[1], b[1], t), mix(a[2], b[2], t)];

const seeded = (seed: number) => {
	let s = seed;
	return () => {
		s = (s * 16807) % 2147483647;
		return (s - 1) / 2147483646;
	};
};

/* ------------------------------------------------------------------ 시간표 */
const truckX = (f: number) => -34 + f * 0.11; // 주인공 트레일러 (m), 초속 3.3m
const SCAN_A = 228;
const SCAN_B = 286;
/** 훑는 벽의 x (m). 시작 전 아주 왼쪽, 끝난 뒤 아주 오른쪽 */
const scanX = (f: number) => (f < SCAN_A ? -1e5 : f > SCAN_B + 4 ? 1e5 : mix(-90, 150, k(f, SCAN_A, SCAN_B, inOut)));
const aiLevel = (f: number) => k(f, SCAN_A + 10, SCAN_B);

// 카메라 열쇠 장면: [프레임, 위치(트럭 기준 x), 보는 곳(트럭 기준 x), 화각]
const KEYS: [number, V3, V3, number][] = [
	[0, [8.5, 0.7, -34], [8.5, 2.6, 0], 17],
	[95, [7.5, 1.4, -30], [7.5, 3.2, 0], 24],
	[170, [-6, 6.5, -21], [6, 2.4, 2], 36],
	[232, [-2, 7.5, -30], [5, 2.2, 3], 38],
	[300, [10, 9, -27], [5, 2, 3], 40],
	[372, [24, 18, -16], [6, 1, 4], 42],
	[440, [10, 150, -0.1], [10, 0, 0], 40],
];

const camAt = (f: number) => {
	let i = 0;
	while (i < KEYS.length - 2 && f > KEYS[i + 1][0]) i++;
	const [f0, p0, l0, v0] = KEYS[i];
	const [f1, p1, l1, v1] = KEYS[i + 1];
	const t = k(f, f0, f1, inOut);
	const tx = truckX(Math.min(f, 400));
	const p = mix3(p0, p1, t);
	const l = mix3(l0, l1, t);
	// 손으로 든 듯한 아주 작은 흔들림
	const sway = Math.sin(f * 0.05) * 0.08;
	return {
		pos: [p[0] + tx, p[1] + sway, p[2]] as V3,
		look: [l[0] + tx, l[1] + sway * 0.5, l[2]] as V3,
		fov: mix(v0, v1, t),
	};
};

/** 화면 좌표 (px). 카메라 뒤면 null */
const projector = (f: number) => {
	const {pos, look, fov} = camAt(f);
	const cam = new THREE.PerspectiveCamera(fov, FOV_ASPECT, 0.1, 5000);
	cam.position.set(...pos);
	cam.lookAt(...look);
	cam.updateMatrixWorld();
	return (p: V3) => {
		const v = new THREE.Vector3(...p).project(cam);
		if (v.z > 1) return null;
		return {x: ((v.x + 1) / 2) * W, y: ((1 - v.y) / 2) * H};
	};
};

const SUN_DIR = new THREE.Vector3(-0.1, 0.06, 1).normalize();

/* ------------------------------------------------------------------ 질감 (코드로 그린 캔버스) */
const canvasTex = (size: number, draw: (g: CanvasRenderingContext2D) => void, repeat?: [number, number]) => {
	const c = document.createElement('canvas');
	c.width = c.height = size;
	const g = c.getContext('2d')!;
	draw(g);
	const t = new THREE.CanvasTexture(c);
	t.colorSpace = THREE.SRGBColorSpace;
	t.anisotropy = 8;
	if (repeat) {
		t.wrapS = t.wrapT = THREE.RepeatWrapping;
		t.repeat.set(...repeat);
	}
	return t;
};

const useTextures = () =>
	useMemo(() => {
		const r = seeded(5);
		const corr = canvasTex(512, (g) => {
			g.fillStyle = '#d8d8d8';
			g.fillRect(0, 0, 512, 512);
			for (let x = 0; x < 512; x += 16) {
				const grad = g.createLinearGradient(x, 0, x + 16, 0);
				grad.addColorStop(0, '#8a8a8a');
				grad.addColorStop(0.5, '#f0f0f0');
				grad.addColorStop(1, '#9a9a9a');
				g.fillStyle = grad;
				g.fillRect(x, 0, 16, 512);
			}
			for (let i = 0; i < 900; i++) {
				g.fillStyle = `rgba(80,40,20,${r() * 0.18})`;
				g.fillRect(r() * 512, r() * 512, 2 + r() * 6, 1 + r() * 3);
			}
			g.fillStyle = 'rgba(30,30,30,0.6)';
			g.fillRect(0, 0, 512, 14);
			g.fillRect(0, 498, 512, 14);
		});
		const asphalt = canvasTex(
			512,
			(g) => {
				g.fillStyle = '#6d6862';
				g.fillRect(0, 0, 512, 512);
				for (let i = 0; i < 9000; i++) {
					const v = 70 + r() * 70;
					g.fillStyle = `rgba(${v},${v - 4},${v - 8},0.5)`;
					g.fillRect(r() * 512, r() * 512, 1.5, 1.5);
				}
				for (let i = 0; i < 20; i++) {
					g.strokeStyle = 'rgba(30,28,26,0.35)';
					g.lineWidth = 1 + r() * 2;
					g.beginPath();
					g.moveTo(r() * 512, r() * 512);
					g.lineTo(r() * 512, r() * 512);
					g.stroke();
				}
			},
			[60, 60],
		);
		const glow = canvasTex(256, (g) => {
			const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
			grad.addColorStop(0, 'rgba(255,248,225,1)');
			grad.addColorStop(0.08, 'rgba(255,226,170,0.95)');
			grad.addColorStop(0.3, 'rgba(255,160,90,0.35)');
			grad.addColorStop(1, 'rgba(255,120,60,0)');
			g.fillStyle = grad;
			g.fillRect(0, 0, 256, 256);
		});
		return {corr, asphalt, glow};
	}, []);

/* ------------------------------------------------------------------ 자르기 면 (훑는 벽) */
type Planes = {solid: THREE.Plane[]; wire: THREE.Plane[]};
const usePlanes = (f: number): Planes => {
	const planes = useMemo(
		() => ({solid: [new THREE.Plane(new THREE.Vector3(1, 0, 0), 1e5)], wire: [new THREE.Plane(new THREE.Vector3(-1, 0, 0), -1e5)]}),
		[],
	);
	const x = scanX(f);
	planes.solid[0].constant = -x; // x > 스캔 이면 실사
	planes.wire[0].constant = x; // x < 스캔 이면 선
	return planes;
};

/** 면의 가장자리만 빛나는 선 재질 (인스턴스에도 쓴다). 화면 두께가 일정하도록 fwidth */
const edgeMaterial = (color: string, planes: THREE.Plane[], fill = 0.05, ribs = 0) => {
	const m = new THREE.MeshBasicMaterial({
		color,
		transparent: true,
		depthWrite: false,
		blending: THREE.AdditiveBlending,
		clippingPlanes: planes,
		fog: false,
		side: THREE.DoubleSide,
	});
	m.defines = {USE_UV: ''};
	m.onBeforeCompile = (s) => {
		s.fragmentShader = s.fragmentShader.replace(
			'#include <dithering_fragment>',
			`float d = min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y));
			float edge = 1.0 - smoothstep(0.0, fwidth(d) * 1.6, d);
			float rib = 0.0;
			if (${ribs.toFixed(1)} > 0.0) {
				float rx = abs(fract(vUv.x * ${ribs.toFixed(1)}) - 0.5);
				rib = (1.0 - smoothstep(0.0, fwidth(vUv.x * ${ribs.toFixed(1)}) * 1.2, 0.5 - rx)) * 0.35;
			}
			gl_FragColor.a *= max(edge, rib) + ${fill.toFixed(3)};
			#include <dithering_fragment>`,
		);
	};
	return m;
};

/* ------------------------------------------------------------------ 부두 배치 */
type Inst = {p: V3; s: V3; c: string};
const PALETTE = ['#7c8a96', '#9b5b40', '#3f6553', '#a8acb0', '#5f5378', '#b48a45', '#3e6487', '#8a3f33', '#6b7a5a'];
const LEN = 12.2;
const HGT = 2.6;
const WID = 2.44;

const YARD: Inst[] = (() => {
	const r = seeded(31);
	const items: Inst[] = [];
	const bands = [
		{z0: 9.5, dir: 1},
		{z0: 33, dir: 1},
		{z0: 57, dir: 1},
		{z0: -40, dir: -1},
		{z0: -64, dir: -1},
	];
	bands.forEach(({z0, dir}) => {
		for (let i = -16; i <= 18; i++) {
			if (i % 7 === 0) continue; // 가로 통로
			if (z0 === 9.5 && i >= -7 && i <= 3) continue; // 오프닝 구간: 트레일러 뒤로 노을이 트인 빈터
			const x = i * 13.6;
			for (let row = 0; row < 6; row++) {
				const z = z0 + dir * (row * (WID + 0.35) + WID / 2);
				const n = r() < 0.1 ? 0 : 1 + Math.floor(r() * 4);
				for (let s = 0; s < n; s++) {
					items.push({p: [x, s * HGT + HGT / 2, z], s: [LEN, HGT - 0.04, WID], c: PALETTE[Math.floor(r() * PALETTE.length)]});
				}
			}
		}
	});
	return items;
})();

/** 크레인·기둥 같은 뼈대 상자들 */
const FRAMES: Inst[] = (() => {
	const items: Inst[] = [];
	const steel = '#3b3236';
	// 장치장 RTG: 띠마다 두 대
	[9.5, 33, 57, -40, -64].forEach((z0, bi) => {
		const dir = z0 > 0 ? 1 : -1;
		const zA = z0 - dir * 1.2;
		const zB = z0 + dir * (6 * (WID + 0.35) + 1.2);
		[-60 + bi * 17, 40 + bi * 11].forEach((x) => {
			[x - 6.5, x + 6.5].forEach((lx) => {
				items.push({p: [lx, 9.5, zA], s: [0.8, 19, 0.8], c: steel});
				items.push({p: [lx, 9.5, zB], s: [0.8, 19, 0.8], c: steel});
			});
			items.push({p: [x, 19.4, (zA + zB) / 2], s: [14.6, 1.4, 1.2], c: steel});
			items.push({p: [x, 19.4, zA], s: [14.6, 1.0, 1.0], c: steel});
			items.push({p: [x, 19.4, zB], s: [14.6, 1.0, 1.0], c: steel});
			items.push({p: [x, 18, (zA + zB) / 2], s: [3, 2, 3], c: '#5a4a3a'});
		});
	});
	// 안벽 STS 크레인: 해를 등진 큰 실루엣
	for (let x = -150; x <= 170; x += 64) {
		const z = 95;
		[z - 9, z + 9].forEach((zz) => {
			items.push({p: [x - 8, 22, zz], s: [1.4, 44, 1.4], c: steel});
			items.push({p: [x + 8, 22, zz], s: [1.4, 44, 1.4], c: steel});
		});
		items.push({p: [x, 44, z], s: [2.4, 2.2, 60], c: steel});
		items.push({p: [x, 52, z - 4], s: [1.2, 16, 1.2], c: steel});
		items.push({p: [x - 8, 30, z], s: [1, 1, 20], c: steel});
		items.push({p: [x + 8, 30, z], s: [1, 1, 20], c: steel});
		items.push({p: [x, 46, z - 22], s: [5, 4, 6], c: '#4a3b3d'});
	}
	// 조명탑
	for (let x = -180; x <= 200; x += 46) {
		[6.8].forEach((z) => {
			items.push({p: [x, 13, z], s: [0.35, 26, 0.35], c: '#2e2a2c'});
			items.push({p: [x, 26.2, z], s: [2.2, 0.5, 0.9], c: '#2e2a2c'});
		});
	}
	return items;
})();

const LAMPS: V3[] = (() => {
	const items: V3[] = [];
	for (let x = -180; x <= 200; x += 46) items.push([x, 25.85, 6.8]);
	return items;
})();

const InstBoxes: React.FC<{items: Inst[]; material: THREE.Material; shadow?: boolean; mono?: boolean}> = ({items, material, shadow, mono}) => {
	const ref = useRef<THREE.InstancedMesh>(null);
	useLayoutEffect(() => {
		const mesh = ref.current!;
		const m = new THREE.Matrix4();
		const q = new THREE.Quaternion();
		const c = new THREE.Color();
		items.forEach((it, i) => {
			m.compose(new THREE.Vector3(...it.p), q, new THREE.Vector3(...it.s));
			mesh.setMatrixAt(i, m);
			if (!mono) mesh.setColorAt(i, c.set(it.c));
		});
		mesh.instanceMatrix.needsUpdate = true;
		if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
	}, [items, mono]);
	return (
		<instancedMesh ref={ref} args={[undefined, undefined, items.length]} material={material} castShadow={shadow} receiveShadow={shadow}>
			<boxGeometry args={[1, 1, 1]} />
		</instancedMesh>
	);
};

/* ------------------------------------------------------------------ 트레일러 */
type TruckSpec = {x: number; z: number; dir: 1 | -1; box: string; hero?: boolean};

const truckParts = (box: string): Inst[] => [
	// 컨테이너 · 섀시 · 트랙터 (원점 = 트레일러 뒤 끝, 땅 높이, 앞이 +x)
	{p: [6.4, 2.65, 0], s: [LEN, HGT, WID], c: box},
	{p: [7.2, 1.15, 0], s: [14.2, 0.32, 2.3], c: '#1d1b1c'},
	{p: [15.3, 2.0, 0], s: [2.6, 3.1, 2.5], c: '#2a2f36'},
	{p: [16.95, 1.45, 0], s: [0.9, 1.9, 2.4], c: '#262a30'},
	{p: [14.0, 2.9, 0], s: [0.25, 1.0, 0.25], c: '#9a9a9a'},
	{p: [15.9, 2.95, 0], s: [0.9, 0.9, 2.52], c: '#20262c'},
];
const WHEELS: V3[] = [
	[1.6, 0.55, 1.05],
	[1.6, 0.55, -1.05],
	[2.9, 0.55, 1.05],
	[2.9, 0.55, -1.05],
	[13.9, 0.55, 1.05],
	[13.9, 0.55, -1.05],
	[16.3, 0.55, 1.05],
	[16.3, 0.55, -1.05],
];

const Truck: React.FC<{spec: TruckSpec; f: number; corr: THREE.Texture; planes: Planes; wireMat: THREE.Material; wheelWire: THREE.Material; heroWire: THREE.Material}> = ({
	spec,
	f,
	corr,
	planes,
	wireMat,
	wheelWire,
	heroWire,
}) => {
	const parts = truckParts(spec.box);
	const spin = (f * 0.11) / 0.55;
	return (
		<group position={[spec.x, 0, spec.z]} rotation={[0, spec.dir === 1 ? 0 : Math.PI, 0]}>
			{parts.map((p, i) => (
				<group key={i}>
					<mesh position={p.p} castShadow receiveShadow>
						<boxGeometry args={p.s} />
						<meshStandardMaterial
							color={p.c}
							map={i === 0 ? corr : null}
							roughness={i === 5 ? 0.12 : i >= 2 ? 0.32 : 0.55}
							metalness={i === 5 ? 0.7 : i >= 2 ? 0.55 : 0.25}
							clippingPlanes={planes.solid}
						/>
					</mesh>
					<mesh position={p.p} material={spec.hero && i === 0 ? heroWire : wireMat}>
						<boxGeometry args={p.s} />
					</mesh>
				</group>
			))}
			{WHEELS.map((w, i) => (
				<group key={i} position={w} rotation={[Math.PI / 2, 0, 0]}>
					<mesh rotation={[0, spin, 0]} castShadow>
						<cylinderGeometry args={[0.55, 0.55, 0.45, 18]} />
						<meshStandardMaterial color="#121112" roughness={0.9} clippingPlanes={planes.solid} />
					</mesh>
					<mesh rotation={[0, spin, 0]} material={wheelWire}>
						<cylinderGeometry args={[0.55, 0.55, 0.45, 12]} />
					</mesh>
				</group>
			))}
			{/* 전조등 */}
			<mesh position={[17.42, 1.2, 0.85]}>
				<boxGeometry args={[0.05, 0.25, 0.4]} />
				<meshBasicMaterial color="#fff2c8" clippingPlanes={planes.solid} />
			</mesh>
			<mesh position={[17.42, 1.2, -0.85]}>
				<boxGeometry args={[0.05, 0.25, 0.4]} />
				<meshBasicMaterial color="#fff2c8" clippingPlanes={planes.solid} />
			</mesh>
		</group>
	);
};

const truckSpecs = (f: number): TruckSpec[] => [
	{x: truckX(f), z: 0, dir: 1, box: '#b2402a', hero: true},
	{x: 95 - f * 0.12, z: -3.4, dir: -1, box: '#3e6487'},
	{x: 40 - f * 0.07, z: 21, dir: -1, box: '#3f6553'},
];

/* ------------------------------------------------------------------ 하늘 */
const skyMaterial = () =>
	new THREE.ShaderMaterial({
		side: THREE.BackSide,
		depthWrite: false,
		fog: false,
		uniforms: {sunDir: {value: SUN_DIR}, dark: {value: 0}},
		vertexShader: `varying vec3 vDir; void main(){ vDir = normalize((modelMatrix * vec4(position,1.0)).xyz - cameraPosition); gl_Position = projectionMatrix * viewMatrix * modelMatrix * vec4(position,1.0); }`,
		fragmentShader: `uniform vec3 sunDir; uniform float dark; varying vec3 vDir;
		void main(){
			vec3 d = normalize(vDir); float h = d.y; float s = max(dot(d, sunDir), 0.0);
			vec3 top = vec3(0.07,0.07,0.13); vec3 mid = vec3(0.45,0.22,0.24); vec3 hor = vec3(1.0,0.58,0.32);
			vec3 c = mix(hor, mid, smoothstep(0.0, 0.16, h)); c = mix(c, top, smoothstep(0.16, 0.6, h));
			c += vec3(1.0,0.62,0.32) * pow(s, 6.0) * 0.55 + vec3(1.0,0.85,0.6) * pow(s, 60.0) * 0.9;
			if (h < 0.0) c = mix(hor * 0.7, vec3(0.2,0.12,0.1), smoothstep(0.0, -0.2, h));
			c = mix(c, vec3(0.012,0.016,0.024), dark);
			gl_FragColor = vec4(c, 1.0);
			#include <tonemapping_fragment>
			#include <colorspace_fragment>
		}`,
	});

/* ------------------------------------------------------------------ 3D 세계 */
const World: React.FC<{f: number}> = ({f}) => {
	const {camera, scene, gl} = useThree();
	const tex = useTextures();
	const planes = usePlanes(f);
	const cam = camAt(f);
	const ai = aiLevel(f);

	const mats = useMemo(
		() => ({
			box: new THREE.MeshStandardMaterial({map: tex.corr, roughness: 0.62, metalness: 0.28, clippingPlanes: planes.solid}),
			frame: new THREE.MeshStandardMaterial({roughness: 0.7, metalness: 0.4, clippingPlanes: planes.solid}),
			boxWire: edgeMaterial(WIRE, planes.wire, 0.025, 10),
			frameWire: edgeMaterial(WIRE, planes.wire, 0.04),
			truckWire: edgeMaterial('#e9f3ff', planes.wire, 0.04, 0),
			heroWire: edgeMaterial(ACCENT, planes.wire, 0.12, 14),
			wheelWire: edgeMaterial('#e9f3ff', planes.wire, 0.03),
			sky: skyMaterial(),
		}),
		[tex, planes],
	);

	useLayoutEffect(() => {
		gl.localClippingEnabled = true;
		gl.toneMapping = THREE.ACESFilmicToneMapping;
		gl.toneMappingExposure = 1.2;
		gl.shadowMap.type = THREE.PCFSoftShadowMap;
		scene.background = new THREE.Color('#030508');
		scene.fog = new THREE.Fog('#d4774f', 25, 260);
	}, [gl, scene]);

	useLayoutEffect(() => {
		const c = camera as THREE.PerspectiveCamera;
		c.position.set(...cam.pos);
		c.fov = cam.fov;
		c.near = 0.1;
		c.far = 5000;
		c.lookAt(...cam.look);
		c.updateProjectionMatrix();
	});
	mats.sky.uniforms.dark.value = ai;

	const tx = truckX(Math.min(f, 400));
	const sunPos = new THREE.Vector3(...cam.pos).addScaledVector(SUN_DIR, 1400);
	const lightTarget = useMemo(() => new THREE.Object3D(), []);
	lightTarget.position.set(tx + 10, 0, 4);
	const lightPos = lightTarget.position.clone().addScaledVector(SUN_DIR, 260);

	// AI 시야의 바닥 점 격자 (선 쪽만 보인다)
	const dots = useMemo(() => {
		const pts: number[] = [];
		for (let x = -200; x <= 240; x += 2.4) for (let z = -60; z <= 80; z += 2.4) pts.push(x, 0.02, z);
		const g = new THREE.BufferGeometry();
		g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
		return g;
	}, []);
	const trucks = truckSpecs(Math.min(f, 400));

	return (
		<>
			<primitive object={lightTarget} />
			<hemisphereLight args={['#ffbe94', '#3a2a2e', 0.9]} />
			<ambientLight intensity={0.08} />
			<directionalLight
				position={lightPos.toArray()}
				target={lightTarget}
				color="#ffae6e"
				intensity={3.4}
				castShadow
				shadow-mapSize={[4096, 4096]}
				shadow-bias={-0.0004}
				shadow-normalBias={0.03}
				shadow-camera-left={-90}
				shadow-camera-right={90}
				shadow-camera-top={70}
				shadow-camera-bottom={-70}
				shadow-camera-near={10}
				shadow-camera-far={600}
			/>
			{/* 카메라 쪽에서 오는 아주 약한 푸른 채움빛 (그림자 쪽이 완전히 묻히지 않게) */}
			<directionalLight position={[cam.pos[0] - 40, 30, cam.pos[2] - 80]} color="#6a7cae" intensity={0.25} />

			<mesh material={mats.sky} position={cam.pos}>
				<sphereGeometry args={[2000, 32, 16]} />
			</mesh>
			{/* 해: 크레인·컨테이너에 가려지도록 깊이 검사 */}
			<sprite position={sunPos.toArray()} scale={[420, 420, 1]}>
				<spriteMaterial map={tex.glow} transparent depthWrite={false} blending={THREE.AdditiveBlending} fog={false} opacity={1 - ai} />
			</sprite>

			{/* 땅 */}
			<mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
				<planeGeometry args={[900, 900]} />
				<meshStandardMaterial map={tex.asphalt} color="#8a8178" roughness={0.42} metalness={0.15} clippingPlanes={planes.solid} />
			</mesh>
			{/* 차선 */}
			{Array.from({length: 40}, (_, i) => (
				<mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[-200 + i * 11, 0.02, -1.6]}>
					<planeGeometry args={[5, 0.18]} />
					<meshStandardMaterial color="#e8d6b0" roughness={0.6} clippingPlanes={planes.solid} />
				</mesh>
			))}
			<points geometry={dots}>
				<pointsMaterial color={WIRE} size={2.2} sizeAttenuation={false} transparent opacity={0.55} clippingPlanes={planes.wire} fog={false} />
			</points>

			<InstBoxes items={YARD} material={mats.box} shadow />
			<InstBoxes items={YARD} material={mats.boxWire} mono />
			<InstBoxes items={FRAMES} material={mats.frame} shadow />
			<InstBoxes items={FRAMES} material={mats.frameWire} mono />
			{LAMPS.map((p, i) => (
				<sprite key={i} position={p} scale={[5, 5, 1]}>
					<spriteMaterial map={tex.glow} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0.6 * (1 - ai)} />
				</sprite>
			))}

			{trucks.map((t, i) => (
				<Truck key={i} spec={t} f={f} corr={tex.corr} planes={planes} wireMat={mats.truckWire} wheelWire={mats.wheelWire} heroWire={mats.heroWire} />
			))}

			{/* 훑는 벽: 밝은 막 + 바닥의 선 */}
			{f >= SCAN_A && f <= SCAN_B + 4 && (
				<group position={[scanX(f), 0, 10]}>
					<mesh position={[0, 30, 0]} rotation={[0, Math.PI / 2, 0]}>
						<planeGeometry args={[220, 60]} />
						<meshBasicMaterial color="#cfe6ff" transparent opacity={0.07} side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending} fog={false} />
					</mesh>
					<mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
						<planeGeometry args={[0.5, 220]} />
						<meshBasicMaterial color="#ffffff" fog={false} />
					</mesh>
				</group>
			)}

			{/* AI 상자: 차량마다 */}
			{ai > 0 &&
				trucks.map((t, i) => (
					<lineSegments key={i} position={[t.x + t.dir * 8.6, 2.2, t.z]}>
						<edgesGeometry args={[new THREE.BoxGeometry(18.4, 4.6, 3.2)]} />
						<lineBasicMaterial color={t.hero ? ACCENT : '#ffffff'} transparent opacity={ai * (t.hero ? 0.6 + 0.4 * Math.sin(f * 0.35) : 0.7)} fog={false} />
					</lineSegments>
				))}
		</>
	);
};

/* ------------------------------------------------------------------ 화면 위 (이름표 · 빛 · 결) */
const Label: React.FC<{x: number; y: number; text: string; sub?: string; red?: boolean; o: number}> = ({x, y, text, sub, red, o}) => (
	<div style={{position: 'absolute', left: x, top: y, transform: 'translate(-50%, -100%)', opacity: o, pointerEvents: 'none'}}>
		<div
			style={{
				fontFamily: WMONO,
				fontSize: 18,
				fontWeight: 700,
				letterSpacing: 1,
				padding: '7px 12px',
				borderRadius: 8,
				whiteSpace: 'nowrap',
				background: red ? ACCENT : 'rgba(233,243,255,0.94)',
				color: red ? '#fff' : '#06090d',
			}}
		>
			{text}
		</div>
		{sub && (
			<div style={{fontFamily: WMONO, fontSize: 16, color: red ? ACCENT : '#e9f3ff', marginTop: 6, textAlign: 'center', whiteSpace: 'nowrap'}}>{sub}</div>
		)}
		<div style={{width: 1.5, height: 26, background: red ? ACCENT : '#e9f3ff', margin: '6px auto 0'}} />
	</div>
);

const Overlay: React.FC<{f: number}> = ({f}) => {
	const proj = projector(f);
	const {pos} = camAt(f);
	const ai = aiLevel(f);
	const sun = proj([pos[0] + SUN_DIR.x * 1400, pos[1] + SUN_DIR.y * 1400, pos[2] + SUN_DIR.z * 1400]);
	const trucks = truckSpecs(Math.min(f, 400));
	const hero = trucks[0];
	const labelO = k(f, SCAN_B - 10, SCAN_B + 10) * (1 - k(f, 372, 392));
	const heroTop = proj([hero.x + 6.4, 5.4, hero.z]);
	const docs: {p: V3; text: string; sub: string; red?: boolean; at: number}[] = [
		{p: [hero.x + 3.2, 4.2, hero.z - 1.3], text: '상업송장', sub: '총중량 6,250 kg', at: SCAN_B + 6},
		{p: [hero.x + 9.6, 4.2, hero.z - 1.3], text: '포장명세서', sub: '총중량 6,520 kg', red: true, at: SCAN_B + 14},
	];
	return (
		<AbsoluteFill style={{pointerEvents: 'none'}}>
			{/* 해 주변 빛 번짐 (역광 플레어) */}
			{sun && (
				<>
					<div
						style={{
							position: 'absolute',
							left: sun.x - 700,
							top: sun.y - 700,
							width: 1400,
							height: 1400,
							borderRadius: '50%',
							background: 'radial-gradient(circle, rgba(255,190,120,0.28) 0%, rgba(255,140,80,0.10) 35%, rgba(255,120,60,0) 70%)',
							mixBlendMode: 'screen',
							opacity: 1 - ai,
						}}
					/>
					{[0.35, 0.62, 1.25].map((t, i) => {
						const x = sun.x + (960 - sun.x) * t * 2;
						const y = sun.y + (540 - sun.y) * t * 2;
						const s = [120, 60, 220][i];
						return (
							<div
								key={i}
								style={{
									position: 'absolute',
									left: x - s / 2,
									top: y - s / 2,
									width: s,
									height: s,
									borderRadius: '50%',
									background: `radial-gradient(circle, rgba(255,${180 + i * 20},140,0.10), rgba(255,160,120,0) 70%)`,
									mixBlendMode: 'screen',
									opacity: 1 - ai,
								}}
							/>
						);
					})}
				</>
			)}
			{/* AI 이름표 */}
			{heroTop && (
				<Label x={heroTop.x} y={heroTop.y - 120} text="B/L BL-2026-0001 · 40FT" sub="컨테이너 SEGU 412839 0" o={labelO} />
			)}
			{docs.map((d, i) => {
				const p = proj(d.p);
				return p ? <Label key={i} x={p.x} y={p.y} text={d.text} sub={d.sub} red={d.red} o={k(f, d.at, d.at + 10) * (1 - k(f, 372, 392))} /> : null;
			})}
			{(() => {
				const p = proj([hero.x + 9, 0.2, hero.z - 2]);
				return p ? (
					<div
						style={{
							position: 'absolute',
							left: p.x,
							top: p.y + 30,
							transform: 'translateX(-50%)',
							fontFamily: WMONO,
							fontSize: 22,
							fontWeight: 700,
							color: ACCENT,
							opacity: k(f, SCAN_B + 24, SCAN_B + 34) * (1 - k(f, 372, 392)),
							whiteSpace: 'nowrap',
						}}
					>
						X-WT-01 · 서류 간 총중량 불일치
					</div>
				) : null;
			})()}
			{/* 모서리 표시 */}
			<div style={{position: 'absolute', left: 96, top: 70, fontFamily: WMONO, fontSize: 18, letterSpacing: 4, color: '#f3e4d4', opacity: 0.75 * k(f, 70, 100) * (1 - ai)}}>
				BUSAN NEW PORT · 18:42 KST
			</div>
			<div style={{position: 'absolute', right: 96, top: 70, fontFamily: WMONO, fontSize: 18, letterSpacing: 4, color: '#e9f3ff', opacity: ai * (0.6 + 0.4 * Math.sin(f * 0.5)) * (1 - k(f, 380, 400))}}>
				● AGENT VIEW · 4 DOCS
			</div>
			{/* 글 */}
			<div style={{position: 'absolute', left: 0, right: 0, bottom: 150, opacity: 1 - k(f, 214, 228)}}>
				<Words f={f} at={118} lines={['서류 한 장의 오타가', '컨테이너 한 대를 멈춘다.']} size={70} />
			</div>
			<div style={{position: 'absolute', left: 96, bottom: 96, opacity: 1 - k(f, 366, 380)}}>
				<Words f={f} at={300} lines={['AI는 읽고,', '코드가 판정한다.']} size={70} align="left" />
			</div>
			{/* 영화 같은 마감: 비네트 · 위아래 어둠 · 결 */}
			<div style={{position: 'absolute', inset: 0, background: 'radial-gradient(ellipse at 50% 55%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)'}} />
			<div style={{position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 70%, rgba(0,0,0,0.45) 100%)'}} />
			<svg width={W} height={H} style={{position: 'absolute', inset: 0, opacity: 0.07, mixBlendMode: 'overlay'}}>
				<filter id="grain">
					<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={f % 12} />
				</filter>
				<rect width={W} height={H} filter="url(#grain)" />
			</svg>
		</AbsoluteFill>
	);
};

/* ------------------------------------------------------------------ 이어 붙이기 */
const Scene3D: React.FC<{f: number}> = ({f}) => {
	// 알약 창: 가는 띠 → 가로로 긴 창 → 화면 가득
	const a = k(f, 2, 26);
	const b = k(f, 60, 112, Easing.bezier(0.76, 0, 0.24, 1));
	const pw = mix(mix(320, 1560, a), W, b);
	const ph = mix(mix(6, 240, a), H, b);
	const radius = mix(ph / 2, 0, b);
	const insetX = (W - pw) / 2;
	const insetY = (H - ph) / 2;
	// 끝: 내려다본 컨테이너가 타일 판으로 어두워진다
	const toTiles = k(f, SCENE_END - 26, SCENE_END);
	return (
		<AbsoluteFill style={{background: '#000'}}>
			<AbsoluteFill style={{clipPath: `inset(${insetY}px ${insetX}px round ${radius}px)`}}>
				<ThreeCanvas width={W} height={H} shadows camera={{fov: 30, near: 0.1, far: 5000}} gl={{antialias: true}}>
					<World f={f} />
				</ThreeCanvas>
				<Overlay f={f} />
			</AbsoluteFill>
			<AbsoluteFill style={{background: '#050607', opacity: toTiles}} />
		</AbsoluteFill>
	);
};

export const Opening3D: React.FC = () => {
	const f = useCurrentFrame();
	if (f < SCENE_END) return <Scene3D f={f} />;
	return <TitleAct f={f - SCENE_END} />;
};

/* 부산항 컨테이너 터미널을 단순화한 3D 세계 (단위: m)
 * 물: y=0, z<0 쪽이 바다. 안벽(quay)은 z 0~45, 장치장(yard)은 z 55~140.
 * 크레인 4기는 안벽을 따라 x=-90,-30,30,90. 선박은 z -44~-4에 접안.
 */
import React, {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import * as THREE from 'three';
import {useThree} from '@react-three/fiber';
import {continueRender, delayRender, staticFile} from 'remotion';
import {rand} from '../ui';

const BOX_COLORS = ['#c2410c', '#0f766e', '#1d4ed8', '#9f1239', '#a16207', '#64748b', '#e5e7eb', '#15803d', '#7c2d12'];

type V3 = [number, number, number];

export const CameraRig: React.FC<{pos: V3; look: V3; fov?: number}> = ({pos, look, fov = 40}) => {
	const {camera} = useThree();
	useLayoutEffect(() => {
		camera.position.set(pos[0], pos[1], pos[2]);
		(camera as THREE.PerspectiveCamera).fov = fov;
		camera.lookAt(look[0], look[1], look[2]);
		camera.updateProjectionMatrix();
	});
	return null;
};

export const useTex = (file: string) => {
	const [handle] = useState(() => delayRender(`texture ${file}`));
	const [tex, setTex] = useState<THREE.Texture | null>(null);
	useEffect(() => {
		new THREE.TextureLoader().load(
			staticFile(file),
			(t) => {
				t.colorSpace = THREE.SRGBColorSpace;
				t.anisotropy = 8;
				setTex(t);
				continueRender(handle);
			},
			undefined,
			() => continueRender(handle),
		);
	}, [file, handle]);
	return tex;
};

type Inst = {p: V3; s: V3; c: string};

const Instances: React.FC<{items: Inst[]; emissive?: string; emissiveIntensity?: number; shadow?: boolean}> = ({
	items,
	emissive,
	emissiveIntensity = 0,
	shadow = true,
}) => {
	const ref = useRef<THREE.InstancedMesh>(null);
	useLayoutEffect(() => {
		const mesh = ref.current;
		if (!mesh) return;
		const m = new THREE.Matrix4();
		const q = new THREE.Quaternion();
		const color = new THREE.Color();
		items.forEach((it, i) => {
			m.compose(new THREE.Vector3(...it.p), q, new THREE.Vector3(...it.s));
			mesh.setMatrixAt(i, m);
			mesh.setColorAt(i, color.set(it.c));
		});
		mesh.instanceMatrix.needsUpdate = true;
		if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
	}, [items]);
	return (
		<instancedMesh ref={ref} args={[undefined, undefined, items.length]} castShadow={shadow} receiveShadow={shadow}>
			<boxGeometry args={[1, 1, 1]} />
			<meshStandardMaterial roughness={0.75} metalness={0.1} emissive={emissive ?? '#000000'} emissiveIntensity={emissiveIntensity} />
		</instancedMesh>
	);
};

const Box: React.FC<{p: V3; s: V3; c: string; e?: string; ei?: number; r?: V3}> = ({p, s, c, e, ei = 0, r}) => (
	<mesh position={p} rotation={r ?? [0, 0, 0]} castShadow receiveShadow>
		<boxGeometry args={s} />
		<meshStandardMaterial color={c} roughness={0.6} metalness={0.2} emissive={e ?? '#000000'} emissiveIntensity={ei} />
	</mesh>
);

/* 하늘: 위는 짙은 남색, 수평선은 노을 */
const Sky: React.FC<{night?: boolean}> = ({night}) => {
	const geo = useMemo(() => {
		const g = new THREE.SphereGeometry(2500, 48, 24);
		const top = new THREE.Color(night ? '#050a18' : '#0b1736');
		const mid = new THREE.Color(night ? '#0d1a36' : '#2e4373');
		const low = new THREE.Color(night ? '#1d2b4d' : '#f0a35e');
		const cols: number[] = [];
		const pos = g.attributes.position;
		for (let i = 0; i < pos.count; i++) {
			const y = pos.getY(i) / 2500;
			const c = y > 0.18 ? mid.clone().lerp(top, Math.min(1, (y - 0.18) / 0.6)) : low.clone().lerp(mid, Math.max(0, y / 0.18));
			cols.push(c.r, c.g, c.b);
		}
		g.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
		return g;
	}, [night]);
	return (
		<mesh geometry={geo}>
			<meshBasicMaterial vertexColors side={THREE.BackSide} fog={false} />
		</mesh>
	);
};

const STSCrane: React.FC<{x: number; trolley: number}> = ({x, trolley}) => {
	const steel = '#d5dde8';
	const accent = '#f59e0b';
	return (
		<group position={[x, 3, 0]}>
			{/* 다리 4개 (레일 간격 26m) */}
			{[
				[-9, 6],
				[9, 6],
				[-9, 32],
				[9, 32],
			].map(([dx, z]) => (
				<Box key={`${dx}-${z}`} p={[dx, 21, z]} s={[1.6, 42, 1.6]} c={steel} />
			))}
			<Box p={[0, 6, 6]} s={[20, 1.4, 1.4]} c={steel} />
			<Box p={[0, 6, 32]} s={[20, 1.4, 1.4]} c={steel} />
			<Box p={[-9, 30, 19]} s={[1.2, 1.2, 26]} c={steel} />
			<Box p={[9, 30, 19]} s={[1.2, 1.2, 26]} c={steel} />
			{/* 붐: 바다 쪽으로 길게 */}
			<Box p={[0, 44, -12]} s={[6, 3, 92]} c={accent} />
			<Box p={[0, 44, 34]} s={[6, 3, 4]} c={accent} />
			{/* A 프레임 */}
			<Box p={[-4, 54, 20]} s={[1.2, 22, 1.2]} c={steel} r={[0.35, 0, 0]} />
			<Box p={[4, 54, 20]} s={[1.2, 22, 1.2]} c={steel} r={[0.35, 0, 0]} />
			{/* 기계실 */}
			<Box p={[0, 48.5, 28]} s={[8, 6, 10]} c="#e2e8f0" />
			{/* 트롤리와 스프레더 */}
			<Box p={[0, 41.6, trolley]} s={[5, 2, 4]} c="#334155" />
			<Box p={[0, 34, trolley]} s={[3, 0.8, 7]} c={accent} e={accent} ei={0.4} />
			{/* 경고등 */}
			<mesh position={[0, 46, -58]}>
				<sphereGeometry args={[0.8, 12, 8]} />
				<meshStandardMaterial color="#ff5a3c" emissive="#ff5a3c" emissiveIntensity={3} />
			</mesh>
		</group>
	);
};

const Ship: React.FC = () => {
	const boxes = useMemo(() => {
		const items: Inst[] = [];
		let k = 0;
		for (let bx = 0; bx < 28; bx++) {
			for (let row = 0; row < 13; row++) {
				const tiers = 3 + Math.floor(rand(bx * 31 + row * 7) * 4);
				for (let t = 0; t < tiers; t++) {
					items.push({
						p: [-110 + bx * 6.6, 15.3 + t * 2.62, -40 + row * 2.6],
						s: [6.05, 2.55, 2.4],
						c: BOX_COLORS[Math.floor(rand(k++ * 3.1) * BOX_COLORS.length)],
					});
				}
			}
		}
		return items;
	}, []);
	return (
		<group>
			{/* 선체 */}
			<Box p={[0, 6, -24]} s={[250, 16, 42]} c="#1f3b63" />
			<Box p={[0, -1, -24]} s={[250, 2, 42]} c="#8b1d1d" />
			<mesh position={[134, 6, -24]} rotation={[0, Math.PI / 4, 0]} castShadow>
				<boxGeometry args={[29.7, 16, 29.7]} />
				<meshStandardMaterial color="#1f3b63" roughness={0.6} />
			</mesh>
			{/* 선교 */}
			<Box p={[95, 28, -24]} s={[14, 26, 36]} c="#e8edf3" />
			<Box p={[95, 41.5, -24]} s={[16, 2, 40]} c="#cbd5e1" />
			<Instances items={boxes} />
		</group>
	);
};

const Yard: React.FC = () => {
	const boxes = useMemo(() => {
		const items: Inst[] = [];
		let k = 0;
		for (let block = 0; block < 4; block++) {
			for (let x = -140; x <= 140; x += 6.6) {
				if (Math.abs(x) < 4) continue;
				for (let row = 0; row < 7; row++) {
					const z = 58 + block * 22 + row * 2.6;
					const h = Math.floor(rand(x * 13 + z * 7) * 5);
					for (let t = 0; t < h; t++) {
						items.push({p: [x, 3 + 1.28 + t * 2.6, z], s: [6.05, 2.55, 2.4], c: BOX_COLORS[Math.floor(rand(k++ * 1.7) * BOX_COLORS.length)]});
					}
				}
			}
		}
		return items;
	}, []);
	// 야드 크레인(RTG) 몇 기
	return (
		<group>
			<Instances items={boxes} />
			{[-100, -20, 60, 120].map((x, i) => (
				<group key={x} position={[x, 3, 58 + i * 22 + 8]}>
					<Box p={[-3, 8, -10]} s={[0.8, 16, 0.8]} c="#e2e8f0" />
					<Box p={[-3, 8, 10]} s={[0.8, 16, 0.8]} c="#e2e8f0" />
					<Box p={[3, 8, -10]} s={[0.8, 16, 0.8]} c="#e2e8f0" />
					<Box p={[3, 8, 10]} s={[0.8, 16, 0.8]} c="#e2e8f0" />
					<Box p={[0, 16.5, 0]} s={[7, 1.2, 22]} c="#f59e0b" />
				</group>
			))}
		</group>
	);
};

const Mountains: React.FC<{night?: boolean}> = ({night}) => {
	const peaks = useMemo(
		() =>
			Array.from({length: 14}, (_, i) => ({
				x: -900 + i * 140 + rand(i) * 80,
				z: 420 + rand(i * 3) * 220,
				r: 110 + rand(i * 5) * 120,
				h: 70 + rand(i * 7) * 130,
			})),
		[],
	);
	const lights = useMemo(() => {
		const items: Inst[] = [];
		for (let i = 0; i < 520; i++) {
			const x = -800 + rand(i * 2.3) * 1500;
			const z = 260 + rand(i * 4.1) * 160;
			const h = 4 + rand(i * 5.7) * 26;
			items.push({p: [x, h / 2, z], s: [6 + rand(i) * 10, h, 6 + rand(i * 9) * 8], c: '#1a2741'});
		}
		return items;
	}, []);
	const windows = useMemo(() => {
		const items: Inst[] = [];
		for (let i = 0; i < 900; i++) {
			items.push({
				p: [-800 + rand(i * 3.7) * 1500, 2 + rand(i * 1.9) * 28, 258 + rand(i * 6.1) * 150],
				s: [1.2, 0.9, 0.3],
				c: rand(i * 8.3) > 0.3 ? '#ffd08a' : '#cfe3ff',
			});
		}
		return items;
	}, []);
	return (
		<group>
			{peaks.map((p, i) => (
				<mesh key={i} position={[p.x, p.h / 2 - 2, p.z]}>
					<coneGeometry args={[p.r, p.h, 7]} />
					<meshStandardMaterial color={night ? '#0e1830' : '#1b2a47'} flatShading roughness={1} />
				</mesh>
			))}
			<Instances items={lights} shadow={false} />
			<Instances items={windows} emissive="#ffd08a" emissiveIntensity={night ? 2.5 : 1.4} shadow={false} />
		</group>
	);
};

/* 부산항대교를 닮은 사장교: 배경 왼쪽 */
const Bridge: React.FC = () => {
	const cables = useMemo(() => {
		const g = new THREE.Group();
		const mat = new THREE.LineBasicMaterial({color: '#cfd8e6', transparent: true, opacity: 0.8});
		[-560, -300].forEach((tx) => {
			for (let i = 1; i <= 8; i++) {
				[-1, 1].forEach((dir) => {
					const pts = [new THREE.Vector3(tx, 150 - i * 4, 230), new THREE.Vector3(tx + dir * i * 15, 44, 230)];
					g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat));
				});
			}
		});
		return g;
	}, []);
	return (
		<group>
			<Box p={[-430, 42, 230]} s={[620, 4, 22]} c="#3b4b66" />
			{[-560, -300].map((x) => (
				<group key={x}>
					<Box p={[x - 6, 75, 230]} s={[4, 150, 5]} c="#dfe6f0" />
					<Box p={[x + 6, 75, 230]} s={[4, 150, 5]} c="#dfe6f0" />
					<Box p={[x, 120, 230]} s={[16, 4, 5]} c="#dfe6f0" />
				</group>
			))}
			{Array.from({length: 26}, (_, i) => (
				<mesh key={i} position={[-735 + i * 24, 45.5, 230]}>
					<sphereGeometry args={[0.9, 8, 6]} />
					<meshStandardMaterial color="#ffd08a" emissive="#ffd08a" emissiveIntensity={3} />
				</mesh>
			))}
			<primitive object={cables} />
		</group>
	);
};

const YardLights: React.FC = () => (
	<group>
		{[-150, -75, 0, 75, 150].flatMap((x) =>
			[50, 100, 145].map((z) => (
				<group key={`${x}-${z}`} position={[x, 3, z]}>
					<Box p={[0, 15, 0]} s={[0.6, 30, 0.6]} c="#94a3b8" />
					<mesh position={[0, 30.5, 0]}>
						<boxGeometry args={[4, 1, 1.5]} />
						<meshStandardMaterial color="#fff3d6" emissive="#ffe7b0" emissiveIntensity={4} />
					</mesh>
				</group>
			)),
		)}
	</group>
);

export const PortWorld: React.FC<{f: number; night?: boolean; sun?: number}> = ({f, night, sun = 1}) => (
	<>
		<Sky night={night} />
		<fog attach="fog" args={[night ? '#101b33' : '#3b4a6b', 260, 1500]} />
		<ambientLight intensity={night ? 0.25 : 0.4} />
		<hemisphereLight args={['#a9c6ff', '#1a2540', night ? 0.35 : 0.7]} />
		<directionalLight
			position={[-260, 160, -260]}
			intensity={(night ? 0.5 : 2.2) * sun}
			color={night ? '#9fb7ff' : '#ffc890'}
			castShadow
			shadow-mapSize-width={2048}
			shadow-mapSize-height={2048}
			shadow-camera-left={-220}
			shadow-camera-right={220}
			shadow-camera-top={200}
			shadow-camera-bottom={-200}
			shadow-camera-near={10}
			shadow-camera-far={900}
			shadow-bias={-0.0004}
		/>
		<pointLight position={[0, 40, 60]} intensity={night ? 1500 : 350} distance={300} color="#ffdca8" />
		{/* 바다 */}
		<mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
			<planeGeometry args={[5000, 5000]} />
			<meshStandardMaterial color={night ? '#0b2140' : '#24578c'} roughness={0.35} metalness={0.15} />
		</mesh>
		{/* 안벽과 장치장 바닥 */}
		<Box p={[0, 1.5, 95]} s={[560, 3, 190]} c="#4b5566" />
		<Box p={[0, 3.02, 22]} s={[560, 0.05, 1]} c="#facc15" />
		{/* 레일 */}
		<Box p={[0, 3.05, 6]} s={[560, 0.1, 0.4]} c="#94a3b8" />
		<Box p={[0, 3.05, 32]} s={[560, 0.1, 0.4]} c="#94a3b8" />
		<Ship />
		{[-90, -30, 30, 90].map((x, i) => (
			<STSCrane key={x} x={x} trolley={-20 + ((f * 0.35 + i * 17) % 45)} />
		))}
		<Yard />
		<YardLights />
		<Mountains night={night} />
		<Bridge />
	</>
);

/* 작업자: 안전모·형광 조끼, 태블릿과 서류철을 든 모습. 정면은 -z */
export const Worker: React.FC<{p: V3; ry?: number; screen?: THREE.Texture | null; doc?: THREE.Texture | null; glow?: number}> = ({
	p,
	ry = 0,
	screen,
	doc,
	glow = 0,
}) => (
	<group position={p} rotation={[0, ry, 0]}>
		{/* 다리 */}
		<mesh position={[-0.12, 0.45, 0]} castShadow>
			<cylinderGeometry args={[0.09, 0.08, 0.9, 12]} />
			<meshStandardMaterial color="#1e293b" />
		</mesh>
		<mesh position={[0.12, 0.45, 0]} castShadow>
			<cylinderGeometry args={[0.09, 0.08, 0.9, 12]} />
			<meshStandardMaterial color="#1e293b" />
		</mesh>
		{/* 몸통 + 형광 조끼 */}
		<mesh position={[0, 1.2, 0]} castShadow>
			<capsuleGeometry args={[0.22, 0.5, 6, 14]} />
			<meshStandardMaterial color="#f97316" roughness={0.55} />
		</mesh>
		{[1.05, 1.3].map((y) => (
			<mesh key={y} position={[0, y, 0]}>
				<cylinderGeometry args={[0.232, 0.232, 0.05, 20]} />
				<meshStandardMaterial color="#e5e7eb" emissive="#e5e7eb" emissiveIntensity={0.6} />
			</mesh>
		))}
		{/* 머리와 안전모 */}
		<mesh position={[0, 1.72, 0]} castShadow>
			<sphereGeometry args={[0.13, 18, 14]} />
			<meshStandardMaterial color="#e8b48a" />
		</mesh>
		<mesh position={[0, 1.78, 0]} castShadow>
			<sphereGeometry args={[0.155, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
			<meshStandardMaterial color="#f8fafc" roughness={0.35} />
		</mesh>
		<mesh position={[0, 1.78, -0.03]}>
			<cylinderGeometry args={[0.2, 0.2, 0.02, 20]} />
			<meshStandardMaterial color="#f8fafc" />
		</mesh>
		{/* 팔 */}
		<mesh position={[0.24, 1.2, -0.18]} rotation={[1.0, 0, -0.25]} castShadow>
			<capsuleGeometry args={[0.06, 0.42, 4, 8]} />
			<meshStandardMaterial color="#f97316" />
		</mesh>
		<mesh position={[-0.24, 1.15, -0.18]} rotation={[1.1, 0, 0.25]} castShadow>
			<capsuleGeometry args={[0.06, 0.42, 4, 8]} />
			<meshStandardMaterial color="#f97316" />
		</mesh>
		{/* 태블릿: 화면이 작업자 쪽(위·뒤)을 향함 */}
		<group position={[0.12, 1.42, -0.42]} rotation={[-0.9, 0, 0]}>
			<mesh castShadow>
				<boxGeometry args={[0.36, 0.26, 0.02]} />
				<meshStandardMaterial color="#0f172a" />
			</mesh>
			<mesh position={[0, 0, 0.011]}>
				<planeGeometry args={[0.33, 0.23]} />
				{screen ? (
					<meshStandardMaterial map={screen} emissive="#ffffff" emissiveMap={screen} emissiveIntensity={0.9 + glow} />
				) : (
					<meshStandardMaterial color="#1e3a8a" emissive="#60a5fa" emissiveIntensity={1} />
				)}
			</mesh>
		</group>
		{/* 서류철 */}
		<group position={[-0.2, 1.08, -0.38]} rotation={[-1.1, 0, 0.1]}>
			<mesh castShadow>
				<boxGeometry args={[0.24, 0.33, 0.012]} />
				<meshStandardMaterial color="#92400e" />
			</mesh>
			<mesh position={[0, -0.01, 0.008]}>
				<planeGeometry args={[0.21, 0.29]} />
				{doc ? <meshStandardMaterial map={doc} /> : <meshStandardMaterial color="#f8fafc" />}
			</mesh>
		</group>
	</group>
);

/* 컨테이너 트럭: 진행 방향 +x */
export const Truck: React.FC<{x: number; z: number}> = ({x, z}) => (
	<group position={[x, 3, z]}>
		<Box p={[8.2, 1.9, 0]} s={[2.6, 2.6, 2.5]} c="#e2e8f0" />
		<Box p={[9.2, 2.3, 0]} s={[0.6, 1.2, 2.3]} c="#38bdf8" e="#0ea5e9" ei={0.3} />
		<Box p={[2, 0.85, 0]} s={[13, 0.4, 2.4]} c="#334155" />
		<Box p={[1.8, 2.4, 0]} s={[12, 2.6, 2.44]} c="#c2410c" />
		{[-3.5, -2.2, 3.5, 7.6].flatMap((wx) =>
			[-1.1, 1.1].map((wz) => (
				<mesh key={`${wx}-${wz}`} position={[wx, 0.5, wz]} rotation={[Math.PI / 2, 0, 0]} castShadow>
					<cylinderGeometry args={[0.5, 0.5, 0.4, 16]} />
					<meshStandardMaterial color="#0b0f19" />
				</mesh>
			)),
		)}
		<mesh position={[9.55, 1.4, 0.8]}>
			<boxGeometry args={[0.1, 0.3, 0.4]} />
			<meshStandardMaterial color="#fff7d6" emissive="#fff3c4" emissiveIntensity={4} />
		</mesh>
		<mesh position={[9.55, 1.4, -0.8]}>
			<boxGeometry args={[0.1, 0.3, 0.4]} />
			<meshStandardMaterial color="#fff7d6" emissive="#fff3c4" emissiveIntensity={4} />
		</mesh>
	</group>
);

/* 반출 게이트: 도로는 x 방향, 차단기는 armUp(0~1)만큼 올라감 */
export const Gate: React.FC<{x: number; z: number; armUp: number; green: boolean}> = ({x, z, armUp, green}) => (
	<group position={[x, 3, z]}>
		<Box p={[0, 0.06, 0]} s={[140, 0.08, 10]} c="#262e3b" />
		{Array.from({length: 18}, (_, i) => (
			<Box key={i} p={[-66 + i * 8, 0.12, 0]} s={[3.5, 0.04, 0.25]} c="#e5e7eb" />
		))}
		<Box p={[0, 0.12, 4.6]} s={[140, 0.04, 0.2]} c="#facc15" />
		<Box p={[0, 0.12, -4.6]} s={[140, 0.04, 0.2]} c="#facc15" />
		<Box p={[0, 3.6, -6]} s={[0.8, 7.2, 0.8]} c="#cbd5e1" />
		<Box p={[0, 3.6, 6]} s={[0.8, 7.2, 0.8]} c="#cbd5e1" />
		<Box p={[0, 7.6, 0]} s={[3.2, 0.9, 13.6]} c="#1e3a8a" e="#1d4ed8" ei={0.3} />
		<Box p={[-3, 1.4, 7.6]} s={[3, 2.8, 2.4]} c="#e2e8f0" />
		<group position={[0.6, 1.1, -4.6]} rotation={[armUp * 1.35, 0, 0]}>
			<Box p={[0, 0, 4]} s={[0.25, 0.25, 8]} c="#ef4444" />
		</group>
		<mesh position={[0, 6.4, -5.5]}>
			<sphereGeometry args={[0.35, 12, 10]} />
			<meshStandardMaterial
				color={green ? '#22c55e' : '#ef4444'}
				emissive={green ? '#22c55e' : '#ef4444'}
				emissiveIntensity={4}
			/>
		</mesh>
	</group>
);

/* 업로드 광선: from → to 로 진행도(p)만큼 뻗음 */
export const Beam: React.FC<{from: V3; to: V3; p: number; color?: string}> = ({from, to, p, color = '#2dd4bf'}) => {
	const a = new THREE.Vector3(...from);
	const b = new THREE.Vector3(...to);
	const len = a.distanceTo(b) * Math.max(0.001, p);
	const dir = b.clone().sub(a).normalize();
	const mid = a.clone().add(dir.clone().multiplyScalar(len / 2));
	const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
	const full = a.distanceTo(b);
	return (
		<group>
			<mesh position={mid} quaternion={quat}>
				<cylinderGeometry args={[0.12, 0.12, len, 10]} />
				<meshStandardMaterial color={color} emissive={color} emissiveIntensity={8} />
			</mesh>
			<mesh position={mid} quaternion={quat}>
				<cylinderGeometry args={[0.6, 0.6, len, 16]} />
				<meshBasicMaterial color={color} transparent opacity={0.18} depthWrite={false} />
			</mesh>
			{/* 데이터 조각이 광선을 따라 올라간다 */}
			{[0, 0.25, 0.5, 0.75].map((o) => {
				const t = (p * 2.2 + o) % 1;
				if (t * full > len) return null;
				const q = a.clone().add(dir.clone().multiplyScalar(t * full));
				return (
					<mesh key={o} position={q}>
						<boxGeometry args={[0.7, 0.9, 0.08]} />
						<meshStandardMaterial color="#f8fafc" emissive="#fef3c7" emissiveIntensity={2.5} />
					</mesh>
				);
			})}
		</group>
	);
};

import React from 'react';
import {ThreeCanvas} from '@remotion/three';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import data from '../data.json';
import {C} from '../theme';
import {ap, Chip, clamp, Count, ease, Panel, Rise, Scene, SceneTitle} from '../ui';
import {Beam, CameraRig, Gate, PortWorld, Truck, useTex, Worker} from './world';

const D = data as any;
const S = D.shipment;
const L = D.logistics;
const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

type V3 = [number, number, number];
const mix = (a: V3, b: V3, t: number): V3 => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const path = (f: number, keys: [number, V3][]): V3 => {
	for (let i = 0; i < keys.length - 1; i++) {
		const [f0, a] = keys[i];
		const [f1, b] = keys[i + 1];
		if (f <= f1) return mix(a, b, ease(Math.max(0, Math.min(1, (f - f0) / (f1 - f0)))));
	}
	return keys[keys.length - 1][1];
};

const Canvas: React.FC<{children: React.ReactNode}> = ({children}) => (
	<ThreeCanvas width={1920} height={1080} shadows camera={{fov: 40, near: 0.05, far: 6000}} gl={{antialias: true}}>
		{children}
	</ThreeCanvas>
);

const Scrim: React.FC<{side?: 'left' | 'bottom' | 'all'; strength?: number}> = ({side = 'left', strength = 0.85}) => (
	<div
		style={{
			position: 'absolute',
			inset: 0,
			background:
				side === 'left'
					? `linear-gradient(90deg, rgba(10,17,32,${strength}) 0%, rgba(10,17,32,${strength * 0.6}) 38%, rgba(10,17,32,0) 62%)`
					: side === 'bottom'
						? `linear-gradient(0deg, rgba(10,17,32,${strength}) 0%, rgba(10,17,32,0) 45%)`
						: `rgba(10,17,32,${strength})`,
		}}
	/>
);

const TopShade: React.FC = () => (
	<div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 140, background: 'linear-gradient(rgba(10,17,32,0.85), rgba(10,17,32,0))'}} />
);

/* ------------------------------------------------------------------ */
/* 3D 오프닝: 바다 위에서 부산항 터미널로 다가간다                        */
/* ------------------------------------------------------------------ */
export const Intro3D: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const pos = path(f, [
		[0, [-380, 120, -460]],
		[dur, [150, 58, -170]],
	]);
	const look = path(f, [
		[0, [-40, 10, 80]],
		[dur, [10, 14, 40]],
	]);
	const stats = [
		{v: 2488, unit: '만 TEU', label: '2025 부산항 컨테이너 물동량'},
		{v: 1078, unit: '만 TEU', label: '그중 수출입 화물 · 우리 대상은 수입'},
		{v: 57, unit: '%', label: '환적 화물 · 수입신고 없음 (대상 제외)'},
	];
	return (
		<Scene dur={dur}>
			<Canvas>
				<PortWorld f={f} />
				<CameraRig pos={pos} look={look} fov={38} />
			</Canvas>
			<Scrim side="left" strength={0.88} />
			<TopShade />
			<div style={{position: 'absolute', left: 120, top: 190}}>
				<Rise at={20}>
					<div style={{color: C.accent, fontSize: 26, fontWeight: 800, letterSpacing: 4}}>부산항 신항 · 컨테이너 터미널</div>
				</Rise>
				<Rise at={30}>
					<div style={{fontSize: 92, fontWeight: 900, color: C.text, letterSpacing: -2, marginTop: 18, lineHeight: 1.1, textShadow: '0 4px 30px #000a'}}>
						부산항 수입 서류,
					</div>
				</Rise>
				<Rise at={40}>
					<div style={{fontSize: 92, fontWeight: 900, color: C.text, letterSpacing: -2, lineHeight: 1.15, textShadow: '0 4px 30px #000a'}}>
						<span style={{color: C.accent}}>입항 전에</span> 바로잡는다
					</div>
				</Rise>
				<Rise at={52}>
					<div style={{fontSize: 31, color: '#c7d3e6', marginTop: 22, fontWeight: 500}}>현장 사진 한 장으로 시작하는 문서 자동화 Agent</div>
				</Rise>
			</div>
			<div style={{position: 'absolute', left: 120, top: 640, display: 'flex', gap: 24}}>
				{stats.map((s, i) => (
					<Rise key={s.label} at={100 + i * 12}>
						<Panel style={{width: 400, padding: '20px 26px', background: 'rgba(15,26,46,0.82)'}}>
							<div style={{fontSize: 48, fontWeight: 900, color: i === 2 ? C.sub : C.text}}>
								<Count to={s.v} at={100 + i * 12} />
								<span style={{fontSize: 26, marginLeft: 6, color: C.sub}}>{s.unit}</span>
							</div>
							<div style={{fontSize: 20, color: C.sub, marginTop: 4}}>{s.label}</div>
						</Panel>
					</Rise>
				))}
			</div>
			<Rise at={130} style={{position: 'absolute', left: 124, top: 790, color: '#8fa1bd', fontSize: 17}}>
				자료: 해양수산부 2025년 전국 무역항 컨테이너 물동량 발표 · 3D 장면은 단순화한 재현입니다
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 3D 현장: 안벽의 작업자가 태블릿으로 서류를 찍고, 클라우드로 올린다       */
/* ------------------------------------------------------------------ */
const WORKER: V3 = [12, 3, 42];
const TABLET: V3 = [12.12, 4.42, 41.58];
const CLOUD: V3 = [14, 44, 16];

export const Field3D: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const doc = useTex('docs/pl.png');
	const shot = 108;
	const flash = interpolate(f, [shot, shot + 3, shot + 16], [0, 0.9, 0], clamp);
	const beam = ap(f, shot + 18, 40);
	const pos = path(f, [
		[0, [24, 9, 57]],
		[80, [15.8, 5.5, 46.6]],
		[shot + 20, [15.8, 5.5, 46.6]],
		[dur - 10, [46, 20, 88]],
	]);
	const look = path(f, [
		[0, [11, 4, 38]],
		[80, [12.0, 4.2, 41.0]],
		[shot + 20, [12.0, 4.2, 41.0]],
		[dur - 10, [13, 28, 22]],
	]);
	const pulse = 1 + 0.12 * Math.sin(f / 5);
	return (
		<Scene dur={dur}>
			<Canvas>
				<PortWorld f={f + 240} />
				<Worker p={WORKER} screen={doc} doc={doc} glow={flash * 2} />
				{beam > 0 ? <Beam from={TABLET} to={CLOUD} p={beam} /> : null}
				<group position={CLOUD} scale={ap(f, shot + 40, 16) * pulse}>
					<mesh>
						<icosahedronGeometry args={[3.2, 1]} />
						<meshStandardMaterial color="#2dd4bf" emissive="#2dd4bf" emissiveIntensity={2.5} wireframe />
					</mesh>
					<mesh>
						<sphereGeometry args={[1.6, 20, 14]} />
						<meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={3} />
					</mesh>
				</group>
				<CameraRig pos={pos} look={look} fov={f < shot + 20 ? 34 : 40} />
			</Canvas>
			<Scrim side="left" strength={0.8} />
			<TopShade />
			<SceneTitle step="STEP 1 · 현장 촬영" title="안벽의 작업자가 태블릿으로 서류를 찍는다" sub={`입항 3일 전 · 선적 ${md(S.onBoard)} → 서류 도착 ${md(L.baseDate)} → 입항 예정 ${md(L.demo.eta)}`} />
			<div style={{position: 'absolute', left: 96, top: 360, display: 'flex', flexDirection: 'column', gap: 16}}>
				<Rise at={40} x={-30} y={0}>
					<Chip color={C.sub} style={{fontSize: 22}}>
						부산신항 컨테이너 터미널 · 안벽
					</Chip>
				</Rise>
				<Rise at={shot - 6} x={-30} y={0}>
					<Chip color={C.accent} style={{fontSize: 22}}>
						Packing List · B/L 촬영
					</Chip>
				</Rise>
				<Rise at={shot + 40} x={-30} y={0}>
					<Chip color={C.teal} style={{fontSize: 22}}>
						AWS 클라우드로 바로 업로드 · Agent 처리 시작
					</Chip>
				</Rise>
			</div>
			{/* 태블릿 화면 확대 */}
			<div
				style={{
					position: 'absolute',
					left: 1380,
					top: 300,
					width: 440,
					opacity: ap(f, 70, 14) * (1 - ap(f, shot + 34, 14)),
					transform: `translateY(${(1 - ap(f, 70, 14)) * 30}px)`,
				}}
			>
				<div style={{color: C.sub, fontSize: 20, marginBottom: 10}}>태블릿 화면</div>
				<div
					style={{
						position: 'relative',
						borderRadius: 22,
						border: '10px solid #0b0f19',
						overflow: 'hidden',
						height: 330,
						background: C.paper,
						boxShadow: '0 30px 80px #000c',
					}}
				>
					<Img src={staticFile('docs/scan_pl.jpg')} style={{width: '100%', transform: 'scale(1.25) translateY(14%)'}} />
					<div
						style={{
							position: 'absolute',
							left: 22,
							top: 24,
							right: 22,
							bottom: 24,
							border: `4px solid ${C.teal}`,
							borderRadius: 10,
							opacity: ap(f, 88, 8),
						}}
					/>
					<div
						style={{
							position: 'absolute',
							left: 0,
							right: 0,
							bottom: 0,
							padding: '8px 0',
							textAlign: 'center',
							background: '#0b0f19cc',
							color: f >= shot ? C.teal : '#fff',
							fontSize: 19,
							fontWeight: 800,
						}}
					>
						{f < 88 ? '문서를 맞추는 중…' : f < shot ? '문서 인식됨 · Packing List' : '✓ 촬영 완료 · 전송 중'}
					</div>
				</div>
			</div>
			<div style={{position: 'absolute', inset: 0, background: '#fff', opacity: flash}} />
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 3D 반출: 입항 당일 트럭이 게이트를 통과한다                              */
/* ------------------------------------------------------------------ */
const GATE_X = 190;
const ROAD_Z = 100;

export const Gate3D: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const x =
		f < 60
			? interpolate(f, [0, 60], [110, 176], {...clamp, easing: ease})
			: interpolate(f, [92, dur], [176, 300], {...clamp, easing: (t) => t * t});
	const armUp = ap(f, 66, 20);
	const green = f >= 64;
	const pos = path(f, [
		[0, [204, 8.5, 121]],
		[dur, [214, 7.5, 117]],
	]);
	const look: V3 = [interpolate(f, [0, dur], [182, 206], clamp), 3.8, ROAD_Z];
	const chips = [
		{at: 58, text: '✓ 세관 신고 수리', color: C.teal},
		{at: 78, text: '✓ 전자인수도증 자동 발급', color: C.teal},
		{at: 98, text: `B/L ${S.blNo} · 프리타임 안에 반출`, color: C.accent},
	];
	return (
		<Scene dur={dur}>
			<Canvas>
				<PortWorld f={f + 520} />
				<Gate x={GATE_X} z={ROAD_Z} armUp={armUp} green={green} />
				<Truck x={x} z={ROAD_Z} />
				<CameraRig pos={pos} look={look} fov={36} />
			</Canvas>
			<Scrim side="left" strength={0.82} />
			<TopShade />
			<SceneTitle
				step={`STEP 7 · 반출 (${md(L.demo.eta)} 입항)`}
				title="입항 당일, 막힘 없이 게이트를 나간다"
				sub="서류를 입항 전에 바로잡고 신고 준비를 끝냈기 때문"
			/>
			<div style={{position: 'absolute', left: 96, top: 400, display: 'flex', flexDirection: 'column', gap: 16}}>
				{chips.map((c) => (
					<Rise key={c.text} at={c.at} x={-30} y={0}>
						<Chip color={c.color} style={{fontSize: 24, padding: '10px 22px'}}>
							{c.text}
						</Chip>
					</Rise>
				))}
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 마무리 배경: 밤의 부산항을 천천히 돈다                                  */
/* ------------------------------------------------------------------ */
export const NightPort: React.FC = () => {
	const f = useCurrentFrame();
	const a = 0.75 + f * 0.0016;
	const pos: V3 = [Math.sin(a) * -420, 150, -Math.cos(a) * 420];
	return (
		<>
			<Canvas>
				<PortWorld f={f + 700} night />
				<CameraRig pos={pos} look={[0, 10, 70]} fov={40} />
			</Canvas>
			<Scrim side="all" strength={0.55} />
		</>
	);
};

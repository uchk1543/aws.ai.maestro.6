// 발표 영상 오프닝 (코드로만 그린다, Blender 없음). 1920×1080, 30fps, 17.5초
//   1막 남색 밤바다: 별, 나침반 과녁, 위에서 본 컨테이너선이 과녁으로 미끄러져 들어오고 큰 제목이 한 줄씩 솟는다
//   2막 알약 창: 빨간 컨테이너 하나가 가로로 긴 창이 되어 화면 가득 열리고, 노을 진 부두와 트레일러가 보인다. 글은 낱말 단위로
//   3막 AI 시야: 훑는 선이 지나간 자리부터 같은 부두가 선과 점으로 바뀌고, 서류 값을 짚는 상자가 붙는다
//   4막 타일 판이 물결처럼 켜졌다가 위로 걷히면 흰 바탕에 제목 (웹 앱과 같은 흑백)
import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {loadPretendard, W, WFONT, WMONO} from '../web/theme';

loadPretendard();

export const OPENING_FRAMES = 525;

const NAVY = '#0f1520';
const STAR = '#d7e0ea';
const ACCENT = '#ff5a3c';
const WIRE = '#9fb6cc';

const out = Easing.bezier(0.16, 1, 0.3, 1);
const inOut = Easing.bezier(0.65, 0, 0.35, 1);
/** f 가 a→b 를 지나는 동안 0→1 (양 끝 고정) */
const k = (f: number, a: number, b: number, easing = out) =>
	interpolate(f, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing});
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** 늘 같은 값이 나오는 난수 (프레임마다 같아야 깜빡이지 않는다) */
const seeded = (seed: number) => {
	let s = seed;
	return () => {
		s = (s * 16807) % 2147483647;
		return (s - 1) / 2147483646;
	};
};

/* ---------------------------------------------------------------- 1막 */
const STARS = (() => {
	const r = seeded(7);
	return Array.from({length: 150}, () => ({x: r() * 1920, y: r() * 1080, s: 0.8 + r() * 2.2, p: r() * 6.28, sp: 0.04 + r() * 0.08}));
})();

const Stars: React.FC<{f: number; drift: number}> = ({f, drift}) => (
	<svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
		{STARS.map((s, i) => (
			<circle
				key={i}
				cx={(s.x - drift * s.s * 40 + 1920 * 4) % 1920}
				cy={s.y}
				r={s.s * 0.9}
				fill={STAR}
				opacity={(0.25 + 0.55 * (0.5 + 0.5 * Math.sin(s.p + f * s.sp))) * k(f, i % 30, i % 30 + 20)}
			/>
		))}
	</svg>
);

/** 나침반 과녁: 점 고리가 시계 방향으로 찍히고, 가운데 별표가 돌며 선다 */
export const Compass: React.FC<{f: number; x: number; y: number; scale?: number; color?: string; opacity?: number}> = ({
	f,
	x,
	y,
	scale = 1,
	color = STAR,
	opacity = 1,
}) => {
	const spin = (1 - k(f, 4, 40)) * -120 + f * 0.15;
	const arm = 60 * k(f, 6, 30);
	return (
		<g transform={`translate(${x} ${y}) scale(${scale})`} opacity={opacity}>
			{Array.from({length: 16}, (_, i) => {
				const a = (i / 16) * Math.PI * 2 - Math.PI / 2;
				const on = k(f, i * 1.4, i * 1.4 + 8);
				return <circle key={i} cx={Math.cos(a) * 120} cy={Math.sin(a) * 120} r={2.6} fill={color} opacity={on} />;
			})}
			<g transform={`rotate(${spin})`} stroke={color} strokeWidth={2.2} strokeLinecap="round">
				{[0, 60, 120].map((d) => (
					<line key={d} x1={-arm} y1={0} x2={arm} y2={0} transform={`rotate(${d})`} />
				))}
			</g>
			<circle r={5 * k(f, 20, 34)} fill={ACCENT} />
		</g>
	);
};

const BAY_COLORS = ['#5d6c7a', '#8b5a43', '#3f5e50', '#9aa4ad', '#6c5d7a', '#b08b4c', '#4e6f8e', '#7d4a3c'];
const SHIP_LEN = 1700;
const SHIP_W = 250;
const RED_BAY = {bay: 15, row: 2};

/** 위에서 본 컨테이너선. 원점 = 뱃머리 끝, 배는 -x 쪽으로 뻗는다 */
const Ship: React.FC<{f: number}> = ({f}) => {
	const r = seeded(11);
	const bays = 22;
	const rows = 6;
	const bayW = 56;
	const rowH = 32;
	const x0 = -SHIP_LEN + 300;
	const hull = `M0 0 C -60 -${SHIP_W / 2} -230 -${SHIP_W / 2} -330 -${SHIP_W / 2} L -${SHIP_LEN - 40} -${SHIP_W / 2}
		Q -${SHIP_LEN} -${SHIP_W / 2} -${SHIP_LEN} -${SHIP_W / 2 - 40} L -${SHIP_LEN} ${SHIP_W / 2 - 40}
		Q -${SHIP_LEN} ${SHIP_W / 2} -${SHIP_LEN - 40} ${SHIP_W / 2} L -330 ${SHIP_W / 2} C -230 ${SHIP_W / 2} -60 ${SHIP_W / 2} 0 0 Z`;
	return (
		<g>
			{/* 물보라: 고물 뒤로 길게 */}
			{[0, 1, 2, 3].map((i) => (
				<path
					key={i}
					d={`M -${SHIP_LEN} ${-40 + i * 26} q -${300 + i * 60} ${(i - 1.5) * 30} -${900 + i * 120} ${(i - 1.5) * 90}`}
					stroke="#ffffff"
					strokeOpacity={0.09 + 0.03 * Math.sin(f * 0.2 + i)}
					strokeWidth={10 - i * 2}
					fill="none"
					strokeLinecap="round"
				/>
			))}
			<path d={hull} fill="#1d232c" />
			<path d={hull} fill="none" stroke="#56606d" strokeWidth={4} />
			<path d={hull} transform="scale(0.94 0.84) translate(-40 0)" fill="#2b323c" />
			{/* 선교: 고물 쪽 흰 건물 */}
			<rect x={-SHIP_LEN + 70} y={-96} width={150} height={192} rx={10} fill="#d9dde2" />
			<rect x={-SHIP_LEN + 82} y={-80} width={126} height={160} rx={6} fill="#b9c0c8" />
			<rect x={-SHIP_LEN + 100} y={-20} width={90} height={40} rx={4} fill="#8e98a3" />
			{/* 컨테이너 칸 */}
			{Array.from({length: bays}, (_, b) =>
				Array.from({length: rows}, (_, row) => {
					const red = b === RED_BAY.bay && row === RED_BAY.row;
					const color = BAY_COLORS[Math.floor(r() * BAY_COLORS.length)];
					const x = x0 + b * (bayW + 6) - 40;
					const y = -rows * (rowH + 3) / 2 + row * (rowH + 3);
					return (
						<g key={`${b}-${row}`}>
							<rect x={x} y={y} width={bayW} height={rowH} rx={2} fill={red ? ACCENT : color} />
							<rect x={x} y={y} width={bayW} height={4} fill="#ffffff" opacity={0.18} />
							{red && (
								<rect
									x={x - 6}
									y={y - 6}
									width={bayW + 12}
									height={rowH + 12}
									rx={6}
									fill="none"
									stroke={ACCENT}
									strokeWidth={3}
									opacity={0.5 + 0.5 * Math.sin(f * 0.3)}
								/>
							)}
						</g>
					);
				}),
			)}
			{/* 해치 사이 통로 */}
			{Array.from({length: bays / 2 + 1}, (_, i) => (
				<rect key={i} x={x0 - 46 + i * 2 * (bayW + 6)} y={-104} width={3} height={208} fill="#0f141a" opacity={0.6} />
			))}
		</g>
	);
};

const HEAD = ['부산항 수입 서류,', '입항 전에', '바로잡는다'];

const ShipAct: React.FC<{f: number}> = ({f}) => {
	// 배: 왼쪽 밖에서 들어와 뱃머리가 과녁에 닿는다 → 비스듬히 돌아 왼쪽 아래로 비켜 선다
	const glide = k(f, 22, 92, Easing.bezier(0.2, 0.7, 0.2, 1));
	const turn = k(f, 96, 140, inOut);
	const shipX = mix(-60, 1060, glide) + mix(0, -560, turn);
	const shipY = 540 + mix(0, 250, turn);
	const rot = mix(0, -28, turn);
	const scale = mix(0.9, 0.62, turn);
	// 끝에서 빨간 컨테이너로 빨려 들어간다 (다음 막의 알약 창)
	const dive = k(f, 140, 168, Easing.bezier(0.7, 0, 0.84, 0));
	const compassFade = 1 - k(f, 88, 104);
	return (
		<AbsoluteFill style={{background: NAVY, overflow: 'hidden'}}>
			<div style={{position: 'absolute', inset: 0, transform: `scale(${1 + dive * 5})`, transformOrigin: '50% 60%', opacity: 1 - k(f, 158, 170)}}>
				<Stars f={f} drift={glide + turn} />
				<svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
					<Compass f={f} x={1060} y={540} opacity={compassFade} />
					<g transform={`translate(${shipX} ${shipY}) rotate(${rot}) scale(${scale})`}>
						<Ship f={f} />
					</g>
				</svg>
				{/* 제목: 줄마다 가림막 안에서 솟는다. 배 아래에 깔린다 → 배가 비키면 드러난다 */}
				<div style={{position: 'absolute', left: 0, right: 0, top: 250, textAlign: 'center', zIndex: -1}}>
					{HEAD.map((line, i) => {
						const p = k(f, 70 + i * 9, 102 + i * 9);
						return (
							<div key={line} style={{overflow: 'hidden', height: 190}}>
								<div
									style={{
										fontFamily: WFONT,
										fontWeight: 900,
										fontSize: 168,
										letterSpacing: -6,
										lineHeight: '190px',
										color: '#ffffff',
										transform: `translateY(${(1 - p) * 110}%)`,
									}}
								>
									{line}
								</div>
							</div>
						);
					})}
				</div>
				<div
					style={{
						position: 'absolute',
						left: 96,
						top: 72,
						fontFamily: WMONO,
						fontSize: 22,
						letterSpacing: 4,
						color: STAR,
						opacity: k(f, 30, 50) * 0.7,
					}}
				>
					35.08°N 128.83°E · BUSAN NEW PORT
				</div>
			</div>
		</AbsoluteFill>
	);
};

/* ---------------------------------------------------------------- 2·3막: 부두 */
type Box = {x: number; y: number; w: number; h: number; c: string; layer: number};
const YARD: Box[] = (() => {
	const r = seeded(23);
	const boxes: Box[] = [];
	// 먼 줄(작게)과 가까운 줄(크게). y 는 바닥선
	const rowsDef = [
		{base: 690, h: 30, w: 120, n: 22, layer: 0},
		{base: 760, h: 52, w: 210, n: 12, layer: 1},
	];
	rowsDef.forEach(({base, h, w, n, layer}) => {
		for (let i = 0; i < n; i++) {
			const stack = 1 + Math.floor(r() * (layer ? 4 : 5));
			const x = i * (w + 14) - 60 + (layer ? 30 : 0);
			if (layer === 1 && x > 520 && x < 1350) continue; // 트레일러가 지나는 자리는 비운다
			for (let s = 0; s < stack; s++) {
				boxes.push({x, y: base - (s + 1) * h, w, h: h - 3, c: BAY_COLORS[Math.floor(r() * BAY_COLORS.length)], layer});
			}
		}
	});
	return boxes;
})();

/** 노을빛을 섞은 색 (가까울수록 진하게, 멀수록 하늘색에 묻힌다) */
const tint = (hex: string, layer: number) => {
	const n = parseInt(hex.slice(1), 16);
	const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
	const fog = layer === 0 ? 0.62 : 0.28;
	const [fr, fg, fb] = [196, 112, 86];
	const dark = layer === 0 ? 0.75 : 0.55;
	return `rgb(${Math.round(mix(r * dark, fr, fog))},${Math.round(mix(g * dark, fg, fog))},${Math.round(mix(b * dark, fb, fog))})`;
};

const Crane: React.FC<{x: number; s: number; wire: boolean; color: string}> = ({x, s, wire, color}) => {
	const st = wire ? {fill: 'none', stroke: color, strokeWidth: 2 / s} : {fill: color};
	return (
		<g transform={`translate(${x} 700) scale(${s})`}>
			<rect x={0} y={-330} width={14} height={330} {...st} />
			<rect x={120} y={-330} width={14} height={330} {...st} />
			<rect x={-40} y={-350} width={300} height={22} {...st} />
			<rect x={-260} y={-360} width={260} height={12} {...st} />
			<path d="M 60 -350 L 60 -440 L 134 -350" {...st} />
			<line x1={60} y1={-440} x2={-250} y2={-358} stroke={color} strokeWidth={3 / s} />
			<line x1={60} y1={-440} x2={250} y2={-352} stroke={color} strokeWidth={3 / s} />
			<rect x={-180} y={-348} width={34} height={24} {...st} />
			<line x1={-163} y1={-324} x2={-163} y2={-220} stroke={color} strokeWidth={2 / s} />
		</g>
	);
};

/** 옆에서 본 트레일러 (원점 = 바퀴 바닥 왼쪽) */
const Truck: React.FC<{wire: boolean; f: number}> = ({wire, f}) => {
	const body = wire ? {fill: 'rgba(10,14,18,0.6)', stroke: WIRE, strokeWidth: 2} : {fill: '#2a1d1d'};
	const box = wire ? {fill: 'rgba(10,14,18,0.6)', stroke: WIRE, strokeWidth: 2} : {fill: '#3a2724'};
	const wheel = (cx: number) => (
		<g key={cx} transform={`translate(${cx} -34) rotate(${f * 6})`}>
			<circle r={34} fill={wire ? 'none' : '#120c0c'} stroke={wire ? WIRE : '#120c0c'} strokeWidth={2} />
			<circle r={14} fill={wire ? 'none' : '#4a3a36'} stroke={wire ? WIRE : 'none'} strokeWidth={1.5} />
			{wire && <line x1={-14} y1={0} x2={14} y2={0} stroke={WIRE} strokeWidth={1.5} />}
		</g>
	);
	return (
		<g>
			{/* 40ft 컨테이너 */}
			<rect x={0} y={-290} width={900} height={210} rx={4} {...box} />
			{Array.from({length: 30}, (_, i) => (
				<line
					key={i}
					x1={18 + i * 29}
					y1={-282}
					x2={18 + i * 29}
					y2={-88}
					stroke={wire ? WIRE : '#ffffff'}
					strokeOpacity={wire ? 0.35 : 0.06}
					strokeWidth={wire ? 1 : 6}
				/>
			))}
			{/* 노을 반사: 위 모서리에 빛 */}
			{!wire && <rect x={0} y={-290} width={900} height={8} fill="#ffb27a" opacity={0.55} />}
			<rect x={-10} y={-80} width={930} height={18} {...body} />
			{/* 트랙터 */}
			<path d="M 930 -60 L 930 -230 Q 930 -262 960 -266 L 1080 -270 Q 1128 -262 1140 -200 L 1160 -120 L 1160 -60 Z" {...body} />
			<path d="M 1060 -252 L 1110 -250 Q 1126 -236 1132 -196 L 1060 -196 Z" fill={wire ? 'none' : '#f3b27c'} stroke={wire ? WIRE : 'none'} opacity={wire ? 1 : 0.75} />
			{!wire && <circle cx={1158} cy={-96} r={9} fill="#fff2c8" />}
			{[90, 170, 720, 800].map(wheel)}
			{[1000, 1110].map(wheel)}
		</g>
	);
};

/** 노을 부두 한 장면. wire=true 면 같은 모양을 선으로만 (AI 시야) */
const Yard: React.FC<{f: number; wire: boolean; truckX: number}> = ({f, wire, truckX}) => {
	const sky = wire ? null : (
		<>
			<defs>
				<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
					<stop offset="0" stopColor="#2b2236" />
					<stop offset="0.45" stopColor="#8c4b4c" />
					<stop offset="0.66" stopColor="#e08b5a" />
					<stop offset="0.72" stopColor="#f6c07a" />
				</linearGradient>
				<linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
					<stop offset="0" stopColor="#3a2626" />
					<stop offset="1" stopColor="#0d090a" />
				</linearGradient>
				<radialGradient id="sun">
					<stop offset="0" stopColor="#fff4d6" />
					<stop offset="0.25" stopColor="#ffd59a" stopOpacity="0.95" />
					<stop offset="1" stopColor="#ff9a5a" stopOpacity="0" />
				</radialGradient>
			</defs>
			<rect width={1920} height={1080} fill="url(#sky)" />
			<circle cx={1290} cy={690} r={360} fill="url(#sun)" />
			<circle cx={1290} cy={690} r={70} fill="#fff1cf" />
		</>
	);
	const lineColor = WIRE;
	return (
		<svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
			{sky}
			{wire && <rect width={1920} height={1080} fill="#06080b" />}
			{wire && <DotFloor f={f} />}
			{/* 크레인 (먼 쪽) */}
			{[160, 760, 1560].map((x, i) => (
				<Crane key={x} x={x} s={0.9 - i * 0.05} wire={wire} color={wire ? lineColor : '#4a2f34'} />
			))}
			{/* 컨테이너 더미 */}
			{YARD.map((b, i) => (
				<g key={i}>
					<rect
						x={b.x}
						y={b.y}
						width={b.w}
						height={b.h}
						fill={wire ? 'rgba(6,8,11,0.85)' : tint(b.c, b.layer)}
						stroke={wire ? lineColor : 'none'}
						strokeOpacity={b.layer ? 0.9 : 0.45}
						strokeWidth={1.4}
					/>
					{!wire && <rect x={b.x} y={b.y} width={b.w} height={2} fill="#ffc48a" opacity={b.layer ? 0.4 : 0.2} />}
					{wire && b.layer === 1 && (
						<line x1={b.x} y1={b.y} x2={b.x + b.w} y2={b.y + b.h} stroke={lineColor} strokeOpacity={0.2} strokeWidth={1} />
					)}
				</g>
			))}
			{/* 땅 */}
			{!wire && <rect x={0} y={760} width={1920} height={320} fill="url(#ground)" />}
			{!wire &&
				[0, 1, 2, 3, 4, 5].map((i) => (
					<rect key={i} x={((i * 380 - f * 9) % 2280) - 180} y={930} width={180} height={6} fill="#f6c07a" opacity={0.25} />
				))}
			<g transform={`translate(${truckX} 960)`}>
				<Truck wire={wire} f={f} />
			</g>
		</svg>
	);
};

/** AI 시야의 바닥: 원근 점 격자가 앞으로 흐른다 */
const DotFloor: React.FC<{f: number}> = ({f}) => {
	const dots: React.ReactNode[] = [];
	const horizon = 700;
	for (let z = 1; z < 26; z++) {
		const zz = z - ((f * 0.06) % 1);
		const y = horizon + 2600 / (zz + 6);
		const spread = 9000 / (zz + 6);
		for (let i = -14; i <= 14; i++) {
			const x = 960 + i * spread * 0.18;
			if (x < -20 || x > 1940) continue;
			dots.push(<circle key={`${z}-${i}`} cx={x} cy={y} r={Math.max(0.8, 3.4 - zz * 0.12)} fill={WIRE} opacity={0.12 + 0.5 / zz} />);
		}
	}
	return <g>{dots}</g>;
};

/** 낱말 하나씩 흐림에서 또렷하게. 마지막 글자는 강조색 */
export const Words: React.FC<{f: number; at: number; lines: string[]; size?: number; color?: string; accent?: string; align?: 'center' | 'left'}> = ({
	f,
	at,
	lines,
	size = 76,
	color = '#ffffff',
	accent = ACCENT,
	align = 'center',
}) => {
	let n = 0;
	return (
		<div style={{fontFamily: WFONT, fontWeight: 500, fontSize: size, letterSpacing: -2, lineHeight: 1.18, color, textAlign: align}}>
			{lines.map((line, li) => {
				const words = line.split(' ');
				return (
					<div key={li}>
						{words.map((w, wi) => {
							const p = k(f, at + n * 4, at + n * 4 + 16);
							n += 1;
							const last = li === lines.length - 1 && wi === words.length - 1;
							return (
								<span
									key={wi}
									style={{
										display: 'inline-block',
										marginRight: wi < words.length - 1 ? size * 0.26 : 0,
										opacity: p,
										filter: `blur(${(1 - p) * 10}px)`,
										transform: `translateY(${(1 - p) * 24}px)`,
									}}
								>
									{last ? (
										<>
											{w.slice(0, -1)}
											<span style={{color: accent}}>{w.slice(-1)}</span>
										</>
									) : (
										w
									)}
								</span>
							);
						})}
					</div>
				);
			})}
		</div>
	);
};

/** 상자 네 귀퉁이만 그은 짚기 표시 + 이름표 */
const Detect: React.FC<{f: number; at: number; x: number; y: number; w: number; h: number; label: string; red?: boolean}> = ({
	f,
	at,
	x,
	y,
	w,
	h,
	label,
	red,
}) => {
	const p = k(f, at, at + 12);
	if (p <= 0) return null;
	const c = red ? ACCENT : '#e8f1fa';
	const g = 26;
	const grow = mix(1.3, 1, p);
	const cx = x + w / 2;
	const cy = y + h / 2;
	return (
		<g opacity={p} transform={`translate(${cx} ${cy}) scale(${grow}) translate(${-cx} ${-cy})`}>
			{red && <rect x={x} y={y} width={w} height={h} fill={ACCENT} opacity={0.12 + 0.06 * Math.sin(f * 0.4)} />}
			<path
				d={`M${x} ${y + g}V${y}H${x + g} M${x + w - g} ${y}H${x + w}V${y + g} M${x + w} ${y + h - g}V${y + h}H${x + w - g} M${x + g} ${y + h}H${x}V${y + h - g}`}
				stroke={c}
				strokeWidth={3}
				fill="none"
			/>
			<g transform={`translate(${x} ${y - 46})`}>
				<rect width={label.length * 15 + 34} height={36} rx={8} fill={red ? ACCENT : 'rgba(232,241,250,0.95)'} />
				<text x={16} y={25} fontFamily={WMONO} fontSize={19} fontWeight={600} fill={red ? '#ffffff' : '#0b0f14'}>
					{label}
				</text>
			</g>
		</g>
	);
};

const YardAct: React.FC<{f: number}> = ({f}) => {
	// f = 이 막 안의 프레임 (0 = 빨간 컨테이너가 화면을 덮은 순간)
	// 알약 창: 빨간 막대 → 가로로 긴 창 → 화면 가득
	const bar = k(f, 0, 22);
	const open = k(f, 34, 78, Easing.bezier(0.7, 0, 0.2, 1));
	const pillW = mix(mix(220, 1500, bar), 1920, open);
	const pillH = mix(mix(70, 170, bar), 1080, open);
	const radius = mix(pillH / 2, 0, open);
	const redCover = 1 - k(f, 10, 30);
	const dolly = mix(1.9, 1.0, k(f, 20, 120, Easing.bezier(0.3, 0, 0.1, 1)));
	const truckX = mix(260, 520, k(f, 0, 220, Easing.linear));
	// AI 시야: 훑는 선이 왼쪽에서 오른쪽으로
	const scan = k(f, 112, 156, inOut) * 2020 - 50;
	const ai = f >= 108;
	return (
		<AbsoluteFill style={{background: NAVY, overflow: 'hidden'}}>
			<div
				style={{
					position: 'absolute',
					left: 960 - pillW / 2,
					top: 540 - pillH / 2,
					width: pillW,
					height: pillH,
					borderRadius: radius,
					overflow: 'hidden',
				}}
			>
				<div style={{position: 'absolute', left: pillW / 2 - 960, top: pillH / 2 - 540, width: 1920, height: 1080}}>
					<div style={{position: 'absolute', inset: 0, transform: `scale(${dolly})`, transformOrigin: '55% 78%'}}>
						<Yard f={f} wire={false} truckX={truckX} />
						{ai && (
							<div style={{position: 'absolute', inset: 0, clipPath: `inset(0 ${Math.max(0, 1920 - scan)}px 0 0)`}}>
								<Yard f={f} wire truckX={truckX} />
							</div>
						)}
					</div>
					{ai && (
						<svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
							<defs>
								<linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
									<stop offset="0" stopColor={WIRE} stopOpacity="0" />
									<stop offset="1" stopColor="#e8f4ff" stopOpacity="0.55" />
								</linearGradient>
							</defs>
							{scan < 1950 && (
								<>
									<rect x={scan - 220} y={0} width={220} height={1080} fill="url(#beam)" />
									<rect x={scan - 2} y={0} width={3} height={1080} fill="#ffffff" />
								</>
							)}
							<Detect f={f} at={150} x={truckX - 4} y={666} w={910} h={216} label="B/L BL-2026-0001 · 40FT" />
							<Detect f={f} at={160} x={truckX + 40} y={760} w={330} h={96} label="상업송장 · 6,250 kg" />
							<Detect f={f} at={168} x={truckX + 470} y={760} w={330} h={96} label="포장명세서 · 6,520 kg" red />
							<g opacity={k(f, 176, 186)}>
								<text x={truckX + 470} y={1010} fontFamily={WMONO} fontSize={22} fontWeight={700} fill={ACCENT}>
									X-WT-01 총중량 불일치
								</text>
							</g>
						</svg>
					)}
				</div>
				<div style={{position: 'absolute', inset: 0, background: ACCENT, opacity: redCover}} />
			</div>

			{/* 2막 글: 노을 위 */}
			<div style={{position: 'absolute', left: 0, right: 0, top: 150, opacity: 1 - k(f, 100, 112)}}>
				<Words f={f} at={56} lines={['서류 한 장의 오타가', '컨테이너 한 대를 멈춘다.']} />
			</div>
			{/* 3막 글: AI 시야 위 */}
			<div style={{position: 'absolute', left: 0, right: 0, top: 150}}>
				<Words f={f} at={128} lines={['AI는 읽고,', '코드가 판정한다.']} />
			</div>
			{/* 모서리 표시 (AI 시야) */}
			<div
				style={{
					position: 'absolute',
					right: 96,
					top: 72,
					fontFamily: WMONO,
					fontSize: 20,
					letterSpacing: 3,
					color: '#e8f1fa',
					opacity: k(f, 116, 130) * (0.6 + 0.4 * Math.sin(f * 0.5)),
				}}
			>
				● READING 4 DOCS
			</div>
		</AbsoluteFill>
	);
};

/* ---------------------------------------------------------------- 4막: 타일 → 제목 */
const COLS = 16;
const ROWS = 9;
const TILE = 108;
const GAP = 12;

export const TitleAct: React.FC<{f: number}> = ({f}) => {
	// 타일이 대각선 물결로 켜진다 → 판이 아래부터 위로 걷힌다(아래 모서리 둥글게) → 흰 바탕 제목
	const lift = k(f, 40, 74, Easing.bezier(0.76, 0, 0.24, 1));
	const panelH = mix(1080, 0, lift);
	const ox = (1920 - (COLS * TILE + (COLS - 1) * GAP)) / 2;
	const oy = (1080 - (ROWS * TILE + (ROWS - 1) * GAP)) / 2;
	const t = f - 56;
	return (
		<AbsoluteFill style={{background: W.bg}}>
			{/* 제목 (판 아래) */}
			<div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
				<svg width={160} height={160} viewBox="-150 -150 300 300" style={{opacity: k(t, 0, 16), marginBottom: 26}}>
					<Compass f={t + 10} x={0} y={0} color={W.ink} />
				</svg>
				{['통관 서류 검토', 'Agent'].map((line, i) => {
					const p = k(t, 4 + i * 7, 30 + i * 7);
					return (
						<div key={line} style={{overflow: 'hidden', height: 150}}>
							<div
								style={{
									fontFamily: WFONT,
									fontWeight: 900,
									fontSize: 136,
									letterSpacing: -5,
									lineHeight: '150px',
									color: W.ink,
									transform: `translateY(${(1 - p) * 110}%)`,
								}}
							>
								{i === 1 ? (
									<>
										Agen<span style={{color: W.red}}>t</span>
									</>
								) : (
									line
								)}
							</div>
						</div>
					);
				})}
				<div
					style={{
						marginTop: 34,
						display: 'flex',
						gap: 14,
						fontFamily: WFONT,
						fontSize: 30,
						fontWeight: 600,
						opacity: k(t, 30, 48),
						transform: `translateY(${(1 - k(t, 30, 48)) * 16}px)`,
					}}
				>
					<span style={{padding: '10px 22px', borderRadius: 999, background: W.ink, color: '#fff'}}>읽기는 AI</span>
					<span style={{padding: '10px 22px', borderRadius: 999, background: W.fill, color: W.ink}}>판정은 코드</span>
					<span style={{padding: '10px 22px', borderRadius: 999, background: W.fill, color: W.muted}}>6팀</span>
				</div>
			</div>
			{/* 타일 판 */}
			<div
				style={{
					position: 'absolute',
					left: 0,
					top: 0,
					width: 1920,
					height: panelH,
					background: '#050607',
					borderBottomLeftRadius: mix(0, 220, Math.min(1, lift * 3)),
					borderBottomRightRadius: mix(0, 220, Math.min(1, lift * 3)),
					overflow: 'hidden',
				}}
			>
				<svg width={1920} height={1080}>
					{Array.from({length: ROWS}, (_, r) =>
						Array.from({length: COLS}, (_, c) => {
							const wave = k(f, (c + r) * 1.1, (c + r) * 1.1 + 10);
							const glow = Math.max(0, 1 - Math.abs(f - 10 - (c + r) * 1.1) / 8);
							return (
								<rect
									key={`${r}-${c}`}
									x={ox + c * (TILE + GAP)}
									y={oy + r * (TILE + GAP)}
									width={TILE}
									height={TILE}
									rx={20}
									fill={glow > 0.05 ? `rgba(255,90,60,${0.08 + glow * 0.5})` : '#0f1113'}
									stroke="#2a2d31"
									strokeOpacity={wave}
									strokeWidth={1.5}
									opacity={wave}
								/>
							);
						}),
					)}
				</svg>
			</div>
		</AbsoluteFill>
	);
};

/* ---------------------------------------------------------------- 이어 붙이기 */
const YARD_AT = 166;
const TITLE_AT = 405;

export const Opening: React.FC = () => {
	const f = useCurrentFrame();
	if (f < YARD_AT) return <ShipAct f={f} />;
	if (f < TITLE_AT) {
		const y = f - YARD_AT;
		// 3막 끝: 훑기가 끝난 화면이 어두워지며 타일 판으로
		const fade = k(f, TITLE_AT - 16, TITLE_AT);
		return (
			<AbsoluteFill>
				<YardAct f={y} />
				<AbsoluteFill style={{background: '#050607', opacity: fade}} />
			</AbsoluteFill>
		);
	}
	return <TitleAct f={f - TITLE_AT} />;
};

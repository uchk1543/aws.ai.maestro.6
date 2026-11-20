import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {C, FONT, MONO} from './theme';

export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export const ap = (f: number, start: number, dur = 18) =>
	interpolate(f, [start, start + dur], [0, 1], {...clamp, easing: ease});

type Kids = {children?: React.ReactNode; style?: React.CSSProperties};

export const Scene: React.FC<Kids & {dur: number}> = ({dur, children}) => {
	const f = useCurrentFrame();
	const o = Math.min(ap(f, 0, 12), 1 - ap(f, dur - 14, 14));
	return <AbsoluteFill style={{opacity: o}}>{children}</AbsoluteFill>;
};

export const Rise: React.FC<Kids & {at: number; dur?: number; y?: number; x?: number}> = ({
	at,
	dur = 18,
	y = 24,
	x = 0,
	style,
	children,
}) => {
	const f = useCurrentFrame();
	const p = ap(f, at, dur);
	return (
		<div style={{opacity: p, transform: `translate(${(1 - p) * x}px, ${(1 - p) * y}px)`, ...style}}>
			{children}
		</div>
	);
};

export const Pop: React.FC<Kids & {at: number}> = ({at, style, children}) => {
	const f = useCurrentFrame();
	const p = ap(f, at, 14);
	const s = 0.6 + 0.4 * p + Math.sin(p * Math.PI) * 0.08;
	return <div style={{opacity: p, transform: `scale(${s})`, ...style}}>{children}</div>;
};

export const Type: React.FC<{text: string; at: number; cps?: number; style?: React.CSSProperties}> = ({
	text,
	at,
	cps = 32,
	style,
}) => {
	const f = useCurrentFrame();
	const n = Math.max(0, Math.floor(((f - at) * cps) / 30));
	const shown = text.slice(0, n);
	const typing = f >= at && n < text.length;
	return (
		<span style={style}>
			{shown}
			{typing ? <span style={{color: C.accent}}>▍</span> : null}
		</span>
	);
};

export const fmt = (v: number, d = 0) =>
	v.toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});

export const Count: React.FC<{to: number; at: number; dur?: number; d?: number; style?: React.CSSProperties}> = ({
	to,
	at,
	dur = 36,
	d = 0,
	style,
}) => {
	const f = useCurrentFrame();
	const v = to * ap(f, at, dur);
	return <span style={style}>{fmt(v, d)}</span>;
};

export const Panel: React.FC<Kids & {glow?: string}> = ({style, children, glow}) => (
	<div
		style={{
			background: `linear-gradient(160deg, ${C.panel2}, ${C.panel})`,
			border: `1.5px solid ${glow ?? C.line}`,
			borderRadius: 22,
			padding: 28,
			boxShadow: glow ? `0 0 0 1px ${glow}33, 0 20px 60px ${glow}22` : '0 20px 60px #0006',
			...style,
		}}
	>
		{children}
	</div>
);

export const Chip: React.FC<Kids & {color?: string; solid?: boolean}> = ({children, color = C.accent, solid, style}) => (
	<span
		style={{
			display: 'inline-flex',
			alignItems: 'center',
			gap: 8,
			padding: '6px 16px',
			borderRadius: 999,
			fontSize: 20,
			fontWeight: 700,
			color: solid ? C.bg : color,
			background: solid ? color : `${color}1f`,
			border: `1.5px solid ${color}88`,
			...style,
		}}
	>
		{children}
	</span>
);

export const SceneTitle: React.FC<{step: string; title: string; sub?: string}> = ({step, title, sub}) => (
	<div style={{position: 'absolute', left: 96, top: 118, width: 1728}}>
		<Rise at={4} y={16}>
			<div style={{color: C.accent, fontSize: 22, fontWeight: 800, letterSpacing: 3}}>{step}</div>
		</Rise>
		<Rise at={8} y={20}>
			<div style={{color: C.text, fontSize: 52, fontWeight: 900, marginTop: 6, letterSpacing: -1}}>{title}</div>
		</Rise>
		{sub ? (
			<Rise at={14} y={20}>
				<div style={{color: C.sub, fontSize: 25, fontWeight: 500, marginTop: 8}}>{sub}</div>
			</Rise>
		) : null}
	</div>
);

export type DocImg = {file: string; w: number; h: number; boxes: Record<string, number[]>};
export type BoxSpec = {key: string; at: number; color?: string};

export const DocView: React.FC<{img: DocImg; width: number; boxes?: BoxSpec[]; style?: React.CSSProperties; crop?: number}> = ({
	img,
	width,
	boxes = [],
	style,
	crop,
}) => {
	const f = useCurrentFrame();
	const k = width / img.w;
	const h = img.h * k;
	return (
		<div
			style={{
				position: 'relative',
				width,
				height: crop ?? h,
				overflow: 'hidden',
				borderRadius: 10,
				background: C.paper,
				boxShadow: '0 24px 70px #000a',
				...style,
			}}
		>
			<Img src={staticFile(img.file)} style={{width, height: h, display: 'block'}} />
			{boxes.map((b) => {
				const r = img.boxes[b.key];
				if (!r) return null;
				const p = ap(f, b.at, 10);
				const color = b.color ?? C.accent;
				const s = 1 + (1 - p) * 0.5;
				return (
					<div
						key={b.key + b.at}
						style={{
							position: 'absolute',
							left: r[0] * k - 7,
							top: r[1] * k - 6,
							width: (r[2] - r[0]) * k + 14,
							height: (r[3] - r[1]) * k + 12,
							border: `3px solid ${color}`,
							background: `${color}26`,
							borderRadius: 6,
							opacity: p,
							transform: `scale(${s})`,
						}}
					/>
				);
			})}
		</div>
	);
};

export const Mono: React.FC<Kids> = ({children, style}) => (
	<span style={{fontFamily: MONO, letterSpacing: 0.5, ...style}}>{children}</span>
);

export const Icon: React.FC<{ok: boolean; size?: number}> = ({ok, size = 30}) => (
	<span
		style={{
			display: 'inline-flex',
			alignItems: 'center',
			justifyContent: 'center',
			width: size,
			height: size,
			borderRadius: size,
			background: ok ? `${C.teal}22` : `${C.red}22`,
			border: `2px solid ${ok ? C.teal : C.red}`,
			color: ok ? C.teal : C.red,
			fontSize: size * 0.6,
			fontWeight: 900,
			fontFamily: FONT,
			flexShrink: 0,
		}}
	>
		{ok ? '✓' : '✕'}
	</span>
);

/** 결정적 의사난수 (렌더마다 같은 그림) */
export const rand = (i: number) => {
	const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453;
	return x - Math.floor(x);
};

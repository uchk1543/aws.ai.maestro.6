// 웹 화면 스타일 부품: 흰 카드, 회색 칸, 알약 칩, 등급 표시. 움직임은 ../ui 의 ap·Rise 를 쓴다
import React from 'react';
import {Img, staticFile, useCurrentFrame} from 'remotion';
import {ap, Rise} from '../ui';
import type {DocImg} from '../ui';
import {W, WMONO} from './theme';

type Kids = {children?: React.ReactNode; style?: React.CSSProperties};

export const Card: React.FC<Kids> = ({style, children}) => (
	<div style={{background: '#fff', border: `1px solid ${W.line}`, borderRadius: 22, padding: 28, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', ...style}}>
		{children}
	</div>
);

export const Fill: React.FC<Kids> = ({style, children}) => (
	<div style={{background: W.fill2, borderRadius: 14, padding: '16px 18px', ...style}}>{children}</div>
);

export const Pill: React.FC<Kids & {dark?: boolean; red?: boolean}> = ({dark, red, style, children}) => (
	<span
		style={{
			display: 'inline-flex',
			alignItems: 'center',
			height: 40,
			padding: '0 18px',
			borderRadius: 999,
			fontSize: 20,
			fontWeight: 600,
			color: dark || red ? '#fff' : W.ink,
			background: red ? W.red : dark ? W.ink : W.fill2,
			border: dark || red ? 'none' : `1px solid ${W.line}`,
			...style,
		}}
	>
		{children}
	</span>
);

export const Mono: React.FC<Kids> = ({style, children}) => <span style={{fontFamily: WMONO, ...style}}>{children}</span>;

/** 화면 위 앱 머리: 앱 이름 칩 + 타일형 메뉴 (웹 App.tsx 와 같은 모양) */
export const AppBar: React.FC<{active: string}> = ({active}) => (
	<div style={{display: 'flex', alignItems: 'center', gap: 16}}>
		<Pill style={{fontSize: 18}}>통관 서류 검토</Pill>
		<div style={{display: 'flex', gap: 4, padding: 5, background: W.fill2, borderRadius: 999}}>
			{['파일 업로드', '문서 분류 내역', '대시보드', 'AI chat'].map((m) => (
				<span
					key={m}
					style={{
						padding: '9px 20px',
						borderRadius: 999,
						fontSize: 18,
						fontWeight: m === active ? 700 : 500,
						color: m === active ? W.ink : W.muted,
						background: m === active ? '#fff' : 'transparent',
						boxShadow: m === active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
					}}
				>
					{m}
				</span>
			))}
		</div>
	</div>
);

/* ---------------------------------------------------------------- */
/* 장면 머리·서류 그림·타자                                           */
/* ---------------------------------------------------------------- */

/** 장면 머리: 단계 이름(회색) + 큰 제목(검정) + 설명 */
export const Head: React.FC<{step: string; title: React.ReactNode; sub?: string}> = ({step, title, sub}) => (
	<div style={{position: 'absolute', left: 96, top: 124, width: 1728}}>
		<Rise at={4} y={14}>
			<div style={{fontSize: 22, fontWeight: 700, color: W.muted}}>{step}</div>
		</Rise>
		<Rise at={8} y={18}>
			<div style={{fontSize: 56, fontWeight: 800, letterSpacing: -1.5, marginTop: 4, color: W.ink}}>{title}</div>
		</Rise>
		{sub ? (
			<Rise at={14} y={18}>
				<div style={{fontSize: 24, color: W.muted, marginTop: 6}}>{sub}</div>
			</Rise>
		) : null}
	</div>
);

export type WBox = {key: string; at: number; red?: boolean};

/** 서류 그림 위에 박스 (웹 서류 보기처럼: 불일치는 빨강, 나머지는 검정 점선) */
export const WDoc: React.FC<{img: DocImg; width: number; boxes?: WBox[]; crop?: number; style?: React.CSSProperties}> = ({
	img,
	width,
	boxes = [],
	crop,
	style,
}) => {
	const f = useCurrentFrame();
	const k = width / img.w;
	const h = img.h * k;
	return (
		<div style={{position: 'relative', width, height: crop ?? h, overflow: 'hidden', borderRadius: 12, background: '#fff', border: `1px solid ${W.line}`, ...style}}>
			<Img src={staticFile(img.file)} style={{width, height: h, display: 'block'}} />
			{boxes.map((b) => {
				const r = img.boxes[b.key];
				if (!r) return null;
				const p = ap(f, b.at, 12);
				const pad = Math.max(4, (r[3] - r[1]) * k * 0.25);
				return (
					<div
						key={b.key + b.at}
						style={{
							position: 'absolute',
							left: r[0] * k - pad,
							top: r[1] * k - pad,
							width: (r[2] - r[0]) * k + pad * 2,
							height: (r[3] - r[1]) * k + pad * 2,
							border: b.red ? `3px solid ${W.red}` : `2px dashed ${W.ink}`,
							borderRadius: 6,
							opacity: p,
							transform: `scale(${1 + (1 - p) * 0.3})`,
						}}
					/>
				);
			})}
		</div>
	);
};

/** 글자가 하나씩 찍힌다 (커서는 검정) */
export const WType: React.FC<{text: string; at: number; cps?: number; style?: React.CSSProperties}> = ({text, at, cps = 32, style}) => {
	const f = useCurrentFrame();
	const n = Math.max(0, Math.floor(((f - at) * cps) / 30));
	const typing = f >= at && n < text.length;
	return (
		<span style={style}>
			{text.slice(0, n)}
			{typing ? <span style={{color: W.ink}}>▍</span> : null}
		</span>
	);
};

/** 상태 칩: 웹 화면의 회색 알약과 같은 크기 */
export const Status: React.FC<{tone?: 'ok' | 'wait' | 'bad'; children: React.ReactNode}> = ({tone = 'wait', children}) => (
	<span
		style={{
			display: 'inline-flex',
			alignItems: 'center',
			height: 34,
			padding: '0 14px',
			borderRadius: 999,
			fontSize: 17,
			fontWeight: 700,
			color: tone === 'bad' ? '#fff' : tone === 'ok' ? '#fff' : W.ink,
			background: tone === 'bad' ? W.red : tone === 'ok' ? W.ink : '#fff',
			border: tone === 'wait' ? `1.5px solid ${W.ink}` : 'none',
		}}
	>
		{children}
	</span>
);

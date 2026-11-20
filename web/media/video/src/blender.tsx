import React from 'react';
import {Video} from '@remotion/media';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import data from './data.json';
import {C} from './theme';
import {ap, Chip, clamp, Count, ease, Panel, Rise, Scene, SceneTitle} from './ui';

/*
 * Blender로 렌더링한 부산항 장면 (video/blender/busan_port.blend, 900프레임, 30fps).
 * 프레임 1-240 오프닝 · 241-480 현장 촬영 · 481-690 반출 게이트 · 691-900 마무리 항공샷
 * 장면마다 public/blender/<장면>.mp4 로 묶어 둔다 (blender/encode_shots.mjs).
 */
type Shot = 'opening' | 'field' | 'gate' | 'outro';

const D = data as any;
const S = D.shipment;
const L = D.logistics;
const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

export const BlenderBg: React.FC<{shot: Shot}> = ({shot}) => (
	<AbsoluteFill>
		<Video
			src={staticFile(`blender/${shot}.mp4`)}
			muted
			objectFit="cover"
			style={{width: '100%', height: '100%', filter: 'contrast(1.06) saturate(1.08)'}}
		/>
	</AbsoluteFill>
);

// 밝은 실사 배경 위에서도 읽히도록 어두운 바탕을 깐 칩
const BChip: React.FC<{color: string; children: React.ReactNode; style?: React.CSSProperties}> = ({color, children, style}) => (
	<Chip color={color} style={{background: `linear-gradient(${color}2e, ${color}2e), rgba(10,17,32,0.86)`, boxShadow: '0 6px 20px #0006', ...style}}>
		{children}
	</Chip>
);
const TEXT_AREA = 'radial-gradient(ellipse 1150px 620px at 0% 22%, rgba(10,17,32,0.78) 0%, rgba(10,17,32,0.45) 45%, rgba(10,17,32,0) 100%)';

const Shade: React.FC<{css: string}> = ({css}) => <div style={{position: 'absolute', inset: 0, background: css}} />;
const TOP = 'linear-gradient(rgba(10,17,32,0.85) 0px, rgba(10,17,32,0.55) 150px, rgba(10,17,32,0) 330px)';
const BOTTOM = 'linear-gradient(0deg, rgba(10,17,32,0.7) 0px, rgba(10,17,32,0) 170px)';

/* ------------------------------------------------------------------ */
/* 오프닝: 바다 쪽에서 부산신항 터미널로 내려온다                          */
/* ------------------------------------------------------------------ */
export const BlenderIntro: React.FC<{dur: number}> = ({dur}) => {
	const stats = [
		{v: 2488, unit: '만 TEU', label: '2025 부산항 컨테이너 물동량'},
		{v: 1078, unit: '만 TEU', label: '그중 수출입 화물 · 우리 대상은 수입'},
		{v: 57, unit: '%', label: '환적 화물 · 수입신고 없음 (대상 제외)'},
	];
	return (
		<Scene dur={dur}>
			<BlenderBg shot="opening" />
			<Shade css="linear-gradient(90deg, rgba(10,17,32,0.9) 0%, rgba(10,17,32,0.62) 36%, rgba(10,17,32,0) 64%)" />
			<Shade css={TOP} />
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
					<div style={{fontSize: 31, color: '#d5deec', marginTop: 22, fontWeight: 500, textShadow: '0 2px 16px #000a'}}>
						현장 사진 한 장으로 시작하는 문서 자동화 Agent
					</div>
				</Rise>
			</div>
			<div style={{position: 'absolute', left: 120, top: 640, display: 'flex', gap: 24}}>
				{stats.map((s, i) => (
					<Rise key={s.label} at={100 + i * 12}>
						<Panel style={{width: 400, padding: '20px 26px', background: 'rgba(15,26,46,0.86)'}}>
							<div style={{fontSize: 48, fontWeight: 900, color: i === 2 ? C.sub : C.text}}>
								<Count to={s.v} at={100 + i * 12} />
								<span style={{fontSize: 26, marginLeft: 6, color: C.sub}}>{s.unit}</span>
							</div>
							<div style={{fontSize: 20, color: C.sub, marginTop: 4}}>{s.label}</div>
						</Panel>
					</Rise>
				))}
			</div>
			<Rise at={130} style={{position: 'absolute', left: 124, top: 790, color: '#a9b8cf', fontSize: 17, textShadow: '0 1px 8px #000'}}>
				자료: 해양수산부 2025년 전국 무역항 컨테이너 물동량 발표 · 3D 장면은 단순화한 재현입니다
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 현장 촬영: 크레인 아래 작업자가 태블릿으로 서류를 찍어 올린다            */
/*   0-89 안벽 진입 · 89-154 작업자에게 다가감 · 154-239 어깨 너머 태블릿  */
/* ------------------------------------------------------------------ */
const SHOT = 185; // 셔터 (Blender 426프레임, 어깨 너머 화면)
const TABLET = {x: 778, y: 686}; // 그 프레임에서 태블릿 화면 중심 (px)
const CLOUD = {x: 1640, y: 214};

export const BlenderField: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const flash = interpolate(f, [SHOT, SHOT + 2, SHOT + 14], [0, 0.85, 0], clamp);
	const fly = interpolate(f, [SHOT + 4, SHOT + 30], [0, 1], {...clamp, easing: ease});
	const card = {
		x: TABLET.x + (CLOUD.x - TABLET.x) * fly,
		y: TABLET.y + (CLOUD.y - TABLET.y) * fly - Math.sin(fly * Math.PI) * 120,
		w: 150 - 80 * fly,
	};
	const showCard = f >= SHOT + 4 && f < SHOT + 34;
	const up = ap(f, SHOT + 22, 12);
	const prog = interpolate(f, [SHOT + 26, dur - 12], [0, 1], clamp);
	return (
		<Scene dur={dur}>
			<BlenderBg shot="field" />
			<Shade css={TEXT_AREA} />
			<Shade css={TOP} />
			<Shade css={BOTTOM} />
			<SceneTitle
				step="STEP 1 · 현장 촬영"
				title="안벽의 작업자가 태블릿으로 서류를 찍는다"
				sub={`입항 3일 전 · 선적 ${md(S.onBoard)} → 서류 도착 ${md(L.baseDate)} → 입항 예정 ${md(L.demo.eta)}`}
			/>
			<div style={{position: 'absolute', left: 96, top: 330, display: 'flex', flexDirection: 'column', gap: 16}}>
				<Rise at={30} x={-30} y={0}>
					<BChip color={C.sub} style={{fontSize: 22}}>
						부산신항 컨테이너 터미널 · 안벽 크레인 아래
					</BChip>
				</Rise>
				<Rise at={150} x={-30} y={0}>
					<BChip color={C.accent} style={{fontSize: 22}}>
						Packing List · B/L 촬영
					</BChip>
				</Rise>
				<Rise at={SHOT + 24} x={-30} y={0}>
					<BChip color={C.teal} style={{fontSize: 22}}>
						AWS 클라우드로 바로 업로드 · Agent 처리 시작
					</BChip>
				</Rise>
			</div>
			{/* 찍힌 서류가 클라우드로 날아간다 */}
			{showCard ? (
				<div
					style={{
						position: 'absolute',
						left: card.x - card.w / 2,
						top: card.y - card.w * 0.7,
						width: card.w,
						borderRadius: 8,
						overflow: 'hidden',
						border: '3px solid #fff',
						boxShadow: '0 18px 40px #000a',
						opacity: 1 - ap(f, SHOT + 28, 6),
					}}
				>
					<Img src={staticFile('docs/scan_pl.jpg')} style={{width: '100%', display: 'block'}} />
				</div>
			) : null}
			<div
				style={{
					position: 'absolute',
					left: CLOUD.x - 190,
					top: CLOUD.y - 46,
					width: 380,
					opacity: up,
					transform: `translateY(${(1 - up) * 16}px) scale(${0.94 + 0.06 * up})`,
				}}
			>
				<Panel style={{padding: '16px 22px', background: 'rgba(12,20,36,0.9)'}} glow={C.teal}>
					<div style={{display: 'flex', alignItems: 'center', gap: 14}}>
						<div
							style={{
								width: 46,
								height: 46,
								borderRadius: 12,
								background: C.teal + '22',
								border: `2px solid ${C.teal}`,
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								color: C.teal,
								fontSize: 24,
								fontWeight: 900,
							}}
						>
							↑
						</div>
						<div style={{flex: 1}}>
							<div style={{fontSize: 21, fontWeight: 800, color: C.text}}>Amazon S3 업로드</div>
							<div style={{fontSize: 17, color: C.sub, marginTop: 2}}>
								사진 2장 + PDF 2개 · {prog >= 1 ? '완료' : `${Math.round(prog * 100)}%`}
							</div>
						</div>
					</div>
					<div style={{height: 6, borderRadius: 6, background: C.line, marginTop: 12, overflow: 'hidden'}}>
						<div style={{width: `${prog * 100}%`, height: '100%', background: C.teal}} />
					</div>
				</Panel>
			</div>
			<div style={{position: 'absolute', inset: 0, background: '#fff', opacity: flash}} />
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 반출: 입항 당일 트럭이 게이트에서 멈췄다가 바로 통과한다                */
/*   0-67 진입 · 67-111 정차 (차단기 75-101) · 111- 출발                 */
/* ------------------------------------------------------------------ */
export const BlenderGate: React.FC<{dur: number}> = ({dur}) => {
	const chips = [
		{at: 52, text: '✓ 세관 신고 수리', color: C.teal},
		{at: 74, text: '✓ 전자인수도증 자동 발급', color: C.teal},
		{at: 104, text: `B/L ${S.blNo} · 프리타임 안에 반출`, color: C.accent},
	];
	return (
		<Scene dur={dur}>
			<BlenderBg shot="gate" />
			<Shade css={TEXT_AREA} />
			<Shade css={TOP} />
			<Shade css={BOTTOM} />
			<SceneTitle
				step={`STEP 7 · 반출 (${md(L.demo.eta)} 입항)`}
				title="입항 당일, 막힘 없이 게이트를 나간다"
				sub="서류를 입항 전에 바로잡고 신고 준비를 끝냈기 때문"
			/>
			<div style={{position: 'absolute', left: 96, top: 400, display: 'flex', flexDirection: 'column', gap: 16}}>
				{chips.map((c) => (
					<Rise key={c.text} at={c.at} x={-30} y={0}>
						<BChip color={c.color} style={{fontSize: 24, padding: '10px 22px'}}>
							{c.text}
						</BChip>
					</Rise>
				))}
			</div>
		</Scene>
	);
};

/* 마무리 배경: 터미널 전체를 내려다보며 천천히 돈다 */
export const BlenderOutroBg: React.FC = () => (
	<>
		<BlenderBg shot="outro" />
		<div style={{position: 'absolute', inset: 0, background: 'rgba(10,17,32,0.58)'}} />
	</>
);

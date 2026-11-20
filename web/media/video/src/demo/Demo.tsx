// 발표 시연영상 (#272 · #278). 1920×1080, 30fps
//   인트로(#278, 1번이 만든 10초 영상의 앞 7초) → 작업자가 태블릿으로 서류를 찍음(blender/field.mp4)
//   → 태블릿 화면으로 확대해 들어가 → 실제 배포본 화면 녹화(record/record.py, 브라우저 틀 + 실제 주소)
//   → 8번 장면 숫자판 → 항구 마무리 컷(blender/outro.mp4) + 장표 1쪽 문장
// 녹화본은 public/demo/take/(screen.mp4, markers.json). 장면 자르기와 배속은 아래 CUTS 표 하나로 정한다.
import React from 'react';
import {Video} from '@remotion/media';
import {AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame} from 'remotion';
import markers from '../../public/demo/take/markers.json';
import {loadPretendard, WFONT, WMONO} from '../web/theme';

loadPretendard();

const FPS = 30;
type Mark = {scene: string; t: number; url?: string; note?: string};
const M = markers as Mark[];
const at = (scene: string) => M.find((m) => m.scene === scene)?.t;
const urlAt = (scene: string) => M.find((m) => m.scene === scene)?.url ?? '';

const k = (f: number, a: number, b: number, easing = Easing.bezier(0.16, 1, 0.3, 1)) =>
	interpolate(f, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing});

/* ---------------------------------------------------------------- 녹화 자르기 표 */
type Cut = {from: string; to: string; speed: number; who: 'worker' | 'manager'; caps?: string[]; trimEnd?: number};
// caps: public/demo/video-cap-*.png 이름 (1번이 만든 자막 판). 4x 는 speed>1 이면 자동
const CUTS: Cut[] = [
	{from: 's2_upload_d003', to: 's2_processing', speed: 1, who: 'worker', caps: ['insight2']},
	{from: 's2_processing', to: 's2_done', speed: 4, who: 'worker', caps: ['insight2']},
	{from: 's2_done', to: 's3_dashboard', speed: 1, who: 'worker'},
	{from: 's3_dashboard', to: 's4_review', speed: 1, who: 'manager', caps: ['insight2', 'refresh', 'demo-data']},
	{from: 's4_review', to: 's5_hs', speed: 1.15, who: 'manager', caps: ['insight2']},
	{from: 's5_hs', to: 's6_upload_d054', speed: 1.15, who: 'manager', caps: ['insight3']},
	{from: 's6_upload_d054', to: 's6_d054_done', speed: 4, who: 'worker'},
	{from: 's6_d054_done', to: 's6_upload_d064', speed: 1, who: 'manager', caps: ['insight3']},
	{from: 's6_upload_d064', to: 's6_d064_done', speed: 5, who: 'worker'},
	{from: 's6_d064_done', to: 's7_hs_pending', speed: 1, who: 'manager', caps: ['refresh']},
	{from: 's7_hs_pending', to: 's8_dashboard', speed: 1.15, who: 'manager', caps: ['insight3']},
	{from: 's8_dashboard', to: 'end', speed: 1, who: 'manager', caps: ['demo-data']},
];

const PLAYED = CUTS.filter((c) => at(c.from) !== undefined && at(c.to) !== undefined).map((c) => {
	const src = Math.round((at(c.from) as number) * FPS);
	const len = Math.max(1, Math.round(((at(c.to) as number) - (at(c.from) as number)) * FPS));
	return {...c, src, len, dur: Math.max(1, Math.round(len / c.speed))};
});
const SCREEN_LEN = PLAYED.reduce((s, c) => s + c.dur, 0);

/* ---------------------------------------------------------------- 길이 */
const INTRO = 7 * FPS; // #278 앞 7초 (검은 끝은 쓰지 않음)
const FIELD = 6 * FPS; // 작업자 장면
const DIVE = 24; // 태블릿으로 확대해 들어가는 시간 (화면 녹화와 겹침)
const NUMBERS = 8 * FPS; // 8번 숫자판 (녹화 끝 위에 얹음)
const OUTRO = Math.round(3.5 * FPS);
const S_INTRO = 0;
const S_FIELD = S_INTRO + INTRO;
const S_SCREEN = S_FIELD + FIELD;
const S_OUTRO = S_SCREEN + SCREEN_LEN;
export const DEMO_FRAMES = S_OUTRO + OUTRO;

/* ---------------------------------------------------------------- 조각 */
const IntroSlot: React.FC = () => {
	// #278 영상을 public/demo/intro-1080p.mp4 로 넣으면 그것을 튼다. 없으면 자리 표시
	const has = typeof INTRO_FILE === 'string' && INTRO_FILE !== '';
	const f = useCurrentFrame();
	if (has) return <Video src={staticFile(INTRO_FILE)} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />;
	return (
		<AbsoluteFill style={{background: '#05070a', alignItems: 'center', justifyContent: 'center', color: '#8a96a6', fontFamily: WMONO, fontSize: 30}}>
			<div style={{opacity: 0.6 + 0.4 * Math.sin(f * 0.1)}}>인트로 #278 자리 (opening-1080p.mp4, 앞 7초)</div>
		</AbsoluteFill>
	);
};
const INTRO_FILE: string = ''; // 받으면 'demo/intro-1080p.mp4'

/** 작업자가 태블릿으로 서류를 찍는 장면. 끝에서 태블릿 화면으로 확대해 들어간다 */
const Field: React.FC = () => {
	const f = useCurrentFrame();
	const zoom = interpolate(f, [FIELD - DIVE - 6, FIELD + 6], [1, 5.2], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.7, 0, 0.3, 1)});
	const fadeIn = k(f, 0, 14);
	return (
		<AbsoluteFill style={{background: '#000', opacity: fadeIn}}>
			<AbsoluteFill style={{transform: `scale(${zoom})`, transformOrigin: '770px 690px'}}>
				<Video src={staticFile('blender/field.mp4')} muted style={{width: '100%', height: '100%'}} />
			</AbsoluteFill>
			<Cap name="worker" o={k(f, 10, 24) * (1 - k(f, FIELD - DIVE - 10, FIELD - DIVE))} />
		</AbsoluteFill>
	);
};

const Cap: React.FC<{name: string; o?: number}> = ({name, o = 1}) => (
	<Img src={staticFile(`demo/video-cap-${name}.png`)} style={{position: 'absolute', inset: 0, width: 1920, height: 1080, opacity: o}} />
);

/** 브라우저 창 틀: 실제 녹화 위에 주소창(녹화 때 page.url)을 그린다 */
const WIN_W = 1696;
const WIN_H = Math.round((WIN_W * 1080) / 1920) + 56;
const Browser: React.FC<{url: string; children: React.ReactNode}> = ({url, children}) => (
	<div
		style={{
			position: 'absolute',
			left: (1920 - WIN_W) / 2,
			top: (1080 - WIN_H) / 2 + 6,
			width: WIN_W,
			height: WIN_H,
			borderRadius: 14,
			overflow: 'hidden',
			background: '#fff',
			boxShadow: '0 30px 80px rgba(0,0,0,0.28), 0 0 0 1px rgba(0,0,0,0.08)',
		}}
	>
		<div style={{height: 56, display: 'flex', alignItems: 'center', gap: 14, padding: '0 18px', background: '#eef0f3', borderBottom: '1px solid #dde1e6'}}>
			<div style={{display: 'flex', gap: 8}}>
				{['#ff5f57', '#febc2e', '#28c840'].map((c) => (
					<span key={c} style={{width: 13, height: 13, borderRadius: 7, background: c}} />
				))}
			</div>
			<div
				style={{
					flex: 1,
					height: 34,
					borderRadius: 17,
					background: '#fff',
					display: 'flex',
					alignItems: 'center',
					gap: 10,
					padding: '0 16px',
					fontFamily: WFONT,
					fontSize: 19,
					color: '#3a3f47',
				}}
			>
				<svg width="14" height="16" viewBox="0 0 14 16">
					<rect x="1" y="7" width="12" height="8" rx="2" fill="#5f6672" />
					<path d="M3.5 7V5a3.5 3.5 0 0 1 7 0v2" stroke="#5f6672" strokeWidth="1.8" fill="none" />
				</svg>
				{url}
			</div>
		</div>
		<div style={{position: 'absolute', left: 0, top: 56, width: WIN_W, height: WIN_H - 56}}>{children}</div>
	</div>
);

/** 화면 녹화 구간: 자르기 표대로 이어 붙이고, 누구 화면인지·배속·알아낸 것 자막을 얹는다 */
const Screen: React.FC = () => {
	const f = useCurrentFrame();
	let start = 0;
	const dive = k(f, 0, DIVE, Easing.bezier(0.2, 0.7, 0.2, 1));
	return (
		<AbsoluteFill style={{background: 'linear-gradient(180deg, #f3f5f8 0%, #e6eaf0 100%)'}}>
			<AbsoluteFill style={{transform: `scale(${0.35 + 0.65 * dive})`, opacity: k(f, 0, 10), transformOrigin: '50% 52%'}}>
				{PLAYED.map((c, i) => {
					const s = start;
					start += c.dur;
					const url = urlAt(c.from).replace(/^http:\/\/localhost:\d+/, 'https://dx8a8z83slbmk.cloudfront.net');
					return (
						<Sequence key={i} from={s} durationInFrames={c.dur} layout="none">
							<Browser url={url}>
								<Video
									src={staticFile('demo/take/screen.mp4')}
									muted
									trimBefore={c.src}
									playbackRate={c.speed}
									style={{width: '100%', height: '100%'}}
								/>
							</Browser>
						</Sequence>
					);
				})}
			</AbsoluteFill>
			{(() => {
				let s2 = 0;
				return PLAYED.map((c, i) => {
					const s = s2;
					s2 += c.dur;
					return (
						<Sequence key={`cap${i}`} from={s} durationInFrames={c.dur} layout="none">
							<Cap name={c.who} />
							{(c.caps ?? []).map((n) => (
								<Cap key={n} name={n} />
							))}
							{c.speed >= 3 && <Cap name="4x" />}
						</Sequence>
					);
				});
			})()}
			{/* 8번: 끝 NUMBERS 동안 숫자판 */}
			<Sequence from={Math.max(0, SCREEN_LEN - NUMBERS)} durationInFrames={NUMBERS} layout="none">
				<Numbers />
			</Sequence>
		</AbsoluteFill>
	);
};

const Numbers: React.FC = () => {
	const f = useCurrentFrame();
	return <Img src={staticFile('demo/video-s8-numbers-overlay.png')} style={{position: 'absolute', inset: 0, width: 1920, height: 1080, opacity: k(f, 0, 16)}} />;
};

/** 마무리: 항구 항공샷 + 장표 1쪽 문장 */
const Outro: React.FC = () => {
	const f = useCurrentFrame();
	return (
		<AbsoluteFill style={{background: '#000', opacity: k(f, 0, 12)}}>
			<Video src={staticFile('blender/outro.mp4')} muted style={{width: '100%', height: '100%'}} />
			<AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(10,14,22,0.82) 0%, rgba(10,14,22,0.35) 55%, rgba(10,14,22,0) 100%)'}} />
			<div style={{position: 'absolute', left: 120, top: 380, fontFamily: WFONT, color: '#fff'}}>
				<div style={{fontSize: 26, fontWeight: 600, color: '#9fc0ff', opacity: k(f, 6, 22)}}>2026 PNU X AWS AI 마에스트로 · 6팀</div>
				{['포워더가 관세사에게 넘기기 전,', '서류 검토를 AI가 대신합니다'].map((line, i) => (
					<div key={line} style={{overflow: 'hidden'}}>
						<div style={{fontSize: 84, fontWeight: 800, letterSpacing: -2.5, lineHeight: 1.22, transform: `translateY(${(1 - k(f, 10 + i * 6, 34 + i * 6)) * 105}%)`}}>{line}</div>
					</div>
				))}
			</div>
			<AbsoluteFill style={{background: '#000', opacity: k(f, OUTRO - 10, OUTRO)}} />
		</AbsoluteFill>
	);
};

export const Demo: React.FC = () => (
	<AbsoluteFill style={{background: '#000'}}>
		<Sequence from={S_INTRO} durationInFrames={INTRO + 10}>
			<IntroSlot />
		</Sequence>
		<Sequence from={S_FIELD} durationInFrames={FIELD + 8}>
			<Field />
		</Sequence>
		<Sequence from={S_SCREEN} durationInFrames={SCREEN_LEN}>
			<Screen />
		</Sequence>
		<Sequence from={S_OUTRO} durationInFrames={OUTRO}>
			<Outro />
		</Sequence>
	</AbsoluteFill>
);

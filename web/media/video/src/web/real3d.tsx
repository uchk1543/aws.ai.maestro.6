// 새 발표 영상의 3D 장면 (실사 질감 Blender 렌더 위에 흰 카드 글자).
// 영상: public/real/<장면>.mp4, 24fps, 1920×1080 (blender/real_port/render_shots.sh 의 네 구간)
//   opening 1-150 입항 · unload 150-270 하역 · gate 300-470 검사·반출 · outro 470-650 항구 전체
import React from 'react';
import {Video} from '@remotion/media';
import {AbsoluteFill, staticFile, useCurrentFrame} from 'remotion';
import {ap, Count, Pop, Rise, Scene} from '../ui';
import {Card, Pill} from './ui';
import {W} from './theme';

type Shot = 'opening' | 'unload' | 'gate' | 'outro';
const FRAMES: Record<Shot, number> = {opening: 150, unload: 121, gate: 171, outro: 181};

/** 렌더 길이를 장면 길이에 맞춰 재생 속도를 정한다 (24fps 영상, 30fps 장면) */
const RealBg: React.FC<{shot: Shot; dur: number}> = ({shot, dur}) => (
	<AbsoluteFill>
		<Video src={staticFile(`real/${shot}.mp4`)} muted objectFit="cover" playbackRate={FRAMES[shot] / 24 / (dur / 30)} style={{width: '100%', height: '100%'}} />
	</AbsoluteFill>
);

const glass: React.CSSProperties = {background: 'rgba(255,255,255,0.94)', boxShadow: '0 18px 50px rgba(0,0,0,0.18)', border: 'none'};

/* 오프닝: 배가 들어온다 */
export const Open3D: React.FC<{dur: number}> = ({dur}) => {
	const stats = [
		{v: 2488, unit: '만 TEU', label: '2025 부산항 컨테이너 물동량'},
		{v: 1078, unit: '만 TEU', label: '그중 수출입 화물 · 우리 대상은 수입'},
		{v: 57, unit: '%', label: '환적 화물 · 수입신고 없음 (대상 제외)'},
	];
	return (
		<Scene dur={dur}>
			<RealBg shot="opening" dur={dur} />
			<Rise at={18} style={{position: 'absolute', left: 96, top: 150}}>
				<Card style={{...glass, padding: '36px 44px', width: 940}}>
					<div style={{fontSize: 24, fontWeight: 700, color: W.muted}}>부산항 신항 · 컨테이너 터미널</div>
					<div style={{fontSize: 80, fontWeight: 800, letterSpacing: -2, lineHeight: 1.12, marginTop: 10}}>
						부산항 수입 서류,
						<br />
						입항 전에 바로잡는다
					</div>
					<div style={{fontSize: 28, color: W.muted, marginTop: 16}}>사진 한 장으로 시작하는 문서 자동화 Agent</div>
				</Card>
			</Rise>
			<div style={{position: 'absolute', left: 96, bottom: 96, display: 'flex', gap: 18}}>
				{stats.map((s, i) => (
					<Rise key={s.label} at={70 + i * 10}>
						<Card style={{...glass, width: 380, padding: '20px 26px'}}>
							<div style={{fontSize: 48, fontWeight: 800}}>
								<Count to={s.v} at={70 + i * 10} />
								<span style={{fontSize: 24, marginLeft: 6, color: W.muted}}>{s.unit}</span>
							</div>
							<div style={{fontSize: 19, color: W.muted, marginTop: 2}}>{s.label}</div>
						</Card>
					</Rise>
				))}
				<Rise at={100} style={{alignSelf: 'flex-end', color: '#fff', fontSize: 16, textShadow: '0 1px 6px rgba(0,0,0,0.6)'}}>
					자료: 해양수산부 2025년 전국 무역항 컨테이너 물동량
				</Rise>
			</div>
		</Scene>
	);
};

/* 하역: 컨테이너가 내려오기 전에 서류를 끝낸다 */
export const Unload3D: React.FC<{dur: number}> = ({dur}) => (
	<Scene dur={dur}>
		<RealBg shot="unload" dur={dur} />
		<Rise at={10} style={{position: 'absolute', left: 96, top: 140}}>
			<Card style={{...glass, padding: '28px 36px', width: 860}}>
				<Pill dark>D-3 · 입항 전</Pill>
				<div style={{fontSize: 54, fontWeight: 800, letterSpacing: -1.2, marginTop: 14, lineHeight: 1.18}}>
					서류는 화물보다 먼저 온다
				</div>
				<div style={{fontSize: 25, color: W.muted, marginTop: 10}}>컨테이너가 크레인에 오르기 전에, 서류 대조를 끝낸다</div>
			</Card>
		</Rise>
	</Scene>
);

/* 반출: 영상 시간에 맞춰 통관 단계를 짚는다 (대시보드 G17 과 같은 칩) */
const GATE_STAGES: [string, number][] = [
	['입항', -1],
	['수입신고', -1],
	['심사 중', 0],
	['검사 중', 3],
	['수리', 4.5],
	['반출', 6],
];

export const Gate3D: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const t = f / 30;
	let now = 2;
	GATE_STAGES.forEach(([, from], i) => {
		if (from >= 0 && t >= from) now = i;
	});
	return (
		<Scene dur={dur}>
			<RealBg shot="gate" dur={dur} />
			<Rise at={8} style={{position: 'absolute', left: 96, top: 140, display: 'flex', gap: 8}}>
				{GATE_STAGES.map(([name], i) => (
					<span
						key={name}
						style={{
							display: 'inline-flex',
							alignItems: 'center',
							gap: 8,
							height: 46,
							padding: '0 18px',
							borderRadius: 999,
							fontSize: 21,
							fontWeight: 700,
							background: i === now ? W.ink : 'rgba(255,255,255,0.94)',
							color: i === now ? '#fff' : i < now ? W.ink : W.muted,
							boxShadow: '0 6px 20px rgba(0,0,0,0.15)',
						}}
					>
						<span style={{width: 9, height: 9, borderRadius: 9, background: 'currentColor', opacity: i <= now ? 1 : 0.4}} />
						{name}
					</span>
				))}
			</Rise>
			<Rise at={16} style={{position: 'absolute', left: 96, bottom: 96}}>
				<Card style={{...glass, padding: '26px 34px', width: 820}}>
					<Pill>입항 당일</Pill>
					<div style={{fontSize: 46, fontWeight: 800, letterSpacing: -1, marginTop: 12}}>서류가 끝나 있으니, 화물은 멈추지 않는다</div>
					<div style={{fontSize: 23, color: W.muted, marginTop: 8}}>검사대를 지나 게이트에서 바로 반출</div>
				</Card>
			</Rise>
		</Scene>
	);
};

/* 마무리: 항구 전체 위에 요약 */
export const Outro3D: React.FC<{dur: number}> = ({dur}) => {
	const req = ['OCR·핵심 항목 추출', '문서 분류·교차 검증', 'HS 코드·신고서 초안', 'WMS 연동', '자연어 현황 조회'];
	const arch = ['웹 · 모바일', 'S3', 'API · 처리 Lambda', 'Strands Agent · Claude', 'Textract · DynamoDB · 가상 WMS'];
	return (
		<Scene dur={dur}>
			<RealBg shot="outro" dur={dur} />
			<AbsoluteFill style={{background: 'linear-gradient(rgba(255,255,255,0.0) 0%, rgba(255,255,255,0.0) 40%, rgba(255,255,255,0.0) 100%)'}} />
			<div style={{position: 'absolute', left: 0, right: 0, top: 150, display: 'flex', justifyContent: 'center'}}>
				<Rise at={8}>
					<Card style={{...glass, padding: '40px 56px', width: 1500, textAlign: 'center'}}>
						<div style={{fontSize: 24, fontWeight: 700, color: W.muted}}>6팀 · AI 기반 첨단물류 문서 자동화 Agent</div>
						<div style={{fontSize: 70, fontWeight: 800, letterSpacing: -2, marginTop: 10}}>추출을 넘어, 신고 전에 틀린 것을 잡는다</div>
						<div style={{display: 'flex', justifyContent: 'center', gap: 12, marginTop: 28}}>
							{req.map((r, i) => (
								<Pop key={r} at={34 + i * 7}>
									<Pill dark style={{fontSize: 21, height: 46}}>
										✓ {r}
									</Pill>
								</Pop>
							))}
						</div>
						<div style={{display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 10, marginTop: 26}}>
							{arch.map((a, i) => (
								<React.Fragment key={a}>
									<Rise at={80 + i * 6}>
										<span style={{display: 'inline-block', padding: '12px 18px', borderRadius: 14, background: W.fill2, border: `1px solid ${W.line}`, fontSize: 20, fontWeight: 700}}>{a}</span>
									</Rise>
									{i < arch.length - 1 ? <span style={{color: W.muted, fontSize: 24}}>→</span> : null}
								</React.Fragment>
							))}
						</div>
						<Rise at={110} style={{fontSize: 17, color: W.muted, marginTop: 22}}>
							영상 속 서류·화물·회사는 모두 합성 데이터(가상 회사)입니다 · 2026 AWS AI 마에스트로 해커톤
						</Rise>
					</Card>
				</Rise>
			</div>
		</Scene>
	);
};

export {ap};

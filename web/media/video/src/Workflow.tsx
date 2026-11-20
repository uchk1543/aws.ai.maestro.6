import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {AgentFix, Capture, Classify, Extract, HsDeclare, Outro, Problem, Query, SceneBackdrop, SystemSync, Validate} from './scenes';
import {BlenderField, BlenderGate, BlenderIntro} from './blender';
import {C, FONT, loadLocalFont} from './theme';
import {ap} from './ui';

loadLocalFont();

// [컴포넌트, 길이(프레임), 진행 단계 번호(-1이면 숨김), D-day 표시]
const PLAN: [React.FC<{dur: number}>, number, number, string][] = [
	[BlenderIntro, 240, -1, ''],
	[Problem, 210, -1, ''],
	[BlenderField, 240, 0, 'D-3 · 입항 전'],
	[Capture, 270, 0, 'D-3 · 입항 전'],
	[Classify, 210, 1, 'D-3 · 입항 전'],
	[Extract, 300, 2, 'D-3 · 입항 전'],
	[Validate, 330, 3, 'D-3 · 입항 전'],
	[AgentFix, 330, 4, 'D-3 · 입항 전'],
	[HsDeclare, 300, 5, 'D-3 · 입항 전'],
	[SystemSync, 300, 6, 'D-3 · 입항 전'],
	[BlenderGate, 210, 6, '입항 당일 · 반출'],
	[Query, 270, 6, '입항 후 · 이번 주'],
	[Outro, 210, -1, ''],
];

export const TOTAL = PLAN.reduce((s, p) => s + p[1], 0);
const STARTS = PLAN.reduce<number[]>((acc, p, i) => [...acc, i === 0 ? 0 : acc[i - 1] + PLAN[i - 1][1]], []);
const STEPS = ['촬영·전송', '문서 분류', '항목 추출', '교차 검증', '설명·정정', 'HS·신고서', '연동·조회'];

const current = (f: number) => {
	let idx = 0;
	STARTS.forEach((s, i) => {
		if (f >= s) idx = i;
	});
	return idx;
};

const Header: React.FC = () => {
	const f = useCurrentFrame();
	const idx = current(f);
	const day = PLAN[idx][3];
	return (
		<div style={{position: 'absolute', left: 96, right: 96, top: 42, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
			<div style={{display: 'flex', alignItems: 'baseline', gap: 18}}>
				<span style={{color: C.accent, fontSize: 20, fontWeight: 800, letterSpacing: 3}}>06 / SMART LOGISTICS</span>
				<span style={{color: C.sub, fontSize: 20}}>AI 기반 첨단물류 문서 자동화 Agent · 6팀</span>
			</div>
			{day ? (
				<span
					style={{
						padding: '8px 20px',
						borderRadius: 999,
						fontSize: 21,
						fontWeight: 800,
						color: day.startsWith('D-3') ? C.bg : C.text,
						background: day.startsWith('D-3') ? C.accent : C.blue + '33',
						border: `1.5px solid ${day.startsWith('D-3') ? C.accent : C.blue}`,
					}}
				>
					{day}
				</span>
			) : null}
		</div>
	);
};

const StepBar: React.FC = () => {
	const f = useCurrentFrame();
	const idx = current(f);
	const step = PLAN[idx][2];
	const visible = step >= 0 ? 1 : 0;
	const o = visible * Math.min(ap(f, STARTS[2], 16), 1 - ap(f, STARTS[PLAN.length - 1] - 10, 10));
	return (
		<div style={{position: 'absolute', left: 96, right: 96, bottom: 34, display: 'flex', gap: 10, opacity: o}}>
			{STEPS.map((s, i) => {
				const done = i < step;
				const on = i === step;
				return (
					<div key={s} style={{flex: 1}}>
						<div style={{height: 6, borderRadius: 6, background: done ? C.teal : on ? C.accent : C.line}} />
						<div style={{marginTop: 8, fontSize: 18, fontWeight: on ? 800 : 500, color: on ? C.text : done ? C.teal : C.dim}}>
							{i + 1}. {s}
						</div>
					</div>
				);
			})}
		</div>
	);
};

export const Workflow: React.FC = () => (
	<AbsoluteFill style={{fontFamily: `'${FONT}', 'Noto Sans KR', 'Malgun Gothic', sans-serif`, color: C.text}}>
		<SceneBackdrop />
		{PLAN.map(([Comp, dur], i) => (
			<Sequence key={i} from={STARTS[i]} durationInFrames={dur}>
				<Comp dur={dur} />
			</Sequence>
		))}
		<Header />
		<StepBar />
	</AbsoluteFill>
);

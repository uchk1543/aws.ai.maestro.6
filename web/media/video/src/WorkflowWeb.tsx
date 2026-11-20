// 새 발표 영상: 3D 는 실사 질감 부산항(입항 → 하역 → 반출 → 전경), 2D 는 웹 앱과 같은 디자인.
import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {ap} from './ui';
import {Open3D, Outro3D, Unload3D, Gate3D} from './web/real3d';
import {AgentFixW, ClassifyW, ExtractW, HsDeclareW, ProblemW, QueryW, SystemSyncW, UploadW, ValidateW} from './web/scenes';
import {StepRow} from './web/ValidateWeb';
import {AppBar, Pill} from './web/ui';
import {W, WFONT, loadPretendard} from './web/theme';

loadPretendard();

// [컴포넌트, 길이(프레임 30fps), 진행 단계(-1 숨김), D-day, 앱 메뉴(3D 는 '')]
const PLAN: [React.FC<{dur: number}>, number, number, string, string][] = [
	[Open3D, 210, -1, '', ''],
	[ProblemW, 210, -1, '', '문서 분류 내역'],
	[Unload3D, 150, -1, '', ''],
	[UploadW, 240, 0, 'D-3 · 입항 전', '파일 업로드'],
	[ClassifyW, 210, 1, 'D-3 · 입항 전', '문서 분류 내역'],
	[ExtractW, 270, 2, 'D-3 · 입항 전', '문서 분류 내역'],
	[ValidateW, 300, 3, 'D-3 · 입항 전', '문서 분류 내역'],
	[AgentFixW, 300, 4, 'D-3 · 입항 전', '문서 분류 내역'],
	[HsDeclareW, 300, 5, 'D-3 · 입항 전', '문서 분류 내역'],
	[SystemSyncW, 270, 6, 'D-3 · 입항 전', '대시보드'],
	[Gate3D, 210, -1, '', ''],
	[QueryW, 270, -1, '입항 후 · 이번 주', 'AI chat'],
	[Outro3D, 240, -1, '', ''],
];

export const TOTAL_WEB = PLAN.reduce((s, p) => s + p[1], 0);
const STARTS = PLAN.reduce<number[]>((acc, p, i) => [...acc, i === 0 ? 0 : acc[i - 1] + PLAN[i - 1][1]], []);
const at = (f: number) => {
	let idx = 0;
	STARTS.forEach((s, i) => {
		if (f >= s) idx = i;
	});
	return idx;
};

/** 2D 장면 머리: 앱 메뉴(왼쪽) + D-day(오른쪽). 장면이 바뀔 때 부드럽게 */
const Header: React.FC = () => {
	const f = useCurrentFrame();
	const i = at(f);
	const [, dur, , day, menu] = PLAN[i];
	if (!menu) return null;
	const o = Math.min(ap(f, STARTS[i], 10), 1 - ap(f, STARTS[i] + dur - 10, 10));
	const keep = i > 0 && PLAN[i - 1][4] !== '' ? 1 : o;
	return (
		<div style={{position: 'absolute', left: 96, right: 96, top: 44, display: 'flex', justifyContent: 'space-between', alignItems: 'center', opacity: keep}}>
			<AppBar active={menu} />
			{day ? <Pill dark>{day}</Pill> : null}
		</div>
	);
};

const Steps: React.FC = () => {
	const f = useCurrentFrame();
	const i = at(f);
	const step = PLAN[i][2];
	if (step < 0) return null;
	return (
		<div style={{position: 'absolute', left: 96, right: 96, bottom: 40}}>
			<StepRow step={step} />
		</div>
	);
};

export const WorkflowWeb: React.FC = () => (
	<AbsoluteFill style={{fontFamily: `'${WFONT}', 'Malgun Gothic', sans-serif`, color: W.ink, background: W.bg}}>
		{PLAN.map(([Comp, dur], i) => (
			<Sequence key={i} from={STARTS[i]} durationInFrames={dur}>
				<Comp dur={dur} />
			</Sequence>
		))}
		<Header />
		<Steps />
	</AbsoluteFill>
);

// 2D 시안: 교차 검증 장면을 웹 화면 스타일로 (왼쪽 서류 원본 + 박스, 오른쪽 오류 카드와 읽은 칸 표)
import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame} from 'remotion';
import data from '../data.json';
import {ap, fmt, Rise} from '../ui';
import {AppBar, Card, Fill, Mono, Pill} from './ui';
import {W, WFONT, loadPretendard} from './theme';

loadPretendard();
const K = (data as any).checks;

const STEPS = ['촬영·전송', '문서 분류', '항목 추출', '교차 검증', '설명·정정', 'HS·신고서', '연동·조회'];

export const StepRow: React.FC<{step: number}> = ({step}) => (
	<div style={{display: 'flex', gap: 8}}>
		{STEPS.map((s, i) => (
			<div key={s} style={{flex: 1}}>
				<div style={{height: 5, borderRadius: 5, background: i < step ? W.ink2 : i === step ? W.ink : W.line}} />
				<div style={{marginTop: 8, fontSize: 17, fontWeight: i === step ? 800 : 500, color: i === step ? W.ink : i < step ? W.ink2 : W.muted}}>
					{i + 1}. {s}
				</div>
			</div>
		))}
	</div>
);

export const ValidateWeb: React.FC = () => {
	const f = useCurrentFrame();
	const box = ap(f, 70, 16);
	const rows: [string, string, boolean][] = [
		['송장 번호', 'SHE-2026-0214', false],
		['총수량', '1,240 CTNS', false],
		['총중량', `${fmt(K.plGrossPrinted, 2)} KG`, true],
		['총포장갯수', '62 PLTS', false],
	];
	return (
		<AbsoluteFill style={{background: W.bg, fontFamily: `'${WFONT}', sans-serif`, color: W.ink}}>
			<div style={{position: 'absolute', left: 96, right: 96, top: 44, display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
				<AppBar active="문서 분류 내역" />
				<Pill dark>D-3 · 입항 전</Pill>
			</div>

			<div style={{position: 'absolute', left: 96, top: 136}}>
				<Rise at={4}>
					<div style={{fontSize: 22, fontWeight: 700, color: W.muted}}>4단계 · 서류끼리 대조</div>
				</Rise>
				<Rise at={10}>
					<div style={{fontSize: 58, fontWeight: 800, letterSpacing: -1.5, marginTop: 6}}>판정은 규칙 코드가 한다</div>
				</Rise>
			</div>

			{/* 왼쪽: 서류 원본, 불일치 칸에 빨간 박스 */}
			<Rise at={18} style={{position: 'absolute', left: 96, top: 290, width: 760}}>
				<Card style={{padding: 18}}>
					<div style={{display: 'flex', gap: 8, marginBottom: 12}}>
						<Pill dark style={{height: 36, fontSize: 18}}>포장명세서 1</Pill>
						<Pill style={{height: 36, fontSize: 18}}>선하증권 1</Pill>
						<Pill style={{height: 36, fontSize: 18}}>상업송장</Pill>
					</div>
					<div style={{position: 'relative', background: W.fill2, borderRadius: 12, overflow: 'hidden', height: 560}}>
						<Img src={staticFile('docs/pl.png')} style={{width: '100%', display: 'block'}} />
						<div
							style={{
								position: 'absolute',
								left: '72.6%',
								top: '51.2%',
								width: '10.6%',
								height: '4.2%',
								border: `3px solid ${W.red}`,
								borderRadius: 6,
								opacity: box,
								transform: `scale(${1.25 - 0.25 * box})`,
								boxShadow: `0 0 0 ${9999 * box}px rgba(20,20,20,${0.06 * box})`,
							}}
						/>
					</div>
				</Card>
			</Rise>

			{/* 오른쪽: 오류 카드 + 읽은 칸 표 (작업 화면 G11·G12 와 같은 모양) */}
			<div style={{position: 'absolute', left: 900, right: 96, top: 290}}>
				<Rise at={60} x={30} y={0}>
					<Card style={{border: `1.5px solid ${W.ink}`, padding: '22px 26px'}}>
						<div style={{display: 'flex', alignItems: 'center', gap: 12}}>
							<Pill red style={{height: 34, fontSize: 17}}>불일치</Pill>
							<span style={{fontSize: 24, fontWeight: 700}}>선하증권 총중량과 포장명세서 총중량이 다릅니다</span>
						</div>
						<div style={{display: 'flex', gap: 12, marginTop: 18}}>
							<Fill style={{flex: 1, background: W.ink2, color: '#fff'}}>
								<div style={{fontSize: 17, color: '#c9c9c9'}}>포장명세서 · 다른 쪽</div>
								<Mono style={{fontSize: 34, fontWeight: 800}}>{fmt(K.plGrossPrinted, 2)}</Mono>
							</Fill>
							<Fill style={{flex: 1}}>
								<div style={{fontSize: 17, color: W.muted}}>선하증권</div>
								<Mono style={{fontSize: 34, fontWeight: 800}}>{fmt(K.blGross, 2)}</Mono>
							</Fill>
						</div>
						<div style={{fontSize: 17, color: W.muted, marginTop: 12}}>
							규칙 <Mono>X-WT-01</Mono> · Textract OCR로 다시 확인 · 품목 합계 {fmt(K.plGrossLineSum, 2)} → 자릿수 뒤바뀜 의심
						</div>
					</Card>
				</Rise>
				<Rise at={110} x={30} y={0} style={{marginTop: 22}}>
					<div style={{fontSize: 19, fontWeight: 700, marginBottom: 8}}>
						읽은 칸 · 포장명세서 <span style={{color: W.muted, fontWeight: 500}}>4칸, 빨간 줄이 불일치</span>
					</div>
					<div>
						{rows.map(([k, v, bad], i) => (
							<div
								key={k}
								style={{
									display: 'flex',
									padding: '14px 16px',
									borderBottom: `1px solid ${W.line}`,
									fontSize: 21,
									background: bad ? W.redSoft : 'transparent',
									boxShadow: bad ? `inset 4px 0 0 ${W.red}` : 'none',
									opacity: ap(f, 116 + i * 6, 10),
								}}
							>
								<span style={{width: 220, fontWeight: 700}}>{k}</span>
								<Mono>{v}</Mono>
							</div>
						))}
					</div>
				</Rise>
			</div>

			<div style={{position: 'absolute', left: 96, right: 96, bottom: 40}}>
				<StepRow step={3} />
			</div>
		</AbsoluteFill>
	);
};

import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import data from './data.json';
import {C, MONO} from './theme';
import {ap, Chip, clamp, Count, DocView, DocImg, ease, fmt, Icon, Mono, Panel, Pop, rand, Rise, Scene, SceneTitle, Type} from './ui';
import {BlenderOutroBg} from './blender';

const D = data as any;
const IM = D.images as Record<string, DocImg>;
const S = D.shipment;
const K = D.checks;
const L = D.logistics;
const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
const failed = new Set((K.findings as [string, string][]).map(([r]) => r));

/* ------------------------------------------------------------------ */
/* 배경 항만 실루엣                                                     */
/* ------------------------------------------------------------------ */
const CONTAINER_COLORS = ['#c2410c', '#0f766e', '#1d4ed8', '#9f1239', '#a16207', '#475569'];

const PortSkyline: React.FC<{f: number}> = ({f}) => {
	const ship = interpolate(f, [0, 180], [-700, 260], clamp);
	const stacks = [];
	for (let i = 0; i < 46; i++) {
		const x = 40 + i * 41;
		const n = 1 + Math.floor(rand(i) * 4);
		for (let j = 0; j < n; j++) {
			const p = ap(f, 4 + i * 0.6 + j * 3, 16);
			stacks.push(
				<rect
					key={`${i}-${j}`}
					x={x}
					y={330 - (j + 1) * 26 + (1 - p) * 40}
					width={38}
					height={24}
					rx={2}
					fill={CONTAINER_COLORS[Math.floor(rand(i * 7 + j) * 6)]}
					opacity={0.55 * p}
				/>,
			);
		}
	}
	const cranes = [260, 760, 1280, 1700].map((cx, i) => {
		const trolley = cx - 120 + ((f * (1.2 + i * 0.3)) % 240);
		return (
			<g key={cx} stroke="#33507a" strokeWidth={6} fill="none" opacity={0.9}>
				<path d={`M${cx - 50} 330 L${cx - 40} 90 L${cx + 40} 90 L${cx + 50} 330`} />
				<path d={`M${cx - 180} 90 L${cx + 220} 90`} strokeWidth={8} />
				<path d={`M${cx - 40} 90 L${cx} 30 L${cx + 40} 90`} />
				<rect x={trolley} y={84} width={30} height={14} fill="#f59e0b" stroke="none" />
				<line x1={trolley + 15} y1={98} x2={trolley + 15} y2={150} strokeWidth={2} stroke="#f59e0b" />
			</g>
		);
	});
	return (
		<svg width={1920} height={420} viewBox="0 0 1920 420" style={{position: 'absolute', left: 0, bottom: 0}}>
			<defs>
				<linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
					<stop offset="0" stopColor="#10284a" />
					<stop offset="1" stopColor="#0a1120" />
				</linearGradient>
			</defs>
			{cranes}
			{stacks}
			<rect x={0} y={330} width={1920} height={90} fill="url(#water)" />
			<g transform={`translate(${ship} 0)`} opacity={0.95}>
				<path d="M0 318 L520 318 L490 362 L40 362 Z" fill="#1e3a5f" />
				{[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((k) => (
					<rect key={k} x={60 + k * 40} y={292} width={36} height={24} rx={2} fill={CONTAINER_COLORS[k % 6]} opacity={0.8} />
				))}
				<rect x={430} y={262} width={50} height={56} fill="#2b4a73" />
			</g>
			{[0, 1, 2, 3, 4, 5].map((k) => (
				<line key={k} x1={0} x2={1920} y1={346 + k * 12} y2={346 + k * 12} stroke="#1e3a5f" strokeWidth={1} opacity={0.4} />
			))}
		</svg>
	);
};

/* ------------------------------------------------------------------ */
/* S1. 오프닝                                                          */
/* ------------------------------------------------------------------ */
export const Intro: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const stats = [
		{v: 2488, unit: '만 TEU', label: '2025 부산항 컨테이너 물동량'},
		{v: 1078, unit: '만 TEU', label: '그중 수출입 화물 · 우리 대상은 수입'},
		{v: 57, unit: '%', label: '환적 화물 · 수입신고 없음 (대상 제외)'},
	];
	return (
		<Scene dur={dur}>
			<PortSkyline f={f} />
			<div style={{position: 'absolute', left: 120, top: 170}}>
				<Rise at={8}>
					<div style={{color: C.accent, fontSize: 26, fontWeight: 800, letterSpacing: 4}}>부산항 수입 물류 · 6팀</div>
				</Rise>
				<Rise at={16}>
					<div style={{fontSize: 96, fontWeight: 900, color: C.text, letterSpacing: -2, marginTop: 18, lineHeight: 1.1}}>
						부산항 수입 서류,
					</div>
				</Rise>
				<Rise at={26}>
					<div style={{fontSize: 96, fontWeight: 900, color: C.text, letterSpacing: -2, lineHeight: 1.15}}>
						<span style={{color: C.accent}}>입항 전에</span> 바로잡는다
					</div>
				</Rise>
				<Rise at={38}>
					<div style={{fontSize: 32, color: C.sub, marginTop: 22, fontWeight: 500}}>
						현장 사진 한 장으로 시작하는 문서 자동화 Agent
					</div>
				</Rise>
			</div>
			<div style={{position: 'absolute', left: 120, top: 530, display: 'flex', gap: 28}}>
				{stats.map((s, i) => (
					<Rise key={s.label} at={64 + i * 12}>
						<Panel style={{width: 430, padding: '22px 28px', background: '#0f1a2ecc'}}>
							<div style={{fontSize: 52, fontWeight: 900, color: i === 2 ? C.sub : C.text}}>
								<Count to={s.v} at={64 + i * 12} />
								<span style={{fontSize: 28, marginLeft: 6, color: C.sub}}>{s.unit}</span>
							</div>
							<div style={{fontSize: 21, color: C.sub, marginTop: 4}}>{s.label}</div>
						</Panel>
					</Rise>
				))}
			</div>
			<Rise at={100} style={{position: 'absolute', left: 124, top: 690, color: C.dim, fontSize: 17}}>
				자료: 해양수산부 2025년 전국 무역항 컨테이너 물동량 발표
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S2. 문제                                                            */
/* ------------------------------------------------------------------ */
export const Problem: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const docs = [
		{img: IM.bl, label: 'B/L (선하증권)', boxes: [{key: 'gross', at: 70}]},
		{img: IM.invoice, label: 'Commercial Invoice', boxes: [{key: 'total', at: 82}]},
		{img: IM.pl, label: 'Packing List', boxes: [{key: 'gross_total', at: 76}]},
		{img: IM.co, label: '원산지증명서', boxes: [{key: 'hs', at: 88}]},
	];
	const pains = [
		['같은 값을 서류마다 다시 입력', '품명·수량·중량·포장 수가 4종에 반복된다'],
		['숫자 하나만 틀려도 화물이 멈춘다', '세관 보완 요구 · 통관 보류 · 적하목록 정정'],
		['반출이 늦어질수록 비용이 쌓인다', '터미널 보관료 · 선사 체화료 (컨테이너·일 단위)'],
	];
	return (
		<Scene dur={dur}>
			<SceneTitle step="문제" title="사람이 서류 4종을 손으로 대조한다" sub="같은 정보가 문서마다 반복되고, 하나라도 틀리면 통관이 늦어진다" />
			<div style={{position: 'absolute', left: 96, top: 330, display: 'flex', gap: 22}}>
				{docs.map((d, i) => {
					const p = ap(f, 20 + i * 8, 20);
					return (
						<div key={d.label} style={{opacity: p, transform: `translateY(${(1 - p) * 60}px) rotate(${(i - 1.5) * 1.6}deg)`}}>
							<DocView img={d.img} width={230} boxes={d.boxes as any} />
							<div style={{color: C.sub, fontSize: 20, marginTop: 14, textAlign: 'center'}}>{d.label}</div>
						</div>
					);
				})}
			</div>
			<Pop at={100} style={{position: 'absolute', left: 300, top: 760}}>
				<Chip color={C.red}>같은 값일까? 사람이 눈으로 비교</Chip>
			</Pop>
			<div style={{position: 'absolute', left: 1160, top: 330, width: 664, display: 'flex', flexDirection: 'column', gap: 22}}>
				{pains.map(([t, s], i) => (
					<Rise key={t} at={60 + i * 22} x={40} y={0}>
						<Panel style={{padding: '22px 28px'}}>
							<div style={{fontSize: 29, fontWeight: 800, color: C.text}}>{t}</div>
							<div style={{fontSize: 21, color: C.sub, marginTop: 6}}>{s}</div>
						</Panel>
					</Rise>
				))}
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S3. 현장 촬영·전송                                                   */
/* ------------------------------------------------------------------ */
const Phone: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<div
		style={{
			width: 400,
			height: 800,
			borderRadius: 56,
			background: '#05080f',
			border: '3px solid #2a3b58',
			padding: 16,
			boxShadow: '0 40px 90px #000c',
			...style,
		}}
	>
		<div style={{position: 'relative', width: '100%', height: '100%', borderRadius: 42, overflow: 'hidden', background: C.bg2}}>
			{children}
		</div>
	</div>
);

export const Capture: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const shot = 104;
	const flash = interpolate(f, [shot, shot + 3, shot + 14], [0, 1, 0], clamp);
	const camera = f < shot + 8;
	const zoom = interpolate(f, [0, shot], [1.35, 1.15], clamp);
	const detect = ap(f, 62, 12);
	const files = [
		{name: 'packing_list.jpg', kind: '사진', at: 128},
		{name: 'bl.jpg', kind: '사진', at: 138},
		{name: 'invoice.pdf', kind: 'PDF', at: 148},
		{name: 'certificate_of_origin.pdf', kind: 'PDF', at: 158},
	];
	const steps = [
		['촬영하면 문서 영역을 자동으로 잘라낸다', '기울기·그림자가 있어도 괜찮다'],
		['사진과 PDF를 한 번에 전송', 'presigned URL로 Amazon S3에 바로 업로드'],
		['도착하는 순간 Agent가 처리 시작', '분류 → 추출 → 검증까지 자동'],
	];
	return (
		<Scene dur={dur}>
			<SceneTitle step="STEP 1 · 촬영·전송" title="찍은 서류는 그 자리에서 클라우드로" sub="사진, 스캔본, PDF 무엇이든 (과제 기능 ①)" />
			<div style={{position: 'absolute', left: 96, top: 330, width: 900, display: 'flex', flexDirection: 'column', gap: 20}}>
				{steps.map(([t, s], i) => (
					<Rise key={t} at={30 + i * 40} x={-30} y={0}>
						<div style={{display: 'flex', gap: 22, alignItems: 'flex-start'}}>
							<div
								style={{
									width: 54,
									height: 54,
									borderRadius: 54,
									background: `${C.accent}22`,
									border: `2px solid ${C.accent}`,
									color: C.accent,
									fontSize: 26,
									fontWeight: 900,
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									flexShrink: 0,
								}}
							>
								{i + 1}
							</div>
							<div>
								<div style={{fontSize: 32, fontWeight: 800, color: C.text}}>{t}</div>
								<div style={{fontSize: 22, color: C.sub, marginTop: 4}}>{s}</div>
							</div>
						</div>
					</Rise>
				))}
				<Rise at={170} style={{marginTop: 26}}>
					<Panel style={{padding: '20px 26px', display: 'flex', gap: 26, alignItems: 'center'}}>
						<Chip color={C.sub}>선적 {md(S.onBoard)}</Chip>
						<span style={{color: C.dim, fontSize: 26}}>→</span>
						<Chip color={C.accent} solid>
							서류 도착 {md(L.baseDate)} · 지금
						</Chip>
						<span style={{color: C.dim, fontSize: 26}}>→</span>
						<Chip color={C.blue}>부산 입항 예정 {md(L.demo.eta)}</Chip>
					</Panel>
				</Rise>
			</div>
			<Rise at={6} x={60} y={0} style={{position: 'absolute', left: 1300, top: 190}}>
				<Phone>
					{camera ? (
						<>
							<Img
								src={staticFile('docs/scan_pl.jpg')}
								style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${zoom})`}}
							/>
							<div style={{position: 'absolute', inset: 0, background: 'linear-gradient(#0008, transparent 25%, transparent 70%, #000a)'}} />
							{/* 문서 인식 프레임 */}
							<div
								style={{
									position: 'absolute',
									left: 34,
									top: 120,
									width: 300,
									height: 440,
									border: `4px solid ${C.teal}`,
									borderRadius: 12,
									opacity: detect,
									transform: `scale(${1.15 - detect * 0.15})`,
								}}
							/>
							<div style={{position: 'absolute', top: 30, width: '100%', textAlign: 'center', color: '#fff', fontSize: 20, fontWeight: 700}}>
								{f < 62 ? '문서를 화면에 맞춰 주세요' : '문서 인식됨 · Packing List'}
							</div>
							<div
								style={{
									position: 'absolute',
									bottom: 34,
									left: '50%',
									marginLeft: -40,
									width: 80,
									height: 80,
									borderRadius: 80,
									border: '6px solid #fff',
									background: f > shot - 10 ? C.accent : '#ffffff55',
								}}
							/>
						</>
					) : (
						<div style={{padding: '46px 24px', color: C.text}}>
							<div style={{fontSize: 16, color: C.accent, fontWeight: 800, letterSpacing: 2}}>서류 전송</div>
							<div style={{fontSize: 24, fontWeight: 800, marginTop: 6}}>B/L {S.blNo}</div>
							<div style={{fontSize: 17, color: C.sub, marginTop: 4}}>{S.consignee}</div>
							<div style={{marginTop: 30, display: 'flex', flexDirection: 'column', gap: 16}}>
								{files.map((x) => {
									const p = ap(f, x.at, 40);
									return (
										<div key={x.name} style={{background: C.panel2, borderRadius: 16, padding: '14px 16px', opacity: ap(f, x.at - 12, 10)}}>
											<div style={{display: 'flex', justifyContent: 'space-between', fontSize: 17}}>
												<span style={{fontWeight: 700}}>{x.name}</span>
												<span style={{color: C.sub}}>{x.kind}</span>
											</div>
											<div style={{height: 8, background: C.line, borderRadius: 8, marginTop: 10, overflow: 'hidden'}}>
												<div style={{width: `${p * 100}%`, height: '100%', background: p >= 1 ? C.teal : C.accent}} />
											</div>
										</div>
									);
								})}
							</div>
							<div style={{marginTop: 28, textAlign: 'center', opacity: ap(f, 205, 12), color: C.teal, fontSize: 24, fontWeight: 800}}>
								✓ 4개 전송 완료
							</div>
						</div>
					)}
					<div style={{position: 'absolute', inset: 0, background: '#fff', opacity: flash}} />
				</Phone>
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S4. 문서 분류                                                       */
/* ------------------------------------------------------------------ */
export const Classify: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const bins = [
		{key: 'bl', title: 'B/L', sub: '선하증권'},
		{key: 'invoice', title: 'Invoice', sub: '상업송장'},
		{key: 'pl', title: 'Packing List', sub: '포장명세서'},
		{key: 'co', title: 'C/O', sub: '원산지증명서'},
	];
	// 들어온 순서: 사진(PL), 사진(B/L), PDF(Invoice), PDF(C/O)
	const order = ['pl', 'bl', 'invoice', 'co'];
	const binX = (i: number) => 700 + i * 290;
	return (
		<Scene dur={dur}>
			<SceneTitle step="STEP 2 · 문서 분류" title="어떤 서류인지 먼저 가른다" sub="Bedrock Data Automation 블루프린트가 서류마다 맞는 양식을 자동으로 고른다 (과제 기능 ②)" />
			<Rise at={6} style={{position: 'absolute', left: 96, top: 360}}>
				<Panel style={{width: 470, padding: '26px 28px'}}>
					<div style={{fontSize: 22, color: C.sub}}>받은 파일</div>
					<div style={{fontSize: 40, fontWeight: 900, color: C.text, marginTop: 6}}>사진 2장 + PDF 2개</div>
					<div style={{fontSize: 21, color: C.sub, marginTop: 10, lineHeight: 1.5}}>
						파일 이름이나 형식과 상관없이
						<br />
						내용을 보고 종류를 판단한다
					</div>
				</Panel>
			</Rise>
			{bins.map((b, i) => (
				<Rise key={b.key} at={10 + i * 5} style={{position: 'absolute', left: binX(i), top: 330}}>
					<div
						style={{
							width: 260,
							height: 560,
							borderRadius: 22,
							border: `2px dashed ${C.line}`,
							background: '#0f1a2e88',
							padding: 18,
						}}
					>
						<div style={{fontSize: 24, fontWeight: 900, color: C.text}}>{b.title}</div>
						<div style={{fontSize: 19, color: C.sub}}>{b.sub}</div>
					</div>
				</Rise>
			))}
			{order.map((key, j) => {
				const i = bins.findIndex((b) => b.key === key);
				const start = 40 + j * 24;
				const p = ap(f, start, 28);
				const x = interpolate(p, [0, 1], [230 + j * 18, binX(i) + 22]);
				const y = interpolate(p, [0, 1], [640 + j * 14, 430]);
				const landed = ap(f, start + 26, 10);
				return (
					<div key={key} style={{position: 'absolute', left: x, top: y, opacity: ap(f, start - 14, 10), transform: `rotate(${(1 - p) * (j - 1.5) * 6}deg)`}}>
						<DocView img={IM[key]} width={216} crop={300} />
						<div style={{marginTop: 14, opacity: landed, transform: `scale(${0.8 + 0.2 * landed})`}}>
							<Chip color={C.teal}>✓ 분류됨</Chip>
						</div>
					</div>
				);
			})}
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S5. 항목 추출                                                       */
/* ------------------------------------------------------------------ */
export const Extract: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const rows = [
		{key: 'bl_no', label: 'B/L No.', value: S.blNo, at: 40},
		{key: 'shipper', label: 'Shipper', value: S.shipper, at: 64},
		{key: 'container', label: 'Container No.', value: K.containerPrinted, at: 88},
		{key: 'packages', label: 'Packages', value: `${fmt(S.packages)} CARTONS`, at: 112},
		{key: 'gross', label: 'Gross Weight', value: `${fmt(K.blGross, 2)} KG`, at: 136},
	];
	return (
		<Scene dur={dur}>
			<SceneTitle step="STEP 3 · 항목 추출" title="값과 함께 원본 위치를 남긴다" sub="사람이 화면에서 바로 확인할 수 있게 (과제 기능 ①)" />
			<Rise at={6} x={-40} y={0} style={{position: 'absolute', left: 96, top: 320}}>
				<DocView img={IM.bl} width={800} crop={580} boxes={rows.map((r) => ({key: r.key, at: r.at}))} />
				<div style={{color: C.sub, fontSize: 19, marginTop: 12}}>B/L 원본 · 하이라이트는 실제 추출 위치</div>
			</Rise>
			<div style={{position: 'absolute', left: 970, top: 320, width: 854}}>
				<Panel style={{padding: '18px 26px'}}>
					<div style={{fontSize: 20, color: C.accent, fontWeight: 800, letterSpacing: 2, marginBottom: 6}}>추출 결과 · B/L</div>
					{rows.map((r) => (
						<div
							key={r.key}
							style={{
								display: 'flex',
								alignItems: 'center',
								gap: 16,
								padding: '9px 0',
								borderTop: `1px solid ${C.line}`,
								opacity: ap(f, r.at + 4, 12),
								transform: `translateX(${(1 - ap(f, r.at + 4, 12)) * 30}px)`,
							}}
						>
							<div style={{width: 170, color: C.sub, fontSize: 21}}>{r.label}</div>
							<div style={{flex: 1, color: C.text, fontSize: r.value.length > 26 ? 19 : 24, fontWeight: 700}}>
								<Mono>{r.value}</Mono>
							</div>
							<Chip color={C.teal} style={{fontSize: 16, padding: '4px 12px'}}>
								원본 위치 ✓
							</Chip>
						</div>
					))}
				</Panel>
				<Rise at={180} style={{marginTop: 22, display: 'flex', gap: 22, alignItems: 'center'}}>
					<DocView img={IM.pl} width={430} crop={210} boxes={[{key: 'gross_line', at: 196, color: C.blue}, {key: 'gross_total', at: 210}]} />
					<div>
						<div style={{color: C.sub, fontSize: 20}}>Packing List에서도 같은 항목 추출</div>
						<div style={{color: C.text, fontSize: 24, marginTop: 10, opacity: ap(f, 200, 12)}}>
							품목 G.W. <Mono style={{color: C.blue, fontWeight: 700}}>{fmt(K.plGrossLineSum, 2)}</Mono>
						</div>
						<div style={{color: C.text, fontSize: 24, marginTop: 6, opacity: ap(f, 214, 12)}}>
							합계 G.W. <Mono style={{color: C.accent, fontWeight: 700}}>{fmt(K.plGrossPrinted, 2)}</Mono>
						</div>
					</div>
				</Rise>
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S6. 교차 검증                                                       */
/* ------------------------------------------------------------------ */
const RULES = [
	['gross_weight_match', '총중량 B/L ↔ Packing List'],
	['pl_gross_weight_sum', 'Packing List 품목 합계 ↔ 합계 칸'],
	['package_count_match', '포장 수 B/L ↔ Packing List'],
	['item_quantity_match', '품목 수량 Invoice ↔ Packing List'],
	['invoice_amount_sum', 'Invoice 금액 = 수량 × 단가 합계'],
	['invoice_reference_match', '서류 번호 참조 (Invoice No.)'],
	['origin_match', '원산지 Invoice ↔ 원산지증명서'],
	['customs_value_info', '과세가격 정보 (Incoterms)'],
	['container_check_digit', '컨테이너 번호 체크디지트 (ISO 6346)'],
];

export const Validate: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const cp: string = K.containerPrinted;
	const digitSpin = f < 270 ? Math.floor(rand(Math.floor(f / 3)) * 10) : K.checkDigitComputed;
	const nFail = RULES.filter(([k]) => failed.has(k)).length;
	return (
		<Scene dur={dur}>
			<SceneTitle
				step="STEP 4 · 서류 간 교차 검증"
				title="판정은 규칙 코드가 한다"
				sub={`9개 규칙을 서류 4종에 적용 · 불일치 ${nFail}건 (과제 기능 ②)`}
			/>
			<Panel style={{position: 'absolute', left: 96, top: 320, width: 780, padding: '14px 26px'}}>
				{RULES.map(([k, label], i) => {
					const at = 22 + i * 13;
					const bad = failed.has(k);
					return (
						<div
							key={k}
							style={{
								display: 'flex',
								alignItems: 'center',
								gap: 16,
								padding: '11px 0',
								borderTop: i ? `1px solid ${C.line}` : 'none',
								opacity: 0.35 + 0.65 * ap(f, at, 8),
							}}
						>
							<div style={{width: 30, opacity: ap(f, at, 8), transform: `scale(${0.5 + 0.5 * ap(f, at, 8)})`}}>
								<Icon ok={!bad} />
							</div>
							<div style={{fontSize: 23, color: bad && f > at ? C.red : C.text, fontWeight: bad ? 800 : 500}}>{label}</div>
						</div>
					);
				})}
				<div style={{display: 'flex', gap: 14, marginTop: 12, opacity: ap(f, 150, 12)}}>
					<Chip color={C.teal}>통과 {RULES.length - nFail}</Chip>
					<Chip color={C.red}>불일치 {nFail}</Chip>
				</div>
			</Panel>
			<Rise at={160} x={40} y={0} style={{position: 'absolute', left: 940, top: 320, width: 884}}>
				<Panel glow={C.red} style={{padding: '24px 30px'}}>
					<div style={{color: C.red, fontSize: 22, fontWeight: 800}}>① 총중량 불일치</div>
					<div style={{display: 'flex', alignItems: 'center', gap: 26, marginTop: 14}}>
						<div>
							<div style={{color: C.sub, fontSize: 19}}>B/L</div>
							<Mono style={{fontSize: 40, fontWeight: 800, color: C.text}}>{fmt(K.blGross, 2)}</Mono>
						</div>
						<div style={{fontSize: 52, color: C.red, fontWeight: 900}}>≠</div>
						<div>
							<div style={{color: C.sub, fontSize: 19}}>Packing List 합계 칸</div>
							<Mono style={{fontSize: 40, fontWeight: 800, color: C.red}}>{fmt(K.plGrossPrinted, 2)}</Mono>
						</div>
						<div style={{color: C.sub, fontSize: 24}}>KG</div>
					</div>
					<div style={{color: C.sub, fontSize: 21, marginTop: 12}}>
						PL 품목 합계는 <Mono style={{color: C.text}}>{fmt(K.plGrossLineSum, 2)}</Mono> → 합계 칸 자릿수 뒤바뀜 의심
					</div>
				</Panel>
			</Rise>
			<Rise at={225} x={40} y={0} style={{position: 'absolute', left: 940, top: 640, width: 884}}>
				<Panel glow={C.red} style={{padding: '24px 30px'}}>
					<div style={{color: C.red, fontSize: 22, fontWeight: 800}}>② 컨테이너 번호 체크디지트 오류</div>
					<div style={{display: 'flex', alignItems: 'center', gap: 6, marginTop: 14}}>
						<Mono style={{fontSize: 46, fontWeight: 800, color: C.text}}>{cp.slice(0, 4)}</Mono>
						<Mono style={{fontSize: 46, fontWeight: 800, color: C.text, marginLeft: 10}}>{cp.slice(4, 10)}</Mono>
						<Mono
							style={{
								fontSize: 46,
								fontWeight: 800,
								color: C.red,
								border: `3px solid ${C.red}`,
								borderRadius: 8,
								padding: '0 10px',
								marginLeft: 10,
							}}
						>
							{cp.slice(10)}
						</Mono>
						<div style={{marginLeft: 30, color: C.sub, fontSize: 22}}>
							계산값{' '}
							<Mono style={{fontSize: 40, fontWeight: 800, color: f < 270 ? C.sub : C.teal}}>{digitSpin}</Mono>
						</div>
					</div>
					<div style={{color: C.sub, fontSize: 20, marginTop: 10}}>
						Σ(문자값 × 2ⁱ) mod 11 mod 10 = {K.checkDigitComputed} ≠ 인쇄값 {K.checkDigitPrinted} → 오타 가능성
					</div>
				</Panel>
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S7. Agent 설명 + 정정 요청 + 재검증                                   */
/* ------------------------------------------------------------------ */
export const AgentFix: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const msg =
		`B/L 총중량은 ${fmt(K.blGross, 2)} KG, Packing List 합계 칸은 ${fmt(K.plGrossPrinted, 2)} KG입니다. ` +
		`PL 품목 합계가 B/L과 같으므로 합계 칸의 자릿수 오기로 보입니다. ` +
		`컨테이너 번호 ${K.containerPrinted}는 체크디지트가 맞지 않아 선사 확인이 필요합니다.`;
	// 커서 끝이 '담당자 승인 후 발송' 버튼 가운데에 오도록 (렌더 프레임에서 측정한 위치)
	const btn = {x: 1690, y: 640};
	const cx = interpolate(f, [150, 196], [1300, btn.x], {...clamp, easing: ease});
	const cy = interpolate(f, [150, 196], [960, btn.y], {...clamp, easing: ease});
	const clicked = f >= 204;
	const ripple = interpolate(f, [204, 226], [0, 1], clamp);
	return (
		<Scene dur={dur}>
			<SceneTitle step="STEP 5 · 설명과 정정 요청" title="Agent가 원인을 설명하고 정정을 요청한다" sub="밖으로 나가는 것은 담당자 승인 뒤에만" />
			<Panel style={{position: 'absolute', left: 96, top: 320, width: 800, height: 620}}>
				<div style={{display: 'flex', gap: 16, alignItems: 'center'}}>
					<div
						style={{
							width: 56,
							height: 56,
							borderRadius: 56,
							background: `linear-gradient(135deg, ${C.accent}, #fb923c)`,
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							fontSize: 26,
							fontWeight: 900,
							color: C.bg,
						}}
					>
						AI
					</div>
					<div>
						<div style={{fontSize: 24, fontWeight: 800, color: C.text}}>문서 자동화 Agent</div>
						<div style={{fontSize: 18, color: C.sub}}>검증 도구 결과를 근거로 설명</div>
					</div>
				</div>
				<div style={{marginTop: 26, fontSize: 27, lineHeight: 1.65, color: C.text}}>
					<Type text={msg} at={16} cps={44} />
				</div>
				<div style={{display: 'flex', gap: 12, marginTop: 22, opacity: ap(f, 110, 12)}}>
					<Chip color={C.blue}>근거: B/L · Packing List</Chip>
					<Chip color={C.blue}>규칙 3개 위반</Chip>
				</div>
			</Panel>
			<Rise at={96} x={40} y={0} style={{position: 'absolute', left: 960, top: 320, width: 864}}>
				<Panel style={{padding: '24px 30px'}}>
					<div style={{fontSize: 20, color: C.accent, fontWeight: 800, letterSpacing: 2}}>정정 요청 초안</div>
					<div style={{fontSize: 20, color: C.sub, marginTop: 12}}>받는 곳</div>
					<div style={{fontSize: 22, color: C.text}}>{S.shipper} · {S.carrier}</div>
					<div style={{fontSize: 20, color: C.sub, marginTop: 12}}>제목</div>
					<div style={{fontSize: 22, color: C.text, fontWeight: 700}}>[정정 요청] B/L {S.blNo} 총중량·컨테이너 번호 확인</div>
					<div style={{fontSize: 20, color: C.text, marginTop: 14, lineHeight: 1.6}}>
						· Packing List 합계 G.W. {fmt(K.plGrossPrinted, 2)} KG → {fmt(K.plGrossLineSum, 2)} KG 정정 요청
						<br />· B/L 컨테이너 번호 {K.containerPrinted} 확인 요청 (체크디지트 불일치)
					</div>
					<div style={{display: 'flex', justifyContent: 'flex-end', gap: 14, marginTop: 22}}>
						<div style={{padding: '12px 26px', borderRadius: 14, border: `1.5px solid ${C.line}`, color: C.sub, fontSize: 21}}>수정</div>
						<div
							style={{
								position: 'relative',
								padding: '12px 26px',
								borderRadius: 14,
								background: clicked ? C.teal : C.accent,
								color: C.bg,
								fontSize: 21,
								fontWeight: 800,
							}}
						>
							{clicked ? '✓ 승인·발송됨' : '담당자 승인 후 발송'}
							<div
								style={{
									position: 'absolute',
									inset: -6,
									borderRadius: 18,
									border: `3px solid ${C.teal}`,
									opacity: 1 - ripple,
									transform: `scale(${1 + ripple * 0.35})`,
									display: f >= 204 ? 'block' : 'none',
								}}
							/>
						</div>
					</div>
				</Panel>
			</Rise>
			<Rise at={236} style={{position: 'absolute', left: 960, top: 790, width: 864}}>
				<Panel glow={C.teal} style={{display: 'flex', alignItems: 'center', gap: 24, padding: '22px 30px'}}>
					<Icon ok size={58} />
					<div>
						<div style={{fontSize: 28, fontWeight: 900, color: C.text}}>정정본 수신 → 재검증 9/9 통과</div>
						<div style={{fontSize: 20, color: C.sub, marginTop: 4}}>
							불일치 {(K.fixedFindings as any[]).length}건 · 입항 3일 전에 서류 정리 완료
						</div>
					</div>
				</Panel>
			</Rise>
			{/* 커서 */}
			<svg width={40} height={40} viewBox="0 0 24 24" style={{position: 'absolute', left: cx, top: cy, opacity: ap(f, 148, 8) * (1 - ap(f, 236, 10))}}>
				<path d="M3 2 L3 20 L8 15 L12 22 L15 20 L11 13 L18 13 Z" fill="#fff" stroke="#000" strokeWidth={1.2} />
			</svg>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S8. HS 추천 + 수입신고서 초안                                          */
/* ------------------------------------------------------------------ */
export const HsDeclare: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const hs: string = S.hs6;
	const levels = [
		['제85류', '전기기기와 그 부분품'],
		['제8507호', '축전지'],
		[`${hs.slice(0, 4)}.${hs.slice(4)}`, '리튬이온 축전지'],
	];
	const rows: [string, string, boolean][] = [
		['B/L 번호', S.blNo, true],
		['선박 / 항차', S.vessel, true],
		['적출항', S.pol, true],
		['원산지', S.origin, true],
		['품명', S.item, true],
		['HS 부호', `${hs.slice(0, 4)}.${hs.slice(4)}-____`, true],
		['수량 / 포장', `${S.quantity} ${S.unit} / ${S.packages} CARTONS`, true],
		['총중량', `${fmt(K.blGross, 2)} KG`, true],
		['인도조건', S.incoterms, true],
		['결제금액', `${S.currency} ${fmt(S.totalAmount, 2)}`, true],
		['통관고유부호', '서류에 없음 · 입력 필요', false],
		['신고인 부호', '서류에 없음 · 입력 필요', false],
		['세관·과 부호', '서류에 없음 · 입력 필요', false],
	];
	return (
		<Scene dur={dur}>
			<SceneTitle step="STEP 6 · HS 코드와 신고서" title="입항 전에 신고 준비를 끝낸다" sub="HS 후보와 근거, 수입신고서 초안 · 최종 판단은 관세사 (과제 기능 ③)" />
			<div style={{position: 'absolute', left: 96, top: 320, width: 760}}>
				<Rise at={6}>
					<Panel style={{padding: '18px 24px'}}>
						<div style={{fontSize: 19, color: C.sub}}>Invoice 품명</div>
						<Mono style={{fontSize: 26, fontWeight: 800, color: C.text}}>{S.item}</Mono>
					</Panel>
				</Rise>
				{levels.map(([code, name], i) => {
					const at = 30 + i * 26;
					const last = i === levels.length - 1;
					return (
						<div key={code} style={{marginLeft: 34 + i * 34, marginTop: 14}}>
							<div style={{width: 3, height: 24, background: C.line, marginLeft: 30, opacity: ap(f, at - 6, 8)}} />
							<Rise at={at} x={-20} y={0}>
								<Panel glow={last ? C.accent : undefined} style={{padding: '14px 22px', display: 'flex', gap: 18, alignItems: 'baseline'}}>
									<Mono style={{fontSize: last ? 34 : 26, fontWeight: 800, color: last ? C.accent : C.text}}>{code}</Mono>
									<span style={{fontSize: 22, color: C.sub}}>{name}</span>
								</Panel>
							</Rise>
						</div>
					);
				})}
				<Rise at={120} style={{marginTop: 24, display: 'flex', gap: 12, flexWrap: 'wrap'}}>
					<Chip color={C.teal}>✓ 품목 마스터 등록 코드와 일치</Chip>
					<Chip color={C.sub}>10단위·수입요건은 관세사 확인</Chip>
				</Rise>
			</div>
			<Rise at={40} x={40} y={0} style={{position: 'absolute', left: 920, top: 320, width: 904}}>
				<Panel style={{padding: '18px 28px'}}>
					<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
						<div style={{fontSize: 22, color: C.accent, fontWeight: 800, letterSpacing: 2}}>수입신고서 초안</div>
						<Chip color={C.blue} style={{fontSize: 16}}>서류에서 자동 입력</Chip>
					</div>
					{rows.map(([k, v, ok], i) => {
						const at = 60 + i * 11;
						return (
							<div
								key={k}
								style={{
									display: 'flex',
									padding: '4px 0',
									borderTop: `1px solid ${C.line}`,
									fontSize: 19,
									opacity: 0.25 + 0.75 * ap(f, at, 8),
									background: ok ? 'transparent' : `${C.accent}${f > at ? '14' : '00'}`,
								}}
							>
								<div style={{width: 170, color: C.sub}}>{k}</div>
								<div style={{flex: 1, color: ok ? C.text : C.accent, fontWeight: ok ? 600 : 800}}>
									{f > at ? ok ? <Mono>{v}</Mono> : `⚠ ${v}` : ''}
								</div>
							</div>
						);
					})}
				</Panel>
				<Rise at={215} style={{marginTop: 12}}>
					<Chip color={C.teal} solid>
						서류 기반 10개 항목 자동 입력 · 3개 입력 필요
					</Chip>
				</Rise>
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S9. 물류 시스템 등록 + 흐름 추적                                       */
/* ------------------------------------------------------------------ */
export const SystemSync: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const others = (L.delayed as any[]).slice(0, 3);
	const fly = ap(f, 30, 34);
	const nodes = [
		{d: md(S.onBoard), t: '선적', done: true},
		{d: md(L.baseDate), t: '서류 검증·정정', done: true},
		{d: '입항 전', t: '수입신고 가능', done: false},
		{d: md(L.demo.eta), t: '부산 입항', done: false},
		{d: '', t: '심사·수리', done: false},
		{d: '', t: '반출·내륙 운송', done: false},
	];
	const prog = interpolate(f, [120, 200], [0, 1], {...clamp, easing: ease});
	return (
		<Scene dur={dur}>
			<SceneTitle
				step="STEP 7 · 시스템 연동"
				title="물류 시스템에 등록하고 흐름을 추적한다"
				sub="가상 WMS·TMS·ERP로 구현 · 실제 시스템은 연동 어댑터만 바꾸면 된다 (과제 기능 ④)"
			/>
			<Panel style={{position: 'absolute', left: 96, top: 320, width: 1728, padding: '18px 28px'}}>
				<div style={{fontSize: 20, color: C.sub, marginBottom: 8}}>화물 현황 · 가상 물류 시스템 (DynamoDB)</div>
				<div style={{display: 'flex', color: C.dim, fontSize: 18, padding: '6px 0'}}>
					<div style={{width: 220}}>화물 ID</div>
					<div style={{width: 520}}>수입자</div>
					<div style={{width: 260}}>통관 상태</div>
					<div style={{flex: 1}}>서류 상태</div>
				</div>
				<div
					style={{
						display: 'flex',
						fontSize: 22,
						padding: '12px 0',
						borderTop: `1px solid ${C.line}`,
						background: `${C.accent}${f > 64 ? '18' : '00'}`,
						opacity: fly,
						transform: `translateY(${(1 - fly) * -80}px) scale(${1 + (1 - fly) * 0.06})`,
					}}
				>
					<div style={{width: 220, color: C.accent, fontWeight: 800}}>
						<Mono>{L.demo.id}</Mono>
					</div>
					<div style={{width: 520, color: C.text}}>{S.consignee}</div>
					<div style={{width: 260, color: C.text}}>입항 예정 {md(L.demo.eta)}</div>
					<div style={{flex: 1, color: C.teal, fontWeight: 800}}>✓ 검증 완료 · 신고 준비됨</div>
				</div>
				{others.map((r) => (
					<div key={r.id} style={{display: 'flex', fontSize: 22, padding: '12px 0', borderTop: `1px solid ${C.line}`, opacity: 0.7}}>
						<div style={{width: 220, color: C.sub}}>
							<Mono>{r.id}</Mono>
						</div>
						<div style={{width: 520, color: C.sub}}>{r.consignee}</div>
						<div style={{width: 260, color: C.sub}}>{r.status}</div>
						<div style={{flex: 1, color: C.sub}}>보완 요청 중</div>
					</div>
				))}
			</Panel>
			<Rise at={100} style={{position: 'absolute', left: 96, top: 700, width: 1728}}>
				<Panel style={{padding: '30px 40px 34px'}}>
					<div style={{fontSize: 20, color: C.sub, marginBottom: 26}}>B/L {S.blNo} 진행 흐름</div>
					<div style={{position: 'relative', height: 90}}>
						<div style={{position: 'absolute', left: 20, right: 20, top: 18, height: 6, background: C.line, borderRadius: 6}} />
						<div style={{position: 'absolute', left: 20, top: 18, height: 6, width: `${prog * 34}%`, background: C.teal, borderRadius: 6}} />
						{nodes.map((n, i) => {
							const x = (i / (nodes.length - 1)) * 100;
							const active = i === 2;
							const pulse = active ? 1 + 0.15 * Math.sin(f / 6) : 1;
							return (
								<div key={n.t} style={{position: 'absolute', left: `calc(${x}% - ${i === 0 ? 0 : i === nodes.length - 1 ? 150 : 75}px)`, top: 0, width: 150, textAlign: i === 0 ? 'left' : i === nodes.length - 1 ? 'right' : 'center'}}>
									<div
										style={{
											width: 42,
											height: 42,
											borderRadius: 42,
											margin: i === 0 ? '0' : i === nodes.length - 1 ? '0 0 0 auto' : '0 auto',
											background: n.done ? C.teal : active ? C.accent : C.panel2,
											border: `3px solid ${n.done ? C.teal : active ? C.accent : C.line}`,
											transform: `scale(${pulse})`,
											color: C.bg,
											fontWeight: 900,
											fontSize: 22,
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'center',
										}}
									>
										{n.done ? '✓' : ''}
									</div>
									<div style={{fontSize: 21, color: n.done || active ? C.text : C.sub, fontWeight: 700, marginTop: 10}}>{n.t}</div>
									<div style={{fontSize: 18, color: C.dim}}>{n.d}</div>
								</div>
							);
						})}
					</div>
				</Panel>
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S10. 자연어 현황 조회                                                 */
/* ------------------------------------------------------------------ */
const Bubble: React.FC<{me?: boolean; at: number; children: React.ReactNode}> = ({me, at, children}) => {
	const f = useCurrentFrame();
	const p = ap(f, at, 12);
	return (
		<div style={{display: 'flex', justifyContent: me ? 'flex-end' : 'flex-start', opacity: p, transform: `translateY(${(1 - p) * 16}px)`}}>
			<div
				style={{
					maxWidth: 1300,
					padding: '14px 24px',
					borderRadius: 22,
					fontSize: 26,
					lineHeight: 1.5,
					background: me ? C.accent : C.panel2,
					color: me ? C.bg : C.text,
					fontWeight: me ? 700 : 500,
					border: me ? 'none' : `1.5px solid ${C.line}`,
				}}
			>
				{children}
			</div>
		</div>
	);
};

export const Query: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const delayed = L.delayed as any[];
	const q1 = '이번 주 통관 지연 건 알려줘';
	const q2 = '프리타임이 이틀 안에 끝나는데 아직 수리 안 된 화물은?';
	return (
		<Scene dur={dur}>
			<SceneTitle step="STEP 7 · 자연어 현황 조회" title="입항 후에는 말로 묻는다" sub="query_shipments 도구가 가상 물류 시스템을 조회 (과제 기능 ⑤)" />
			<div style={{position: 'absolute', left: 96, top: 300, width: 1728, display: 'flex', flexDirection: 'column', gap: 14}}>
				<Bubble me at={6}>
					<Type text={q1} at={10} cps={26} />
				</Bubble>
				<Bubble at={44}>
					이번 주({md(L.weekStart)}~{md(L.weekEnd)}) 통관이 지연된 화물은 <b style={{color: C.accent}}>{delayed.length}건</b>입니다.
				</Bubble>
				<Panel style={{padding: '6px 24px', opacity: ap(f, 56, 10)}}>
					{delayed.map((r, i) => (
						<div
							key={r.id}
							style={{
								display: 'flex',
								fontSize: 19,
								padding: '8px 0',
								borderTop: i ? `1px solid ${C.line}` : 'none',
								opacity: ap(f, 60 + i * 9, 8),
							}}
						>
							<div style={{width: 190, color: C.accent}}>
								<Mono>{r.id}</Mono>
							</div>
							<div style={{width: 420, color: C.text}}>{r.consignee}</div>
							<div style={{width: 130, color: C.sub}}>{r.status}</div>
							<div style={{flex: 1, color: C.text}}>{r.reason}</div>
						</div>
					))}
				</Panel>
				<Bubble me at={150}>
					<Type text={q2} at={154} cps={30} />
				</Bubble>
				<Bubble at={210}>
					<b style={{color: C.accent}}>{L.freeTimeSoon}건</b>입니다. 보관료가 붙기 전에 서류 보완부터 처리하도록 담당자에게 알림을 보낼까요?
				</Bubble>
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* S11. 마무리                                                          */
/* ------------------------------------------------------------------ */
export const Outro: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const req = ['OCR·핵심 항목 추출', '문서 분류·교차 검증', 'HS 코드·통관 서류 작성', '물류 시스템 연동', '자연어 현황 조회'];
	const arch = ['모바일·웹', 'Amazon S3', 'Bedrock Data Automation', 'Agent · Lambda + Strands', 'Claude · Knowledge Bases · DynamoDB'];
	return (
		<Scene dur={dur}>
			<BlenderOutroBg />
			<div style={{position: 'absolute', left: 0, right: 0, top: 150, textAlign: 'center'}}>
				<Rise at={6}>
					<div style={{fontSize: 30, color: C.accent, fontWeight: 800, letterSpacing: 4}}>6팀 · AI 기반 첨단물류 문서 자동화 Agent</div>
				</Rise>
				<Rise at={14}>
					<div style={{fontSize: 84, fontWeight: 900, color: C.text, marginTop: 20, letterSpacing: -2}}>
						추출을 넘어, <span style={{color: C.accent}}>신고 전에</span> 틀린 것을 잡는다
					</div>
				</Rise>
			</div>
			<div style={{position: 'absolute', left: 0, right: 0, top: 390, display: 'flex', justifyContent: 'center', gap: 18}}>
				{req.map((r, i) => (
					<Pop key={r} at={40 + i * 8}>
						<Chip color={C.teal} style={{fontSize: 24, padding: '10px 22px'}}>
							✓ {r}
						</Chip>
					</Pop>
				))}
			</div>
			<div style={{position: 'absolute', left: 0, right: 0, top: 500, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 14}}>
				{arch.map((a, i) => (
					<React.Fragment key={a}>
						<Rise at={86 + i * 7}>
							<Panel style={{padding: '16px 22px', fontSize: 22, fontWeight: 700, color: i === 3 ? C.accent : C.text}} glow={i === 3 ? C.accent : undefined}>
								{a}
							</Panel>
						</Rise>
						{i < arch.length - 1 ? (
							<Rise at={90 + i * 7}>
								<span style={{color: C.dim, fontSize: 30}}>→</span>
							</Rise>
						) : null}
					</React.Fragment>
				))}
			</div>
			<Rise at={110} style={{position: 'absolute', left: 0, right: 0, top: 610, textAlign: 'center', color: C.sub, fontSize: 19}}>
				영상 속 서류·화물·회사는 모두 합성 데이터(가상 회사)입니다 · 2026 AWS AI 마에스트로 해커톤
			</Rise>
		</Scene>
	);
};

export const SceneBackdrop: React.FC = () => {
	const f = useCurrentFrame();
	const gx = 960 + Math.sin(f / 90) * 300;
	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(1200px 700px at ${gx}px 0px, #16294a 0%, ${C.bg} 60%)`,
			}}
		>
			<AbsoluteFill
				style={{
					backgroundImage: `linear-gradient(${C.line}22 1px, transparent 1px), linear-gradient(90deg, ${C.line}22 1px, transparent 1px)`,
					backgroundSize: '64px 64px',
				}}
			/>
		</AbsoluteFill>
	);
};

export {MONO};

// 새 발표 영상의 2D 장면 (웹 앱과 같은 디자인: 흰 바탕, 검정 글자, 회색 칸, 빨강은 불일치에만).
// 화면 모양은 실제 웹 앱(web/src)의 업로드 · 문서 분류 내역 · 작업 화면 · HS 고르기 · 신고서 초안 · WMS · AI chat 을 따른다.
import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import data from '../data.json';
import {ap, clamp, Count, ease, fmt, Pop, Rise, Scene} from '../ui';
import type {DocImg} from '../ui';
import {Card, Fill, Head, Mono, Pill, Status, WDoc, WType} from './ui';
import {W} from './theme';

const D = data as any;
const IM = D.images as Record<string, DocImg>;
const S = D.shipment;
const K = D.checks;
const L = D.logistics;
const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

/* ------------------------------------------------------------------ */
/* 문제: 사람이 서류 4종을 눈으로 대조                                    */
/* ------------------------------------------------------------------ */
export const ProblemW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const docs = [
		{img: IM.bl, label: '선하증권 (B/L)', box: 'gross'},
		{img: IM.invoice, label: '상업송장', box: 'total'},
		{img: IM.pl, label: '포장명세서', box: 'gross_total'},
		{img: IM.co, label: '원산지증명서', box: 'hs'},
	];
	const pains = [
		['같은 값을 서류마다 다시 확인', '품명·수량·중량·포장 수가 4종에 반복된다'],
		['숫자 하나만 틀려도 화물이 멈춘다', '세관 보완 요구 · 통관 보류 · 적하목록 정정'],
		['반출이 늦어질수록 비용이 쌓인다', '터미널 보관료 · 선사 체화료 (컨테이너·일 단위)'],
	];
	return (
		<Scene dur={dur}>
			<Head step="문제" title="사람이 서류 4종을 눈으로 대조한다" sub="같은 정보가 서류마다 반복되고, 하나라도 틀리면 통관이 늦어진다" />
			<div style={{position: 'absolute', left: 96, top: 340, display: 'flex', gap: 20}}>
				{docs.map((d, i) => {
					const p = ap(f, 18 + i * 8, 20);
					return (
						<div key={d.label} style={{opacity: p, transform: `translateY(${(1 - p) * 50}px)`}}>
							<WDoc img={d.img} width={236} boxes={[{key: d.box, at: 70 + i * 6}]} />
							<div style={{fontSize: 20, fontWeight: 600, marginTop: 12, textAlign: 'center'}}>{d.label}</div>
						</div>
					);
				})}
			</div>
			<Pop at={100} style={{position: 'absolute', left: 330, top: 790}}>
				<Pill dark style={{fontSize: 22, height: 46}}>
					같은 값일까? 사람이 눈으로 비교
				</Pill>
			</Pop>
			<div style={{position: 'absolute', left: 1172, top: 340, width: 652, display: 'flex', flexDirection: 'column', gap: 18}}>
				{pains.map(([t, s], i) => (
					<Rise key={t} at={56 + i * 20} x={30} y={0}>
						<Card style={{padding: '24px 28px'}}>
							<div style={{fontSize: 28, fontWeight: 800}}>{t}</div>
							<div style={{fontSize: 20, color: W.muted, marginTop: 6}}>{s}</div>
						</Card>
					</Rise>
				))}
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 1. 올리기: 휴대폰 업로드 화면 (웹 앱 파일 업로드와 같은 모양)              */
/* ------------------------------------------------------------------ */
const Phone: React.FC<{children: React.ReactNode}> = ({children}) => (
	<div style={{width: 400, height: 820, borderRadius: 58, background: '#111', padding: 14, boxShadow: '0 30px 80px rgba(0,0,0,0.18)'}}>
		<div style={{position: 'relative', width: '100%', height: '100%', borderRadius: 46, overflow: 'hidden', background: '#fff'}}>{children}</div>
	</div>
);

export const UploadW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const shot = 96;
	const flash = interpolate(f, [shot, shot + 3, shot + 14], [0, 1, 0], clamp);
	const camera = f < shot + 8;
	const files = [
		{name: 'packing_list.jpg', size: '3.8MB', at: 120},
		{name: 'bl.jpg', size: '4.1MB', at: 130},
		{name: 'invoice.pdf', size: '412KB', at: 140},
		{name: 'certificate_of_origin.pdf', size: '388KB', at: 150},
	];
	const steps = [
		['서류를 찍거나 PDF를 고른다', '사진 20MB · PDF 4.5MB까지, 한 번에 10개'],
		['서류 종류는 고르지 않는다', '올리면 Agent가 자동으로 분류한다'],
		['S3에 바로 올리고 작업이 시작된다', '미리 서명된 주소로 화면에서 직접 전송'],
	];
	const sent = ap(f, 200, 12);
	return (
		<Scene dur={dur}>
			<Head step="1단계 · 촬영·전송" title="찍은 서류는 그 자리에서 클라우드로" sub="사진, 스캔본, PDF 무엇이든 (과제 기능 ①)" />
			<div style={{position: 'absolute', left: 96, top: 360, width: 960, display: 'flex', flexDirection: 'column', gap: 26}}>
				{steps.map(([t, s], i) => (
					<Rise key={t} at={24 + i * 34} x={-24} y={0}>
						<div style={{display: 'flex', gap: 22, alignItems: 'flex-start'}}>
							<div style={{width: 52, height: 52, borderRadius: 52, background: W.ink, color: '#fff', fontSize: 24, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
								{i + 1}
							</div>
							<div>
								<div style={{fontSize: 32, fontWeight: 800}}>{t}</div>
								<div style={{fontSize: 22, color: W.muted, marginTop: 4}}>{s}</div>
							</div>
						</div>
					</Rise>
				))}
				<Rise at={150} style={{marginTop: 10}}>
					<Fill style={{display: 'flex', gap: 16, alignItems: 'center', padding: '18px 22px'}}>
						<Pill>선적 {md(S.onBoard)}</Pill>
						<span style={{color: W.muted, fontSize: 24}}>→</span>
						<Pill dark>서류 도착 {md(L.baseDate)} · 지금</Pill>
						<span style={{color: W.muted, fontSize: 24}}>→</span>
						<Pill>부산 입항 예정 {md(L.demo.eta)}</Pill>
					</Fill>
				</Rise>
			</div>
			<Rise at={6} x={50} y={0} style={{position: 'absolute', left: 1330, top: 170}}>
				<Phone>
					{camera ? (
						<>
							<Img src={staticFile('docs/scan_pl.jpg')} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${interpolate(f, [0, shot], [1.3, 1.12], clamp)})`}} />
							<div style={{position: 'absolute', left: 36, top: 130, width: 300, height: 430, border: '4px solid #fff', borderRadius: 12, opacity: ap(f, 56, 12), boxShadow: '0 0 0 9999px rgba(0,0,0,0.25)'}} />
							<div style={{position: 'absolute', top: 40, width: '100%', textAlign: 'center', color: '#fff', fontSize: 20, fontWeight: 700}}>
								{f < 56 ? '서류를 화면에 맞춰 주세요' : '서류를 찍었습니다'}
							</div>
							<div style={{position: 'absolute', bottom: 40, left: '50%', marginLeft: -38, width: 76, height: 76, borderRadius: 76, border: '6px solid #fff', background: f > shot - 10 ? '#fff' : 'transparent'}} />
						</>
					) : (
						<div style={{padding: '44px 22px'}}>
							<Pill style={{height: 30, fontSize: 14, padding: '0 12px'}}>통관 서류 검토</Pill>
							<div style={{fontSize: 30, fontWeight: 800, marginTop: 16, lineHeight: 1.25}}>검토할 서류를 올려 주세요</div>
							<div style={{fontSize: 15, color: W.muted, marginTop: 6}}>서류 종류는 자동으로 분류합니다</div>
							<div style={{fontSize: 17, fontWeight: 700, marginTop: 22}}>선택된 파일 {files.filter((x) => f >= x.at - 12).length}</div>
							<div style={{marginTop: 10, display: 'flex', flexDirection: 'column', gap: 10}}>
								{files.map((x) => {
									const p = ap(f, x.at, 40);
									return (
										<div key={x.name} style={{display: 'flex', gap: 10, alignItems: 'center', background: W.fill2, borderRadius: 14, padding: '10px 12px', opacity: ap(f, x.at - 12, 10)}}>
											<span style={{width: 40, height: 40, borderRadius: 10, background: '#fff', border: `1px solid ${W.line}`, fontSize: 11, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
												{x.name.endsWith('pdf') ? 'PDF' : 'JPG'}
											</span>
											<div style={{flex: 1, minWidth: 0}}>
												<div style={{fontSize: 14, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{x.name}</div>
												<div style={{height: 5, background: W.line, borderRadius: 5, marginTop: 6, overflow: 'hidden'}}>
													<div style={{width: `${p * 100}%`, height: '100%', background: W.ink}} />
												</div>
											</div>
										</div>
									);
								})}
							</div>
							<div style={{position: 'absolute', left: 22, right: 22, bottom: 36, height: 56, borderRadius: 16, background: W.ink, color: '#fff', fontSize: 18, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
								{sent > 0.5 ? '✓ 4개 올림 · 작업 시작' : '4개 업로드'}
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
/* 2. 분류: 문서 분류 내역의 종류 칩으로 서류가 들어간다                       */
/* ------------------------------------------------------------------ */
export const ClassifyW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const bins = [
		{key: 'bl', title: '선하증권', reason: '제목 BILL OF LADING · Shipper · Port of Loading 칸'},
		{key: 'invoice', title: '상업송장', reason: '제목 COMMERCIAL INVOICE · Unit Price · Amount 칸'},
		{key: 'pl', title: '포장명세서', reason: '제목 PACKING LIST · N.W. · G.W. · Meas. 칸'},
		{key: 'co', title: '원산지증명서', reason: '제목 CERTIFICATE OF ORIGIN · Origin Criterion 칸'},
	];
	const order = ['pl', 'bl', 'invoice', 'co'];
	const binX = (i: number) => 700 + i * 285;
	return (
		<Scene dur={dur}>
			<Head step="2단계 · 문서 분류" title="어떤 서류인지 먼저 가른다" sub="파일 이름·형식과 상관없이 제목과 특징 칸을 보고 고른다. 근거도 함께 남긴다 (과제 기능 ②)" />
			<Rise at={6} style={{position: 'absolute', left: 96, top: 360}}>
				<Card style={{width: 500, padding: '26px 28px'}}>
					<div style={{fontSize: 20, color: W.muted}}>받은 파일</div>
					<div style={{fontSize: 38, fontWeight: 800, marginTop: 4}}>사진 2장 + PDF 2개</div>
					<div style={{fontSize: 20, color: W.muted, marginTop: 10, lineHeight: 1.5}}>
						분류는 읽기와 따로, 가벼운 호출로 한다
						<br />
						애매하면 '분류 못 함'으로 두고 사람이 고친다
					</div>
				</Card>
			</Rise>
			{bins.map((b, i) => {
				const j = order.indexOf(b.key);
				const landed = ap(f, 40 + j * 24 + 26, 10);
				return (
					<Rise key={b.key} at={10 + i * 5} style={{position: 'absolute', left: binX(i), top: 330}}>
						<div style={{width: 262, height: 600, borderRadius: 22, background: W.fill2, padding: 18}}>
							<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
								<span style={{fontSize: 22, fontWeight: 800}}>{b.title}</span>
								<span style={{fontSize: 18, color: W.muted, fontWeight: 700}}>{landed > 0.5 ? '1건' : '0건'}</span>
							</div>
							<div style={{position: 'absolute', left: 18, right: 18, bottom: 18, fontSize: 15, color: W.muted, lineHeight: 1.45, opacity: landed}}>
								근거: {b.reason}
							</div>
						</div>
					</Rise>
				);
			})}
			{order.map((key, j) => {
				const i = bins.findIndex((b) => b.key === key);
				const start = 40 + j * 24;
				const p = ap(f, start, 28);
				const x = interpolate(p, [0, 1], [240 + j * 18, binX(i) + 23]);
				const y = interpolate(p, [0, 1], [650 + j * 14, 400]);
				return (
					<div key={key} style={{position: 'absolute', left: x, top: y, opacity: ap(f, start - 14, 10), transform: `rotate(${(1 - p) * (j - 1.5) * 6}deg)`}}>
						<WDoc img={IM[key]} width={216} crop={300} style={{boxShadow: '0 12px 30px rgba(0,0,0,0.12)'}} />
					</div>
				);
			})}
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 3. 추출: 서류 위 박스 + 돋보기 + 읽은 값                                  */
/* ------------------------------------------------------------------ */
export const ExtractW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const rows = [
		{key: 'bl_no', label: '선하증권 번호', value: S.blNo, at: 40},
		{key: 'shipper', label: '송하인', value: S.shipper, at: 62},
		{key: 'container', label: '컨테이너 번호', value: K.containerPrinted, at: 84},
		{key: 'packages', label: '총포장갯수', value: `${fmt(S.packages)} CARTONS`, at: 106},
		{key: 'gross', label: '총중량', value: `${fmt(K.blGross, 2)} KG`, at: 128},
	];
	// 돋보기: 총중량 칸을 크게 (G16 서류 보기와 같은 방식)
	const img = IM.bl;
	const r = img.boxes.gross;
	const lens = ap(f, 170, 16);
	const W0 = 760;
	const k = W0 / img.w;
	const zoom = 2.6;
	return (
		<Scene dur={dur}>
			<Head step="3단계 · 항목 추출" title="값과 함께 원본 위치를 남긴다" sub="AI는 적힌 그대로 옮기고, 숫자 풀기·대조는 코드가 한다. 위치는 Textract OCR (과제 기능 ①)" />
			<Rise at={6} x={-30} y={0} style={{position: 'absolute', left: 96, top: 320}}>
				<Card style={{padding: 16}}>
					<WDoc img={img} width={W0} crop={600} boxes={rows.map((x) => ({key: x.key, at: x.at}))} />
				</Card>
			</Rise>
			{/* 돋보기 상자 */}
			<div
				style={{
					position: 'absolute',
					left: 96 + 16 + r[0] * k - 40,
					top: 320 + 16 + r[3] * k + 18,
					width: 420,
					background: W.ink,
					color: '#fff',
					borderRadius: 16,
					padding: 12,
					opacity: lens,
					transform: `translateY(${(1 - lens) * 14}px)`,
					boxShadow: '0 16px 40px rgba(0,0,0,0.25)',
				}}
			>
				<div style={{position: 'relative', height: 110, overflow: 'hidden', borderRadius: 10, background: '#fff'}}>
					<Img
						src={staticFile(img.file)}
						style={{position: 'absolute', width: img.w * k * zoom, left: -(r[0] * k * zoom) + 60, top: -(r[1] * k * zoom) + 34, maxWidth: 'none'}}
					/>
					<div style={{position: 'absolute', left: 52, top: 26, width: (r[2] - r[0]) * k * zoom + 16, height: (r[3] - r[1]) * k * zoom + 16, border: `2px solid ${W.ink}`, borderRadius: 4, boxShadow: '0 0 0 999px rgba(20,20,20,0.08)'}} />
				</div>
				<div style={{fontSize: 15, color: '#c9c9c9', marginTop: 10}}>읽은 값 · 총중량</div>
				<Mono style={{fontSize: 26, fontWeight: 800}}>{fmt(K.blGross, 2)} KG</Mono>
			</div>
			<div style={{position: 'absolute', left: 940, top: 320, width: 884}}>
				<Card style={{padding: '22px 28px'}}>
					<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6}}>
						<span style={{fontSize: 22, fontWeight: 800}}>읽은 값 · 선하증권</span>
						<Status>Textract 위치 {rows.length}칸</Status>
					</div>
					{rows.map((x) => (
						<div
							key={x.key}
							style={{display: 'flex', alignItems: 'center', gap: 16, padding: '13px 0', borderTop: `1px solid ${W.line}`, opacity: ap(f, x.at + 4, 12), transform: `translateX(${(1 - ap(f, x.at + 4, 12)) * 24}px)`}}
						>
							<div style={{width: 190, fontSize: 20, fontWeight: 700}}>{x.label}</div>
							<Mono style={{flex: 1, fontSize: x.value.length > 26 ? 18 : 23}}>{x.value}</Mono>
						</div>
					))}
				</Card>
				<Rise at={190} style={{marginTop: 18}}>
					<Fill style={{display: 'flex', gap: 18, alignItems: 'center'}}>
						<WDoc img={IM.pl} width={320} crop={150} boxes={[{key: 'gross_line', at: 200}, {key: 'gross_total', at: 212, red: true}]} />
						<div style={{fontSize: 21, lineHeight: 1.6}}>
							<div style={{color: W.muted}}>포장명세서도 같은 칸을 따로 읽는다</div>
							<div>
								품목 G.W. <Mono style={{fontWeight: 700}}>{fmt(K.plGrossLineSum, 2)}</Mono>
							</div>
							<div>
								합계 G.W. <Mono style={{fontWeight: 700, color: W.red}}>{fmt(K.plGrossPrinted, 2)}</Mono>
							</div>
						</div>
					</Fill>
				</Rise>
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 4. 교차 검증: 규칙 표 → 작업 화면의 오류 카드와 읽은 칸 표                  */
/* ------------------------------------------------------------------ */
const RULES: [string, string, boolean][] = [
	['X-WT-01', '총중량 선하증권 ↔ 포장명세서', true],
	['PL-SUM', '포장명세서 품목 합계 ↔ 합계 칸', true],
	['X-PKG-01', '포장 수 선하증권 ↔ 포장명세서', false],
	['X-QTY-01', '품목 수량 상업송장 ↔ 포장명세서', false],
	['INV-AMT', '상업송장 금액 = 수량 × 단가', false],
	['X-INV-01', '서류 번호 (송장 번호)', false],
	['X-ORG-01', '원산지 상업송장 ↔ 원산지증명서', false],
	['CNT-ISO', '컨테이너 번호 체크디지트 (ISO 6346)', true],
];

export const ValidateW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const nFail = RULES.filter((r) => r[2]).length;
	const box = ap(f, 170, 16);
	return (
		<Scene dur={dur}>
			<Head step="4단계 · 서류끼리 대조" title="판정은 AI가 아니라 규칙 코드가 한다" sub={`규칙 ${RULES.length}개를 서류 4종에 적용 · 불일치 ${nFail}건 · 불일치 칸은 다른 방법(OCR)으로 다시 확인 (과제 기능 ②)`} />
			<Rise at={6} style={{position: 'absolute', left: 96, top: 330, width: 700}}>
				<Card style={{padding: '12px 24px'}}>
					{RULES.map(([id, label, bad], i) => {
						const at = 18 + i * 12;
						const on = ap(f, at, 8);
						return (
							<div key={id} style={{display: 'flex', alignItems: 'center', gap: 14, padding: '11px 0', borderTop: i ? `1px solid ${W.line}` : 'none', opacity: 0.3 + 0.7 * on}}>
								<span style={{width: 30, height: 30, borderRadius: 30, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 17, fontWeight: 800, color: '#fff', background: bad ? W.red : W.ink, transform: `scale(${0.5 + 0.5 * on})`}}>
									{bad ? '✕' : '✓'}
								</span>
								<span style={{flex: 1, fontSize: 21, fontWeight: bad ? 800 : 500, color: bad && on > 0.5 ? W.red : W.ink}}>{label}</span>
								<Mono style={{fontSize: 15, color: W.muted}}>{id}</Mono>
							</div>
						);
					})}
				</Card>
				<div style={{display: 'flex', gap: 10, marginTop: 14, opacity: ap(f, 120, 10)}}>
					<Pill dark>통과 {RULES.length - nFail}</Pill>
					<Pill red>불일치 {nFail}</Pill>
				</div>
			</Rise>
			<div style={{position: 'absolute', left: 840, top: 330, width: 984}}>
				<Rise at={140} x={30} y={0}>
					<Card style={{border: `1.5px solid ${W.ink}`, padding: '22px 26px'}}>
						<div style={{display: 'flex', alignItems: 'center', gap: 12}}>
							<Pill red style={{height: 34, fontSize: 17}}>불일치</Pill>
							<span style={{fontSize: 23, fontWeight: 700}}>선하증권 총중량과 포장명세서 총중량이 다릅니다</span>
						</div>
						<div style={{display: 'flex', gap: 12, marginTop: 16}}>
							<Fill style={{flex: 1, background: W.ink2, color: '#fff'}}>
								<div style={{fontSize: 16, color: '#c9c9c9'}}>포장명세서 · 다른 쪽</div>
								<Mono style={{fontSize: 34, fontWeight: 800}}>{fmt(K.plGrossPrinted, 2)}</Mono>
							</Fill>
							<Fill style={{flex: 1}}>
								<div style={{fontSize: 16, color: W.muted}}>선하증권</div>
								<Mono style={{fontSize: 34, fontWeight: 800}}>{fmt(K.blGross, 2)}</Mono>
							</Fill>
						</div>
						<div style={{fontSize: 17, color: W.muted, marginTop: 12}}>
							규칙 <Mono>X-WT-01</Mono> · Textract OCR로 다시 확인 · 품목 합계 {fmt(K.plGrossLineSum, 2)} → 합계 칸 자릿수 뒤바뀜 의심
						</div>
					</Card>
				</Rise>
				<Rise at={190} x={30} y={0} style={{marginTop: 16, display: 'flex', gap: 16}}>
					<Card style={{padding: 12, width: 380}}>
						<div style={{position: 'relative'}}>
							<WDoc img={IM.pl} width={356} crop={220} style={{border: 'none'}} />
							<div style={{position: 'absolute', left: '72.6%', top: 220 * 0 + (IM.pl.boxes.gross_total?.[1] ?? 0) * (356 / IM.pl.w) - 6, width: '12%', height: 22, border: `3px solid ${W.red}`, borderRadius: 5, opacity: box, display: 'none'}} />
						</div>
					</Card>
					<Card style={{flex: 1, padding: '16px 20px'}}>
						<div style={{fontSize: 18, fontWeight: 700, marginBottom: 6}}>
							읽은 칸 · 포장명세서 <span style={{color: W.muted, fontWeight: 500}}>빨간 줄이 불일치</span>
						</div>
						{(
							[
								['송장 번호', S.invoiceNo, false],
								['총수량', `${S.quantity} ${S.unit}`, false],
								['총중량', `${fmt(K.plGrossPrinted, 2)} KG`, true],
								['총포장갯수', `${S.packages} CARTONS`, false],
							] as [string, string, boolean][]
						).map(([k, v, bad], i) => (
							<div key={k} style={{display: 'flex', padding: '9px 10px', borderTop: `1px solid ${W.line}`, fontSize: 19, background: bad ? W.redSoft : 'transparent', boxShadow: bad ? `inset 4px 0 0 ${W.red}` : 'none', opacity: ap(f, 200 + i * 6, 10)}}>
								<span style={{width: 150, fontWeight: 700}}>{k}</span>
								<Mono>{v}</Mono>
							</div>
						))}
					</Card>
				</Rise>
			</div>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 5. 설명과 정정 요청: Agent 설명 + 관리자에게 보낼 문서 + 승인 뒤 재검증         */
/* ------------------------------------------------------------------ */
export const AgentFixW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const msg =
		`선하증권 총중량은 ${fmt(K.blGross, 2)} KG, 포장명세서 합계 칸은 ${fmt(K.plGrossPrinted, 2)} KG입니다. ` +
		`포장명세서 품목 합계가 선하증권과 같으므로 합계 칸의 자릿수 오기로 보입니다. ` +
		`컨테이너 번호 ${K.containerPrinted}는 체크디지트가 맞지 않아 선사 확인이 필요합니다.`;
	const btn = {x: 1650, y: 708};
	const cx = interpolate(f, [150, 196], [1300, btn.x], {...clamp, easing: ease});
	const cy = interpolate(f, [150, 196], [960, btn.y], {...clamp, easing: ease});
	const clicked = f >= 204;
	return (
		<Scene dur={dur}>
			<Head step="5단계 · 설명과 정정 요청" title="Agent가 원인을 설명하고 정정을 요청한다" sub="설명은 검증 결과에 있는 값만 쓴다 · 밖으로 나가는 것은 담당자 승인 뒤에만" />
			<Card style={{position: 'absolute', left: 96, top: 330, width: 800, height: 600}}>
				<div style={{display: 'flex', gap: 14, alignItems: 'center'}}>
					<div style={{width: 52, height: 52, borderRadius: 52, background: W.ink, color: '#fff', fontSize: 20, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>AI</div>
					<div>
						<div style={{fontSize: 23, fontWeight: 800}}>문서 처리 Agent</div>
						<div style={{fontSize: 17, color: W.muted}}>검증 도구 결과를 근거로 설명</div>
					</div>
				</div>
				<div style={{marginTop: 24, fontSize: 26, lineHeight: 1.65}}>
					<WType text={msg} at={16} cps={44} />
				</div>
				<div style={{display: 'flex', gap: 10, marginTop: 22, opacity: ap(f, 110, 12)}}>
					<Pill>근거: 선하증권 · 포장명세서</Pill>
					<Pill>규칙 3개</Pill>
				</div>
			</Card>
			<Rise at={96} x={30} y={0} style={{position: 'absolute', left: 940, top: 330, width: 884}}>
				<Card style={{padding: '24px 28px'}}>
					<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
						<span style={{fontSize: 22, fontWeight: 800}}>관리자에게 보낼 문서</span>
						<Status>초안</Status>
					</div>
					<div style={{fontSize: 18, color: W.muted, marginTop: 14}}>받는 곳</div>
					<div style={{fontSize: 21}}>
						{S.shipper} · {S.carrier}
					</div>
					<div style={{fontSize: 18, color: W.muted, marginTop: 12}}>제목</div>
					<div style={{fontSize: 21, fontWeight: 700}}>[정정 요청] B/L {S.blNo} 총중량·컨테이너 번호 확인</div>
					<div style={{fontSize: 19, marginTop: 12, lineHeight: 1.6}}>
						· 포장명세서 합계 G.W. {fmt(K.plGrossPrinted, 2)} KG → {fmt(K.plGrossLineSum, 2)} KG 정정 요청
						<br />· 선하증권 컨테이너 번호 {K.containerPrinted} 확인 요청 (체크디지트 불일치)
					</div>
					<div style={{display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 20}}>
						<div style={{padding: '12px 24px', borderRadius: 999, background: W.fill2, border: `1px solid ${W.line}`, fontSize: 19, fontWeight: 600}}>수정</div>
						<div style={{padding: '12px 26px', borderRadius: 999, background: W.ink, color: '#fff', fontSize: 19, fontWeight: 700, transform: `scale(${clicked ? 1 - 0.04 * (1 - ap(f, 204, 8)) : 1})`}}>
							{clicked ? '✓ 승인 · 보냄' : '담당자 승인 후 보내기'}
						</div>
					</div>
				</Card>
			</Rise>
			<Rise at={236} style={{position: 'absolute', left: 940, top: 790, width: 884}}>
				<Card style={{display: 'flex', alignItems: 'center', gap: 22, padding: '22px 28px', border: `1.5px solid ${W.ink}`}}>
					<span style={{width: 54, height: 54, borderRadius: 54, background: W.ink, color: '#fff', fontSize: 28, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>✓</span>
					<div>
						<div style={{fontSize: 27, fontWeight: 800}}>정정본을 다시 올림 → 다시 대조 통과</div>
						<div style={{fontSize: 19, color: W.muted, marginTop: 4}}>불일치 0건 · 입항 3일 전에 서류 정리 완료</div>
					</div>
				</Card>
			</Rise>
			<svg width={40} height={40} viewBox="0 0 24 24" style={{position: 'absolute', left: cx, top: cy, opacity: ap(f, 148, 8) * (1 - ap(f, 236, 10))}}>
				<path d="M3 2 L3 20 L8 15 L12 22 L15 20 L11 13 L18 13 Z" fill="#fff" stroke="#000" strokeWidth={1.2} />
			</svg>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 6. HS 코드와 신고서: 후보 3개 중 고르기 + 신고서 초안 (빈칸 표시)             */
/* ------------------------------------------------------------------ */
export const HsDeclareW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const hs: string = S.hs6;
	// 후보는 관세청 HS부호 표(data/hs/hs_codes.csv)의 실제 10자리
	void hs;
	const cands = [
		['8507.60-9000', '리튬이온 축전지 · 기타', '품명 칸 LITHIUM-ION BATTERY PACK · 용도 표시 없음'],
		['8507.60-3000', '리튬이온 축전지 · 에너지 저장장치용', '품명 칸 · 용도가 ESS일 때'],
		['8507.60-2000', '리튬이온 축전지 · 전기차용', '품명 칸 · 용도가 전기차일 때'],
	];
	const pick = f >= 150;
	const hsValue = pick ? cands[0][0] : '';
	const rows: [string, string, 'ok' | 'need' | 'hs'][] = [
		['B/L 번호', S.blNo, 'ok'],
		['선기명', S.vessel, 'ok'],
		['수입자', S.consignee, 'ok'],
		['해외공급자', S.shipper, 'ok'],
		['적출국', S.pol, 'ok'],
		['품명', S.item, 'ok'],
		['세번부호', hsValue, 'hs'],
		['수량', `${S.quantity} ${S.unit}`, 'ok'],
		['총중량(kg)', fmt(K.blGross, 2), 'ok'],
		['인도조건', S.incoterms, 'ok'],
		['결제금액', `${S.currency} ${fmt(S.totalAmount, 2)}`, 'ok'],
		['원산지', S.origin, 'ok'],
	];
	return (
		<Scene dur={dur}>
			<Head step="6단계 · HS 코드와 신고서" title="입항 전에 신고 준비를 끝낸다" sub="AI는 HS부호 표의 후보 안에서만 고르고, 확정은 사람이 한다 · 신고서 칸은 코드가 채운다 (과제 기능 ③)" />
			<div style={{position: 'absolute', left: 96, top: 330, width: 780}}>
				<Rise at={6}>
					<Card style={{padding: '20px 24px'}}>
						<div style={{display: 'flex', alignItems: 'center', gap: 12}}>
							<span style={{fontSize: 22, fontWeight: 800}}>1행</span>
							<Status tone={pick ? 'ok' : 'wait'}>{pick ? '사람 확정' : '사람 확인 필요'}</Status>
						</div>
						<Mono style={{display: 'block', fontSize: 20, color: W.muted, marginTop: 8}}>{S.item}</Mono>
						<div style={{marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10}}>
							{cands.map(([code, name, why], i) => {
								const on = pick && i === 0;
								return (
									<Rise key={code} at={30 + i * 14}>
										<div style={{display: 'flex', gap: 14, alignItems: 'center', padding: '14px 16px', borderRadius: 14, background: on ? W.ink2 : W.fill2, color: on ? '#fff' : W.ink}}>
											<span style={{width: 24, height: 24, borderRadius: 24, border: `2px solid ${on ? '#fff' : W.ink}`, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
												{on ? <span style={{width: 12, height: 12, borderRadius: 12, background: '#fff'}} /> : null}
											</span>
											<div>
												<div style={{fontSize: 21, fontWeight: 700}}>
													<Mono>{code}</Mono> <span style={{fontWeight: 500}}>{name}</span>
												</div>
												<div style={{fontSize: 16, color: on ? '#c9c9c9' : W.muted, marginTop: 2}}>근거: {why}</div>
											</div>
										</div>
									</Rise>
								);
							})}
						</div>
						<div style={{fontSize: 17, color: W.muted, marginTop: 14, opacity: ap(f, 170, 10)}}>
							고른 HS는 확정 이력에 남아, 같은 수입자의 같은 품목은 다음부터 자동 확정된다
						</div>
					</Card>
				</Rise>
			</div>
			<Rise at={40} x={30} y={0} style={{position: 'absolute', left: 920, top: 330, width: 904}}>
				<Card style={{padding: '18px 26px'}}>
					<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6}}>
						<span style={{fontSize: 22, fontWeight: 800}}>수입신고서 초안</span>
						<Status>사람 검토 전 초안</Status>
					</div>
					{rows.map(([k, v, kind], i) => {
						const at = 60 + i * 8;
						const blank = kind === 'hs' && !pick;
						return (
							<div key={k} style={{display: 'flex', padding: '6px 0', borderTop: `1px solid ${W.line}`, fontSize: 18, opacity: 0.25 + 0.75 * ap(f, at, 8)}}>
								<div style={{width: 170, fontWeight: 700}}>{k}</div>
								<div style={{flex: 1}}>{blank ? <span style={{color: W.muted}}>비움 · HS 확정 전</span> : <Mono style={{background: kind === 'hs' && pick ? W.fill : 'transparent', padding: '0 4px'}}>{v}</Mono>}</div>
							</div>
						);
					})}
				</Card>
				<Rise at={200} style={{marginTop: 12}}>
					<Pill dark>서류에서 채운 칸마다 출처(서류.칸)를 함께 남긴다 · 실제 신고 전송은 하지 않는다</Pill>
				</Rise>
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 7. 시스템 연동: 가상 WMS 등록 + 대시보드 통관 흐름                          */
/* ------------------------------------------------------------------ */
export const SystemSyncW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const others = (L.delayed as any[]).slice(0, 3);
	const fly = ap(f, 30, 30);
	const flow = [
		['입항', 7],
		['수입신고', 9],
		['심사 중', 4],
		['검사 중', 5],
		['수리', 22],
		['반출', 29],
	] as [string, number][];
	const max = 29;
	return (
		<Scene dur={dur}>
			<Head step="7단계 · 시스템 연동" title="문제가 없으면 사람 손 없이 WMS까지" sub="불일치·확인 필요가 없고 HS가 모두 확정되면 코드가 바로 등록한다 · 실제 시스템은 어댑터만 바꾸면 된다 (과제 기능 ④)" />
			<Card style={{position: 'absolute', left: 96, top: 330, width: 1060, padding: '20px 28px'}}>
				<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
					<span style={{fontSize: 22, fontWeight: 800}}>가상 WMS · 화물 기록</span>
					<span style={{fontSize: 17, color: W.muted}}>DynamoDB · 같은 B/L은 한 번만 들어간다</span>
				</div>
				<div style={{display: 'flex', color: W.muted, fontSize: 17, padding: '12px 0 6px'}}>
					<div style={{width: 230}}>B/L 번호</div>
					<div style={{width: 430}}>수하인</div>
					<div style={{flex: 1}}>상태</div>
				</div>
				<div style={{display: 'flex', alignItems: 'center', fontSize: 21, padding: '12px 0', borderTop: `1px solid ${W.line}`, background: f > 64 ? W.fill2 : 'transparent', opacity: fly, transform: `translateY(${(1 - fly) * -60}px)`}}>
					<Mono style={{width: 230, fontWeight: 800}}>{S.blNo}</Mono>
					<div style={{width: 430}}>{S.consignee}</div>
					<div style={{flex: 1}}>
						<Status tone="ok">등록됨 · 자동</Status>
					</div>
				</div>
				{others.map((r) => (
					<div key={r.id} style={{display: 'flex', alignItems: 'center', fontSize: 21, padding: '12px 0', borderTop: `1px solid ${W.line}`, color: W.muted}}>
						<Mono style={{width: 230}}>{r.bl_no}</Mono>
						<div style={{width: 430}}>{r.consignee}</div>
						<div style={{flex: 1}}>
							<Status>승인 대기</Status>
						</div>
					</div>
				))}
			</Card>
			<Rise at={90} x={30} y={0} style={{position: 'absolute', left: 1196, top: 330, width: 628}}>
				<Card style={{padding: '22px 26px'}}>
					<div style={{fontSize: 22, fontWeight: 800}}>대시보드 · 통관 흐름</div>
					<div style={{fontSize: 16, color: W.muted, marginTop: 2}}>숫자는 서버가 센 값 그대로</div>
					<div style={{marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10}}>
						{flow.map(([name, n], i) => {
							const p = ap(f, 110 + i * 8, 24);
							return (
								<div key={name} style={{display: 'flex', alignItems: 'center', gap: 12, fontSize: 19}}>
									<span style={{width: 90, fontWeight: 700}}>{name}</span>
									<div style={{flex: 1, height: 14, background: W.fill, borderRadius: 14, overflow: 'hidden'}}>
										<div style={{width: `${(n / max) * 100 * p}%`, height: '100%', background: W.ink, borderRadius: 14}} />
									</div>
									<span style={{width: 40, textAlign: 'right', fontWeight: 700}}>
										<Count to={n} at={110 + i * 8} dur={24} />
									</span>
								</div>
							);
						})}
					</div>
				</Card>
			</Rise>
			<Rise at={170} style={{position: 'absolute', left: 96, top: 720, width: 1728}}>
				<Fill style={{display: 'flex', gap: 14, alignItems: 'center', padding: '20px 24px'}}>
					{['선적', '서류 검증·정정', '수입신고 가능', '부산 입항', '심사·수리', '반출'].map((t, i) => (
						<React.Fragment key={t}>
							<Pill dark={i < 3} style={{fontSize: 20}}>
								{i < 3 ? '✓ ' : ''}
								{t}
							</Pill>
							{i < 5 ? <span style={{color: W.muted, fontSize: 22}}>→</span> : null}
						</React.Fragment>
					))}
				</Fill>
			</Rise>
		</Scene>
	);
};

/* ------------------------------------------------------------------ */
/* 8. 현황 조회: AI chat (웹 앱 채팅 화면과 같은 모양)                         */
/* ------------------------------------------------------------------ */
const Bubble: React.FC<{me?: boolean; at: number; children: React.ReactNode}> = ({me, at, children}) => {
	const f = useCurrentFrame();
	const p = ap(f, at, 12);
	return (
		<div style={{display: 'flex', justifyContent: me ? 'flex-end' : 'flex-start', opacity: p, transform: `translateY(${(1 - p) * 14}px)`}}>
			<div style={{maxWidth: 1300, padding: me ? '14px 22px' : '4px 0', borderRadius: 22, fontSize: 26, lineHeight: 1.55, background: me ? W.ink2 : 'transparent', color: me ? '#fff' : W.ink, fontWeight: me ? 600 : 500}}>
				{children}
			</div>
		</div>
	);
};

export const QueryW: React.FC<{dur: number}> = ({dur}) => {
	const f = useCurrentFrame();
	const delayed = L.delayed as any[];
	const q1 = '이번 주 통관 지연 건 알려줘';
	const q2 = '오늘 점심 메뉴 추천해 줘';
	return (
		<Scene dur={dur}>
			<Head step="입항 후 · 현황 조회" title="입항 후에는 말로 묻는다" sub="AI는 질문을 조회 조건으로 바꾸기만 하고, 조회·건수·기간 계산은 코드가 한다 (과제 기능 ⑤)" />
			<div style={{position: 'absolute', left: 96, top: 320, width: 1728, display: 'flex', flexDirection: 'column', gap: 12}}>
				<Bubble me at={6}>
					<WType text={q1} at={10} cps={26} />
				</Bubble>
				<Bubble at={44}>
					이번 주({md(L.weekStart)}~{md(L.weekEnd)}) 통관 지연 건은 <b>{delayed.length}건</b>입니다.
				</Bubble>
				<div style={{display: 'flex', gap: 8, opacity: ap(f, 50, 10)}}>
					<Pill>상태: 통관 지연</Pill>
					<Pill>기간: 이번 주</Pill>
					<Pill dark>{delayed.length}건</Pill>
					<span style={{fontSize: 18, color: W.muted, alignSelf: 'center', marginLeft: 8}}>기준: 입항 후 3일 지나도 수리·반출 아님</span>
				</div>
				<Card style={{padding: '6px 24px', opacity: ap(f, 58, 10)}}>
					{delayed.map((r, i) => (
						<div key={r.id} style={{display: 'flex', fontSize: 19, padding: '9px 0', borderTop: i ? `1px solid ${W.line}` : 'none', opacity: ap(f, 62 + i * 8, 8)}}>
							<Mono style={{width: 220, fontWeight: 700}}>{r.bl_no}</Mono>
							<div style={{width: 440}}>{r.consignee}</div>
							<div style={{width: 120, color: W.muted}}>{r.status}</div>
							<div style={{flex: 1}}>{r.reason}</div>
						</div>
					))}
				</Card>
				<Bubble me at={160}>
					<WType text={q2} at={164} cps={26} />
				</Bubble>
				<div style={{opacity: ap(f, 200, 12), alignSelf: 'flex-start', maxWidth: 1100, padding: '14px 22px', borderRadius: 16, background: W.fill2, color: W.muted, fontSize: 24}}>
					통관·화물 현황 질문만 답합니다. 예: 이번 주 통관 지연 건 몇 건이야?
					<div style={{fontSize: 16, marginTop: 4}}>안내 · 무관한 질문 (가드레일)</div>
				</div>
			</div>
		</Scene>
	);
};

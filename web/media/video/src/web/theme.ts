import {continueRender, delayRender, staticFile} from 'remotion';

// 웹 화면(web/src/styles.css)과 같은 색: 흰 바탕, 검정 글자, 회색 칸, 빨강은 불일치에만
export const W = {
	bg: '#ffffff',
	ink: '#141414',
	ink2: '#2a2a2a',
	muted: '#6f6f6f',
	line: '#e6e6e6',
	fill: '#efefef',
	fill2: '#f6f6f6',
	red: '#d6402a',
	redSoft: '#fdf0ee',
};

export const WFONT = 'Pretendard Team6';
export const WMONO = "'JetBrains Mono', Consolas, 'Courier New', monospace";

let started = false;
export const loadPretendard = () => {
	if (started || typeof document === 'undefined') return;
	started = true;
	const handle = delayRender('Pretendard');
	const face = new FontFace(WFONT, `url(${staticFile('fonts/PretendardVariable.woff2')}) format('woff2')`, {weight: '45 920'});
	face
		.load()
		.then((f) => {
			(document as any).fonts.add(f);
			continueRender(handle);
		})
		.catch((err) => {
			console.error(err);
			continueRender(handle);
		});
};

import {continueRender, delayRender, staticFile} from 'remotion';

export const C = {
	bg: '#0a1120',
	bg2: '#0f1a2e',
	panel: '#121f35',
	panel2: '#18273f',
	line: '#26385a',
	text: '#eaf0f9',
	sub: '#93a4c0',
	dim: '#5f7190',
	accent: '#f59e0b',
	teal: '#2dd4bf',
	red: '#fb5a6e',
	blue: '#60a5fa',
	paper: '#f5f6f8',
};

export const FONT = 'Team6 Noto KR';
export const MONO = "Consolas, 'Courier New', monospace";

let started = false;
export const loadLocalFont = () => {
	if (started || typeof document === 'undefined') {
		return;
	}
	started = true;
	const handle = delayRender('Korean font');
	const face = new FontFace(FONT, `url(${staticFile('fonts/NotoSansKR-VF.ttf')}) format('truetype')`, {
		weight: '100 900',
	});
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

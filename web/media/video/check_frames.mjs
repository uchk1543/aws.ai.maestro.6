// 주요 장면의 정지 프레임을 렌더링해 레이아웃을 확인한다.
// 실행: node check_frames.mjs 120 330 560
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import path from 'node:path';

const frames = process.argv.slice(2).map(Number);
const chromiumOptions = {gl: 'angle'};
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts')});
const composition = await selectComposition({serveUrl, id: 'Workflow', chromiumOptions});
for (const frame of frames) {
	const output = path.resolve('out/frames', `f${String(frame).padStart(4, '0')}.png`);
	await renderStill({composition, serveUrl, output, frame, scale: 0.5, chromiumOptions});
	console.log('rendered', frame);
}

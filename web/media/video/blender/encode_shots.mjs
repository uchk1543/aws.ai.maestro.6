// Blender PNG 프레임(blender/renders/seq/f_####.png)을 장면별 MP4로 묶어 public/blender/ 에 둔다.
// node blender/encode_shots.mjs            -> 4개 모두
// node blender/encode_shots.mjs field gate -> 고른 장면만
import {execFileSync} from 'node:child_process';
import {existsSync, mkdirSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const video = path.resolve(here, '..');
const seq = path.join(here, 'renders', 'seq');
const outDir = path.join(video, 'public', 'blender');
mkdirSync(outDir, {recursive: true});

const SHOTS = {opening: [1, 240], field: [241, 480], gate: [481, 690], outro: [691, 900]};
const pick = process.argv.slice(2);
const names = pick.length ? pick : Object.keys(SHOTS);

for (const name of names) {
	const [a, b] = SHOTS[name];
	const missing = [];
	for (let i = a; i <= b; i++) if (!existsSync(path.join(seq, `f_${String(i).padStart(4, '0')}.png`))) missing.push(i);
	if (missing.length) {
		console.log(`${name}: ${missing.length} frames missing (first ${missing[0]}) - skipped`);
		continue;
	}
	const out = path.join(outDir, `${name}.mp4`);
	execFileSync(
		'npx',
		['remotion', 'ffmpeg', '-y', '-loglevel', 'error', '-framerate', '30', '-start_number', String(a), '-i', path.join(seq, 'f_%04d.png'),
			'-frames:v', String(b - a + 1), '-c:v', 'libx264', '-crf', '14', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out],
		{cwd: video, stdio: 'inherit', shell: true},
	);
	console.log(`${name}: ${b - a + 1} frames -> ${path.relative(video, out)}`);
}

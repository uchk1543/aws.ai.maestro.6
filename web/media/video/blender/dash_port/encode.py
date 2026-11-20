# 렌더한 프레임(frames/f0001.png …)을 대시보드 영상으로 묶는다.
#   port-intro.mp4 : 1~576 (24초, 입항 → 반출)
#   port-loop.mp4  : 577~864 (12초). 앞 24프레임은 865~888 과 겹쳐 섞어 이음매(물결)를 숨긴다
#   port-poster.jpg: 인트로 첫 장 (영상을 받기 전에 보인다)
# 실행: FFMPEG=<ffmpeg 경로> uv run --no-project --with pillow python encode.py <web/public/dashboard 경로>
import os, subprocess, sys, shutil
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, "frames")
FF = os.environ.get("FFMPEG") or "ffmpeg"   # libx264 가 든 ffmpeg
OUT = sys.argv[1]
INTRO, LOOP, XF = 576, 288, 24
TMP = os.path.join(HERE, "loopframes")


def f(n):
    return os.path.join(FR, f"f{n:04d}.png")


def encode(pattern, start, count, out):
    subprocess.run([FF, "-v", "error", "-y", "-framerate", "24", "-start_number", str(start), "-i", pattern,
                    "-frames:v", str(count), "-c:v", "libx264", "-preset", "slow", "-crf", os.environ.get("CRF", "20"),
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out], check=True)


encode(os.path.join(FR, "f%04d.png"), 1, INTRO, os.path.join(OUT, "port-intro.mp4"))

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
for i in range(LOOP):
    a = Image.open(f(INTRO + 1 + i)).convert("RGB")
    if i < XF:
        b = Image.open(f(INTRO + LOOP + 1 + i)).convert("RGB")
        a = Image.blend(b, a, (i + 1) / (XF + 1))
    a.save(os.path.join(TMP, f"l{i:04d}.png"))
encode(os.path.join(TMP, "l%04d.png"), 0, LOOP, os.path.join(OUT, "port-loop.mp4"))
Image.open(f(1)).convert("RGB").save(os.path.join(OUT, "port-poster.jpg"), quality=92)
for n in ("port-intro.mp4", "port-loop.mp4", "port-poster.jpg"):
    print(n, os.path.getsize(os.path.join(OUT, n)))

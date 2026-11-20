"""태블릿 화면 이미지 (카메라 앱으로 포장명세서를 찍는 화면).

uv run --with pillow python blender/make_tablet_screen.py
출력: blender/assets/tablet_screen.png (화면 비율 0.24 x 0.17 m 에 맞춘 1680 x 1190)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
VIDEO = ROOT.parent
W, H = 1680, 1190
GREEN = (52, 211, 153)

font_path = str(VIDEO / "public" / "fonts" / "NotoSansKR-VF.ttf")


def font(size, weight="Bold"):
    f = ImageFont.truetype(font_path, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


# 1) 카메라에 비친 장면: 어두운 책상 위 서류
img = Image.new("RGB", (W, H), (46, 49, 53))
desk = Image.effect_noise((W, H), 18).convert("RGB")
img = Image.blend(img, desk, 0.12)

doc = Image.open(VIDEO / "public" / "docs" / "scan_pl.jpg").convert("RGB")
dh = int(H * 0.86)
dw = int(doc.width * dh / doc.height)
doc = doc.resize((dw, dh), Image.LANCZOS)
dx, dy = (W - 260 - dw) // 2 + 20, (H - dh) // 2 + 20
shadow = Image.new("L", (W, H), 0)
ImageDraw.Draw(shadow).rectangle([dx + 14, dy + 18, dx + dw + 14, dy + dh + 18], fill=150)
shadow = shadow.filter(ImageFilter.GaussianBlur(22))
img.paste((10, 10, 12), mask=shadow)
img.paste(doc, (dx, dy))

# 비네팅
vig = Image.new("L", (W, H), 0)
ImageDraw.Draw(vig).ellipse([-W * 0.25, -H * 0.3, W * 1.25, H * 1.3], fill=255)
vig = vig.filter(ImageFilter.GaussianBlur(120))
img = Image.composite(img, Image.new("RGB", (W, H), (8, 8, 10)), vig)

d = ImageDraw.Draw(img, "RGBA")

# 2) 문서 인식 모서리 표시
pad, L, t = 14, 90, 12
x0, y0, x1, y1 = dx - pad, dy - pad, dx + dw + pad, dy + dh + pad
for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
    d.rectangle(sorted([cx, cx + sx * L]) and [min(cx, cx + sx * L), min(cy, cy + sy * t), max(cx, cx + sx * L), max(cy, cy + sy * t)], fill=GREEN)
    d.rectangle([min(cx, cx + sx * t), min(cy, cy + sy * L), max(cx, cx + sx * t), max(cy, cy + sy * L)], fill=GREEN)
d.rectangle([x0, y0, x1, y1], outline=GREEN + (90,), width=3)

# 인식 배지
f1 = font(46)
label = "포장명세서 인식됨"
tw = d.textlength(label, font=f1)
bx, by = x0 + (x1 - x0 - tw - 96) // 2, y1 - 120
d.rounded_rectangle([bx, by, bx + tw + 96, by + 74], radius=37, fill=(16, 24, 20, 225))
d.ellipse([bx + 26, by + 25, bx + 50, by + 49], fill=GREEN)
d.text((bx + 66, by + 9), label, font=f1, fill=(255, 255, 255))

# 3) 상단 상태줄
d.rectangle([0, 0, W, 64], fill=(0, 0, 0, 150))
f2 = font(34, "Medium")
d.text((28, 12), "09:41", font=f2, fill=(255, 255, 255))
d.text((W - 430, 12), "LTE   업로드 대기 2", font=f2, fill=(255, 255, 255))

# 4) 오른쪽 촬영 바
d.rectangle([W - 250, 64, W, H], fill=(0, 0, 0, 170))
cx, cy = W - 125, H // 2
d.ellipse([cx - 82, cy - 82, cx + 82, cy + 82], outline=(255, 255, 255), width=10)
d.ellipse([cx - 64, cy - 64, cx + 64, cy + 64], fill=(255, 255, 255))
thumb = doc.resize((96, int(96 * dh / dw)))
ty = cy + 200
d.rounded_rectangle([cx - 54, ty - 6, cx + 54, ty + thumb.height + 6], radius=10, fill=(255, 255, 255))
img.paste(thumb, (cx - 48, ty))
f3 = font(30, "Medium")
d.text((cx - d.textlength("문서", font=f3) / 2, cy - 200), "문서", font=f3, fill=(255, 214, 10))
d.text((cx - d.textlength("사진", font=f3) / 2, cy - 260), "사진", font=f3, fill=(200, 200, 200))

out = ROOT / "assets" / "tablet_screen.png"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out)
print(out, img.size)

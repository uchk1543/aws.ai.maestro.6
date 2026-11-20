"""시연영상(#272) 화면 녹화: Chrome을 Playwright로 움직이고, 브라우저가 보내는 화면 프레임(CDP screencast)을 모은다.

- 바탕화면을 찍지 않는다. 창이 가려지거나 다른 일을 해도 페이지 화면만 1920×1080으로 남는다 (headless).
- 주소창은 편집에서 실제 주소(page.url)로 브라우저 틀을 그려 얹는다. 주소는 markers.json에 함께 남긴다.
- 장면마다 녹화 시작부터의 초를 markers.json에 남긴다. 편집(Remotion Demo)은 이 표로 자른다.
- 클릭 위치가 보이도록 페이지에 작은 커서를 그려 넣는다 (Playwright 클릭은 실제 마우스를 움직이지 않는다).
- 내려받은 문서(통지 문서 html, 검수 완료서 pdf)는 같은 탭에서 열어 보여 준 뒤 돌아온다.

쓰는 법:
  uv run --with playwright --with pymupdf python record/record.py --base http://localhost:5173 --out record/dry     (목업 시험)
  uv run --with playwright --with pymupdf python record/record.py --base https://dx8a8z83slbmk.cloudfront.net --out record/take1
배포본 녹화는 PM이 reset_demo로 비운 뒤에 한다. 업로드·HS 선택·승인은 배포본에서 실제로 일어난다.
"""

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe"
SAMPLES = ROOT.parents[2] / "samples" / "dev"  # 저장소의 samples/dev (web/media/video 기준 세 단계 위)
APPROVER = "6팀 관리자"
HS = {"D003": {1: "9401699000", 2: "9403609090"}, "D064": {1: "6907210000"}}
VIEW_W, VIEW_H, DPR = 1600, 900, 1.2  # 프레임 1920×1080

CURSOR_JS = """
(() => {
  if (window.__cursor) return;
  const make = () => {
    const c = document.createElement('div');
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l16 9-7 2-3 7z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'-40px', top:'-40px', zIndex: 2147483647, pointerEvents:'none',
      transition:'left .55s cubic-bezier(.3,.7,.2,1), top .55s cubic-bezier(.3,.7,.2,1)', filter:'drop-shadow(0 2px 3px rgba(0,0,0,.35))'});
    document.documentElement.appendChild(c);
    const r = document.createElement('div');
    Object.assign(r.style, {position:'fixed', width:'34px', height:'34px', marginLeft:'-17px', marginTop:'-17px', borderRadius:'50%',
      border:'2px solid rgba(0,100,255,.9)', zIndex: 2147483646, pointerEvents:'none', opacity:'0', transform:'scale(.4)'});
    document.documentElement.appendChild(r);
    window.__cursor = {
      move(x, y) { c.style.left = (x - 3) + 'px'; c.style.top = (y - 2) + 'px'; try { sessionStorage.setItem('__cur', x + ',' + y); } catch (e) {} },
      ripple(x, y) { r.style.left = x + 'px'; r.style.top = y + 'px'; r.style.transition = 'none'; r.style.opacity = '1'; r.style.transform = 'scale(.4)';
        requestAnimationFrame(() => requestAnimationFrame(() => { r.style.transition = 'opacity .45s, transform .45s'; r.style.opacity = '0'; r.style.transform = 'scale(1.6)'; })); },
    };
    let last = [];
    try { last = (sessionStorage.getItem('__cur') || '').split(','); } catch (e) {}
    if (last.length === 2) { c.style.transition = 'none'; window.__cursor.move(+last[0], +last[1]); requestAnimationFrame(() => c.style.transition = ''); }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', make); else make();
})();
"""


class Screencast:
    """CDP Page.startScreencast 프레임을 파일로 모으고, 장면 표지를 남긴다."""

    def __init__(self, page: Page, out: Path):
        self.page, self.out = page, out
        self.frames: list[tuple[float, str]] = []
        self.marks: list[dict] = []
        self.t0: float | None = None
        (out / "frames").mkdir(parents=True, exist_ok=True)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev):
        ts = ev["metadata"].get("timestamp") or time.time()
        if self.t0 is None:
            self.t0 = ts
        name = f"frames/{len(self.frames):06d}.jpg"
        (self.out / name).write_bytes(base64.b64decode(ev["data"]))
        self.frames.append((ts - self.t0, name))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:
            pass

    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        self.page.wait_for_timeout(800)

    def now(self) -> float:
        return round(self.frames[-1][0] if self.frames else 0.0, 2)

    def mark(self, scene: str, note: str = ""):
        # 표지 시각은 '지금 화면'의 시각. 브라우저 시계 기준이라 마지막 프레임 시각 + 경과로 어림한다
        t = round(time.time() - (self.t0 or time.time()), 2) if self.t0 else 0.0
        self.marks.append({"scene": scene, "t": t, "url": self.page.url, "note": note})
        print(f"[mark] {t:7.2f}s {scene} {note}", flush=True)
        (self.out / "markers.json").write_text(json.dumps(self.marks, ensure_ascii=False, indent=1), encoding="utf-8")

    def stop(self):
        try:
            self.page.wait_for_timeout(600)
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        self.encode()

    def encode(self):
        """변할 때만 오는 프레임을 시간대로 늘여 30fps 영상으로 (concat 길이 목록)."""
        if not self.frames:
            return
        lines = []
        for i, (t, name) in enumerate(self.frames):
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else t + 1.0
            lines.append(f"file '{name}'\nduration {max(nxt - t, 0.001):.4f}")
        lines.append(f"file '{self.frames[-1][1]}'")
        (self.out / "frames.txt").write_text("\n".join(lines), encoding="utf-8")
        subprocess.run(
            [str(FFMPEG), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "frames.txt",
             "-vsync", "cfr", "-r", "30", "-s", "1920x1080", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
             "-pix_fmt", "yuv420p", "screen.mp4"],
            cwd=self.out, check=True,
        )
        print(f"[encode] {len(self.frames)} frames → {self.out / 'screen.mp4'} ({self.frames[-1][0]:.1f}s)", flush=True)


class Demo:
    def __init__(self, page: Page, cast: Screencast, base: str, out: Path, dry: bool):
        self.page, self.cast, self.base, self.out, self.dry = page, cast, base, out, dry

    def pause(self, s: float):
        self.page.wait_for_timeout(int(s * 1000))  # 이벤트(프레임)를 받으며 기다린다

    def point(self, locator, click=True, settle=0.7):
        """커서를 요소 가운데로 옮기고(보이게) 누른다."""
        locator.scroll_into_view_if_needed(timeout=15_000)
        self.pause(0.3)
        box = locator.bounding_box()
        if box:
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            self.page.evaluate("([x,y]) => window.__cursor && window.__cursor.move(x,y)", [x, y])
            self.pause(0.7)
            if click:
                self.page.evaluate("([x,y]) => window.__cursor && window.__cursor.ripple(x,y)", [x, y])
        if click:
            locator.click()
        self.pause(settle)

    def scroll(self, dy: int, steps=30):
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.pause(0.03)

    def nav(self, label: str, settle=2.5):
        self.point(self.page.get_by_role("button", name=label, exact=True), settle=settle)

    def stage(self, label: str, settle=1.5):
        self.point(self.page.get_by_role("tab", name=label).first, settle=settle)

    def wait_done(self, limit=180):
        """작업 처리가 끝날 때까지 (다음 할 일이 '처리 중'이 아닐 때까지)."""
        end = time.monotonic() + limit
        while time.monotonic() < end:
            body = self.page.inner_text("body")
            if "처리 중입니다" not in body and any(w in body for w in ("승인 대기", "끝남", "완료", "실패")):
                return True
            self.pause(1.0)
        print("[warn] 처리 대기 시간 초과", flush=True)
        return False

    def upload(self, set_id: str) -> str:
        self.nav("파일 업로드", settle=1.5)
        files = sorted((SAMPLES / set_id).iterdir())
        self.page.locator('input[type="file"]').set_input_files([str(f) for f in files])
        self.pause(1.8)
        self.point(self.page.get_by_role("button", name=f"{len(files)}개 업로드"))
        self.page.wait_for_url("**/#/jobs/*", timeout=60_000)
        job_id = self.page.url.split("/jobs/")[-1]
        print(f"[job] {set_id} → {job_id}", flush=True)
        return job_id

    def choose_hs(self, answers: dict[int, str]):
        self.stage("3. HS 코드")
        for line, hs in answers.items():
            radio = self.page.locator(f'input[name="hs-{line}"][value="{hs}"]')
            if radio.count():
                self.point(radio.first, settle=0.6)
            else:  # 후보에 없으면 직접 입력
                box = self.page.get_by_label(f"{line}행 HS 직접 입력")
                self.point(box)
                box.type(hs, delay=90)
        self.pause(0.8)
        self.point(self.page.get_by_role("button", name="고른 HS 확정").first, settle=2.5)

    def show_download(self, trigger, hold=5.0):
        """내려받은 문서를 같은 탭에서 열어 보여 준 뒤 돌아온다. PDF는 쪽 그림으로 바꿔 띄운다."""
        back = self.page.url
        with self.page.expect_download() as info:
            self.point(trigger)
        dl = info.value
        target = self.out / "downloads" / dl.suggested_filename
        target.parent.mkdir(exist_ok=True)
        dl.save_as(target)
        if target.suffix.lower() == ".pdf":
            import fitz

            doc = fitz.open(target)
            imgs = []
            for i, pg in enumerate(doc):
                if i >= 2:
                    break
                png = target.with_name(f"{target.stem}.p{i + 1}.png")
                pg.get_pixmap(dpi=110).save(png)
                imgs.append(png.name)
            html = target.with_suffix(".view.html")
            html.write_text(
                "<!doctype html><meta charset=utf-8><body style='margin:0;background:#525659;text-align:center'>"
                + "".join(f"<img src='{n}' style='width:62%;margin:24px auto;display:block;box-shadow:0 4px 18px rgba(0,0,0,.4)'>" for n in imgs),
                encoding="utf-8",
            )
            target = html
        self.page.goto(target.resolve().as_uri())
        self.pause(hold)
        self.scroll(500)
        self.pause(2.0)
        self.page.goto(back)
        self.pause(2.0)

    def run(self):
        page, mark = self.page, self.cast.mark
        page.goto(f"{self.base}/#/dashboard")
        self.pause(3.0)
        mark("s2_upload_d003")
        d003 = self.upload("D003")
        mark("s2_processing", d003)
        self.wait_done()
        mark("s2_done", d003)
        self.pause(2.5)

        mark("s3_dashboard")
        self.nav("대시보드")
        self.point(page.get_by_role("button", name="오류 서류").first, settle=2.0)
        self.point(page.locator(".dash-job").first, settle=2.5)

        mark("s4_review", page.url)
        self.stage("2. 서류 대조")
        cell = page.locator(".review-side .issue button").first
        if cell.count():
            self.point(cell, settle=2.5)
        self.show_download(page.get_by_role("link", name="관리자에게 보낼 문서 받기"))

        mark("s5_hs")
        if self.dry:
            self.stage("3. HS 코드", settle=2.0)
        else:
            self.choose_hs(HS["D003"])
        self.stage("4. 신고서 초안", settle=2.5)
        self.scroll(400)
        self.pause(1.5)

        mark("s6_upload_d054")
        d054 = self.upload("D054")
        self.wait_done()
        mark("s6_d054_done", d054)
        self.stage("3. HS 코드", settle=2.5)
        self.stage("5. WMS 등록", settle=2.5)
        mark("s6_upload_d064")
        d064 = self.upload("D064")
        self.wait_done()
        mark("s6_d064_done", d064)
        self.nav("대시보드", settle=3.0)

        mark("s7_hs_pending")
        self.point(page.get_by_role("button", name="HS 미작성").first, settle=2.0)
        rows = page.locator(".dash-job")
        if rows.count():
            self.point(rows.first, settle=2.5)
        else:  # 목록이 비면(목업 등) 방금 올린 작업으로
            page.goto(f"{self.base}/#/jobs/{d064}")
            self.pause(2.5)
        if not self.dry:
            self.choose_hs(HS["D064"])
        self.stage("2. 서류 대조", settle=2.5)
        self.stage("5. WMS 등록", settle=1.2)
        name = page.get_by_label("승인자")
        self.point(name)
        name.type(APPROVER, delay=110)
        self.pause(0.6)
        if not self.dry:
            self.point(page.get_by_role("button", name="승인하고 WMS 등록"), settle=3.0)
            mark("s7_approved", d064)
            self.show_download(page.get_by_role("link", name="검수 완료서 받기"), hold=4.0)

        mark("s8_dashboard")
        self.nav("대시보드", settle=3.0)
        self.scroll(700, steps=60)
        self.pause(3.0)
        mark("end")


def main(base: str, out: Path):
    dry = "localhost" in base
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--lang=ko-KR", "--hide-scrollbars"])
        context = browser.new_context(
            viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=DPR, accept_downloads=True, locale="ko-KR"
        )
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        cast = Screencast(page, out)
        cast.start()
        try:
            Demo(page, cast, base, out, dry).run()
        except Exception as exc:  # 녹화는 남기고 어디서 멈췄는지 적는다
            cast.mark("error", f"{type(exc).__name__}: {exc}"[:300])
            raise
        finally:
            cast.stop()
            context.close()
            browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    main(a.base.rstrip("/"), Path(a.out))

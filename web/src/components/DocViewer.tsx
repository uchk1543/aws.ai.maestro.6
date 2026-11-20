// G11·G16 서류 보기: 서버가 준 쪽 그림 위에 표시(bbox, 0~1 비율)를 박스로 그린다.
// 위치는 계산하지 않는다. 받은 bbox 를 화면에서만 조금 넓혀(padBox) % 로 놓는다. 서버 값은 그대로다.
// 박스를 누르면 그 부분을 돋보기처럼 크게 보여 주고(zoomRegion), 아래에 무엇을 읽었는지(이름 · 값 · 설명)를 적는다.
// 태블릿·PC 는 박스 옆에 꼬리 달린 상자로, 모바일은 화면 아래 시트로 연다.
import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { DocMark, JobFileView } from "../types";
import { Icon } from "./Icon";

export type BoxTone = "mismatch" | "ink" | "soft";

export interface Box {
  id: string;
  mark: DocMark;
  tone: BoxTone;
  label: string;
  /** 팝업에 덧붙일 설명 줄 (서버 값 그대로. 예: 근거 문장, 다른 서류의 값) */
  detail?: string[];
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const pct = (v: number) => `${(v * 100).toFixed(3)}%`;

type Bbox = DocMark["bbox"];

/**
 * 박스 여백 (G16). Textract 박스는 글자에 딱 붙어 있어 화면에서는 글자 가장자리가 밖으로 걸쳐 보인다.
 * 사방으로 max(박스 높이 × heightRatio, 쪽 크기 × pageRatio) 만큼 넓힌다. 화면 표시만 바꾼다.
 */
export const MARK_PAD = { heightRatio: 0.25, pageRatio: 0.004 };
/** 돋보기 범위: 넓힌 박스를 한 번 더 이만큼(박스 높이 배수) 넓혀 앞뒤 맥락을 보이고, 너무 작으면 쪽 너비의 minWidth 까지 키운다 */
export const ZOOM = { contextRatio: 1.2, minWidth: 0.22, minAspect: 1.6, maxAspect: 4.5 };

/** 0~1 범위 [left, top, width, height] 로 자른다. */
function clip(l: number, t: number, w: number, h: number): Bbox {
  const L = clamp01(l);
  const T = clamp01(t);
  return [L, T, Math.max(0, Math.min(l + w, 1) - L), Math.max(0, Math.min(t + h, 1) - T)];
}

/**
 * 박스를 사방으로 넓힌다. ar 은 쪽의 가로/세로 (가로 여백을 세로와 같은 픽셀 길이로 맞추려고). 쪽 밖은 잘라 낸다.
 * 예: 높이 0.02 박스 → 위아래 max(0.005, 0.004) = 0.005 씩.
 */
export function padBox(bbox: Bbox, ar = 1, pad = MARK_PAD): Bbox {
  const [l, t, w, h] = bbox.map(clamp01);
  const py = Math.max(h * pad.heightRatio, pad.pageRatio);
  const px = Math.max((h * pad.heightRatio) / ar, pad.pageRatio);
  return clip(l - px, t - py, w + 2 * px, h + 2 * py);
}

/** bbox(0~1) → CSS 위치(%). 화면에서 조금 넓히고(padBox) 0~1 밖의 값은 잘라 낸다. */
export function boxStyle(bbox: Bbox, ar = 1): { left: string; top: string; width: string; height: string } {
  const [l, t, w, h] = padBox(bbox, ar);
  return { left: pct(l), top: pct(t), width: pct(w), height: pct(h) };
}

/**
 * 돋보기로 잘라 볼 범위 (쪽 기준 0~1). 넓힌 박스를 맥락만큼 더 넓히고, 너무 작은 박스는 쪽 너비 minWidth 까지 키워
 * 배율을 제한한다(작은 그림을 너무 키우면 깨져 보인다). 가로/세로 비는 minAspect~maxAspect 안으로 맞추고,
 * 쪽 밖으로 나가면 잘라 내지 않고 안쪽으로 민다.
 */
export function zoomRegion(bbox: Bbox, ar = 1, zoom = ZOOM): Bbox {
  const [pl, pt, pw, ph] = padBox(bbox, ar);
  const cy = pt + ph / 2;
  const cx = pl + pw / 2;
  let h = ph + 2 * ph * zoom.contextRatio;
  let w = pw + (2 * ph * zoom.contextRatio) / ar;
  w = Math.max(w, zoom.minWidth);
  // 픽셀 기준 가로/세로 비 = (w × 쪽 가로) / (h × 쪽 세로) = w × ar / h
  const aspect = (w * ar) / h;
  if (aspect < zoom.minAspect) w = (zoom.minAspect * h) / ar;
  if (aspect > zoom.maxAspect) h = (w * ar) / zoom.maxAspect;
  w = Math.min(w, 1);
  h = Math.min(h, 1);
  // 쪽 너비에 막혀 넓히지 못했으면 세로를 줄여 비를 맞춘다 (넓힌 박스보다는 작아지지 않게)
  if ((w * ar) / h < zoom.minAspect) h = Math.max(ph, (w * ar) / zoom.minAspect);
  const l = Math.min(Math.max(cx - w / 2, 0), 1 - w);
  const t = Math.min(Math.max(cy - h / 2, 0), 1 - h);
  return [l, t, w, h];
}

/** 확대 범위 안에서 그림을 놓을 자리(%)와, 그 안에 원래 인식 범위를 그릴 자리(%). */
export function lensLayout(bbox: Bbox, region: Bbox) {
  const [rl, rt, rw, rh] = region;
  const [l, t, w, h] = bbox.map(clamp01);
  return {
    image: { width: pct(1 / rw), left: pct(-rl / rw), top: pct(-rt / rh) },
    mark: { left: pct((l - rl) / rw), top: pct((t - rt) / rh), width: pct(w / rw), height: pct(h / rh) },
    /** 화면 그림 가로 대비 몇 배인지 (안내용) */
    scale: 1 / rw,
  };
}

/** 팝업 자리: 박스가 위쪽이면 박스 아래, 아래쪽이면 박스 위. 왼쪽 반이면 박스 왼쪽 끝에, 오른쪽 반이면 오른쪽 끝에 맞춘다. */
export function popStyle(bbox: DocMark["bbox"]): CSSProperties {
  const [l, t, w, h] = bbox.map(clamp01);
  const style: CSSProperties = {};
  if (t + h / 2 < 0.6) style.top = `calc(${pct(Math.min(t + h, 1))} + 8px)`;
  else style.bottom = `calc(${pct(1 - t)} + 8px)`;
  if (l + w / 2 < 0.5) style.left = pct(l);
  else style.right = pct(Math.max(0, 1 - (l + w)));
  return style;
}

/**
 * PDF 원본을 iframe 으로 띄울 주소. 브라우저 PDF 보기의 검은 도구 막대·쪽 목록을 끄고 쪽 너비에 맞춘다
 * (Chrome·Edge 가 따른다. 미리 서명된 주소의 ?조건은 그대로 두고 #조각만 붙인다).
 */
export function pdfViewSrc(url: string): string {
  return `${url.split("#")[0]}#toolbar=0&navpanes=0&statusbar=0&messages=0&view=FitH`;
}

/** 꼬리 방향: 상자가 박스 아래에 있으면 위를, 위에 있으면 아래를 가리킨다. 왼쪽·오른쪽 끝 맞춤도 같이. */
export function popSide(bbox: Bbox): string {
  const [l, t, w, h] = bbox.map(clamp01);
  const below = t + h / 2 < 0.6;
  const left = l + w / 2 < 0.5;
  return `pop-${below ? "below" : "above"} pop-${left ? "left" : "right"}`;
}

/** 돋보기: 쪽 그림에서 확대 범위만 잘라 크게 보이고, 원래 인식 범위를 얇은 선으로 그린다. */
function Lens({ src, bbox, ar, label }: { src: string; bbox: Bbox; ar: number; label: string }) {
  const region = zoomRegion(bbox, ar);
  const { image, mark } = lensLayout(bbox, region);
  return (
    <div className="lens" style={{ aspectRatio: `${region[2] * ar} / ${region[3]}` }} data-testid="lens">
      <img className="lens-img" src={src} alt={`확대: ${label}`} style={image} draggable={false} />
      <span className="lens-mark" style={mark} aria-hidden="true" />
    </div>
  );
}

export function DocViewer({
  file,
  boxes,
  activeId,
  onSelect,
  note,
}: {
  file: JobFileView;
  boxes: Box[];
  activeId: string | null;
  onSelect?: (id: string) => void;
  note?: string | null;
}) {
  const activeRef = useRef<HTMLButtonElement>(null);
  // 닫기를 누른 박스. 같은 박스를 다시 누르거나 다른 박스를 고르면 팝업이 다시 뜬다
  const [closedId, setClosedId] = useState<string | null>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [activeId, file.key]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setClosedId(activeId);
    // 바깥을 누르면 닫는다. 박스를 누른 것은 박스가 처리한다 (다른 박스로 바로 바뀜)
    const onDown = (e: PointerEvent) => {
      const target = e.target as Element | null;
      if (!target?.closest?.(".mark-pop, .mark")) setClosedId(activeId);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [activeId]);

  return (
    <div className="viewer">
      {note && (
        <p className="viewer-note" role="status">
          {note}
        </p>
      )}
      {file.pages.length === 0 ? (
        // 쪽 그림이 없으면(PDF를 아직 그리지 않은 서버) 원본을 그대로 띄운다. 박스는 그리지 않는다
        file.url && file.content_type === "application/pdf" ? (
          <div className="viewer-pdf">
            <iframe className="viewer-original" src={pdfViewSrc(file.url)} title={`${file.file_name} 원본`} />
          </div>
        ) : file.url && file.content_type?.startsWith("image/") ? (
          <img className="viewer-original" src={file.url} alt={`${file.file_name} 원본`} />
        ) : (
          <p className="empty">이 서류의 그림이 없습니다.</p>
        )
      ) : (
        file.pages.map((page, i) => {
          const pageNo = i + 1;
          const onPage = boxes.filter((b) => b.mark.page === pageNo);
          const open = onPage.find((b) => b.id === activeId && closedId !== b.id) ?? null;
          const ar = page.width / page.height;
          return (
            <figure
              key={pageNo}
              className="viewer-page"
              // --ar: 가로/세로. 쓸 수 있는 높이(--fit-h)가 정해진 곳에서는 그 높이에 맞춰 너비를 줄인다 (한 화면에 한 쪽이 다 보이게)
              style={{ aspectRatio: `${page.width} / ${page.height}`, "--ar": page.width / page.height } as CSSProperties}
            >
              <img src={page.url} alt={`${file.file_name} ${pageNo}쪽`} />
              {onPage.map((b) => {
                const active = b.id === activeId;
                return (
                  <button
                    key={b.id}
                    ref={active ? activeRef : undefined}
                    type="button"
                    className={`mark mark-${b.tone}${active ? " active" : ""}`}
                    style={boxStyle(b.mark.bbox, ar)}
                    aria-label={`${b.label}: ${b.mark.text}`}
                    aria-pressed={active}
                    onClick={() => {
                      setClosedId(null);
                      onSelect?.(b.id);
                    }}
                  />
                );
              })}
              {open && (
                <div
                  className={`mark-pop mark-pop-${open.tone} ${popSide(open.mark.bbox)}`}
                  role="dialog"
                  aria-label={open.label}
                  style={popStyle(padBox(open.mark.bbox, ar))}
                >
                  <Lens src={page.url} bbox={open.mark.bbox} ar={ar} label={open.mark.text} />
                  <div className="mark-pop-head">
                    <span className="mark-pop-label">{open.label}</span>
                    <button type="button" className="mark-pop-close" aria-label="팝업 닫기" onClick={() => setClosedId(open.id)}>
                      <Icon name="close" size={18} />
                    </button>
                  </div>
                  <p className="mark-pop-text">{open.mark.text}</p>
                  {open.detail?.map((line) => (
                    <p key={line} className="mark-pop-detail">
                      {line}
                    </p>
                  ))}
                </div>
              )}
              {file.pages.length > 1 && <figcaption className="hint">{pageNo}쪽</figcaption>}
            </figure>
          );
        })
      )}
    </div>
  );
}

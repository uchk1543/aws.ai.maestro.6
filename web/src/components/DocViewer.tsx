// G11 서류 보기: 서버가 준 쪽 그림 위에 표시(bbox, 0~1 비율)를 박스로 그린다.
// 위치는 계산하지 않는다. 받은 bbox 를 % 로 바꿔 그대로 놓는다. 강조한 박스는 보이는 곳으로 스크롤한다.
// 박스를 누르면 그 자리에 작은 팝업으로 무엇을 읽었는지(이름 · 값 · 설명)를 보여 준다. 모바일에서 긴 목록 대신 쓴다.
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

/** bbox(0~1) → CSS 위치(%). 0~1 밖의 값은 잘라 낸다. */
export function boxStyle(bbox: DocMark["bbox"]): { left: string; top: string; width: string; height: string } {
  const [l, t, w, h] = bbox.map(clamp01);
  return { left: pct(l), top: pct(t), width: pct(Math.min(w, 1 - l)), height: pct(Math.min(h, 1 - t)) };
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
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
                    style={boxStyle(b.mark.bbox)}
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
                <div className={`mark-pop mark-pop-${open.tone}`} role="dialog" aria-label={open.label} style={popStyle(open.mark.bbox)}>
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

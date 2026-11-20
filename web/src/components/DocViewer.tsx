// G11 서류 보기: 서버가 준 쪽 그림 위에 표시(bbox, 0~1 비율)를 박스로 그린다.
// 위치는 계산하지 않는다. 받은 bbox 를 % 로 바꿔 그대로 놓는다. 강조한 박스는 보이는 곳으로 스크롤한다.
import { useEffect, useRef } from "react";
import type { DocMark, JobFileView } from "../types";

export type BoxTone = "mismatch" | "ink" | "soft";

export interface Box {
  id: string;
  mark: DocMark;
  tone: BoxTone;
  label: string;
}

/** bbox(0~1) → CSS 위치(%). 0~1 밖의 값은 잘라 낸다. */
export function boxStyle(bbox: DocMark["bbox"]): { left: string; top: string; width: string; height: string } {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  const [l, t, w, h] = bbox.map(clamp);
  const pct = (v: number) => `${(v * 100).toFixed(3)}%`;
  return { left: pct(l), top: pct(t), width: pct(Math.min(w, 1 - l)), height: pct(Math.min(h, 1 - t)) };
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

  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [activeId, file.key]);

  return (
    <div className="viewer">
      {note && (
        <p className="viewer-note" role="status">
          {note}
        </p>
      )}
      {file.pages.length === 0 ? (
        <p className="empty">이 서류의 그림이 없습니다.</p>
      ) : (
        file.pages.map((page, i) => {
          const pageNo = i + 1;
          const onPage = boxes.filter((b) => b.mark.page === pageNo);
          return (
            <figure key={pageNo} className="viewer-page" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
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
                    onClick={() => onSelect?.(b.id)}
                  >
                    {active && <span className="mark-tag">{b.label}</span>}
                  </button>
                );
              })}
              {file.pages.length > 1 && <figcaption className="hint">{pageNo}쪽</figcaption>}
            </figure>
          );
        })
      )}
    </div>
  );
}

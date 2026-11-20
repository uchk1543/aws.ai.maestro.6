// G11 문서 분류 내역에서 서류 하나를 누르면 여는 창: 서류 그림 위에 분류 근거(제목·특징 칸)와 읽은 값을 박스로 보여 준다.
// 종류·근거 문장·표시 위치는 서버 값 그대로다. 화면은 다시 분류하지 않는다.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { getJobFiles } from "../api";
import { navigate } from "../route";
import type { ClassifiedBy, DocMark, DocumentRecord } from "../types";
import { DocViewer, type Box } from "./DocViewer";
import { Icon } from "./Icon";

const BY_KO: Record<ClassifiedBy, string> = { model: "AI 자동 분류", user: "사용자가 고름" };

export function DocDetail({
  record,
  kindLabel,
  statusLabel,
  onClose,
}: {
  record: DocumentRecord;
  kindLabel: string;
  statusLabel: string;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["job-files", record.job_id],
    queryFn: () => getJobFiles(record.job_id),
    retry: false,
  });
  const file = query.data?.files.find((f) => f.key === record.key) ?? null;
  const marks = file?.marks ?? [];
  const reasonMarks = marks.filter((m) => m.kind !== "field");
  const fieldMarks = marks.filter((m) => m.kind === "field");
  const idOf = (m: DocMark) => `${marks.indexOf(m)}`;
  const [activeId, setActiveId] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const boxes: Box[] = marks.map((m) => ({
    id: idOf(m),
    mark: m,
    tone: m.kind === "field" ? "soft" : "ink",
    label: m.kind === "field" ? m.label : `분류 근거 · ${m.label}`,
  }));

  const markButton = (m: DocMark) => (
    <li key={idOf(m)}>
      <button
        type="button"
        className={activeId === idOf(m) ? "mark-row active" : "mark-row"}
        aria-pressed={activeId === idOf(m)}
        onClick={() => setActiveId(idOf(m))}
      >
        <span className="mark-row-label">{m.label}</span>
        <span className="mark-row-text">{m.text}</span>
      </button>
    </li>
  );

  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="doc-detail-title">
        <header className="sheet-head">
          <div className="sheet-title">
            <span className="tag dark">{kindLabel}</span>
            <h2 id="doc-detail-title">{record.file_name}</h2>
          </div>
          <button ref={closeRef} type="button" className="sheet-close" aria-label="닫기" onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>

        <div className="sheet-body">
          <div className="sheet-doc">
            {query.isPending && (
              <p className="hint" role="status">
                서류를 불러오는 중…
              </p>
            )}
            {query.error && (
              <p className="hint" role="alert">
                서류 그림을 불러오지 못했습니다: {query.error.message}
              </p>
            )}
            {query.isSuccess && !file && <p className="hint">이 서류의 그림이 없습니다.</p>}
            {file && <DocViewer file={file} boxes={boxes} activeId={activeId} onSelect={setActiveId} />}
          </div>

          <div className="sheet-info">
            <section>
              <h3>분류 결과</h3>
              <dl className="info-list">
                <div>
                  <dt>종류</dt>
                  <dd>{kindLabel}</dd>
                </div>
                <div>
                  <dt>분류</dt>
                  <dd>{BY_KO[record.classified_by]}</dd>
                </div>
                <div>
                  <dt>근거</dt>
                  <dd>{record.reason}</dd>
                </div>
              </dl>
            </section>

            {reasonMarks.length > 0 && (
              <section>
                <h3>근거가 된 곳</h3>
                <ul className="mark-list" aria-label="근거가 된 곳">
                  {reasonMarks.map(markButton)}
                </ul>
              </section>
            )}

            {fieldMarks.length > 0 && (
              <section>
                <h3>읽은 값</h3>
                <ul className="mark-list" aria-label="읽은 값">
                  {fieldMarks.map(markButton)}
                </ul>
              </section>
            )}

            <section>
              <h3>작업</h3>
              <dl className="info-list">
                <div>
                  <dt>작업</dt>
                  <dd>{record.job_id}</dd>
                </div>
                <div>
                  <dt>상태</dt>
                  <dd>
                    <span className={`status status-${record.job_status}`}>{statusLabel}</span>
                  </dd>
                </div>
                <div>
                  <dt>올린 날짜</dt>
                  <dd>{record.created_at}</dd>
                </div>
              </dl>
              <button type="button" className="primary block" onClick={() => navigate(`/jobs/${encodeURIComponent(record.job_id)}`)}>
                작업 화면 열기
              </button>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

// G11 문서 분류 내역의 서류 카드 한 장: 왼쪽 서류 원본(쪽 그림) | 오른쪽 인식 결과.
// 서류 그림 위에 분류 근거(제목·특징 칸)와 읽은 값을 박스로 보여 주고, 오른쪽 목록을 누르면 그 박스를 강조한다.
// 종류·근거 문장·표시 위치·서류 번호는 서버 값 그대로다. 화면은 다시 분류하지 않는다.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getJobFiles } from "../api";
import { navigate } from "../route";
import type { ClassifiedBy, DocMark, DocumentRecord } from "../types";
import { DocViewer, type Box } from "./DocViewer";

const BY_KO: Record<ClassifiedBy, string> = { model: "AI 자동 분류", user: "사용자가 고름" };

export function DocCard({
  record,
  kindLabel,
  statusLabel,
  load,
}: {
  record: DocumentRecord;
  kindLabel: string;
  statusLabel: string;
  /** 지금 보는 카드와 그 양옆만 서류 그림을 불러온다 */
  load: boolean;
}) {
  const query = useQuery({
    queryKey: ["job-files", record.job_id],
    queryFn: () => getJobFiles(record.job_id),
    enabled: load,
    retry: false,
  });
  const file = query.data?.files.find((f) => f.key === record.key) ?? null;
  const marks = file?.marks ?? [];
  const reasonMarks = marks.filter((m) => m.kind !== "field");
  const fieldMarks = marks.filter((m) => m.kind === "field");
  const idOf = (m: DocMark) => `${marks.indexOf(m)}`;
  const [activeId, setActiveId] = useState<string | null>(null);

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
    <article className="doc-card" aria-label={record.file_name}>
      <header className="doc-card-head">
        <span className="tag dark">{kindLabel}</span>
        <h3>{record.file_name}</h3>
        <span className={`status status-${record.job_status}`}>{statusLabel}</span>
      </header>

      <div className="doc-card-body">
        <div className="doc-card-doc">
          {query.isPending && load && (
            <p className="hint" role="status">
              서류를 불러오는 중…
            </p>
          )}
          {query.error && (
            <p className="hint doc-card-missing" role="alert">
              서류 원본을 불러오지 못했습니다: {query.error.message}
            </p>
          )}
          {query.isSuccess && !file && <p className="hint doc-card-missing">이 서류의 원본 그림이 없습니다.</p>}
          {file && <DocViewer file={file} boxes={boxes} activeId={activeId} onSelect={setActiveId} />}
        </div>

        <div className="doc-card-info">
          <section>
            <h4>분류 결과</h4>
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
              <h4>근거가 된 곳</h4>
              <ul className="mark-list" aria-label="근거가 된 곳">
                {reasonMarks.map(markButton)}
              </ul>
            </section>
          )}

          {fieldMarks.length > 0 && (
            <section>
              <h4>읽은 값</h4>
              <ul className="mark-list" aria-label="읽은 값">
                {fieldMarks.map(markButton)}
              </ul>
            </section>
          )}

          <section>
            <h4>서류 정보</h4>
            <dl className="info-list">
              <div>
                <dt>서류 번호</dt>
                <dd>{record.doc_no ?? "-"}</dd>
              </div>
              <div>
                <dt>수하인</dt>
                <dd>{record.consignee ?? "-"}</dd>
              </div>
              <div>
                <dt>작업</dt>
                <dd>{record.job_id}</dd>
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
    </article>
  );
}

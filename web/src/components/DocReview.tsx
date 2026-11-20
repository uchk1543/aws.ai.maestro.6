// G11·G12 작업 화면 위변조 확인: 왼쪽 서류 원본 | 오른쪽 오류 목록과 그 서류의 읽은 칸 표.
// 오류(또는 서류별 값)를 누르면 그 서류로 바꾸고, 원본의 칸 위치에 박스를, 읽은 칸 표의 그 줄을 강조한다.
// 등급·근거 문장·raw 는 서버 값 그대로 쓴다. 칸 위치는 서버가 준 표시(mark)에서 field 이름이 같은 것을 찾을 뿐이다.
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { DOC_TYPE_KO, type DocType, type Grade, type Issue, type IssueCell, type JobFileView } from "../types";
import { DocViewer, type Box } from "./DocViewer";
import { CHECKED_BY_KO, GRADE_CLASS, sortByGrade } from "./IssueList";

/** 오류 칸 하나에 맞는 서류와 표시. 서류 종류와 칸 이름(field)이 같은 것을 찾는다. */
export function locate(files: JobFileView[], cell: IssueCell) {
  const file = files.find((f) => f.doc_type === cell.doc) ?? null;
  const mark = file?.marks.find((m) => m.kind === "field" && m.field === cell.field) ?? null;
  return { file, mark };
}

const cellId = (i: number, c: number) => `${i}:${c}`;

/** 읽은 칸 한 줄에 걸린 오류: 그 칸을 짚은 첫 오류(등급 순으로 정렬된 목록 기준). */
interface FieldHit {
  i: number;
  c: number;
  issue: Issue;
}

/** 서류 하나에서 칸 이름 → 그 칸을 짚은 오류. 같은 칸을 여러 오류가 짚으면 등급이 높은(앞) 것. */
export function hitsFor(sorted: Issue[], doc: DocType | null): Map<string, FieldHit> {
  const hits = new Map<string, FieldHit>();
  sorted.forEach((issue, i) =>
    issue.cells.forEach((cell, c) => {
      if (cell.doc === doc && !hits.has(cell.field)) hits.set(cell.field, { i, c, issue });
    }),
  );
  return hits;
}

const ROW_TONE: Record<Grade, string> = { 불일치: "row-mismatch", "확인 필요": "row-check", 참고: "row-note" };

export function DocReview({ issues, files }: { issues: Issue[]; files: JobFileView[] }) {
  const sorted = useMemo(() => sortByGrade(issues), [issues]);
  const firstCell = (issue: Issue) => Math.max(0, issue.cells.findIndex((c) => c.doc === issue.suspect));
  const [active, setActive] = useState<{ i: number; c: number }>(() => ({ i: 0, c: sorted[0] ? firstCell(sorted[0]) : 0 }));
  const activeCell = sorted[active.i]?.cells[active.c] ?? null;
  const [viewDoc, setViewDoc] = useState<DocType | null>(activeCell?.doc ?? files[0]?.doc_type ?? null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const activeRowRef = useRef<HTMLTableRowElement>(null);

  const file = files.find((f) => f.doc_type === viewDoc) ?? null;

  // 지금 보는 서류에 걸린 오류 칸마다 박스 하나 (불일치는 빨강, 나머지는 검정)
  const boxes: Box[] = [];
  sorted.forEach((issue, i) =>
    issue.cells.forEach((cell, c) => {
      if (cell.doc !== viewDoc) return;
      const { mark } = locate(files, cell);
      if (!mark) return;
      // 팝업: 근거 문장과 서류별 값(서버 값 그대로)
      const detail = [issue.evidence, ...issue.cells.map((x) => `${DOC_TYPE_KO[x.doc]} ${x.raw ?? "못 읽음"}`)];
      boxes.push({ id: cellId(i, c), mark, tone: issue.grade === "불일치" ? "mismatch" : "ink", label: `${issue.grade} · ${mark.label}`, detail });
    }),
  );

  const activeId = activeCell && activeCell.doc === viewDoc ? cellId(active.i, active.c) : null;
  const hits = hitsFor(sorted, viewDoc);
  const activeField = activeCell && activeCell.doc === viewDoc ? activeCell.field : null;

  // 고른 칸의 줄을 읽은 칸 표 안에서 보이게 한다
  useEffect(() => {
    activeRowRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [activeField, viewDoc]);
  const missing = activeCell && activeCell.doc === viewDoc && !boxes.some((b) => b.id === activeId);

  function select(i: number, c: number) {
    setActive({ i, c });
    setViewDoc(sorted[i].cells[c].doc);
    // 한 칸 배치(모바일·태블릿)에서는 서류가 위에 있으므로 서류로 올라간다
    if (typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1199px)").matches) {
      viewerRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    }
  }

  const issueCount = (doc: DocType) => sorted.reduce((n, issue) => n + issue.cells.filter((c) => c.doc === doc).length, 0);

  return (
    <div className="panel review">
      <div className="review-head">
        <h2>오류 목록 ({issues.length})</h2>
        {/* 관리자에게 보낼 불일치 통지 문서. C7(#158)·F9(#155)가 들어오면 연결한다 */}
        <button type="button" className="review-admin" disabled aria-describedby="review-admin-note">
          관리자에게 보낼 문서 받기
        </button>
        <span id="review-admin-note" className="hint">
          준비 중
        </span>
      </div>
      <div className="review-grid">
        <div className="review-doc" ref={viewerRef}>
          <div className="doc-tabs" role="tablist" aria-label="서류">
            {files.map((f) => (
              <button
                key={f.key}
                type="button"
                role="tab"
                aria-selected={f.doc_type === viewDoc}
                className={f.doc_type === viewDoc ? "doc-tab active" : "doc-tab"}
                onClick={() => setViewDoc(f.doc_type)}
              >
                {DOC_TYPE_KO[f.doc_type]}
                {issueCount(f.doc_type) > 0 && <span className="doc-tab-count">{issueCount(f.doc_type)}</span>}
              </button>
            ))}
          </div>
          {file ? (
            <DocViewer
              file={file}
              boxes={boxes}
              activeId={activeId}
              onSelect={(id) => {
                const [i, c] = id.split(":").map(Number);
                setActive({ i, c });
              }}
              note={missing ? `이 칸(${activeCell!.field})의 위치를 찾지 못했습니다.` : null}
            />
          ) : (
            <p className="empty">이 서류의 그림이 없습니다.</p>
          )}
        </div>

        <div className="review-side">
          {/* 왼쪽 서류 탭과 같은 높이로 두어, 오류 카드 위쪽이 서류 그림 위쪽과 맞게 한다 */}
          <p className="review-side-head">
            <strong>오류 {issues.length}건</strong>
            <span className="hint">값을 누르면 서류에서 위치를 보여 줍니다</span>
          </p>
          <ul className="review-list" aria-label="오류">
          {sorted.map((issue, i) => (
            <li key={`${issue.rule_id}-${i}`} className={active.i === i ? "review-item active" : "review-item"}>
              <div className="issue-head">
                <span className={`grade ${GRADE_CLASS[issue.grade]}`}>{issue.grade}</span>
                <span className="issue-evidence">{issue.evidence}</span>
              </div>
              <div className="value-tiles">
                {issue.cells.map((cell, c) => {
                  const on = active.i === i && active.c === c;
                  const suspect = issue.suspect === cell.doc;
                  return (
                    <button
                      key={c}
                      type="button"
                      className={on ? "value-tile active" : "value-tile"}
                      aria-pressed={on}
                      onClick={() => select(i, c)}
                    >
                      <span className="value-doc">
                        {DOC_TYPE_KO[cell.doc]}
                        {suspect && <span className="value-suspect"> · 다른 쪽</span>}
                      </span>
                      <span className="value-raw">{cell.raw ?? "못 읽음"}</span>
                      <code className="value-field">{cell.field}</code>
                    </button>
                  );
                })}
              </div>
              <p className="issue-meta">
                규칙 <code>{issue.rule_id}</code> · {CHECKED_BY_KO[issue.checked_by]}
              </p>
            </li>
          ))}
          </ul>

          <ReadTable
            file={file}
            hits={hits}
            activeField={activeField}
            activeRowRef={activeRowRef}
            onPick={(hit) => select(hit.i, hit.c)}
          />
        </div>
      </div>
    </div>
  );
}

/** 오른쪽 아래: 지금 보는 서류의 읽은 칸 표 (서버 fields 그대로). 오류가 짚은 칸은 등급 색과 근거 문장·확인 방법을 붙인다. */
function ReadTable({
  file,
  hits,
  activeField,
  activeRowRef,
  onPick,
}: {
  file: JobFileView | null;
  hits: Map<string, FieldHit>;
  activeField: string | null;
  activeRowRef: RefObject<HTMLTableRowElement | null>;
  onPick: (hit: FieldHit) => void;
}) {
  const fields = file?.fields ?? [];
  const name = file ? DOC_TYPE_KO[file.doc_type] : "서류";
  return (
    <section className="read-fields" aria-label={`${name} 읽은 칸`}>
      <p className="review-side-head">
        <strong>읽은 칸 · {name}</strong>
        <span className="hint">{fields.length > 0 ? `${fields.length}칸, 빨간 줄이 불일치` : ""}</span>
      </p>
      {fields.length === 0 ? (
        <p className="empty">이 서류의 읽은 칸이 없습니다.</p>
      ) : (
        <table className="read-table">
          <thead>
            <tr>
              <th scope="col">칸</th>
              <th scope="col">읽은 값</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => {
              const hit = hits.get(f.field);
              const on = activeField === f.field;
              const cls = [hit ? ROW_TONE[hit.issue.grade] : "", on ? "active" : ""].filter(Boolean).join(" ");
              return (
                <tr key={f.field} ref={on ? activeRowRef : undefined} className={cls || undefined} aria-current={on ? "true" : undefined}>
                  <th scope="row">
                    {hit ? (
                      <button type="button" className="read-pick" onClick={() => onPick(hit)}>
                        {f.label}
                      </button>
                    ) : (
                      f.label
                    )}
                    <code className="read-key">{f.field}</code>
                  </th>
                  <td>
                    {f.raw ?? <span className="read-missing">못 읽음{f.unreadable ? ` · ${f.unreadable}` : ""}</span>}
                    {hit && (
                      <span className="read-issue">
                        <span className={`grade ${GRADE_CLASS[hit.issue.grade]}`}>{hit.issue.grade}</span> {hit.issue.evidence}
                        <span className="read-how">{CHECKED_BY_KO[hit.issue.checked_by]}</span>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

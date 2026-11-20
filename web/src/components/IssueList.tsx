// G4 결과 화면: 오류 목록 (result.issues). 등급·근거·서류·칸·raw·확인 방법을 보여 준다.
// 등급과 근거 문장은 서버 코드가 만든 값을 그대로 쓴다. 화면은 판정하지 않는다.
import { DOC_TYPE_KO, type CheckedBy, type Grade, type Issue } from "../types";

const GRADE_ORDER: Grade[] = ["불일치", "확인 필요", "참고"];
const GRADE_CLASS: Record<Grade, string> = { 불일치: "grade-mismatch", "확인 필요": "grade-check", 참고: "grade-note" };

const CHECKED_BY_KO: Record<CheckedBy, string> = {
  pdf_text: "PDF 글자로 다시 확인",
  textract: "Textract OCR로 다시 확인",
  model_reread: "모델에게 다시 물어 확인",
  none: "다시 확인 안 함",
};

/** 불일치 → 확인 필요 → 참고 순서. 같은 등급 안에서는 서버가 준 순서를 지킨다. */
export function sortByGrade(issues: Issue[]): Issue[] {
  return issues
    .map((issue, i) => ({ issue, i }))
    .sort((a, b) => GRADE_ORDER.indexOf(a.issue.grade) - GRADE_ORDER.indexOf(b.issue.grade) || a.i - b.i)
    .map((x) => x.issue);
}

export function IssueList({ issues }: { issues: Issue[] }) {
  const counts = GRADE_ORDER.map((g) => ({ g, n: issues.filter((i) => i.grade === g).length })).filter((c) => c.n > 0);

  return (
    <div className="panel">
      <h2>오류 목록 ({issues.length})</h2>
      {issues.length === 0 ? (
        <p className="empty">찾은 문제가 없습니다.</p>
      ) : (
        <>
          <p className="grade-counts">
            {counts.map((c) => (
              <span key={c.g} className={`grade ${GRADE_CLASS[c.g]}`}>
                {c.g} {c.n}
              </span>
            ))}
          </p>
          <ul className="issues">
            {sortByGrade(issues).map((issue, i) => (
              <li key={`${issue.rule_id}-${i}`} className="issue">
                <div className="issue-head">
                  <span className={`grade ${GRADE_CLASS[issue.grade]}`}>{issue.grade}</span>
                  <span className="issue-evidence">{issue.evidence}</span>
                </div>
                <table className="cells">
                  <thead>
                    <tr>
                      <th>서류</th>
                      <th>칸</th>
                      <th>서류에 적힌 값</th>
                    </tr>
                  </thead>
                  <tbody>
                    {issue.cells.map((c, j) => (
                      <tr key={j} className={issue.suspect === c.doc ? "suspect" : undefined}>
                        <td>
                          {DOC_TYPE_KO[c.doc]}
                          {issue.suspect === c.doc && <span className="warn"> (의심)</span>}
                        </td>
                        <td>
                          <code>{c.field}</code>
                        </td>
                        <td>{c.raw ?? <span className="hint">못 읽음</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="issue-meta">
                  규칙 <code>{issue.rule_id}</code> · {CHECKED_BY_KO[issue.checked_by]}
                  {issue.suspect && <> · 다른 서류와 다른 쪽: {DOC_TYPE_KO[issue.suspect]}</>}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

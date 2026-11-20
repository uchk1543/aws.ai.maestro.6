// G6 결과 화면: 신고서 초안 표 (result.declaration_draft).
// 칸 값은 서버 코드(draft_declaration)가 채운 그대로 보여 준다. 실제 신고 전송은 하지 않는다 (agent-design.md 7번).
import type { DeclarationDraft } from "../types";

export function DeclarationTable({ draft }: { draft: DeclarationDraft | null }) {
  return (
    <div className="panel">
      <h2>신고서 초안</h2>
      <p className="draft-banner" role="note">
        사람 검토 전 초안입니다. 실제 신고 전송은 하지 않습니다.
      </p>

      {!draft ? (
        <p className="empty">아직 신고서 초안이 없습니다.</p>
      ) : (
        <>
          {draft.fields.length === 0 ? (
            <p className="empty">채운 칸이 없습니다.</p>
          ) : (
            <table className="cells declaration">
              <thead>
                <tr>
                  <th>칸</th>
                  <th>값</th>
                  <th>출처</th>
                </tr>
              </thead>
              <tbody>
                {draft.fields.map((f, i) => (
                  <tr key={`${f.name}-${i}`}>
                    <td>{f.name}</td>
                    <td>{f.value ?? <span className="hint">(값 없음)</span>}</td>
                    <td>
                      <code>{f.source}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {draft.blank_fields.length > 0 && (
            <div className="blank-fields">
              <h3>비워 둔 칸 ({draft.blank_fields.length})</h3>
              <p className="hint">확인 필요·불일치가 남았거나 HS가 확정되지 않아 채우지 않은 칸입니다.</p>
              <ul>
                {draft.blank_fields.map((b) => (
                  <li key={b}>
                    <code>{b}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {draft.pdf_url && /^https?:\/\//.test(draft.pdf_url) && (
            <p>
              <a href={draft.pdf_url} target="_blank" rel="noreferrer">
                PDF 받기
              </a>
            </p>
          )}
        </>
      )}
    </div>
  );
}

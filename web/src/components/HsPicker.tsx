// G5 결과 화면: HS 선택 (result.hs). '사람 확인 필요' 품목은 후보 3개 중 하나를 골라 보낸다.
// 확정 조건과 후보는 서버 코드가 정한다. 화면은 사람이 고른 값을 보내기만 한다 (agent-design.md 6번).
// FB07-c: 행 제목에 품명·서류 HS(서버 값 그대로)를 보이고, 후보가 모두 틀리면 10자리를 직접 넣는다.
//         HS부호 표에 있는 코드인지는 서버가 검사한다 (#209). 화면은 숫자 10자리인지만 본다.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { chooseHs, hsRequestUrl } from "../api";
import type { HSBy, HSResult, JobStatus } from "../types";

const BY_KO: Record<HSBy, string> = {
  history: "확정 이력",
  auto_match: "서류 HS와 추천 1순위 일치",
  human: "사람이 고름",
};

/** 직접 입력: 점·줄표·빈칸을 빼고 숫자만. 10자리가 아니면 null (보내기를 막는다) */
export function manualHs(text: string): string | null {
  const digits = text.replace(/[\s.-]/g, "");
  return /^[0-9]{10}$/.test(digits) ? digits : null;
}

/** 행 제목: "1행 · 품명 (서류 HS 9401.61)". 서버가 품명·서류 HS를 주지 않으면 "1행" */
export function lineTitle(r: HSResult): string {
  const name = r.item_name ? ` · ${r.item_name}` : "";
  const doc = r.doc_hs_code ? ` (서류 HS ${r.doc_hs_code})` : "";
  return `${r.line}행${name}${doc}`;
}

const MANUAL = "manual";

/** 1234567890 → 1234.56-7890 (읽기 쉽게만 바꾼다. 보내는 값은 숫자 10자리 그대로) */
export function formatHs(code: string): string {
  return /^[0-9]{10}$/.test(code) ? `${code.slice(0, 4)}.${code.slice(4, 6)}-${code.slice(6)}` : code;
}

export function HsPicker({ jobId, jobStatus, results }: { jobId: string; jobStatus: JobStatus; results: HSResult[] }) {
  const queryClient = useQueryClient();
  // 행마다 고른 후보 HS, 또는 MANUAL(직접 입력)
  const [picked, setPicked] = useState<Record<number, string>>({});
  const [typed, setTyped] = useState<Record<number, string>>({});
  const choices = Object.entries(picked).map(([line, v]) => ({
    line: Number(line),
    hs: v === MANUAL ? manualHs(typed[Number(line)] ?? "") : v,
  }));
  const invalidManual = choices.some((c) => c.hs === null);
  const mutation = useMutation({
    mutationFn: () => chooseHs(jobId, choices.map((c) => ({ line: c.line, hs: c.hs as string }))),
    onSuccess: async () => {
      setPicked({});
      setTyped({});
      // 서버가 HS 결과·단계 기록·신고서 초안을 바꿨으므로 작업을 다시 불러온다
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    },
  });

  const pending = results.filter((r) => r.status === "사람 확인 필요");
  const canChoose = jobStatus === "waiting_approval";
  const pickedCount = Object.keys(picked).length;

  return (
    <div className="panel">
      <h2>HS 코드</h2>
      {results.length === 0 ? (
        <p className="empty">HS 결과가 아직 없습니다.</p>
      ) : (
        <ul className="hs-list">
          {results.map((r) => (
            <li key={r.line} className="hs-item">
              <div className="hs-head">
                <strong>{lineTitle(r)}</strong>
                <span className={r.status === "사람 확인 필요" ? "grade grade-check" : "grade grade-ok"}>{r.status}</span>
                {r.hs_code && <code className="hs-code">{formatHs(r.hs_code)}</code>}
                {r.by && <span className="hint">{BY_KO[r.by]}</span>}
              </div>

              {r.status === "사람 확인 필요" && (
                  <fieldset className="hs-candidates" disabled={!canChoose || mutation.isPending}>
                    <legend>{r.line}행 후보</legend>
                    {r.candidates.length === 0 && <p className="empty">후보가 없습니다. 서류의 품명 칸을 확인하고 직접 입력해 주세요.</p>}
                    {r.candidates.map((c) => (
                      <label key={c.hs} className="hs-candidate">
                        <input
                          type="radio"
                          name={`hs-${r.line}`}
                          value={c.hs}
                          checked={picked[r.line] === c.hs}
                          onChange={() => setPicked((p) => ({ ...p, [r.line]: c.hs }))}
                        />
                        <span>
                          <code>{formatHs(c.hs)}</code> {c.name}
                          <span className="hs-reason">{c.reason}</span>
                        </span>
                      </label>
                    ))}
                    <label className="hs-candidate hs-manual">
                      <input
                        type="radio"
                        name={`hs-${r.line}`}
                        value={MANUAL}
                        checked={picked[r.line] === MANUAL}
                        onChange={() => setPicked((p) => ({ ...p, [r.line]: MANUAL }))}
                      />
                      <span>
                        직접 입력 (10자리)
                        <input
                          type="text"
                          inputMode="numeric"
                          className="hs-manual-input"
                          aria-label={`${r.line}행 HS 직접 입력`}
                          placeholder="예: 8507609000"
                          maxLength={14}
                          value={typed[r.line] ?? ""}
                          onFocus={() => setPicked((p) => ({ ...p, [r.line]: MANUAL }))}
                          onChange={(e) => {
                            const v = e.target.value;
                            setTyped((t) => ({ ...t, [r.line]: v }));
                            setPicked((p) => ({ ...p, [r.line]: MANUAL }));
                          }}
                        />
                        {picked[r.line] === MANUAL && (typed[r.line] ?? "") !== "" && !manualHs(typed[r.line] ?? "") && (
                          <span className="hs-reason warn">숫자 10자리로 적어 주세요</span>
                        )}
                      </span>
                    </label>
                  </fieldset>
                )}
            </li>
          ))}
        </ul>
      )}

      {pending.length > 0 && (
        <div className="hs-actions">
          {/* HS를 서류에서 확정하지 못한 품목을 관세사에게 알릴 PDF (X2 #260). 서버가 만든다 */}
          <p className="hs-request">
            <a className="hs-request-link" href={hsRequestUrl(jobId)} download>
              HS 확인 요청서 받기
            </a>
            <span className="hint">관세사에게 전달할 문서입니다 (품목 {pending.length}개)</span>
          </p>
          {!canChoose && <p className="hint">HS는 승인 대기 중인 작업에서만 고를 수 있습니다.</p>}
          {mutation.error && (
            <p className="error" role="alert">
              {mutation.error.message}
            </p>
          )}
          <button
            type="button"
            className="primary"
            disabled={!canChoose || pickedCount === 0 || invalidManual || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "보내는 중…" : `고른 HS 확정 (${pickedCount}/${pending.length})`}
          </button>
        </div>
      )}
    </div>
  );
}

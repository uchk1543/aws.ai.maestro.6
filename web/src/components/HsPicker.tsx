// G5 결과 화면: HS 선택 (result.hs). '사람 확인 필요' 품목은 후보 3개 중 하나를 골라 보낸다.
// 확정 조건과 후보는 서버 코드가 정한다. 화면은 사람이 고른 값을 보내기만 한다 (agent-design.md 6번).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { chooseHs } from "../api";
import type { HSBy, HSResult, JobStatus } from "../types";

const BY_KO: Record<HSBy, string> = {
  history: "확정 이력",
  auto_match: "서류 HS와 추천 1순위 일치",
  human: "사람이 고름",
};

/** 1234567890 → 1234.56-7890 (읽기 쉽게만 바꾼다. 보내는 값은 숫자 10자리 그대로) */
export function formatHs(code: string): string {
  return /^[0-9]{10}$/.test(code) ? `${code.slice(0, 4)}.${code.slice(4, 6)}-${code.slice(6)}` : code;
}

export function HsPicker({ jobId, jobStatus, results }: { jobId: string; jobStatus: JobStatus; results: HSResult[] }) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Record<number, string>>({});
  const mutation = useMutation({
    mutationFn: () =>
      chooseHs(
        jobId,
        Object.entries(picked).map(([line, hs]) => ({ line: Number(line), hs })),
      ),
    onSuccess: async () => {
      setPicked({});
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
                <strong>{r.line}행</strong>
                <span className={r.status === "사람 확인 필요" ? "grade grade-check" : "grade grade-ok"}>{r.status}</span>
                {r.hs_code && <code className="hs-code">{formatHs(r.hs_code)}</code>}
                {r.by && <span className="hint">{BY_KO[r.by]}</span>}
              </div>

              {r.status === "사람 확인 필요" &&
                (r.candidates.length === 0 ? (
                  <p className="empty">후보가 없습니다. 서류의 품명 칸을 확인해 주세요.</p>
                ) : (
                  <fieldset className="hs-candidates" disabled={!canChoose || mutation.isPending}>
                    <legend>{r.line}행 후보</legend>
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
                  </fieldset>
                ))}
            </li>
          ))}
        </ul>
      )}

      {pending.length > 0 && (
        <div className="hs-actions">
          {!canChoose && <p className="hint">HS는 승인 대기 중인 작업에서만 고를 수 있습니다.</p>}
          {mutation.error && (
            <p className="error" role="alert">
              {mutation.error.message}
            </p>
          )}
          <button
            type="button"
            className="primary"
            disabled={!canChoose || pickedCount === 0 || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "보내는 중…" : `고른 HS 확정 (${pickedCount}/${pending.length})`}
          </button>
        </div>
      )}
    </div>
  );
}

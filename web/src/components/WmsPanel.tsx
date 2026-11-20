// G7 결과 화면: WMS 상태와 승인 (result.wms, POST /api/jobs/{id}/approve).
// 등록할 수 있는지는 서버가 정한다. 불일치가 남은 건은 서버가 409 로 거절하고, 화면은 안내만 한다 (agent-design.md 8번).
// FB01-b: 서버 배포 전·옛 작업은 승인 대기인데 result.wms 가 null 이다. 그때도 승인 입력을 보인다 (서버가 다시 검사한다).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, approveJob } from "../api";
import type { JobStatus, WmsBy, WmsState } from "../types";

const BY_KO: Record<WmsBy, string> = { auto: "자동 등록", human: "사람 승인" };

export function WmsPanel({ jobId, jobStatus, wms }: { jobId: string; jobStatus: JobStatus; wms: WmsState | null }) {
  const queryClient = useQueryClient();
  const [approver, setApprover] = useState("");
  const mutation = useMutation({
    mutationFn: () => approveJob(jobId, approver.trim()),
    onSuccess: async () => {
      // 서버가 WMS 상태·단계 기록을 바꿨으므로 작업을 다시 불러온다
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    },
  });

  const conflict = mutation.error instanceof ApiError && mutation.error.status === 409;
  // wms 가 없어도 작업이 승인 대기면 승인 대기로 본다 (FB01-b)
  const waiting = jobStatus === "waiting_approval" && (wms === null || wms.status === "승인 대기");
  const shown: WmsState | null = wms ?? (waiting ? { status: "승인 대기", by: null, wms_id: null } : null);
  const canApprove = waiting;

  return (
    <div className="panel">
      <h2>WMS 등록</h2>
      {!shown ? (
        <p className="empty">WMS 상태가 아직 없습니다.</p>
      ) : (
        <p className="wms-state">
          <span className={shown.status === "등록됨" ? "grade grade-ok" : "grade grade-check"}>{shown.status}</span>
          {shown.by && <span className="hint">{BY_KO[shown.by]}</span>}
          {shown.wms_id && (
            <span>
              WMS 번호 <code>{shown.wms_id}</code>
            </span>
          )}
        </p>
      )}

      {canApprove && (
        <form
          className="wms-approve"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <label>
            승인자
            <input
              type="text"
              value={approver}
              maxLength={50}
              disabled={mutation.isPending}
              onChange={(e) => setApprover(e.target.value)}
            />
          </label>
          <button type="submit" className="primary" disabled={approver.trim() === "" || mutation.isPending}>
            {mutation.isPending ? "등록하는 중…" : "승인하고 WMS 등록"}
          </button>
        </form>
      )}

      {conflict && (
        <div className="wms-conflict" role="alert">
          <strong>WMS에 등록하지 못했습니다.</strong>
          <p>불일치가 남은 건은 승인해도 등록하지 않습니다. 서류를 고쳐 다시 올려 주세요.</p>
          <p className="hint">서버: {mutation.error?.message}</p>
        </div>
      )}
      {mutation.error && !conflict && (
        <p className="error" role="alert">
          {mutation.error.message}
        </p>
      )}
    </div>
  );
}

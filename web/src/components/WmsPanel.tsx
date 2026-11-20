// G7 결과 화면: WMS 상태와 승인 (result.wms, POST /api/jobs/{id}/approve).
// 등록할 수 있는지는 서버가 정한다. 불일치가 남은 건은 서버가 409 로 거절한다 (agent-design.md 8번).
// 판독 오류 예외: 서류는 맞는데 판독이 틀린 불일치는, 검수자가 원본을 확인했다고 체크하고 사유를 적으면 승인할 수 있다.
// FB01-b: 서버 배포 전·옛 작업은 승인 대기인데 result.wms 가 null 이다. 그때도 승인 입력을 보인다 (서버가 다시 검사한다).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, approveJob, certificateUrl } from "../api";
import type { JobStatus, WmsBy, WmsState } from "../types";

const BY_KO: Record<WmsBy, string> = { auto: "자동 등록", human: "사람 승인" };
export const OVERRIDE_REASON_MAX = 200; // 서버 api/handler.py OVERRIDE_REASON_MAX 와 같다

export function WmsPanel({
  jobId,
  jobStatus,
  wms,
  blocked = null,
}: {
  jobId: string;
  jobStatus: JobStatus;
  wms: WmsState | null;
  /** 불일치가 남은 이유 (FB22). 있으면 판독 오류 확인 체크와 사유를 채워야 승인 버튼이 켜진다 */
  blocked?: string | null;
}) {
  const queryClient = useQueryClient();
  const [approver, setApprover] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const overriding = Boolean(blocked);
  const overrideReady = !overriding || (confirmed && reason.trim() !== "");
  const mutation = useMutation({
    mutationFn: () => (overriding ? approveJob(jobId, approver.trim(), reason.trim()) : approveJob(jobId, approver.trim())),
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

      {/* 사람이 승인해 등록한 작업만 검수 완료서를 받는다 (X1 #258). 자동 등록은 검수자가 없어 링크를 숨긴다 */}
      {shown?.status === "등록됨" && shown.by === "human" && (
        <p className="wms-certificate">
          {shown.approver && (
            <span className="hint">
              검수자 {shown.approver}
              {shown.approved_at ? ` · ${shown.approved_at.slice(0, 16).replace("T", " ")}` : ""}
            </span>
          )}
          {shown.override_reason && (
            <span className="wms-override-note">불일치를 판독 오류로 확인해 승인 · 사유: {shown.override_reason}</span>
          )}
          <a className="wms-certificate-link" href={certificateUrl(jobId)} download>
            검수 완료서 받기
          </a>
        </p>
      )}
      {canApprove && blocked && (
        <p className="wms-blocked" role="note">
          {blocked}
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
          <p className="hint wms-approver-note">입력한 이름이 검수 완료서에 검수자로 찍힙니다.</p>
          {overriding && (
            <fieldset className="wms-override">
              <legend>판독 오류로 넘기기</legend>
              <p className="hint">
                원본 서류에는 문제가 없는데 글자를 잘못 읽어 불일치가 난 경우에만 씁니다. 사유는 단계 기록과 검수 완료서에 남습니다.
              </p>
              <label className="wms-override-check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={mutation.isPending}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                원본 서류를 직접 확인했고, 불일치는 판독 오류입니다
              </label>
              <label>
                사유
                <textarea
                  value={reason}
                  maxLength={OVERRIDE_REASON_MAX}
                  rows={2}
                  placeholder="예: 원본 포장명세서 송장 번호가 QDT/26/0289로 상업송장과 같음"
                  disabled={mutation.isPending}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            </fieldset>
          )}
          <button type="submit" className="primary" disabled={approver.trim() === "" || mutation.isPending || !overrideReady}>
            {mutation.isPending ? "등록하는 중…" : overriding ? "판독 오류로 승인하고 WMS 등록" : "승인하고 WMS 등록"}
          </button>
        </form>
      )}

      {conflict && (
        <div className="wms-conflict" role="alert">
          <strong>WMS에 등록하지 못했습니다.</strong>
          <p>불일치가 남은 건은 서류를 고쳐 다시 올리거나, 원본을 확인해 판독 오류면 사유를 적고 승인해 주세요.</p>
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

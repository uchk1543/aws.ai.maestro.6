// FB22 #178: 작업 화면 맨 위 '지금 상태와 다음 할 일'.
// 서버(GET /api/jobs/{id})가 next_action 을 주면 그대로 쓰고, 주지 않으면(배포 전·옛 서버) 같은 규칙으로 여기서 정한다.
// 규칙은 서버 tools/wms.py 의 next_action 과 같다: 불일치 → 고를 HS → 확인 후 승인.
import type { Job, NextAction } from "./types";

export function nextActionOf(job: Job): NextAction {
  if (job.next_action) return job.next_action;
  if (job.status === "queued" || job.status === "running") {
    return { kind: "wait", message: "처리 중입니다. 끝나면 할 일을 알려 드립니다", count: null };
  }
  if (job.status === "failed") return { kind: "reupload", message: "처리하지 못했습니다. 서류를 다시 올려 주세요", count: null };
  const result = job.result;
  if (job.status === "done") {
    return result?.wms?.status === "등록됨"
      ? { kind: "none", message: "WMS에 등록됐습니다. 더 할 일이 없습니다", count: null }
      : { kind: "none", message: "처리가 끝났습니다. 더 할 일이 없습니다", count: null };
  }
  const issues = result?.issues ?? [];
  const mismatch = issues.filter((i) => i.grade === "불일치").length;
  if (mismatch > 0) {
    return { kind: "fix_docs", message: `불일치 ${mismatch}건: 서류를 고쳐 다시 올려야 등록할 수 있습니다`, count: mismatch };
  }
  const pending = (result?.hs ?? []).filter((h) => h.status === "사람 확인 필요").length;
  if (pending > 0) return { kind: "choose_hs", message: `HS ${pending}개를 고르세요`, count: pending };
  const check = issues.filter((i) => i.grade === "확인 필요").length;
  if (check > 0) return { kind: "approve", message: `확인 필요 ${check}건을 확인한 뒤 승인하세요`, count: check };
  return { kind: "approve", message: "확인한 뒤 승인하세요", count: null };
}
